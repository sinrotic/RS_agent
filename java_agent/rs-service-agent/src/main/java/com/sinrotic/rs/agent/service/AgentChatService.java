package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentChatVO;

public interface AgentChatService {

    AgentChatVO chat(AgentChatRequestDTO request);
}
