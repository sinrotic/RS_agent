package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.dto.AgentRuntimeSkillUpsertDTO;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeSystemPromptUpdateDTO;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeToolUpsertDTO;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class InMemoryAgentRuntimeConfigurationServiceTest {

    @Test
    void loadsBuiltInSkillsAndDefaultToolsForRuntimeMetadata() {
        InMemoryAgentRuntimeConfigurationService service = new InMemoryAgentRuntimeConfigurationService();

        assertThat(service.systemPrompt().content())
                .contains("中文购物推荐智能体")
                .contains("所有面向用户的回答、追问、总结、推荐理由和解释都必须使用中文")
                .contains("如果用户需求已经明确，直接推荐并解释关键匹配因素，不要重复追问品类");
        assertThat(service.skills()).extracting("name")
                .contains(
                        "explicit-need-recommendation",
                        "unclear-need-clarification",
                        "cold-user-onboarding",
                        "feedback-adaptation",
                        "evidence-grounded-explanation"
                );
        assertThat(service.skill("explicit-need-recommendation").content()).contains("Workflow");
        assertThat(service.tools()).extracting("name")
                .contains(
                        "load_skill",
                        "call_agent",
                        "emit_final_answer",
                        "render_product_cards",
                        "recommend_candidates",
                        "recommend_semantic_recall",
                        "recommend_profile_pipeline",
                        "recommend_cold_fallback",
                        "recommend_rerank_candidates",
                        "rag_support",
                        "rag_evidence_search",
                        "catalog_card"
                );
        assertThat(service.tools().stream()
                .filter(tool -> "rag_support".equals(tool.name()))
                .findFirst()
                .orElseThrow()
                .service()).isEqualTo("rs-service-recommend");
        assertThat(service.tools().stream()
                .filter(tool -> "rag_evidence_search".equals(tool.name()))
                .findFirst()
                .orElseThrow()
                .service()).isEqualTo("rs-service-recommend");
    }

    @Test
    void customSkillAndToolDefinitionsOverrideRuntimeMetadata() {
        InMemoryAgentRuntimeConfigurationService service = new InMemoryAgentRuntimeConfigurationService();

        service.updateSystemPrompt(new AgentRuntimeSystemPromptUpdateDTO(
                "experiment-a",
                "Always cite tool evidence."
        ));
        service.upsertSkill("explicit-need-recommendation", new AgentRuntimeSkillUpsertDTO(
                "Custom trigger",
                "---\nname: explicit-need-recommendation\n---\n# Custom workflow\n",
                true
        ));
        service.upsertTool("recommend_candidates", new AgentRuntimeToolUpsertDTO(
                "rs-service-recommend",
                "Custom candidate retriever.",
                false,
                Map.of("type", "object", "properties", Map.of("limit", Map.of("type", "integer")))
        ));

        assertThat(service.systemPrompt().name()).isEqualTo("experiment-a");
        assertThat(service.skill("explicit-need-recommendation").description()).isEqualTo("Custom trigger");
        assertThat(service.skill("explicit-need-recommendation").source()).isEqualTo("custom");
        assertThat(service.tools().stream()
                .filter(tool -> "recommend_candidates".equals(tool.name()))
                .findFirst()
                .orElseThrow()
                .enabled()).isFalse();
    }

    @Test
    void modelContextIncludesSkillAndAgentListingsButOmitsCoreToolListingByDefault() {
        InMemoryAgentRuntimeConfigurationService service = new InMemoryAgentRuntimeConfigurationService();

        Map<String, Object> context = service.modelContext();

        assertThat(context).containsKey("runtime_context_messages");
        assertThat((Iterable<?>) context.get("runtime_context_messages"))
                .anySatisfy(message -> assertThat((String) message)
                        .contains("<system-reminder>")
                        .contains("以下 skill 可以通过 load_skill 工具按需加载：")
                        .contains("- explicit-need-recommendation:")
                        .contains("</system-reminder>"))
                .anySatisfy(message -> assertThat((String) message)
                        .contains("<system-reminder>")
                        .contains("以下 agent 可以通过 call_agent 工具调用：")
                        .contains("- rag_agent:")
                        .contains("</system-reminder>"));
        assertThat((Iterable<?>) context.get("runtime_context_messages"))
                .noneSatisfy(message -> assertThat((String) message)
                        .contains("以下扩展工具可用："));
    }

    @Test
    void extensionToolListingCanBeEnabledForToolSearchStyleDiscovery() {
        InMemoryAgentRuntimeConfigurationService service = new InMemoryAgentRuntimeConfigurationService();
        service.setExtensionToolListingEnabled(true);

        Map<String, Object> context = service.modelContext();

        assertThat((Iterable<?>) context.get("runtime_context_messages"))
                .anySatisfy(message -> assertThat((String) message)
                        .contains("<system-reminder>")
                        .contains("以下扩展工具可用：")
                        .contains("- recommend_semantic_recall:")
                        .contains("- recommend_profile_pipeline:")
                        .contains("- recommend_cold_fallback:")
                        .contains("- recommend_rerank_candidates:")
                        .contains("</system-reminder>"));
    }

    @Test
    void recommendationToolSchemaExposesStructuredPriceConstraints() {
        InMemoryAgentRuntimeConfigurationService service = new InMemoryAgentRuntimeConfigurationService();

        Map<String, Object> schema = service.tools().stream()
                .filter(tool -> "recommend_semantic_recall".equals(tool.name()))
                .findFirst()
                .orElseThrow()
                .parametersSchema();
        Map<?, ?> properties = (Map<?, ?>) schema.get("properties");
        Map<?, ?> constraints = (Map<?, ?>) properties.get("constraints");
        Map<?, ?> constraintProperties = (Map<?, ?>) constraints.get("properties");

        assertThat(constraints.get("description")).asString()
                .contains("price_min")
                .contains("price_max")
                .contains("semantic recall");
        Map<?, ?> priceMin = (Map<?, ?>) constraintProperties.get("price_min");
        Map<?, ?> priceMax = (Map<?, ?>) constraintProperties.get("price_max");
        assertThat(priceMin.get("type")).isEqualTo("number");
        assertThat(priceMin.get("minimum")).isEqualTo(0);
        assertThat(priceMax.get("type")).isEqualTo("number");
        assertThat(priceMax.get("minimum")).isEqualTo(0);
    }
}
