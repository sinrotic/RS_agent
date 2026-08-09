package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.config.AgentTemplateProperties;
import com.sinrotic.rs.agent.domain.AgentRuntimeProfile;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeSkillUpsertDTO;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeSystemPromptUpdateDTO;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeToolUpsertDTO;
import com.sinrotic.rs.agent.domain.vo.AgentRuntimeSkillVO;
import com.sinrotic.rs.agent.domain.vo.AgentRuntimeSystemPromptVO;
import com.sinrotic.rs.agent.domain.vo.AgentRuntimeToolVO;
import com.sinrotic.rs.agent.service.AgentRuntimeConfigurationService;
import org.springframework.core.io.Resource;
import org.springframework.core.io.support.PathMatchingResourcePatternResolver;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

public class InMemoryAgentRuntimeConfigurationService implements AgentRuntimeConfigurationService {

    private final AgentProfileRegistry profileRegistry;

    private final ConcurrentMap<String, AgentRuntimeSkillVO> skills = new ConcurrentHashMap<>();

    private final ConcurrentMap<String, AgentRuntimeToolVO> tools = new ConcurrentHashMap<>();

    private volatile boolean extensionToolListingEnabled;

    private volatile AgentRuntimeSystemPromptVO systemPrompt = new AgentRuntimeSystemPromptVO(
            "default",
            """
                    你是一个中文购物推荐智能体。

                    你的任务是帮助用户澄清需求、发现合适商品、比较选项，并解释为什么这些推荐适合用户。

                    语言规则：
                    - 除非用户明确要求使用其他语言，所有面向用户的回答、追问、总结、推荐理由和解释都必须使用中文。
                    - 如果工具结果、商品标题或证据是其他语言，可以保留商品专有名词，但解释必须使用中文。
                    - 用户用中文提问时，不要切换成英文。

                    技能使用规则：
                    - 当可用 skill 的触发条件匹配当前会话状态时，先调用 load_skill 加载对应 skill。
                    - 不要默认加载所有 skill，只加载当前步骤真正需要的 skill。

                    工具使用规则：
                    - 当你需要候选商品、商品详情、用户上下文、检索证据或解释依据时使用工具。
                    - 优先基于工具证据回答，不要凭空猜测。

                    响应策略：
                    - 如果用户需求已经明确，直接推荐并解释关键匹配因素，不要重复追问品类。
                    - 如果用户需求不明确，先问一个简短的中文澄清问题，再进入推荐。
                    - 如果用户是冷启动或历史信息不足，先进行宽泛偏好探索，并给出低风险推荐方向。
                    - 如果用户提供反馈，调整推荐策略，并用中文说明调整点。
                    - 回答要简洁、实用，并基于可用证据。

                    安全边界：
                    - 不要编造商品事实、价格、库存、用户偏好或证据。
                    - 除非用户画像或会话上下文支持，不要声称推荐是个性化的。
                    - 如果证据不足，用中文说明缺少什么，并只询问最小必要澄清问题。
                    - 当工具结果冲突时，优先使用最新且可靠的工具结果，并简短说明不确定性。

                    生成最终答案时：
                    - 所有用户可见内容都必须通过 emit_final_answer 工具输出。
                    - 使用有序 blocks 组织答案，例如 text、product_cards、comparison_table 或 followup_question。
                    - 开头直接给出推荐结论或下一个最关键的问题。
                    - 推荐理由要围绕用户意图、商品属性和证据说明。
                    - 不要向用户暴露内部工具名、skill 名称或编排细节。
                    """
    );

    public InMemoryAgentRuntimeConfigurationService() {
        this(new AgentTemplateProperties());
    }

    public InMemoryAgentRuntimeConfigurationService(AgentTemplateProperties properties) {
        profileRegistry = new AgentProfileRegistry(properties);
        loadBuiltInSkills();
        loadDefaultTools();
    }

    @Override
    public AgentRuntimeProfile defaultProfile() {
        return profileRegistry.defaultProfile();
    }

    @Override
    public AgentRuntimeProfile profile(String id) {
        return profileRegistry.profile(id);
    }

