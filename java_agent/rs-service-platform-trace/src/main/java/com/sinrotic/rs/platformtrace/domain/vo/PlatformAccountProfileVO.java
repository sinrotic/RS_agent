package com.sinrotic.rs.platformtrace.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

public record PlatformAccountProfileVO(
        @JsonProperty("account_id")
        String accountId,
        @JsonProperty("profile_user_id")
        String profileUserId,
        @JsonProperty("profile_summary")
        String profileSummary,
        @JsonProperty("top_categories")
        List<String> topCategories,
        @JsonProperty("top_stores")
        List<String> topStores
) {
    public PlatformAccountProfileVO {
        topCategories = topCategories == null ? List.of() : List.copyOf(topCategories);
        topStores = topStores == null ? List.of() : List.copyOf(topStores);
    }

    public static PlatformAccountProfileVO empty(String accountId) {
        return new PlatformAccountProfileVO(
                accountId,
                "",
                "No account profile trace captured yet.",
                List.of(),
                List.of()
        );
    }
}
