package com.sinrotic.rs.searchrag.controller.agent;

import com.sinrotic.rs.searchrag.domain.dto.AgentRagSupportRequestDTO;
import com.sinrotic.rs.searchrag.domain.vo.AgentRagSupportVO;
import com.sinrotic.rs.searchrag.service.AgentRagService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Provides Agent-facing RAG grounding support.
 */
@RestController
@RequestMapping("/agent/rag")
public class AgentRagController {

    private final AgentRagService agentRagService;

    public AgentRagController(AgentRagService agentRagService) {
        this.agentRagService = agentRagService;
    }

    @PostMapping("/support")
    public AgentRagSupportVO support(@RequestBody AgentRagSupportRequestDTO request) {
        return agentRagService.support(request.withDefaults());
    }
}
