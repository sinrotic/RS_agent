package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.dto.AgentRuntimeSkillUpsertDTO;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeSystemPromptUpdateDTO;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeToolUpsertDTO;
import com.sinrotic.rs.agent.domain.vo.AgentRuntimeSkillVO;
import com.sinrotic.rs.agent.domain.vo.AgentRuntimeSystemPromptVO;
import com.sinrotic.rs.agent.domain.vo.AgentRuntimeToolVO;
import com.sinrotic.rs.agent.service.AgentRuntimeConfigurationService;
import org.springframework.core.io.Resource;
import org.springframework.core.io.support.PathMatchingResourcePatternResolver;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

@Service
public class InMemoryAgentRuntimeConfigurationService implements AgentRuntimeConfigurationService {

    private final ConcurrentMap<String, AgentRuntimeSkillVO> skills = new ConcurrentHashMap<>();

    private final ConcurrentMap<String, AgentRuntimeToolVO> tools = new ConcurrentHashMap<>();

    private volatile boolean extensionToolListingEnabled;

    private volatile AgentRuntimeSystemPromptVO systemPrompt = new AgentRuntimeSystemPromptVO(
            "default",
            """
                    You are an AI shopping recommendation assistant.

                    Your job is to help the user clarify needs, discover suitable items, compare options,
                    and understand why each recommendation is relevant.

                    Use the available skills when their trigger conditions match. Do not load every skill
                    by default. Load only the skill that helps the current conversation state.

                    Use tools when you need candidate items, item details, user context, retrieval evidence,
                    or explanation support. Prefer tool evidence over guessing.

                    Follow these response guidelines:
                    - If the user has a clear need, recommend directly and explain the key matching factors.
                    - If the user need is unclear, ask one concise clarification question before recommending.
                    - If the user is cold or has little history, start with broad preference discovery and low-risk recommendations.
                    - If the user gives feedback, adapt the recommendation strategy and explain what changed.
                    - Keep responses concise, practical, and grounded in retrieved evidence.

                    Follow these guardrails:
                    - Do not invent product facts, prices, inventory, user preferences, or evidence.
                    - Do not claim a recommendation is personalized unless user profile or session context supports it.
                    - If evidence is insufficient, say what is missing and ask for the minimum useful clarification.
                    - When tool results conflict, prefer the latest reliable tool result and mention uncertainty briefly.

                    When producing the final answer:
                    - Use the emit_final_answer tool for all user-visible response content.
                    - Structure the answer as ordered blocks, such as text and product_cards.
                    - Lead with the recommendation or next best question.
                    - Explain the reason in terms of user intent, product attributes, and evidence.
                    - Avoid exposing internal tool names, skill names, or orchestration details to the user.
                    """
    );

    public InMemoryAgentRuntimeConfigurationService() {
        loadBuiltInSkills();
        loadDefaultTools();
    }

    @Override
    public AgentRuntimeSystemPromptVO systemPrompt() {
        return systemPrompt;
    }

    @Override
    public AgentRuntimeSystemPromptVO updateSystemPrompt(AgentRuntimeSystemPromptUpdateDTO request) {
        systemPrompt = new AgentRuntimeSystemPromptVO(
                valueOrDefault(request.name(), "custom"),
                valueOrDefault(request.content(), "")
        );
        return systemPrompt;
    }

    @Override
    public List<AgentRuntimeSkillVO> skills() {
        return skills.values().stream()
                .sorted(Comparator.comparing(AgentRuntimeSkillVO::name))
                .toList();
    }

    @Override
    public AgentRuntimeSkillVO skill(String name) {
        AgentRuntimeSkillVO skill = skills.get(name);
        if (skill == null) {
            throw new IllegalArgumentException("unknown agent skill: " + name);
        }
        return skill;
    }

    @Override
    public AgentRuntimeSkillVO upsertSkill(String name, AgentRuntimeSkillUpsertDTO request) {
        AgentRuntimeSkillVO skill = new AgentRuntimeSkillVO(
                name,
                valueOrDefault(request.description(), ""),
                "custom",
                request.enabled() == null || request.enabled(),
                valueOrDefault(request.content(), "")
        );
        skills.put(name, skill);
        return skill;
    }

