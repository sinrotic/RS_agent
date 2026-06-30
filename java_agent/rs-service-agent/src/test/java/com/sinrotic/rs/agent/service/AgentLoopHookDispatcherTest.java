package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.service.impl.AgentLoopHookContext;
import com.sinrotic.rs.agent.service.impl.AgentLoopHookResult;
import com.sinrotic.rs.agent.service.impl.AgentProfile;
import com.sinrotic.rs.agent.service.impl.CompositeAgentLoopHookDispatcher;
import com.sinrotic.rs.agent.service.impl.GlobalAgentLoopHookDispatcher;
import com.sinrotic.rs.agent.service.impl.ProfileAwareAgentLoopHookDispatcher;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class AgentLoopHookDispatcherTest {

    @Test
    void compositeRunsGlobalHookBeforeMatchingProfileHookAndMergesContext() {
        List<String> calls = new ArrayList<>();
        AgentLoopHookDispatcher dispatcher = new CompositeAgentLoopHookDispatcher(
                context -> {
                    calls.add("global:" + context.agentName());
                    return AgentLoopHookResult.proceed()
                            .withAdditionalContext(Map.of("global_hook", true));
                },
                List.of(
                        new ProfileAwareAgentLoopHookDispatcher("rs_agent", context -> {
                            calls.add("rs:" + context.agentName());
                            return AgentLoopHookResult.proceed()
                                    .withAdditionalContext(Map.of("rs_hook", true));
                        }),
                        new ProfileAwareAgentLoopHookDispatcher("rag_agent", context -> {
                            calls.add("rag:" + context.agentName());
                            return AgentLoopHookResult.proceed()
                                    .withAdditionalContext(Map.of("rag_hook", true));
                        })
                )
        );

        AgentLoopHookResult result = dispatcher.dispatch(context("rs_agent"));

        assertThat(calls).containsExactly("global:rs_agent", "rs:rs_agent");
        assertThat(result.additionalContext())
                .containsEntry("global_hook", true)
                .containsEntry("rs_hook", true)
                .doesNotContainKey("rag_hook");
    }

    @Test
    void compositeSkipsProfileHookWhenGlobalHookBlocks() {
        List<String> calls = new ArrayList<>();
        AgentLoopHookDispatcher dispatcher = new CompositeAgentLoopHookDispatcher(
                context -> {
                    calls.add("global");
                    return AgentLoopHookResult.block("blocked by global policy");
                },
                List.of(new ProfileAwareAgentLoopHookDispatcher("rs_agent", context -> {
                    calls.add("rs");
                    return AgentLoopHookResult.proceed();
                }))
        );

        AgentLoopHookResult result = dispatcher.dispatch(context("rs_agent"));

        assertThat(calls).containsExactly("global");
        assertThat(result.blocked()).isTrue();
        assertThat(result.message()).isEqualTo("blocked by global policy");
    }

    @Test
    void defaultGlobalAndProfileDispatchersProceedWithoutChangingContext() {
        AgentLoopHookDispatcher dispatcher = new CompositeAgentLoopHookDispatcher(
                new GlobalAgentLoopHookDispatcher(),
                List.of(
                        new ProfileAwareAgentLoopHookDispatcher("rs_agent", context -> AgentLoopHookResult.proceed()),
                        new ProfileAwareAgentLoopHookDispatcher("rag_agent", context -> AgentLoopHookResult.proceed())
                )
        );

        AgentLoopHookResult result = dispatcher.dispatch(context("rag_agent"));

        assertThat(result.blocked()).isFalse();
        assertThat(result.preventContinuation()).isFalse();
        assertThat(result.additionalContext()).isEmpty();
    }

    private AgentLoopHookContext context(String agentName) {
        return AgentLoopHookContext.of(
                "PreToolUse",
                "agent_req_001",
                new AgentProfile(agentName, "test", Map.of()),
                0,
                new AgentChatRequestDTO("sess_001", "A1XYZ", "hello", 1, Map.of())
        );
    }
}
