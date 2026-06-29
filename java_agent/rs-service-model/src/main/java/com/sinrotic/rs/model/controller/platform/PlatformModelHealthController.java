package com.sinrotic.rs.model.controller.platform;

import com.sinrotic.rs.model.domain.vo.ModelHealthVO;
import com.sinrotic.rs.model.domain.vo.ModelRuntimeHealthVO;
import com.sinrotic.rs.model.service.ModelHealthService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/platform/models")
public class PlatformModelHealthController {

    private final ModelHealthService modelHealthService;

    public PlatformModelHealthController(ModelHealthService modelHealthService) {
        this.modelHealthService = modelHealthService;
    }

    @GetMapping("/health")
    public ModelHealthVO getHealth() {
        return modelHealthService.getHealth();
    }

    @GetMapping("/{modelKey}/health")
    public ModelRuntimeHealthVO getModelHealth(@PathVariable String modelKey) {
        return modelHealthService.getModelHealth(modelKey);
    }
}