    @Override
    public List<AgentRuntimeProfile> profiles() {
        return profileRegistry.profiles();
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
                以下 skill 可以通过 load_skill 工具按需加载：

                %s

                当某个 skill 匹配当前会话状态时，回答前先调用 load_skill。
                不要默认加载所有 skill。如果本轮已经加载过某个 skill，直接遵循该 skill 的流程。
                如果当前模型接口没有可用工具调用能力，不要向用户说明工具不可用，也不要输出工具调用计划；直接基于已有上下文给出中文用户可见答案。
                </system-reminder>
                """.formatted(listing);
    }

    private String agentListingReminder() {
        return """
                <system-reminder>
                以下 agent 可以通过 call_agent 工具调用：

                - rag_agent: 当推荐流程需要检索证据、语义搜索、文档支撑或外部知识解释依据时使用。优先用它收集证据，不要让主 agent 编造事实。

                只有当专门 agent 的上下文或检索能力能明显改善答案时才调用。
                如果当前模型接口没有可用工具调用能力，不要向用户说明工具不可用，也不要输出 agent 调用计划；直接基于已有上下文给出中文用户可见答案。
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
                以下扩展工具可用：

                %s

                这些信息用于 tool-search 风格的能力发现。核心工具仍应由模型 provider 的 tool schema 提供。
                只有启用扩展工具并且当前 tool schema 没有对应能力时，才使用这个列表。
                如果当前模型接口没有可用工具调用能力，不要向用户说明工具不可用，也不要输出工具调用计划；直接基于已有上下文给出中文用户可见答案。
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
                ragSupportToolSchema()
        ));
        tools.put("rag_evidence_search", new AgentRuntimeToolVO(
                "rag_evidence_search",
                "rs-service-recommend",
                "Search and compress recommendation RAG evidence for the rag_agent. Uses candidate-scoped BM25/vector recall, RRF fusion, and rerank in the recommendation service.",
                true,
                ragSupportToolSchema()
        ));
        tools.put("session_memory", new AgentRuntimeToolVO(
                "session_memory",
                "rs-service-agent",
                "Read the current server-owned session memory snapshot.",
                true,
                Map.of(
                        "type", "object",
                        "properties", Map.of("session_id", Map.of("type", "string")),
                        "required", List.of("session_id")
                )
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
        properties.put("constraints", recommendationConstraintsSchema());
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

    private Map<String, Object> recommendationConstraintsSchema() {
        return Map.of(
                "type", "object",
                "description", "Structured filters extracted from user intent. Use price_min and price_max for budget constraints instead of relying on semantic recall.",
                "properties", Map.of(
                        "price_min", Map.of(
                                "type", "number",
                                "minimum", 0,
                                "description", "Minimum acceptable product price, inclusive."
                        ),
                        "price_max", Map.of(
                                "type", "number",
                                "minimum", 0,
                                "description", "Maximum acceptable product price, inclusive. Use for budgets like 500以内 or 一千左右."
                        ),
                        "category", Map.of("type", "string"),
                        "scenario", Map.of("type", "string"),
                        "features", Map.of(
                                "type", "array",
                                "items", Map.of("type", "string")
                        )
                )
        );
    }

    private Map<String, Object> ragSupportToolSchema() {
        return Map.of(
                "type", "object",
                "properties", Map.of(
                        "session_id", Map.of("type", "string"),
                        "query", Map.of("type", "string"),
                        "task", Map.of("type", "string"),
                        "candidate_item_ids", Map.of(
                                "type", "array",
                                "items", Map.of("type", "string")
                        ),
                        "top_k", Map.of("type", "integer", "default", 20, "maximum", 100),
                        "rerank_top_k", Map.of("type", "integer", "default", 10, "maximum", 50),
                        "providers", Map.of(
                                "type", "array",
                                "items", Map.of("type", "string")
                        ),
                        "small2big", Map.of("type", "boolean"),
                        "max_support_per_item", Map.of("type", "integer", "default", 2, "maximum", 5),
                        "max_text_chars", Map.of("type", "integer", "default", 1200, "maximum", 2000)
                )
        );
    }

    private String valueOrDefault(String value, String fallback) {
        if (value == null || value.isBlank()) {
            return fallback;
        }
        return value;
    }
}
