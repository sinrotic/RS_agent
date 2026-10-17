package com.sinrotic.rs.agent.service;

public class AgentBusyException extends RuntimeException {

    public AgentBusyException(String message) {
        super(message);
    }

    public AgentBusyException(String message, Throwable cause) {
        super(message, cause);
    }
}
