package com.sinrotic.rs.agent.domain.dto;

public record AgentInterruptRequestDTO(String reason) {

    public String resolvedReason() {
        return reason == null || reason.isBlank() ? "user_interrupt" : reason;
    }
}
