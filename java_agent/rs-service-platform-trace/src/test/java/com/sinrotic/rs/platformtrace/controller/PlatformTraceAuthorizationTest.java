package com.sinrotic.rs.platformtrace.controller;

import com.sinrotic.rs.platformtrace.controller.platform.*;
import com.sinrotic.rs.platformtrace.service.impl.InMemoryPlatformTraceService;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class PlatformTraceAuthorizationTest {
    @Test
    void ordinaryAccountsCannotUseThePlatformObserverClient() throws Exception {
        var mvc = MockMvcBuilders.standaloneSetup(new PlatformUserTraceController(new InMemoryPlatformTraceService()))
                .setControllerAdvice(new PlatformTraceAuthorization()).build();
        mvc.perform(get("/api/platform/accounts/account/profile")).andExpect(status().isForbidden());
        mvc.perform(get("/api/platform/accounts/account/profile").header("X-User-Roles", "USER"))
                .andExpect(status().isForbidden());
        mvc.perform(get("/api/platform/accounts/account/profile").header("X-User-Roles", "OBSERVER"))
                .andExpect(status().isOk());
    }
}
