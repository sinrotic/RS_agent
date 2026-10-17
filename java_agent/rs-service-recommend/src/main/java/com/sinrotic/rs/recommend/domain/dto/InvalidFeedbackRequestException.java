package com.sinrotic.rs.recommend.domain.dto;

public final class InvalidFeedbackRequestException extends IllegalArgumentException {
    public InvalidFeedbackRequestException(String message) { super(message); }
}
