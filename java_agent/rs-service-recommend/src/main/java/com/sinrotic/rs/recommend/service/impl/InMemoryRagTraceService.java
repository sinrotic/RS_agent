package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.vo.RagHealthProviderVO;
import com.sinrotic.rs.recommend.domain.vo.RagHealthVO;
import com.sinrotic.rs.recommend.domain.vo.RagPipelineProviderStatusVO;
import com.sinrotic.rs.recommend.domain.vo.RagPipelineStageCountsVO;
import com.sinrotic.rs.recommend.domain.vo.RagTraceVO;
import com.sinrotic.rs.recommend.service.RagTraceService;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;

/**
 * In-memory trace placeholder until recommendation RAG pipeline persistence is added.
 */
@Service
public class InMemoryRagTraceService implements RagTraceService {

    @Override
    public RagTraceVO getTrace(String requestId) {
        return new RagTraceVO(
                requestId,
                "",
                "",
                List.of(
                        new RagPipelineProviderStatusVO("elasticsearch_bm25", "READY", 0, 0),
                        new RagPipelineProviderStatusVO("milvus_vector", "READY", 0, 0)
                ),
                Map.of("elasticsearch_bm25", 0, "milvus_vector", 0),
                new RagPipelineStageCountsVO(0, 0, 0, 0, 0),
                "",
                0
        );
    }

    @Override
    public RagHealthVO health() {
        return new RagHealthVO(
                "UP",
                List.of(
                        new RagHealthProviderVO("elasticsearch_bm25", "READY", "rs_agent_rag_bm25_v1", ""),
                        new RagHealthProviderVO("milvus_vector", "READY", "", "rs_agent_rag_chunks_milvus_v1")
                )
        );
    }
}
