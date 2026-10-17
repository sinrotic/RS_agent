package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.config.AgentModelProviderConfiguration;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.ai.model.chat.client.autoconfigure.ChatClientAutoConfiguration;
import org.springframework.ai.model.openai.autoconfigure.OpenAiChatAutoConfiguration;
import org.springframework.ai.model.tool.autoconfigure.ToolCallingAutoConfiguration;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import java.util.ArrayList;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

@EnabledIfEnvironmentVariable(named = "RS_AGENT_TEST_VLLM_BASE_URL", matches = ".+")
class LocalVllmConstrainedDecodingSmokeTest {

    @ParameterizedTest
    @ValueSource(booleans = {false, true})
    void existingAgentClientReceivesConstrainedToolArgumentsFromLocalQwen(boolean finalAnswerOnly) {
        new ApplicationContextRunner()
                .withConfiguration(AutoConfigurations.of(
                        ToolCallingAutoConfiguration.class,
                        OpenAiChatAutoConfiguration.class,
                        ChatClientAutoConfiguration.class))
                .withUserConfiguration(AgentModelProviderConfiguration.class, InMemoryAgentRuntimeConfigurationService.class)
                .withPropertyValues(
                        "rs.agent.model-provider.type=spring_ai",
                        "rs.agent.model-provider.constrained-decoding-enabled=true",
                        "spring.ai.model.chat=openai",
                        "spring.ai.chat.client.tool-calling.enabled=false",
                        "spring.ai.openai.base-url=" + System.getenv("RS_AGENT_TEST_VLLM_BASE_URL"),
                        "spring.ai.openai.api-key=local-unused",
                        "spring.ai.openai.chat.options.model=qwen35-4b",
                        "spring.ai.openai.chat.options.temperature=0",
                        "spring.ai.openai.chat.options.max-tokens=512",
                        "spring.ai.openai.chat.options.timeout=30s")
                .run(context -> {
                    var events = new ArrayList<AgentModelStreamEvent>();
                    context.getBean(AgentModelStreamClient.class).streamAssistantEvents(
                            "local-constrained-smoke",
                            new AgentChatRequestDTO("local-smoke", "local-smoke", "请回复一句中文：本地约束解码验证通过。这是连通性测试，不涉及商品检索。",
                                    1, Map.of(
                                            "system_prompt", "本次只需调用 emit_final_answer，返回一个 text block。无需调用检索或其他工具。",
                                            "final_answer_only", finalAnswerOnly)),
                            events::add);
                    assertThat(events).filteredOn(AgentModelStreamEvent::isToolUse).hasSize(1);
                    assertThat(events.getLast().isDone()).isTrue();
                    var tool = events.stream().filter(AgentModelStreamEvent::isToolUse).findFirst().orElseThrow();
                    assertThat(tool.toolName()).isEqualTo("emit_final_answer");
                    assertThat(tool.toolCallId()).isNotBlank();
                    assertThat(tool.arguments()).containsOnlyKeys("blocks");
                    var runtime = context.getBean(AgentRuntimeConfigurationService.class);
                    var projected = new PublicAgentResponseProjector().projectBlocks(tool.arguments().get("blocks"), runtime.defaultProfile());
                    assertThat(projected).isNotEmpty();
                    assertThat(projected.getFirst()).containsEntry("type", "text");
                });
    }
}

