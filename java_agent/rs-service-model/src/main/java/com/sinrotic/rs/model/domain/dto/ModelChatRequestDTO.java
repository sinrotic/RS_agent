package com.sinrotic.rs.model.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;
import java.util.Map;

public record ModelChatRequestDTO(
        @JsonProperty("model_key") String modelKey,
        @JsonProperty("request_id") String requestId,
        List<ModelMessageDTO> messages,
        Map<String, Object> options
) {

    public ModelChatRequestDTO {
        messages = messages == null ? List.of() : List.copyOf(messages);
        options = options == null ? Map.of() : Map.copyOf(options);
    }
}