    @Override
    public List<AgentRuntimeToolVO> tools() {
        return tools.values().stream()
                .sorted(Comparator.comparing(AgentRuntimeToolVO::name))
                .toList();
    }

    @Override
    public AgentRuntimeToolVO upsertTool(String name, AgentRuntimeToolUpsertDTO request) {
        AgentRuntimeToolVO tool = new AgentRuntimeToolVO(
                name,
                valueOrDefault(request.service(), "rs-service-agent"),
                valueOrDefault(request.description(), ""),
                request.enabled() == null || request.enabled(),
                request.parametersSchema() == null ? Map.of() : Map.copyOf(request.parametersSchema())
        );
        tools.put(name, tool);
        return tool;
    }

    @Override
    public Map<String, Object> modelContext() {
        Map<String, Object> context = new LinkedHashMap<>();
        context.put("system_prompt", systemPrompt.content());
        context.put("runtime_context_messages", runtimeContextMessages());
        context.put("available_skills", skills().stream()
                .filter(AgentRuntimeSkillVO::enabled)
                .map(skill -> Map.of(
                        "name", skill.name(),
                        "description", skill.description(),
                        "source", skill.source()
                ))
                .toList());
        context.put("available_tools", tools().stream()
                .filter(AgentRuntimeToolVO::enabled)
                .map(tool -> Map.of(
                        "name", tool.name(),
                        "service", tool.service(),
                        "description", tool.description(),
                        "parameters_schema", tool.parametersSchema()
                ))
                .toList());
        return context;
    }

    @Override
    public List<String> runtimeContextMessages() {
        List<String> messages = new java.util.ArrayList<>();
        messages.add(skillListingReminder());
        messages.add(agentListingReminder());
        if (extensionToolListingEnabled) {
            messages.add(extensionToolListingReminder());
        }
        return List.copyOf(messages);
    }

    public void setExtensionToolListingEnabled(boolean extensionToolListingEnabled) {
        this.extensionToolListingEnabled = extensionToolListingEnabled;
    }

    private String skillListingReminder() {
        String listing = skills().stream()
                .filter(AgentRuntimeSkillVO::enabled)
                .map(skill -> "- " + skill.name() + ": " + skill.description())
                .reduce((left, right) -> left + "\n" + right)
                .orElse("- No skills are currently enabled.");
        return """
                <system-reminder>
                The following skills are available for use with the load_skill tool:

                %s

                When a listed skill matches the current conversation state, call load_skill before answering.
                Do not load every skill by default. If a skill has already been loaded in this turn, follow its instructions directly.
                </system-reminder>
                """.formatted(listing);
    }

    private String agentListingReminder() {
        return """
                <system-reminder>
                The following agents are available through the call_agent tool:

                - rag_agent: Use when the recommendation flow needs retrieval evidence, semantic search, document-backed support, or explanation grounding from external knowledge. Prefer it for evidence collection rather than asking the main agent to invent facts.

                Use specialist agents only when their context or retrieval ability materially improves the answer.
                </system-reminder>
                """;
    }

    private String extensionToolListingReminder() {
        String listing = tools().stream()
                .filter(AgentRuntimeToolVO::enabled)
                .map(tool -> "- " + tool.name() + ": " + tool.description() + " (service: " + tool.service() + ")")
                .reduce((left, right) -> left + "\n" + right)
                .orElse("- No tools are currently enabled.");
        return """
                <system-reminder>
                The following extension tools are available:

                %s

                These are discovery hints for tool-search style expansion. Core tools should still be supplied through the provider tool schema.
                Use this listing only when extension tools are enabled and you need a capability not already available in the active tool schema.
                </system-reminder>
                """.formatted(listing);
    }

