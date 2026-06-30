package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.dto.RecallRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.PipelineCandidateVO;
import com.sinrotic.rs.recommend.service.impl.DefaultRecommendPipelineService;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;

class DefaultRecommendPipelineServiceTest {

    @Test
    void recallInvokesTwoTowerProviderWhenSourceIsRequested() {
        CapturingTwoTowerRecallProvider provider = new CapturingTwoTowerRecallProvider(List.of(
                new PipelineCandidateVO("B100", "two_tower", 0.88, null, null, null),
                new PipelineCandidateVO("B101", "two_tower", 0.77, null, null, null)
        ));
        DefaultRecommendPipelineService service = new DefaultRecommendPipelineService(provider);

        var response = service.recall(new RecallRequestDTO(
                "A1XYZ",
                "sess-1",
                5,
                List.of("two_tower", "popular")
        ).withDefaults());

        assertEquals("A1XYZ", provider.userId);
        assertEquals(5, provider.limit);
        assertEquals(2, response.sourceDistribution().get("two_tower"));
        assertEquals("B100", response.candidates().getFirst().itemId());
    }

    @Test
    void recallKeepsExistingMockBehaviorWhenTwoTowerIsNotRequested() {
        CapturingTwoTowerRecallProvider provider = new CapturingTwoTowerRecallProvider(List.of(
                new PipelineCandidateVO("B100", "two_tower", 0.88, null, null, null)
        ));
        DefaultRecommendPipelineService service = new DefaultRecommendPipelineService(provider);

        var response = service.recall(new RecallRequestDTO(
                "A1XYZ",
                "sess-1",
                5,
                List.of("popular")
        ).withDefaults());

        assertEquals(null, provider.userId);
        assertEquals("B001", response.candidates().getFirst().itemId());
        assertEquals("popular", response.candidates().getFirst().source());
    }

    private static final class CapturingTwoTowerRecallProvider implements TwoTowerRecallProvider {
        private final List<PipelineCandidateVO> candidates;
        private String userId;
        private int limit;

        private CapturingTwoTowerRecallProvider(List<PipelineCandidateVO> candidates) {
            this.candidates = candidates;
        }

        @Override
        public List<PipelineCandidateVO> recall(String userId, String requestId, int limit) {
            this.userId = userId;
            this.limit = limit;
            return candidates;
        }
    }
}
