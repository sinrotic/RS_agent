package com.sinrotic.rs.agent.service.impl;

public final class AgentModelBudgetException extends RuntimeException {
    private final String code;
    public AgentModelBudgetException(String code) { super(code); this.code = code; }
    public String code() { return code; }
}
