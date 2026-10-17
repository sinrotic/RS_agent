package com.sinrotic.rs.agent.benchmark;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeSkillUpsertDTO;
import com.sinrotic.rs.agent.service.AgentModelStreamClient;
import com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.impl.RsAgentLoop;
import com.sinrotic.rs.agent.service.impl.VirtualThreadAgentToolUseExecutor;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * 离线评测专用进程：真实 RsAgentLoop + 内存 Skill overlay + loopback fixture 工具。
 * 不启动 Spring 服务，不访问生产账号、数据库和推荐服务。
 * 模型使用显式 OpenAI-compatible JSON Adapter，不冒充生产 Spring AI transport。
 */
public final class SkillBenchmarkMain {
    private static final ObjectMapper JSON = new ObjectMapper().enable(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS);
    private static final TypeReference<Map<String, Object>> MAP = new TypeReference<>() { };
    private static final HttpClient HTTP = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10)).build();

    private SkillBenchmarkMain() { }

    public static void main(String[] args) throws Exception {
        Map<String, Object> input = JSON.readValue(System.in.readAllBytes(), MAP);
        if (!"rs-skill-agent/1".equals(input.get("protocol"))) throw new IllegalArgumentException("Unsupported protocol");
        URI fixture = URI.create((String) input.get("fixture_url"));
        if (!"http".equals(fixture.getScheme()) || !"127.0.0.1".equals(fixture.getHost())) {
            throw new IllegalArgumentException("Fixture must be loopback");
        }
        var runtime = new InMemoryAgentRuntimeConfigurationService();
        Map<String, Object> runtimeSnapshot = new TreeMap<>();
        runtimeSnapshot.put("system_prompt", runtime.systemPrompt().content());
        var profile = runtime.defaultProfile();
        runtimeSnapshot.put("profile", Map.of("id", profile.id(), "model_ref", profile.modelRef(),
                "system_prompt_ref", profile.systemPromptRef(), "max_loops", profile.maxLoops(),
                "failure_policy", profile.failurePolicy().name(),
                "allowed_capabilities", profile.allowedCapabilities().stream().sorted().toList(),
                "allowed_output_blocks", profile.allowedOutputBlocks().stream().map(Enum::name).sorted().toList()));
        runtimeSnapshot.put("tools", canonical(runtime.toolsForProfile(runtime.defaultProfile()), "tools"));
        runtimeSnapshot.put("transport", "benchmark-openai-json/1");
        runtimeSnapshot.put("loop_class_sha256", classHash(RsAgentLoop.class));
        runtimeSnapshot.put("implementation_class_sha256", classHash(com.sinrotic.rs.agent.service.impl.AgentLoop.class));
        runtimeSnapshot.put("runtime_class_sha256", classHash(InMemoryAgentRuntimeConfigurationService.class));
        runtimeSnapshot.put("executor_class_sha256", classHash(VirtualThreadAgentToolUseExecutor.class));
        runtimeSnapshot.put("projector_class_sha256", classHash(com.sinrotic.rs.agent.service.PublicAgentResponseProjector.class));
        runtimeSnapshot.put("harness_class_sha256", classHash(SkillBenchmarkMain.class));
        runtimeSnapshot.put("agent_classes_sha256", classesHash(RsAgentLoop.class));
        runtimeSnapshot.put("java_version", System.getProperty("java.version"));
        for (var entry : map(input.get("skills")).entrySet()) {
            Map<String, Object> skill = map(entry.getValue());
            runtime.upsertSkill(entry.getKey(), new AgentRuntimeSkillUpsertDTO(
                    String.valueOf(skill.get("description")), String.valueOf(skill.get("content")), true));
        }
        Map<String, String> skillHashes = new TreeMap<>();
        for (var skill : runtime.skills()) {
            skillHashes.put(skill.name(), hash(JSON.writeValueAsBytes(skill.content())));
        }
        List<Object> answers = new ArrayList<>();
        List<Object> history = new ArrayList<>();
        List<Object> trace = new ArrayList<>();
        Map<String, Object> model = map(input.get("model"));
        AgentModelStreamClient modelClient = (requestId, request, consumer) -> {
            try {
                var context = new LinkedHashMap<>(request.resolvedContext());
                Object tools = context.remove("available_tools");
                String prompt = String.valueOf(context.remove("system_prompt")) + "\n评测工具只覆盖冻结目录，不代表全网。\n"
                        + "已有工具结果应直接使用；通过 emit_final_answer 输出答案，不要反复调用相同工具。\n"
                        + JSON.writeValueAsString(canonical(context, "context"));
                List<Object> definitions = new ArrayList<>();
                for (Object raw : list(tools)) {
                    var tool = map(raw);
                    if (Boolean.TRUE.equals(request.resolvedContext().get("final_answer_only"))
                            && !"emit_final_answer".equals(tool.get("name"))) continue;
                    definitions.add(Map.of("type", "function", "function", Map.of(
                            "name", tool.get("name"), "description", tool.get("description"),
                            "parameters", canonical(tool.get("parameters_schema"), "parameters_schema"))));
                }
                Map<String, Object> body = new LinkedHashMap<>();
                body.put("model", model.get("model"));
                body.put("temperature", model.getOrDefault("temperature", 0));
                body.put("max_tokens", model.getOrDefault("max_tokens", 1600));
                body.put("seed", model.getOrDefault("seed", 0));
                body.put("stream", false);
                body.put("messages", List.of(Map.of("role", "system", "content", prompt),
                        Map.of("role", "user", "content", request.userMessage())));
                body.put("tools", definitions);
                body.put("tool_choice", "required");
                String base = String.valueOf(model.get("base_url")).replaceAll("/+$", "");
                var response = post(URI.create(base + "/chat/completions"), body, true);
                var message = map(map(list(response.get("choices")).getFirst()).get("message"));
                if (response.get("usage") instanceof Map<?, ?>) consumer.accept(AgentModelStreamEvent.usage(map(response.get("usage"))));
                for (Object raw : list(message.get("tool_calls"))) {
                    var call = map(raw);
                    var function = map(call.get("function"));
                    String name = String.valueOf(function.get("name"));
                    // 不允许模型绕过当前 profile 的工具 allowlist。
                    if (runtime.toolsForProfile(runtime.defaultProfile()).stream().noneMatch(tool -> tool.name().equals(name))) {
                        throw new IllegalArgumentException("Tool outside profile");
                    }
                    consumer.accept(AgentModelStreamEvent.toolUse(String.valueOf(call.get("id")), name,
                            JSON.readValue(String.valueOf(function.get("arguments")), MAP)));
                }
                if (list(message.get("tool_calls")).isEmpty()) throw new IllegalStateException("Structured final answer required");
                consumer.accept(AgentModelStreamEvent.done());
            } catch (RuntimeException error) {
                throw error;
            } catch (Exception error) {
                throw new IllegalStateException("Model request failed", error);
            }
        };
        try (var internal = new VirtualThreadAgentToolUseExecutor(runtime);
             var tools = new VirtualThreadAgentToolUseExecutor(event -> {
                 if ("load_skill".equals(event.toolName()) || "render_product_cards".equals(event.toolName())
                         || "read_tool_result_lines".equals(event.toolName())) {
                     return internal.execute(event).join();
                 }
                 try {
                     return post(fixture.resolve("/tool"), Map.of("tool_name", event.toolName(), "arguments", event.arguments()), false);
                 } catch (Exception error) {
                     return Map.of("status", "FAILED", "error", "FIXTURE_CALL_FAILED");
                 }
             })) {
            var loop = new RsAgentLoop(runtime, tools, modelClient);
            int index = 0;
            List<Object> pendingTurns = new ArrayList<>(list(input.get("turns")));
            boolean customerDialogue = Boolean.TRUE.equals(input.get("customer_dialogue"));
            int customerTurnLimit = ((Number) input.getOrDefault("customer_turn_limit", pendingTurns.size())).intValue();
            while (index < pendingTurns.size() && index < customerTurnLimit) {
                Object raw = pendingTurns.get(index);
                Map<String, Object> turn = map(raw);
                post(fixture.resolve("/turn"), Map.of("turn_index", index), false);
                List<Map<String, Object>> blocks = new ArrayList<>();
                Map<String, List<String>> cardSets = new LinkedHashMap<>();
                Map<String, Object> context = new LinkedHashMap<>();
                context.put("benchmark_session_history", List.copyOf(history));
                context.put("benchmark_profile_snapshot", map(input.get("profile_snapshot")));
                if (customerDialogue) context.put("benchmark_shopping_context", map(input.get("shopping_context")));
                final int turnIndex = index;
                var result = loop.run(new AgentChatRequestDTO((String) input.get("session_id"),
                        (String) input.get("profile_user_id"), (String) turn.get("user_message"),
                        ((Number) turn.get("limit")).intValue(), context), event -> {
                    trace.add(Map.of("turn_index", turnIndex, "event", event.event(), "data", event.data()));
                    if ("answer_block".equals(event.event())) blocks.add(event.data());
                    if ("tool_result".equals(event.event()) && "render_product_cards".equals(event.data().get("tool_name"))) {
                        var metadata = map(event.data().get("metadata"));
                        List<String> rendered = new ArrayList<>();
                        for (Object card : list(metadata.get("cards"))) rendered.add(String.valueOf(map(card).get("item_id")));
                        cardSets.put(String.valueOf(metadata.get("card_set_id")), rendered);
                    }
                });
                List<String> ids = new ArrayList<>();
                List<String> text = new ArrayList<>();
                List<String> questions = new ArrayList<>();
                boolean asksQuestion = false;
                boolean unsupported = false;
                for (var block : blocks) {
                    String type = String.valueOf(block.get("type"));
                    if ("product_cards".equals(type)) {
                        if (block.containsKey("item_ids")) {
                            for (Object id : list(block.get("item_ids"))) ids.add(String.valueOf(id));
                        } else if (cardSets.containsKey(String.valueOf(block.get("card_set_id")))) {
                            ids.addAll(cardSets.get(String.valueOf(block.get("card_set_id"))));
                        } else unsupported = true;
                    }
                    if ("a2ui".equals(type)) unsupported = true;
                    if (block.get("content") instanceof String value) text.add(value);
                    if ("followup_question".equals(type)) {
                        asksQuestion = true;
                        if (block.get("content") instanceof String question) questions.add(question);
                    }
                }
                for (var block : blocks) {
                    if ("comparison_table".equals(block.get("type"))) {
                        if (!block.containsKey("item_ids")) unsupported = true;
                        for (Object rawId : list(block.get("item_ids"))) {
                            String id = String.valueOf(rawId);
                            if (!ids.contains(id)) ids.add(id);
                        }
                    }
                }
                String message = String.join("\n", text);
                List<String> limitations = new ArrayList<>();
                boolean uncertain = asksQuestion || contains(message, "无法确认", "不能确认", "信息不足", "缺少信息", "未提供", "没有提供", "无法核实");
                String outcome = !ids.isEmpty() ? "recommend" : uncertain ? "uncertain_match" : "no_match";
                if (ids.isEmpty()) limitations.add(uncertain ? "unknown_attributes" : "no_matches");
                if (contains(message, "不足", "只有", "仅有", "仅找到", "只找到", "仅能")) limitations.add("insufficient_matches");
                var answer = new LinkedHashMap<String, Object>();
                answer.put("item_ids", ids);
                answer.put("outcome", outcome);
                answer.put("message", message);
                answer.put("questions", questions);
                answer.put("limitations", limitations);
                answer.put("status", "FINAL_ANSWER".equals(result.finishReason().name()) && !blocks.isEmpty() && !unsupported ? "ok" : "failed");
                answer.put("unsupported_output", unsupported);
                answer.put("finish_reason", result.finishReason().name());
                answer.put("blocks", blocks);
                answers.add(answer);
                history.add(Map.of("user_message", turn.get("user_message"), "answer", answer));
                if (customerDialogue) {
                    Map<String, Object> continuation = post(fixture.resolve("/customer"),
                            Map.of("turn_index", index, "answer", answer), false);
                    if (!Boolean.TRUE.equals(continuation.get("done"))) {
                        pendingTurns.add(map(continuation.get("next_turn")));
                    }
                }
                index++;
            }
        }
        System.out.write(JSON.writeValueAsBytes(Map.of("turns", answers, "trace", trace,
                "runtime", Map.of("runtime_sha256", hash(JSON.writeValueAsBytes(runtimeSnapshot)),
                "snapshot", runtimeSnapshot, "skill_sha256", skillHashes, "transport", "benchmark-openai-json/1",
                "profile_user_id", input.get("profile_user_id"),
                "profile_snapshot_sha256", hash(JSON.writeValueAsBytes(map(input.get("profile_snapshot"))))))));
        System.out.write('\n');
        System.out.flush();
    }

    private static boolean contains(String message, String... values) {
        for (String value : values) if (message.contains(value)) return true;
        return false;
    }

    private static String classHash(Class<?> type) throws Exception {
        try (var stream = type.getResourceAsStream("/" + type.getName().replace('.', '/') + ".class")) {
            if (stream == null) throw new IllegalStateException("Missing class resource");
            return hash(stream.readAllBytes());
        }
    }

    private static String hash(byte[] bytes) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }

    private static String classesHash(Class<?> type) throws Exception {
        Path location = Path.of(type.getProtectionDomain().getCodeSource().getLocation().toURI());
        if (!Files.isDirectory(location)) return hash(Files.readAllBytes(location));
        var digest = MessageDigest.getInstance("SHA-256");
        try (var files = Files.walk(location)) {
            for (Path file : files.filter(Files::isRegularFile).filter(file -> file.toString().endsWith(".class")).sorted().toList()) {
                digest.update(location.relativize(file).toString().replace('\\', '/').getBytes(StandardCharsets.UTF_8));
                digest.update(Files.readAllBytes(file));
            }
        }
        return HexFormat.of().formatHex(digest.digest());
    }

    // JSON Schema 的 enum/required/oneOf 等列表语义无序；同时规范化实际发送内容和指纹，
    // 避免 Map.of 的跨 JVM 随机迭代顺序改变工具 schema/模型输入。
    private static Object canonical(Object value, String key) throws Exception {
        if (value == null || value instanceof String || value instanceof Number || value instanceof Boolean) return value;
        if (value instanceof Map<?, ?> values) {
            var ordered = new TreeMap<String, Object>();
            for (var entry : values.entrySet()) ordered.put(String.valueOf(entry.getKey()), canonical(entry.getValue(), String.valueOf(entry.getKey())));
            return ordered;
        }
        if (value instanceof java.util.Collection<?> values) {
            List<Object> ordered = new ArrayList<>();
            for (var entry : values) ordered.add(canonical(entry, ""));
            if (value instanceof java.util.Set<?> || List.of("oneOf", "anyOf", "allOf", "enum", "required", "type").contains(key)) {
                ordered.sort(java.util.Comparator.comparing(entry -> {
                    try { return JSON.writeValueAsString(entry); }
                    catch (Exception error) { throw new IllegalStateException(error); }
                }));
            }
            return ordered;
        }
        return canonical(JSON.convertValue(value, Object.class), key);
    }

    private static Map<String, Object> post(URI uri, Object body, boolean model) throws Exception {
        var builder = HttpRequest.newBuilder(uri).timeout(Duration.ofSeconds(60))
                .header("Content-Type", "application/json; charset=utf-8")
                .POST(HttpRequest.BodyPublishers.ofString(JSON.writeValueAsString(body), StandardCharsets.UTF_8));
        String key = System.getenv("RS_BENCHMARK_API_KEY");
        if (model && key != null && !key.isBlank()) builder.header("Authorization", "Bearer " + key);
        var response = HTTP.send(builder.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        if (response.statusCode() != 200) throw new IllegalStateException("HTTP_" + response.statusCode());
        return JSON.readValue(response.body(), MAP);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> map(Object value) {
        return value instanceof Map<?, ?> values ? (Map<String, Object>) values : Map.of();
    }

    private static List<?> list(Object value) {
        return value instanceof List<?> values ? values : List.of();
    }
}
