package com.sinrotic.rs.agent.controller.app;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.dto.AgentInterruptRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentChatVO;
import com.sinrotic.rs.agent.domain.vo.AgentInterruptVO;
import com.sinrotic.rs.agent.domain.vo.AgentSessionTraceVO;
import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;
import com.sinrotic.rs.agent.service.AgentChatService;
import com.sinrotic.rs.agent.service.AgentChatStreamService;
import com.sinrotic.rs.agent.service.AgentInterrupter;
import com.sinrotic.rs.agent.service.AgentTraceService;
import com.sinrotic.rs.agent.service.PublicAgentStreamProjector;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

@RestController
@RequestMapping("/api/agent")
public class AgentChatController {

    private final AgentChatService chatService;

    private final AgentChatStreamService streamService;

    private final AgentTraceService traceService;

    private final AgentInterrupter interrupter;

    private final ObjectMapper objectMapper = new ObjectMapper();

    private final PublicAgentStreamProjector streamProjector = new PublicAgentStreamProjector();

    public AgentChatController(
            AgentChatService chatService,
            AgentChatStreamService streamService,
            AgentTraceService traceService,
            AgentInterrupter interrupter
    ) {
        this.chatService = chatService;
        this.streamService = streamService;
        this.traceService = traceService;
        this.interrupter = interrupter;
    }

    @PostMapping("/chat")
    public AgentChatVO chat(@RequestBody AgentChatRequestDTO request) {
        validateChatRequest(request);
        return chatService.chat(request);
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, String>> invalidRequest(IllegalArgumentException exception) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(Map.of(
                "code", "INVALID_AGENT_REQUEST",
                "message", exception.getMessage()
        ));
    }

    @PostMapping("/chat/stream")
    public ResponseEntity<StreamingResponseBody> streamChat(@RequestBody AgentChatRequestDTO request) {
        StreamingResponseBody body = outputStream -> {
            OutputStreamWriter writer = new OutputStreamWriter(outputStream, StandardCharsets.UTF_8);
            AtomicReference<String> requestIdRef = new AtomicReference<>("");
            try {
                streamService.streamChat(request, event -> {
                    requestIdRef.set(event.requestId());
                    streamProjector.project(event).ifPresent(projected -> writeSseEvent(writer, projected));
                });
            } catch (Exception ex) {
                writeStreamError(writer, requestIdRef.get(), ex);
            }
        };
        return ResponseEntity.ok()
                .contentType(MediaType.TEXT_EVENT_STREAM)
                .body(body);
    }

    @GetMapping("/sessions/{sessionId}/turns")
    public AgentSessionTraceVO sessionTurns(@PathVariable String sessionId) {
        return traceService.sessionTurns(sessionId);
    }

    @PostMapping("/requests/{requestId}/interrupt")
    public AgentInterruptVO interrupt(
            @PathVariable String requestId,
            @RequestBody(required = false) AgentInterruptRequestDTO request
    ) {
        String reason = request == null ? "user_interrupt" : request.resolvedReason();
        boolean interrupted = interrupter.interrupt(requestId, reason);
        return new AgentInterruptVO(requestId, interrupted, reason);
    }

    private void writeSseEvent(OutputStreamWriter writer, AgentStreamEventVO event) {
        try {
            writer.write("event: " + event.event() + "\n");
            writer.write("data: " + objectMapper.writeValueAsString(event.data()) + "\n\n");
            writer.flush();
        } catch (java.io.IOException ex) {
            throw new IllegalStateException("failed to write agent stream event", ex);
        }
    }

    private void validateChatRequest(AgentChatRequestDTO request) {
        if (request == null || isBlank(request.sessionId())) {
            throw new IllegalArgumentException("session_id is required");
        }
        if (isBlank(request.profileUserId())) {
            throw new IllegalArgumentException("profile_user_id is required");
        }
        if (isBlank(request.userMessage())) {
            throw new IllegalArgumentException("user_message is required");
        }
    }

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }

    private void writeStreamError(OutputStreamWriter writer, String requestId, Exception ex) {
        writeSseEvent(writer, new AgentStreamEventVO("error", requestId, Map.of(
                "message", "agent stream failed",
                "error_code", "AGENT_STREAM_FAILED"
        )));
        writeSseEvent(writer, new AgentStreamEventVO("done", requestId, Map.of(
                "done", true,
                "finish_reason", "error"
        )));
    }
}
