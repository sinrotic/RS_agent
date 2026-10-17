package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentTurnVO;
import java.util.List;

/** Called after the final semantic event is durable; failure never changes the Turn. */
@FunctionalInterface
public interface AgentOnlineEvaluationObserver {
    void completed(AgentChatRequestDTO request, AgentTurnVO turn, List<AgentTurnVO> previousTurns);
}
