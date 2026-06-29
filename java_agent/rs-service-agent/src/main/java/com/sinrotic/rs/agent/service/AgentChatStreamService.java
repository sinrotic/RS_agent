package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;

import java.util.ArrayList;
import java.util.List;
import java.util.function.Consumer;

public interface AgentChatStreamService {

    void streamChat(AgentChatRequestDTO request, Consumer<AgentStreamEventVO> consumer);

    default List<AgentStreamEventVO> streamChat(AgentChatRequestDTO request) {
        List<AgentStreamEventVO> events = new ArrayList<>();
        streamChat(request, events::add);
        return events;
    }
}
