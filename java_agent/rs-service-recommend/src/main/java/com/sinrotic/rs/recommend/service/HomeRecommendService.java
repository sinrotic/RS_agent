package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.dto.HomeRecommendRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.HomeRecommendVO;

/**
 * Orchestrates homepage recommendation from session context to final top20 response.
 */
public interface HomeRecommendService {

    HomeRecommendVO recommendHome(HomeRecommendRequestDTO request);
}
