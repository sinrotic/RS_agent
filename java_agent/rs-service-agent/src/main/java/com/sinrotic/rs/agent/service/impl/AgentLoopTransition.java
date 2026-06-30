package com.sinrotic.rs.agent.service.impl;

public record AgentLoopTransition(
        AgentLoopNextAction nextAction,
        AgentFinishReason finishReason
) {
    public static AgentLoopTransition continueLoop() {
        return new AgentLoopTransition(AgentLoopNextAction.CONTINUE_MODEL_LOOP, AgentFinishReason.NEXT_TURN);
    }

    public static AgentLoopTransition complete(AgentFinishReason finishReason) {
        return new AgentLoopTransition(AgentLoopNextAction.COMPLETE, finishReason);
    }
}
