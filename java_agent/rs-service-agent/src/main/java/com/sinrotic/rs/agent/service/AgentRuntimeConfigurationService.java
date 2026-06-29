package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.dto.AgentRuntimeSkillUpsertDTO;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeSystemPromptUpdateDTO;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeToolUpsertDTO;
import com.sinrotic.rs.agent.domain.vo.AgentRuntimeSkillVO;
import com.sinrotic.rs.agent.domain.vo.AgentRuntimeSystemPromptVO;
import com.sinrotic.rs.agent.domain.vo.AgentRuntimeToolVO;

import java.util.List;
import java.util.Map;

public interface AgentRuntimeConfigurationService {

    AgentRuntimeSystemPromptVO systemPrompt();

    AgentRuntimeSystemPromptVO updateSystemPrompt(AgentRuntimeSystemPromptUpdateDTO request);

    List<AgentRuntimeSkillVO> skills();

    AgentRuntimeSkillVO skill(String name);

    AgentRuntimeSkillVO upsertSkill(String name, AgentRuntimeSkillUpsertDTO request);

    List<AgentRuntimeToolVO> tools();

    AgentRuntimeToolVO upsertTool(String name, AgentRuntimeToolUpsertDTO request);

    Map<String, Object> modelContext();

    List<String> runtimeContextMessages();
}
