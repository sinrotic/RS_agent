package com.sinrotic.rs.model.controller.platform;

import com.sinrotic.rs.model.domain.vo.ModelRequestTraceVO;
import com.sinrotic.rs.model.service.ModelTraceService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/platform/models")
public class PlatformModelTraceController {

    private final ModelTraceService modelTraceService;

    public PlatformModelTraceController(ModelTraceService modelTraceService) {
        this.modelTraceService = modelTraceService;
    }

    @GetMapping("/requests/{requestId}/trace")
    public ModelRequestTraceVO getTrace(@PathVariable String requestId) {
        return modelTraceService.getTrace(requestId);
    }
}
