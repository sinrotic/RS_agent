package com.sinrotic.rs.recommend.service;

public class RecommendationFeedbackRejectedException extends RuntimeException {

    private final String code;

    public RecommendationFeedbackRejectedException(String code, String message) {
        super(message);
        this.code = code;
    }

    public String code() {
        return code;
    }
}
