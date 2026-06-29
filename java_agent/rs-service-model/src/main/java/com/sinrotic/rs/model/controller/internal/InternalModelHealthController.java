package com.sinrotic.rs.model.controller.internal;

import com.sinrotic.rs.model.domain.vo.ModelRuntimeHealthVO;
import com.sinrotic.rs.model.service.ModelHealthService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/internal/model")
public class InternalModelHealthController {

    private final ModelHealthService modelHealthService;

    public InternalModelHealthController(ModelHealthService modelHealthService) {
        this.modelHealthService = modelHealthService;
    }

    @GetMapping("/{modelKey}/health")
    public ModelRuntimeHealthVO getModelHealth(@PathVariable String modelKey) {
        return modelHealthService.getModelHealth(modelKey);
    }
}
