package com.sinrotic.rs.agent.controller.app;

import com.sinrotic.rs.agent.service.*;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentInterrupter;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class AgentInterruptOwnershipTest {
    @Test
    void sameProfileDoesNotGrantAnotherAccountInterruptPermission() throws Exception {
        var interrupter = new InMemoryAgentInterrupter();
        var context = interrupter.createTurn("request", "session", "owner", "shared-profile");
        var mvc = MockMvcBuilders.standaloneSetup(new AgentChatController(mock(AgentChatService.class),
                mock(AgentChatStreamService.class), mock(AgentTraceService.class), interrupter)).build();
        mvc.perform(post("/api/agent/requests/request/interrupt").header("X-Profile-User-Id", "shared-profile"))
                .andExpect(status().isBadRequest());
        mvc.perform(post("/api/agent/requests/request/interrupt").header("X-Account-Id", "other")
                .header("X-Profile-User-Id", "shared-profile"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.interrupted").value(false));
        assertThat(context.interrupted()).isFalse();
        assertThat(interrupter.interruptOwned("request", "shared-profile", "legacy_bypass")).isFalse();
        mvc.perform(post("/api/agent/requests/request/interrupt").header("X-Account-Id", "owner")
                .header("X-Profile-User-Id", "shared-profile"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.interrupted").value(true));
    }
}
