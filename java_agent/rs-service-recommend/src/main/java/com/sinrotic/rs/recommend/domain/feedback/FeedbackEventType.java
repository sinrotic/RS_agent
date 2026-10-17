package com.sinrotic.rs.recommend.domain.feedback;

import java.util.Locale;

public enum FeedbackEventType {
    EXPOSURE(false),
    CLICK(false),
    LIKE(true),
    DISLIKE(true),
    WHY(false),
    REVERSAL(true);

    private final boolean preferenceChanging;

    FeedbackEventType(boolean preferenceChanging) {
        this.preferenceChanging = preferenceChanging;
    }

    public boolean preferenceChanging() {
        return preferenceChanging;
    }

    public static FeedbackEventType parse(String value) {
        try {
            return valueOf(value.toUpperCase(Locale.ROOT));
        } catch (RuntimeException exception) {
            throw new IllegalArgumentException("unsupported feedback event type: " + value, exception);
        }
    }

    public String apiValue() {
        return name().toLowerCase(Locale.ROOT);
    }
}
