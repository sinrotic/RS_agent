package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

public record RagAgentContextVO(
        String instruction,
        @JsonProperty("public_payload_allowed")
        boolean publicPayloadAllowed
) {
}
