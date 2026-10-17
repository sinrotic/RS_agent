package com.sinrotic.rs.agent.service;

public interface AgentSessionTurnScheduler {

    void runExclusive(String sessionId, AgentSessionTurnAction action);

    <T> T callExclusive(String sessionId, AgentSessionTurnTask<T> task);

    @FunctionalInterface
    interface AgentSessionTurnAction {

        void run() throws Exception;
    }

    @FunctionalInterface
    interface AgentSessionTurnTask<T> {

        T call() throws Exception;
    }
}
