package com.sinrotic.rs.agent.controller.platform;

import com.sinrotic.rs.agent.controller.GatewayRoleGuard;
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
import org.springframework.web.bind.annotation.RequestHeader;
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
    public AgentRuntimeSystemPromptVO systemPrompt(@RequestHeader("X-User-Roles") String roles) {
        GatewayRoleGuard.requireAny(roles, "ADMIN", "AGENT_OPERATOR");
        return runtimeConfigurationService.systemPrompt();
    }

    @PutMapping("/system-prompt")
    public AgentRuntimeSystemPromptVO updateSystemPrompt(
            @RequestHeader("X-User-Roles") String roles,
            @RequestBody AgentRuntimeSystemPromptUpdateDTO request
    ) {
        GatewayRoleGuard.requireAny(roles, "ADMIN");
        return runtimeConfigurationService.updateSystemPrompt(request);
    }

    @GetMapping("/skills")
    public List<AgentRuntimeSkillVO> skills(@RequestHeader("X-User-Roles") String roles) {
        GatewayRoleGuard.requireAny(roles, "ADMIN", "AGENT_OPERATOR");
        return runtimeConfigurationService.skills();
    }

    @GetMapping("/skills/{name}")
    public AgentRuntimeSkillVO skill(
            @RequestHeader("X-User-Roles") String roles,
            @PathVariable String name
    ) {
        GatewayRoleGuard.requireAny(roles, "ADMIN", "AGENT_OPERATOR");
        return runtimeConfigurationService.skill(name);
    }

    @PutMapping("/skills/{name}")
    public AgentRuntimeSkillVO upsertSkill(
            @PathVariable String name,
            @RequestHeader("X-User-Roles") String roles,
            @RequestBody AgentRuntimeSkillUpsertDTO request
    ) {
        GatewayRoleGuard.requireAny(roles, "ADMIN");
        return runtimeConfigurationService.upsertSkill(name, request);
    }

    @GetMapping("/tools")
    public List<AgentRuntimeToolVO> tools(@RequestHeader("X-User-Roles") String roles) {
        GatewayRoleGuard.requireAny(roles, "ADMIN", "AGENT_OPERATOR");
        return runtimeConfigurationService.tools();
    }

    @PutMapping("/tools/{name}")
    public AgentRuntimeToolVO upsertTool(
            @PathVariable String name,
            @RequestHeader("X-User-Roles") String roles,
            @RequestBody AgentRuntimeToolUpsertDTO request
    ) {
        GatewayRoleGuard.requireAny(roles, "ADMIN");
        return runtimeConfigurationService.upsertTool(name, request);
    }
}
