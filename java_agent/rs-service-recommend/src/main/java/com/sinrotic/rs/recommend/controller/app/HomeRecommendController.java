package com.sinrotic.rs.recommend.controller.app;

import com.sinrotic.rs.recommend.domain.dto.HomeRecommendRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.HomeRecommendRefreshRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.HomeRecommendVO;
import com.sinrotic.rs.recommend.service.HomeRecommendService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Provides homepage recommendation results for the frontend.
 */
@RestController
@RequestMapping("/api/recommend")
public class HomeRecommendController {

    private final HomeRecommendService homeRecommendService;

    public HomeRecommendController(HomeRecommendService homeRecommendService) {
        this.homeRecommendService = homeRecommendService;
    }

    @PostMapping("/home")
    public HomeRecommendVO recommendHome(@RequestBody HomeRecommendRequestDTO request) {
        return homeRecommendService.recommendHome(request.withDefaults());
    }

    @PostMapping("/home/refresh")
    public HomeRecommendVO refreshHome(@RequestBody HomeRecommendRefreshRequestDTO request) {
        return homeRecommendService.recommendHome(request.toHomeRecommendRequest());
    }
}
