package com.sinrotic.rs.agent.service.impl;

public final class AgentLoopHookEvent {

    public static final String SESSION_START = "SessionStart";
    public static final String USER_PROMPT_SUBMIT = "UserPromptSubmit";
    public static final String BEFORE_MODEL_CALL = "BeforeModelCall";
    public static final String POST_MODEL_STREAM = "PostModelStream";
    public static final String PRE_TOOL_USE = "PreToolUse";
    public static final String POST_TOOL_USE = "PostToolUse";
    public static final String POST_TOOL_USE_FAILURE = "PostToolUseFailure";
    public static final String STOP = "Stop";
    public static final String STOP_FAILURE = "StopFailure";
    public static final String INTERRUPT = "Interrupt";

    private AgentLoopHookEvent() {
    }
}
