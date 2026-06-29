package com.sinrotic.rs.platformtrace.controller.platform;

import com.sinrotic.rs.platformtrace.domain.vo.PlatformAccountProfileVO;
import com.sinrotic.rs.platformtrace.service.PlatformTraceService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/platform/accounts")
public class PlatformUserTraceController {

    private final PlatformTraceService traceService;

    public PlatformUserTraceController(PlatformTraceService traceService) {
        this.traceService = traceService;
    }

    @GetMapping("/{accountId}/profile")
    public PlatformAccountProfileVO accountProfile(@PathVariable String accountId) {
        return traceService.accountProfile(accountId);
    }
}
