package com.sinrotic.rs.model.controller.platform;

import com.sinrotic.rs.model.domain.vo.ModelDefinitionVO;
import com.sinrotic.rs.model.domain.vo.ModelRegistryVO;
import com.sinrotic.rs.model.service.ModelRegistryService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/platform/models")
public class PlatformModelRegistryController {

    private final ModelRegistryService modelRegistryService;

    public PlatformModelRegistryController(ModelRegistryService modelRegistryService) {
        this.modelRegistryService = modelRegistryService;
    }

    @GetMapping
    public ModelRegistryVO listModels() {
        return modelRegistryService.listPlatformModels();
    }

    @GetMapping("/{modelKey}")
    public ModelDefinitionVO getModel(@PathVariable String modelKey) {
        return modelRegistryService.getPlatformModel(modelKey);
    }
}
