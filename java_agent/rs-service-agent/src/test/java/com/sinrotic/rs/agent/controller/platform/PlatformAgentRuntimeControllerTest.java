package com.sinrotic.rs.agent.controller.platform;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeSkillUpsertDTO;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeSystemPromptUpdateDTO;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeToolUpsertDTO;
import com.sinrotic.rs.agent.domain.vo.AgentRuntimeSkillVO;
import com.sinrotic.rs.agent.domain.vo.AgentRuntimeSystemPromptVO;
import com.sinrotic.rs.agent.domain.vo.AgentRuntimeToolVO;
import com.sinrotic.rs.agent.service.AgentRuntimeConfigurationService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class PlatformAgentRuntimeControllerTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    private MockMvc mockMvc;

    private AgentRuntimeConfigurationService runtimeConfigurationService;

    @BeforeEach
    void setUp() {
        runtimeConfigurationService = mock(AgentRuntimeConfigurationService.class);
        mockMvc = MockMvcBuilders
                .standaloneSetup(new PlatformAgentRuntimeController(runtimeConfigurationService))
                .build();
    }

    @Test
    void systemPromptCanBeReadAndUpdatedFromPlatform() throws Exception {
        when(runtimeConfigurationService.systemPrompt()).thenReturn(new AgentRuntimeSystemPromptVO(
                "default",
                "Use concise recommendation reasoning."
        ));
        when(runtimeConfigurationService.updateSystemPrompt(argThat(request ->
                "custom".equals(request.name())
                        && "Prefer tool evidence.".equals(request.content())
        ))).thenReturn(new AgentRuntimeSystemPromptVO("custom", "Prefer tool evidence."));

        mockMvc.perform(get("/api/platform/agent/runtime/system-prompt"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.name").value("default"))
                .andExpect(jsonPath("$.content").value("Use concise recommendation reasoning."));

        mockMvc.perform(put("/api/platform/agent/runtime/system-prompt")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(new AgentRuntimeSystemPromptUpdateDTO(
                                "custom",
                                "Prefer tool evidence."
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.name").value("custom"))
                .andExpect(jsonPath("$.content").value("Prefer tool evidence."));

        verify(runtimeConfigurationService).updateSystemPrompt(argThat(request ->
                "custom".equals(request.name())
                        && "Prefer tool evidence.".equals(request.content())
        ));
    }

    @Test
    void skillsCanBeListedReadAndOverriddenFromPlatform() throws Exception {
        AgentRuntimeSkillVO skill = new AgentRuntimeSkillVO(
                "explicit-need-recommendation",
                "Use when the user gives a clear need.",
                "custom",
                true,
                "---\nname: explicit-need-recommendation\n---\n# Workflow\n"
        );
        when(runtimeConfigurationService.skills()).thenReturn(List.of(skill));
        when(runtimeConfigurationService.skill("explicit-need-recommendation")).thenReturn(skill);
        when(runtimeConfigurationService.upsertSkill(
                "explicit-need-recommendation",
                new AgentRuntimeSkillUpsertDTO(
                        "Use when the user gives a clear need.",
                        "---\nname: explicit-need-recommendation\n---\n# Workflow\n",
                        true
                )
        )).thenReturn(skill);

        mockMvc.perform(get("/api/platform/agent/runtime/skills"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].name").value("explicit-need-recommendation"))
                .andExpect(jsonPath("$[0].source").value("custom"))
                .andExpect(jsonPath("$[0].enabled").value(true));

        mockMvc.perform(get("/api/platform/agent/runtime/skills/explicit-need-recommendation"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.content").value(skill.content()));

        mockMvc.perform(put("/api/platform/agent/runtime/skills/explicit-need-recommendation")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(new AgentRuntimeSkillUpsertDTO(
                                "Use when the user gives a clear need.",
                                skill.content(),
                                true
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.name").value("explicit-need-recommendation"))
                .andExpect(jsonPath("$.source").value("custom"));
    }

    @Test
    void toolDefinitionsCanBeListedAndUpdatedWithoutExecutingTools() throws Exception {
        AgentRuntimeToolVO tool = new AgentRuntimeToolVO(
                "recommend_candidates",
                "rs-service-recommend",
                "Fetch candidate items.",
                true,
                Map.of("type", "object")
        );
        when(runtimeConfigurationService.tools()).thenReturn(List.of(tool));
        when(runtimeConfigurationService.upsertTool(
                "recommend_candidates",
                new AgentRuntimeToolUpsertDTO(
                        "rs-service-recommend",
                        "Fetch candidate items.",
                        true,
                        Map.of("type", "object")
                )
        )).thenReturn(tool);

        mockMvc.perform(get("/api/platform/agent/runtime/tools"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].name").value("recommend_candidates"))
                .andExpect(jsonPath("$[0].service").value("rs-service-recommend"));

        mockMvc.perform(put("/api/platform/agent/runtime/tools/recommend_candidates")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(new AgentRuntimeToolUpsertDTO(
                                "rs-service-recommend",
                                "Fetch candidate items.",
                                true,
                                Map.of("type", "object")
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.enabled").value(true));
    }
}
