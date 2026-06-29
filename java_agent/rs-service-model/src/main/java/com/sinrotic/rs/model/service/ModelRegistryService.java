package com.sinrotic.rs.model.service;

import com.sinrotic.rs.model.domain.vo.ModelDefinitionVO;
import com.sinrotic.rs.model.domain.vo.ModelRegistryVO;

public interface ModelRegistryService {

    ModelRegistryVO listModels();

    ModelRegistryVO listPlatformModels();

    ModelDefinitionVO getModel(String modelKey);

    ModelDefinitionVO getPlatformModel(String modelKey);
}
