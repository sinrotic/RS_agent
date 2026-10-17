package com.sinrotic.rs.agent.service;

public interface AgentSessionExpirationArchiveService {

    void archiveExpiredSession(String sessionId);
}
