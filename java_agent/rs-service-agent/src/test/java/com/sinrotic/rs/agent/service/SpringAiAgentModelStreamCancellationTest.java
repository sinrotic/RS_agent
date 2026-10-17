package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;
import com.sinrotic.rs.agent.service.impl.AgentFinishReason;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.impl.RsAgentLoop;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentInterrupter;
import com.sinrotic.rs.agent.service.impl.NoopAgentLoopHookDispatcher;
import com.sinrotic.rs.agent.service.impl.SpringAiAgentModelStreamClient;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.ai.chat.prompt.Prompt;
import reactor.core.publisher.Flux;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@Timeout(5)
class SpringAiAgentModelStreamCancellationTest {

    @Test
    void anAlreadyPublishedFinalAnswerKeepsItsCompletionReasonWhenInterruptRacesWithIt() {
        var runtime = new InMemoryAgentRuntimeConfigurationService();
        var interrupter = new InMemoryAgentInterrupter();
        var client = new SpringAiAgentModelStreamClient(model(Flux.just(finalAnswer()).concatWith(Flux.never())), runtime);
        var loop = new RsAgentLoop(runtime, event -> { throw new AssertionError("must not execute tools"); },
                client, new NoopAgentLoopHookDispatcher(), interrupter);
        var result = loop.run(request(), event -> {
            if (event.event().equals("answer_block")) {
                assertThat(interrupter.interruptOwned(event.requestId(), "test-user", "user_interrupt")).isTrue();
            }
        });
        assertThat(result.finishReason()).isEqualTo(AgentFinishReason.FINAL_ANSWER);
        assertThat(result.assistantMessage()).isEqualTo("完整回答");
    }

    @Test
    void finalAnswerStopsTheUpstreamStreamWithoutWaitingForItsTail() {
        var cancelled = new AtomicBoolean();
        var runtime = new InMemoryAgentRuntimeConfigurationService();
        var client = new SpringAiAgentModelStreamClient(model(Flux.just(finalAnswer())
                .concatWith(Flux.never()).doOnCancel(() -> cancelled.set(true))), runtime);
        var loop = new RsAgentLoop(runtime, event -> {
            throw new AssertionError("final answer must not execute a business tool");
        }, client);
        var events = new ArrayList<AgentStreamEventVO>();

        var result = loop.run(request(), events::add);

        assertThat(result.finishReason()).isEqualTo(AgentFinishReason.FINAL_ANSWER);
        assertThat(result.assistantMessage()).isEqualTo("完整回答");
        assertThat(events.stream().filter(event -> !event.event().startsWith("model_call_")))
                .extracting(AgentStreamEventVO::event).containsExactly("answer_block", "done");
        assertThat(cancelled).as("upstream generation must stop when the Agent has finished").isTrue();
    }

    @Test
    void consumerFailureAlsoStopsTheUpstreamStreamAndPreservesTheOriginalError() {
        var cancelled = new AtomicBoolean();
        var failure = new IllegalStateException("consumer disconnected");
        var client = new SpringAiAgentModelStreamClient(model(Flux.just(finalAnswer())
                .concatWith(Flux.never()).doOnCancel(() -> cancelled.set(true))),
                new InMemoryAgentRuntimeConfigurationService());

        assertThatThrownBy(() -> client.streamAssistantEvents("disconnect", request(), event -> {
            throw failure;
        })).isSameAs(failure);
        assertThat(cancelled).as("failed consumers must not leave generation running").isTrue();
    }

    private static AgentChatRequestDTO request() {
        return new AgentChatRequestDTO("cancel-test", "test-user", "回复一句话", 1, Map.of());
    }

    private static ChatResponse finalAnswer() {
        return new ChatResponse(List.of(new Generation(AssistantMessage.builder()
                .content("")
                .toolCalls(List.of(new AssistantMessage.ToolCall("call-final", "function", "emit_final_answer", """
                        {"blocks":[{"type":"text","content":"完整回答","card_set_id":null,"item_ids":null,"layout":null,"messages":null}]}
                        """)))
                .build())));
    }

    private static ChatModel model(Flux<ChatResponse> responses) {
        return new ChatModel() {
            @Override
            public ChatResponse call(Prompt prompt) {
                throw new AssertionError("must use streaming");
            }

            @Override
            public Flux<ChatResponse> stream(Prompt prompt) {
                return responses;
            }
        };
    }
}
