package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentRecommendedItemVO;

import java.util.List;

public interface AgentRecommendationService {

    List<AgentRecommendedItemVO> recommend(AgentChatRequestDTO request);
}
