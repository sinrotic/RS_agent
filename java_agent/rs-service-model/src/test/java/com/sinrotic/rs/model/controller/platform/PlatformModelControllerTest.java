package com.sinrotic.rs.model.controller.platform;

import com.sinrotic.rs.model.domain.vo.ModelDefinitionVO;
import com.sinrotic.rs.model.domain.vo.ModelHealthVO;
import com.sinrotic.rs.model.domain.vo.ModelRegistryVO;
import com.sinrotic.rs.model.domain.vo.ModelRequestTraceVO;
import com.sinrotic.rs.model.service.ModelHealthService;
import com.sinrotic.rs.model.service.ModelRegistryService;
import com.sinrotic.rs.model.service.ModelTraceService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.Map;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class PlatformModelControllerTest {

    private MockMvc mockMvc;

    private ModelRegistryService registryService;

    private ModelHealthService healthService;

    private ModelTraceService traceService;

    @BeforeEach
    void setUp() {
        registryService = mock(ModelRegistryService.class);
        healthService = mock(ModelHealthService.class);
        traceService = mock(ModelTraceService.class);
        mockMvc = MockMvcBuilders.standaloneSetup(
                new PlatformModelRegistryController(registryService),
                new PlatformModelHealthController(healthService),
                new PlatformModelTraceController(traceService)
        ).build();
    }

    @Test
    void platformModelsHideRuntimeEndpoint() throws Exception {
        when(registryService.listPlatformModels()).thenReturn(new ModelRegistryVO(List.of(new ModelDefinitionVO(
                "agent_4b",
                "llm",
                "vllm",
                "v1",
                null,
                null,
                30000,
                null,
                "gpu",
                true
        ))));

        mockMvc.perform(get("/api/platform/models"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.models[0].model_key").value("agent_4b"))
                .andExpect(jsonPath("$.models[0].runtime").value("vllm"))
                .andExpect(jsonPath("$.models[0].endpoint").doesNotExist());
    }

    @Test
    void platformHealthReturnsManifestAndRuntimeStatus() throws Exception {
        when(healthService.getHealth()).thenReturn(new ModelHealthVO(
                "UP",
                Map.of("status", "UP", "model_count", 4, "enabled_model_count", 4),
                List.of(Map.of("name", "vllm-agent", "type", "vllm", "status", "UP"))
        ));

        mockMvc.perform(get("/api/platform/models/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("UP"))
                .andExpect(jsonPath("$.manifest.model_count").value(4))
                .andExpect(jsonPath("$.runtimes[0].name").value("vllm-agent"));
    }

    @Test
    void platformTraceReturnsModelRequestTrace() throws Exception {
        when(traceService.getTrace("agent_req_001")).thenReturn(new ModelRequestTraceVO(
                "agent_req_001",
                "agent_4b",
                "v1",
                "vllm",
                1280,
                "SUCCESS",
                null
        ));

        mockMvc.perform(get("/api/platform/models/requests/agent_req_001/trace"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("agent_req_001"))
                .andExpect(jsonPath("$.model_key").value("agent_4b"))
                .andExpect(jsonPath("$.status").value("SUCCESS"));
    }
}
