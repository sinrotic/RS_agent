package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.vo.AgentToolCallVO;

import java.util.List;

public record AgentLoopResult(
        String agentName,
        String requestId,
        String assistantMessage,
        List<AgentToolCallVO> toolCalls
) {
}
