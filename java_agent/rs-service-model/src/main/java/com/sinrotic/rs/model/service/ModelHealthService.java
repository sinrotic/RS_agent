package com.sinrotic.rs.model.service;

import com.sinrotic.rs.model.domain.vo.ModelHealthVO;
import com.sinrotic.rs.model.domain.vo.ModelRuntimeHealthVO;

public interface ModelHealthService {

    ModelHealthVO getHealth();

    ModelRuntimeHealthVO getModelHealth(String modelKey);
}
