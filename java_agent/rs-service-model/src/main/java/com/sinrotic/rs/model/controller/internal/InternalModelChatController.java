package com.sinrotic.rs.model.controller.internal;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.model.domain.dto.ModelChatRequestDTO;
import com.sinrotic.rs.model.domain.vo.ModelChatVO;
import com.sinrotic.rs.model.domain.vo.ModelChatStreamEventVO;
import com.sinrotic.rs.model.service.ModelGatewayService;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;

@RestController
@RequestMapping("/internal/model")
public class InternalModelChatController {

    private final ModelGatewayService modelGatewayService;

    private final ObjectMapper objectMapper = new ObjectMapper();

    public InternalModelChatController(ModelGatewayService modelGatewayService) {
        this.modelGatewayService = modelGatewayService;
    }

    @PostMapping("/chat")
    public ModelChatVO chat(@RequestBody ModelChatRequestDTO request) {
        return modelGatewayService.chat(request);
    }

    @PostMapping("/chat/stream")
    public ResponseEntity<StreamingResponseBody> streamChat(@RequestBody ModelChatRequestDTO request) {
        StreamingResponseBody body = outputStream -> {
            OutputStreamWriter writer = new OutputStreamWriter(outputStream, StandardCharsets.UTF_8);
            for (ModelChatStreamEventVO event : modelGatewayService.streamChat(request)) {
                writer.write("event: " + event.event() + "\n");
                writer.write("data: " + objectMapper.writeValueAsString(event) + "\n\n");
                writer.flush();
            }
        };
        return ResponseEntity.ok()
                .contentType(MediaType.TEXT_EVENT_STREAM)
                .body(body);
    }
}
