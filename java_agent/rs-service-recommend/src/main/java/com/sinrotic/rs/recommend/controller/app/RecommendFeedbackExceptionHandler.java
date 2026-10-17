package com.sinrotic.rs.recommend.controller.app;

import com.sinrotic.rs.recommend.service.RecommendationFeedbackRejectedException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.Map;

@RestControllerAdvice
public class RecommendFeedbackExceptionHandler {
    @ExceptionHandler(com.sinrotic.rs.recommend.domain.dto.InvalidFeedbackRequestException.class)
    public ResponseEntity<Map<String,Object>> invalid(com.sinrotic.rs.recommend.domain.dto.InvalidFeedbackRequestException exception) {
        return ResponseEntity.badRequest().body(Map.of("error", Map.of("code", "INVALID_FEEDBACK_REQUEST", "message", exception.getMessage())));
    }

    @ExceptionHandler(RecommendationFeedbackRejectedException.class)
    public ResponseEntity<Map<String, Object>> rejected(RecommendationFeedbackRejectedException exception) {
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY).body(Map.of(
                "error", Map.of("code", exception.code(), "message", exception.getMessage())
        ));
    }
}
