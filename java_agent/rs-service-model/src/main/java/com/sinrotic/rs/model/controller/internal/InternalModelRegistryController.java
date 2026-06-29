package com.sinrotic.rs.model.controller.internal;

import com.sinrotic.rs.model.domain.vo.ModelDefinitionVO;
import com.sinrotic.rs.model.domain.vo.ModelRegistryVO;
import com.sinrotic.rs.model.service.ModelRegistryService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/internal/model")
public class InternalModelRegistryController {

    private final ModelRegistryService modelRegistryService;

    public InternalModelRegistryController(ModelRegistryService modelRegistryService) {
        this.modelRegistryService = modelRegistryService;
    }

    @GetMapping("/registry")
    public ModelRegistryVO listModels() {
        return modelRegistryService.listModels();
    }

    @GetMapping("/{modelKey}")
    public ModelDefinitionVO getModel(@PathVariable String modelKey) {
        return modelRegistryService.getModel(modelKey);
    }
}
