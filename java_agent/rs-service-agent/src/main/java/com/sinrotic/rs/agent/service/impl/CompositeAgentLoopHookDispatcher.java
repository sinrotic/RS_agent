package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.service.AgentLoopHookDispatcher;
import com.sinrotic.rs.agent.service.AgentProfileHookDispatcher;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Primary
@Service
public class CompositeAgentLoopHookDispatcher implements AgentLoopHookDispatcher {

    private final AgentLoopHookDispatcher globalDispatcher;

    private final List<AgentProfileHookDispatcher> profileDispatchers;

    @Autowired
    public CompositeAgentLoopHookDispatcher(
            GlobalAgentLoopHookDispatcher globalDispatcher,
            List<AgentProfileHookDispatcher> profileDispatchers
    ) {
        this((AgentLoopHookDispatcher) globalDispatcher, profileDispatchers);
    }

    public CompositeAgentLoopHookDispatcher(
            AgentLoopHookDispatcher globalDispatcher,
            List<AgentProfileHookDispatcher> profileDispatchers
    ) {
        this.globalDispatcher = globalDispatcher;
        this.profileDispatchers = profileDispatchers == null ? List.of() : List.copyOf(profileDispatchers);
    }

    @Override
    public AgentLoopHookResult dispatch(AgentLoopHookContext context) {
        AgentLoopHookResult globalResult = globalDispatcher.dispatch(context);
        if (globalResult.blocked() || globalResult.preventContinuation()) {
            return globalResult;
        }
        AgentLoopHookResult result = globalResult;
        for (AgentProfileHookDispatcher profileDispatcher : profileDispatchers) {
            if (profileDispatcher.supports(context.agentName())) {
                result = merge(result, profileDispatcher.dispatch(context));
            }
        }
        return result;
    }

    private AgentLoopHookResult merge(AgentLoopHookResult first, AgentLoopHookResult second) {
        Map<String, Object> updatedToolArguments = new LinkedHashMap<>(first.updatedToolArguments());
        updatedToolArguments.putAll(second.updatedToolArguments());
        Map<String, Object> additionalContext = new LinkedHashMap<>(first.additionalContext());
        additionalContext.putAll(second.additionalContext());
        String message = second.message() == null || second.message().isBlank()
                ? first.message()
                : second.message();
        return new AgentLoopHookResult(
                first.blocked() || second.blocked(),
                first.preventContinuation() || second.preventContinuation(),
                message,
                Map.copyOf(updatedToolArguments),
                Map.copyOf(additionalContext)
        );
    }
}
