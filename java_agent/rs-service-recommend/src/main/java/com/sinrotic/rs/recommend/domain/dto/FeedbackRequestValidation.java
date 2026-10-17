package com.sinrotic.rs.recommend.domain.dto;

import java.time.Instant;

final class FeedbackRequestValidation {
    static final int MAX_EXPOSURE_ITEMS = 100;
    private static final Instant MIN_TIME = Instant.parse("1000-01-01T00:00:00Z");
    private static final Instant MAX_TIME = Instant.parse("9999-12-31T23:59:59.999Z");
    private FeedbackRequestValidation() { }

    static void text(String value, String name) {
        if (value == null || value.isBlank()) fail(name + "不能为空");
    }
    static void timestamp(Long value, String name) {
        if (value != null) {
            Instant instant = Instant.ofEpochMilli(value);
            if (instant.isBefore(MIN_TIME) || instant.isAfter(MAX_TIME)) fail(name + "超出有效时间范围");
        }
    }
    static void fail(String message) { throw new InvalidFeedbackRequestException(message); }
}
