package com.sinrotic.rs.model.controller.app;

import com.sinrotic.rs.model.domain.vo.ModelHealthVO;
import com.sinrotic.rs.model.service.ModelHealthService;
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

class ModelHealthControllerTest {

    private MockMvc mockMvc;

    private ModelHealthService healthService;

    @BeforeEach
    void setUp() {
        healthService = mock(ModelHealthService.class);
        mockMvc = MockMvcBuilders
                .standaloneSetup(new ModelHealthController(healthService))
                .build();
    }

    @Test
    void appHealthReturnsServiceReadiness() throws Exception {
        when(healthService.getHealth()).thenReturn(new ModelHealthVO(
                "UP",
                Map.of("status", "UP", "model_count", 4, "enabled_model_count", 4),
                List.of()
        ));

        mockMvc.perform(get("/api/model/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("UP"))
                .andExpect(jsonPath("$.manifest.enabled_model_count").value(4));
    }
}
