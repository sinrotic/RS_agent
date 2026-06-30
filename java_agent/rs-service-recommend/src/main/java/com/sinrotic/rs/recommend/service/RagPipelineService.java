package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.dto.RagPipelineRunRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.RagPipelineRunVO;

public interface RagPipelineService {

    RagPipelineRunVO run(RagPipelineRunRequestDTO request);
}
