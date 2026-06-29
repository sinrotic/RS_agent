package com.sinrotic.rs.searchrag.service;

import com.sinrotic.rs.searchrag.domain.dto.RagPipelineRunRequestDTO;
import com.sinrotic.rs.searchrag.domain.vo.RagPipelineRunVO;

/**
 * Internal RAG evidence pipeline contract.
 */
public interface RagPipelineService {

    RagPipelineRunVO run(RagPipelineRunRequestDTO request);
}
