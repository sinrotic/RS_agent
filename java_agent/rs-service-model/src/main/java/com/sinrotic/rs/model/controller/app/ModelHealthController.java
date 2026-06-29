package com.sinrotic.rs.model.controller.app;

import com.sinrotic.rs.model.domain.vo.ModelHealthVO;
import com.sinrotic.rs.model.service.ModelHealthService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/model")
public class ModelHealthController {

    private final ModelHealthService modelHealthService;

    public ModelHealthController(ModelHealthService modelHealthService) {
        this.modelHealthService = modelHealthService;
    }

    @GetMapping("/health")
    public ModelHealthVO getHealth() {
        return modelHealthService.getHealth();
    }
}
