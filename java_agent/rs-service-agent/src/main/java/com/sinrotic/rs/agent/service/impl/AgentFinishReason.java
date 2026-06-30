package com.sinrotic.rs.agent.service.impl;

public enum AgentFinishReason {
    NEXT_TURN,
    FINAL_ANSWER,
    INTERRUPTED,
    HOOK_STOPPED,
    MAX_LOOP,
    MODEL_ERROR,
    TOOL_ERROR
}
