package com.sinrotic.rs.agent.service;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
@FunctionalInterface
public interface AgentSessionAdmissionClient {
    void admit(AgentChatRequestDTO request);
    default void verifyOwner(String accountId, String profileUserId, String sessionId) { }
}
