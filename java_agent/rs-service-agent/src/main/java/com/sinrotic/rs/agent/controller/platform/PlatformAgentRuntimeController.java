package com.sinrotic.rs.agent.controller.platform;

import com.sinrotic.rs.agent.domain.dto.AgentRuntimeSkillUpsertDTO;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeSystemPromptUpdateDTO;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeToolUpsertDTO;
import com.sinrotic.rs.agent.domain.vo.AgentRuntimeSkillVO;
import com.sinrotic.rs.agent.domain.vo.AgentRuntimeSystemPromptVO;
import com.sinrotic.rs.agent.domain.vo.AgentRuntimeToolVO;
import com.sinrotic.rs.agent.service.AgentRuntimeConfigurationService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/platform/agent/runtime")
public class PlatformAgentRuntimeController {

    private final AgentRuntimeConfigurationService runtimeConfigurationService;

    public PlatformAgentRuntimeController(AgentRuntimeConfigurationService runtimeConfigurationService) {
        this.runtimeConfigurationService = runtimeConfigurationService;
    }

    @GetMapping("/system-prompt")
    public AgentRuntimeSystemPromptVO systemPrompt() {
        return runtimeConfigurationService.systemPrompt();
    }

    @PutMapping("/system-prompt")
    public AgentRuntimeSystemPromptVO updateSystemPrompt(@RequestBody AgentRuntimeSystemPromptUpdateDTO request) {
        return runtimeConfigurationService.updateSystemPrompt(request);
    }

    @GetMapping("/skills")
    public List<AgentRuntimeSkillVO> skills() {
        return runtimeConfigurationService.skills();
    }

    @GetMapping("/skills/{name}")
    public AgentRuntimeSkillVO skill(@PathVariable String name) {
        return runtimeConfigurationService.skill(name);
    }

    @PutMapping("/skills/{name}")
    public AgentRuntimeSkillVO upsertSkill(
            @PathVariable String name,
            @RequestBody AgentRuntimeSkillUpsertDTO request
    ) {
        return runtimeConfigurationService.upsertSkill(name, request);
    }

    @GetMapping("/tools")
    public List<AgentRuntimeToolVO> tools() {
        return runtimeConfigurationService.tools();
    }

    @PutMapping("/tools/{name}")
    public AgentRuntimeToolVO upsertTool(
            @PathVariable String name,
            @RequestBody AgentRuntimeToolUpsertDTO request
    ) {
        return runtimeConfigurationService.upsertTool(name, request);
    }
}
