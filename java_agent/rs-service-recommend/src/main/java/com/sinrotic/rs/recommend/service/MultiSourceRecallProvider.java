package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.vo.PipelineCandidateVO;
import java.util.List;
import java.util.Map;

public interface MultiSourceRecallProvider {
    List<String> SOURCES = List.of("itemcf_weak", "itemcf_strong", "swing_recall", "usercf_recall", "category", "popular");
    Map<String, List<PipelineCandidateVO>> recall(String profileUserId, List<String> history, List<String> sources, int limit);
}
