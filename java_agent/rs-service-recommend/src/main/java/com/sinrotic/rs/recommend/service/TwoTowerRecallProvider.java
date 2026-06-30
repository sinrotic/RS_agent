package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.vo.PipelineCandidateVO;

import java.util.List;

/**
 * Produces two-tower recall candidates for a profile user.
 */
public interface TwoTowerRecallProvider {

    List<PipelineCandidateVO> recall(String userId, String requestId, int limit);
}
