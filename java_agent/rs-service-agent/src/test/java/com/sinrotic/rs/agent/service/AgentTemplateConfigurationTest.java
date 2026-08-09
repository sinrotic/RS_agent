package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.config.AgentTemplateConfiguration;
import com.sinrotic.rs.agent.domain.AgentProfileFailurePolicy;
import com.sinrotic.rs.agent.domain.AgentPublicOutputBlock;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class AgentTemplateConfigurationTest {

    private final ApplicationContextRunner contextRunner = new ApplicationContextRunner()
            .withUserConfiguration(AgentTemplateConfiguration.class);

    @Test
    void noTemplateConfigurationUsesBuiltInShoppingAssistantProfile() {
        contextRunner.run(context -> {
            assertThat(context).hasNotFailed();
            AgentRuntimeConfigurationService service = context.getBean(AgentRuntimeConfigurationService.class);

            assertThat(service.defaultProfile().id()).isEqualTo("shopping-assistant");
            assertThat(service.defaultProfile().modelRef()).isEqualTo("default");
            assertThat(service.defaultProfile().systemPromptRef()).isEqualTo("default");
            assertThat(service.defaultProfile().allowedCapabilities())
                    .containsExactly("recommend", "rag-explain", "session-memory");
            assertThat(service.defaultProfile().allowedOutputBlocks())
                    .containsExactly(
                            AgentPublicOutputBlock.TEXT,
                            AgentPublicOutputBlock.PRODUCT_CARDS,
                            AgentPublicOutputBlock.COMPARISON_TABLE,
                            AgentPublicOutputBlock.FOLLOWUP_QUESTION
                    );
            assertThat(service.defaultProfile().maxLoops()).isEqualTo(8);
            assertThat(service.defaultProfile().failurePolicy()).isEqualTo(AgentProfileFailurePolicy.FAIL_TURN);
        });
    }

    @Test
    void unknownDefaultProfileFailsDuringConfigurationLoad() {
        contextRunner
                .withPropertyValues("rs.agent.templates.default-profile=missing-profile")
                .run(context -> assertThat(context).hasFailed());
    }

    @Test
    void duplicateProfileIdsFailDuringConfigurationLoad() {
        contextRunner
                .withPropertyValues(
                        "rs.agent.templates.default-profile=duplicate",
                        "rs.agent.templates.profiles[0].id=duplicate",
                        "rs.agent.templates.profiles[0].model-ref=default",
                        "rs.agent.templates.profiles[0].system-prompt-ref=default",
                        "rs.agent.templates.profiles[0].allowed-capabilities[0]=recommend",
                        "rs.agent.templates.profiles[0].allowed-output-blocks[0]=text",
                        "rs.agent.templates.profiles[0].max-loops=8",
                        "rs.agent.templates.profiles[0].failure-policy=fail_turn",
                        "rs.agent.templates.profiles[1].id=duplicate",
                        "rs.agent.templates.profiles[1].model-ref=other",
                        "rs.agent.templates.profiles[1].system-prompt-ref=other",
                        "rs.agent.templates.profiles[1].allowed-capabilities[0]=rag-explain",
                        "rs.agent.templates.profiles[1].allowed-output-blocks[0]=text",
                        "rs.agent.templates.profiles[1].max-loops=4",
                        "rs.agent.templates.profiles[1].failure-policy=fail_turn"
                )
                .run(context -> assertThat(context).hasFailed());
    }

    @Test
    void missingRequiredProfileReferenceFailsDuringConfigurationLoad() {
        contextRunner
                .withPropertyValues(
                        "rs.agent.templates.default-profile=incomplete",
                        "rs.agent.templates.profiles[0].id=incomplete",
                        "rs.agent.templates.profiles[0].system-prompt-ref=default",
                        "rs.agent.templates.profiles[0].allowed-capabilities[0]=recommend",
                        "rs.agent.templates.profiles[0].allowed-output-blocks[0]=text",
                        "rs.agent.templates.profiles[0].max-loops=8",
                        "rs.agent.templates.profiles[0].failure-policy=fail_turn"
                )
                .run(context -> assertThat(context).hasFailed());
    }

    @Test
    void emptyCapabilityAllowlistFailsDuringConfigurationLoad() {
        contextRunner
                .withPropertyValues(
                        "rs.agent.templates.default-profile=no-capabilities",
                        "rs.agent.templates.profiles[0].id=no-capabilities",
                        "rs.agent.templates.profiles[0].model-ref=default",
                        "rs.agent.templates.profiles[0].system-prompt-ref=default",
                        "rs.agent.templates.profiles[0].allowed-output-blocks[0]=text",
                        "rs.agent.templates.profiles[0].max-loops=8",
                        "rs.agent.templates.profiles[0].failure-policy=fail_turn"
                )
                .run(context -> assertThat(context).hasFailed());
    }

    @Test
    void nonPositiveMaxLoopsFailsDuringConfigurationLoad() {
        contextRunner
                .withPropertyValues(
                        "rs.agent.templates.default-profile=shopping-assistant",
                        "rs.agent.templates.profiles[0].id=shopping-assistant",
                        "rs.agent.templates.profiles[0].model-ref=default",
                        "rs.agent.templates.profiles[0].system-prompt-ref=default",
                        "rs.agent.templates.profiles[0].allowed-capabilities[0]=recommend",
                        "rs.agent.templates.profiles[0].allowed-output-blocks[0]=text",
                        "rs.agent.templates.profiles[0].max-loops=0",
                        "rs.agent.templates.profiles[0].failure-policy=fail_turn"
                )
                .run(context -> assertThat(context).hasFailed());
    }

    @Test
    void configuredProfileIsExposedAsAnImmutableRuntimeProfile() {
        contextRunner
                .withPropertyValues(
                        "rs.agent.templates.default-profile=guided-shopping",
                        "rs.agent.templates.profiles[0].id=guided-shopping",
                        "rs.agent.templates.profiles[0].model-ref=shopping-model",
                        "rs.agent.templates.profiles[0].system-prompt-ref=shopping-prompt",
                        "rs.agent.templates.profiles[0].allowed-capabilities[0]=recommend",
                        "rs.agent.templates.profiles[0].allowed-capabilities[1]=rag-explain",
                        "rs.agent.templates.profiles[0].allowed-output-blocks[0]=text",
                        "rs.agent.templates.profiles[0].allowed-output-blocks[1]=product_cards",
                        "rs.agent.templates.profiles[0].max-loops=4",
                        "rs.agent.templates.profiles[0].failure-policy=fallback_to_default"
                )
                .run(context -> {
                    AgentRuntimeConfigurationService service = context.getBean(AgentRuntimeConfigurationService.class);
                    assertThat(service.defaultProfile().id()).isEqualTo("guided-shopping");
                    assertThat(service.defaultProfile().modelRef()).isEqualTo("shopping-model");
                    assertThat(service.defaultProfile().systemPromptRef()).isEqualTo("shopping-prompt");
                    assertThat(service.defaultProfile().allowedCapabilities())
                            .containsExactly("recommend", "rag-explain");
                    assertThat(service.defaultProfile().maxLoops()).isEqualTo(4);
                    assertThat(service.defaultProfile().failurePolicy())
                            .isEqualTo(AgentProfileFailurePolicy.FALLBACK_TO_DEFAULT);
                    assertThat(service.profiles()).extracting("id")
                            .containsExactly("guided-shopping", "shopping-assistant");
                    assertThat(service.profile("shopping-assistant").modelRef()).isEqualTo("default");
                    assertThatThrownBy(() -> service.defaultProfile().allowedCapabilities().add("inventory"))
                            .isInstanceOf(UnsupportedOperationException.class);
                });
    }

    @Test
    void invalidFailurePolicyFailsDuringPropertyBinding() {
        contextRunner
                .withPropertyValues(
                        "rs.agent.templates.profiles[0].failure-policy=retry-forever"
                )
                .run(context -> assertThat(context).hasFailed());
    }
}
