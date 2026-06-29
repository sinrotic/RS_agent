package com.sinrotic.rs.searchrag.service;

import com.sinrotic.rs.searchrag.domain.dto.AgentRagSupportRequestDTO;
import com.sinrotic.rs.searchrag.domain.vo.AgentRagSupportVO;

/**
 * Agent-facing RAG pipeline contract.
 */
public interface AgentRagService {

    AgentRagSupportVO support(AgentRagSupportRequestDTO request);
}
