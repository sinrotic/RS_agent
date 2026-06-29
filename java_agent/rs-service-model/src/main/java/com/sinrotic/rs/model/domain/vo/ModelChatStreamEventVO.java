package com.sinrotic.rs.model.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

public record ModelChatStreamEventVO(
        @JsonProperty("event")
        String event,
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("delta")
        String delta,
        @JsonProperty("done")
        boolean done
) {
}
