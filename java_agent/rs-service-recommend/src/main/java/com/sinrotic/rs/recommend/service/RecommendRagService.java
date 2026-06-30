package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.dto.AgentRagSupportRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.AgentRagSupportVO;

public interface RecommendRagService {

    AgentRagSupportVO support(AgentRagSupportRequestDTO request);
}