    private void loadBuiltInSkills() {
        PathMatchingResourcePatternResolver resolver = new PathMatchingResourcePatternResolver();
        try {
            Resource[] resources = resolver.getResources("classpath*:agent-skills/*/SKILL.md");
            for (Resource resource : resources) {
                String content = resource.getContentAsString(StandardCharsets.UTF_8);
                AgentRuntimeSkillVO skill = parseSkill(resource, content);
                skills.put(skill.name(), skill);
            }
        } catch (IOException ex) {
            throw new IllegalStateException("failed to load agent skills", ex);
        }
    }

    private AgentRuntimeSkillVO parseSkill(Resource resource, String content) throws IOException {
        String filename = resource.getURL().toString();
        String fallbackName = filename.substring(filename.lastIndexOf("agent-skills/") + "agent-skills/".length());
        fallbackName = fallbackName.substring(0, fallbackName.indexOf("/SKILL.md"));
        String name = frontMatterValue(content, "name", fallbackName);
        String description = frontMatterValue(content, "description", "");
        return new AgentRuntimeSkillVO(name, description, "built-in", true, content);
    }

    private String frontMatterValue(String content, String key, String fallback) {
        if (!content.startsWith("---")) {
            return fallback;
        }
        int end = content.indexOf("\n---", 3);
        if (end < 0) {
            return fallback;
        }
        String prefix = key + ":";
        String[] lines = content.substring(3, end).split("\\R");
        for (String line : lines) {
            String trimmed = line.trim();
            if (trimmed.startsWith(prefix)) {
                return trimmed.substring(prefix.length()).trim();
            }
        }
        return fallback;
    }

