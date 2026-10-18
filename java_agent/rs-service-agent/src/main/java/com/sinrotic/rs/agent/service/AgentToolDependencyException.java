package com.sinrotic.rs.agent.service;

/** 下游 HTTP 失败的结构化信号；不保存响应正文或 endpoint。 */
public final class AgentToolDependencyException extends RuntimeException {
    private final int status;
    public AgentToolDependencyException(int status) { super("Dependency returned HTTP " + status); this.status = status; }
    public int status() { return status; }
}
