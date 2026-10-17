package com.sinrotic.rs.agent.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;

import java.io.OutputStream;
import java.security.DigestOutputStream;
import java.security.MessageDigest;
import java.util.*;
import java.util.function.Consumer;
import java.util.function.Supplier;

/** 仅记录摘要。配置指纹与含用户数据的实际请求摘要分开，后者禁止外发。 */
public final class AgentModelRequestFingerprint {
    public static final String VERSION = "rs-agent-model-request-fingerprint/1";
    public static final List<String> HASH_FIELDS = List.of("prompt_sha256", "tools_sha256", "skills_sha256",
            "request_sha256", "request_options_sha256", "adapter_sha256", "declared_model_sha256");
    public static final Set<String> SCOPES = Set.of("spring_ai_prepared_request", "self_hosted_adapter_request", "python_agent_adapter_request");
    private static final ObjectMapper JSON = new ObjectMapper().enable(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS);
    private static final ClassValue<String> ADAPTER_HASH = new ClassValue<>() {
        @Override protected String computeValue(Class<?> type) {
            try (var input = type.getResourceAsStream(type.getSimpleName() + ".class")) {
                if (input == null) throw new IllegalStateException("Adapter artifact unavailable");
                return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(input.readAllBytes()));
            } catch (Exception failure) { throw new IllegalStateException("Adapter fingerprint unavailable"); }
        }
    };

    private AgentModelRequestFingerprint() { }

    public static Map<String, Object> capture(String scope, Class<?> adapter, AgentChatRequestDTO request,
            Object configuredPrompt, Object actualTools, Object actualRequest, Object requestOptions, String declaredModel) {
        if (!SCOPES.contains(scope)) throw new IllegalArgumentException("Unknown request observation scope");
        var result = new LinkedHashMap<String, Object>();
        result.put("fingerprint_schema_version", VERSION);
        result.put("fingerprint_status", "observed");
        result.put("fingerprint_scope", scope);
        String adapterHash = ADAPTER_HASH.get(adapter);
        result.put("adapter_sha256", adapterHash);
        // 只有配置及渲染器参与此版本；用户问题、商品和普通工具正文只影响 request_sha256。
        result.put("prompt_sha256", sha256(Map.of("configured_prompt", configuredPrompt,
                "adapter_sha256", adapterHash, "runtime_rules", select(request.resolvedContext(), List.of("runtime_context_messages")))));
        result.put("tools_sha256", sha256(actualTools));
        result.put("skills_sha256", sha256(skillViews(request.resolvedContext())));
        result.put("request_options_sha256", sha256(requestOptions));
        result.put("request_sha256", sha256(actualRequest));
        result.put("model_identity_status", declaredModel == null || declaredModel.isBlank() ? "unknown" : "configured_alias");
        if (declaredModel != null && !declaredModel.isBlank()) result.put("declared_model_sha256", sha256(declaredModel));
        return Collections.unmodifiableMap(result);
    }

    /** 观测计算或接收异常都不改变模型调用和取消语义；不记录异常内容。 */
    public static void publish(Consumer<Map<String, Object>> observer, Supplier<Map<String, Object>> snapshot) {
        Map<String, Object> result;
        try { result = snapshot.get(); }
        catch (RuntimeException unavailable) { result = Map.of("fingerprint_schema_version", VERSION, "fingerprint_status", "unavailable"); }
        try { observer.accept(result); }
        catch (RuntimeException ignored) {
            System.getLogger(AgentModelRequestFingerprint.class.getName()).log(System.Logger.Level.WARNING,
                    "Agent request observation delivery failed");
        }
    }

    public static String sha256(Object value) {
        try {
            var digest = MessageDigest.getInstance("SHA-256");
            try (var output = new DigestOutputStream(OutputStream.nullOutputStream(), digest)) { JSON.writeValue(output, value); }
            return HexFormat.of().formatHex(digest.digest());
        } catch (Exception invalidValue) { throw new IllegalStateException("Request fingerprint unavailable"); }
    }

    private static Map<String, Object> select(Map<?, ?> values, List<String> names) {
        var selected = new LinkedHashMap<String, Object>();
        for (String name : names) if (values.get(name) != null) selected.put(name, values.get(name));
        return selected;
    }

    private static Map<String, Object> skillViews(Map<String, Object> context) {
        var selected = select(context, List.of("available_skills", "server_loaded_skills"));
        var loaded = new ArrayList<Map<String, Object>>();
        if (context.get("tool_results") instanceof List<?> results) for (var value : results) {
            if (value instanceof Map<?, ?> result && "load_skill".equals(result.get("tool_name"))
                    && "SUCCESS".equals(result.get("status")) && result.get("metadata") instanceof Map<?, ?> metadata
                    && Boolean.TRUE.equals(metadata.get("loaded")))
                loaded.add(select(metadata, List.of("skill_name", "description", "content", "source", "content_sha256")));
        }
        selected.put("loaded_skill_results", loaded);
        return selected;
    }
}