    private void loadDefaultTools() {
        tools.put("load_skill", new AgentRuntimeToolVO(
                "load_skill",
                "rs-service-agent",
                "Load one enabled agent skill by name and return its SKILL.md content as a tool result.",
                true,
                Map.of(
                        "type", "object",
                        "properties", Map.of("skill_name", Map.of("type", "string"))
                )
        ));
        tools.put("call_agent", new AgentRuntimeToolVO(
                "call_agent",
                "rs-service-agent",
                "Delegate a scoped task to a registered specialist agent and return the agent result.",
                true,
                Map.of(
                        "type", "object",
                        "properties", Map.of(
                                "agent_name", Map.of("type", "string"),
                                "task", Map.of("type", "string"),
                                "query", Map.of("type", "string"),
                                "candidate_item_ids", Map.of("type", "array", "items", Map.of("type", "string"))
                        )
                )
        ));
        tools.put("emit_final_answer", new AgentRuntimeToolVO(
                "emit_final_answer",
                "rs-service-agent",
                "Emit the ordered user-visible final answer blocks. Use this after required internal tools are complete.",
                true,
                Map.of(
                        "type", "object",
                        "properties", Map.of(
                                "blocks", Map.of(
                                        "type", "array",
                                        "items", Map.of(
                                                "type", "object",
                                                "properties", Map.of(
                                                        "type", Map.of(
                                                                "type", "string",
                                                                "enum", List.of(
                                                                        "text",
                                                                        "product_cards",
                                                                        "comparison_table",
                                                                        "followup_question"
                                                                )
                                                        ),
                                                        "content", Map.of("type", "string"),
                                                        "card_set_id", Map.of("type", "string"),
                                                        "item_ids", Map.of(
                                                                "type", "array",
                                                                "items", Map.of("type", "string")
                                                        ),
                                                        "layout", Map.of("type", "string")
                                                ),
                                                "required", List.of("type")
                                        )
                                )
                        ),
                        "required", List.of("blocks")
                )
        ));
        tools.put("recommend_candidates", new AgentRuntimeToolVO(
                "recommend_candidates",
                "rs-service-recommend",
                "Legacy compatibility tool for fetching recommendation candidates. Prefer the more specific recommendation tools when choosing a route.",
                true,
                Map.of("type", "object")
        ));
        tools.put("recommend_semantic_recall", new AgentRuntimeToolVO(
                "recommend_semantic_recall",
                "rs-service-recommend",
                "Use when the current user message contains a concrete product need or constraints. Returns up to 20 lightweight answer-ready candidates after semantic recall and ranking; internal scores are not exposed.",
                true,
                recommendationToolSchema(true, false)
        ));
        tools.put("recommend_profile_pipeline", new AgentRuntimeToolVO(
                "recommend_profile_pipeline",
                "rs-service-recommend",
                "Use when current intent is broad or empty but profile/session signals are sufficient. Returns the final answer-ready top products from the normal recommendation pipeline.",
                true,
                recommendationToolSchema(false, false)
        ));
        tools.put("recommend_cold_fallback", new AgentRuntimeToolVO(
                "recommend_cold_fallback",
                "rs-service-recommend",
                "Use when both current intent and profile/session signals are weak. Returns answer-ready fallback products with broad popularity and diversity.",
                true,
                recommendationToolSchema(false, false)
        ));
        tools.put("recommend_rerank_candidates", new AgentRuntimeToolVO(
                "recommend_rerank_candidates",
                "rs-service-recommend",
                "Use when reranking an existing candidate set after user feedback, filtering, or constraint changes.",
                true,
                recommendationToolSchema(false, true)
        ));
        tools.put("rag_support", new AgentRuntimeToolVO(
                "rag_support",
                "rs-service-recommend",
                "Retrieve candidate-scoped RAG support from the recommendation service for evidence-grounded explanations.",
                true,
                Map.of("type", "object")
        ));
        tools.put("catalog_card", new AgentRuntimeToolVO(
                "catalog_card",
                "rs-service-catalog",
                "Fetch item details for products selected by the agent.",
                true,
                Map.of("type", "object")
        ));
        tools.put("render_product_cards", new AgentRuntimeToolVO(
                "render_product_cards",
                "rs-service-agent",
                "Prepare user-visible product card blocks for selected recommendation item ids before emitting the final answer.",
                true,
                Map.of(
                        "type", "object",
                        "properties", Map.of(
                                "item_ids", Map.of(
                                        "type", "array",
                                        "items", Map.of("type", "string")
                                ),
                                "layout", Map.of("type", "string"),
                                "reason_fields", Map.of(
                                        "type", "array",
                                        "items", Map.of("type", "string")
                                )
                        ),
                        "required", List.of("item_ids")
                )
        ));
        tools.put("read_tool_result_lines", new AgentRuntimeToolVO(
                "read_tool_result_lines",
                "rs-service-agent",
                "Read a bounded line range from a large tool result using result_ref, offset, and limit. Use this when a prior tool result was truncated and more detail is needed.",
                true,
                Map.of(
                        "type", "object",
                        "properties", Map.of(
                                "result_ref", Map.of("type", "string"),
                                "offset", Map.of("type", "integer", "default", 0, "minimum", 0),
                                "limit", Map.of("type", "integer", "default", 20, "minimum", 1, "maximum", 200)
                        ),
                        "required", List.of("result_ref")
                )
        ));
    }

    private Map<String, Object> recommendationToolSchema(boolean includeQuery, boolean includeCandidates) {
        Map<String, Object> properties = new LinkedHashMap<>();
        properties.put("agent_id", Map.of("type", "string"));
        properties.put("task_id", Map.of("type", "string"));
        properties.put("session_id", Map.of("type", "string"));
        properties.put("profile_user_id", Map.of("type", "string"));
        properties.put("return_count", Map.of("type", "integer", "default", 20, "maximum", 50));
        properties.put("constraints", Map.of("type", "object"));
        if (includeQuery) {
            properties.put("query", Map.of("type", "string"));
            properties.put("recall_limit", Map.of("type", "integer", "default", 100, "maximum", 200));
        }
        if (includeCandidates) {
            properties.put("candidate_item_ids", Map.of(
                    "type", "array",
                    "items", Map.of("type", "string")
            ));
        }
        return Map.of(
                "type", "object",
                "properties", properties
        );
    }

    private String valueOrDefault(String value, String fallback) {
        if (value == null || value.isBlank()) {
            return fallback;
        }
        return value;
    }
}
