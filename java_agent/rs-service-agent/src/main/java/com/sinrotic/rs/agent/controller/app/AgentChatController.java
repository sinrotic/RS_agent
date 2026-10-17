package com.sinrotic.rs.agent.controller.app;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.dto.AgentInterruptRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentChatVO;
import com.sinrotic.rs.agent.domain.vo.AgentInterruptVO;
import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;
import com.sinrotic.rs.agent.service.AgentChatService;
import com.sinrotic.rs.agent.service.AgentChatStreamService;
import com.sinrotic.rs.agent.service.AgentInterrupter;
import com.sinrotic.rs.agent.service.AgentTraceService;
import com.sinrotic.rs.agent.service.PublicAgentStreamProjector;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.HashMap;
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
    public Map<String, Object> chat(
            @RequestHeader("X-Account-Id") String accountId,
            @RequestHeader("X-Profile-User-Id") String profileUserId,
            @RequestBody AgentChatRequestDTO request
    ) {
        AgentChatRequestDTO trustedRequest = withTrustedIdentity(request, accountId, profileUserId);
        validateChatRequest(trustedRequest);
        AgentChatVO response = chatService.chat(trustedRequest);
        var raw = objectMapper.convertValue(response, new com.fasterxml.jackson.core.type.TypeReference<Map<String, Object>>() {});
        raw.put("answer_blocks", response.answerBlocks().stream().map(block -> streamProjector.project(
                new AgentStreamEventVO("answer_block", response.requestId(), block)).orElseThrow().data()).toList());
        var projected = streamProjector.project(new AgentStreamEventVO("done", response.requestId(), Map.of("response", raw))).orElseThrow();
        return objectMapper.convertValue(projected.data().get("response"), new com.fasterxml.jackson.core.type.TypeReference<Map<String, Object>>() {});
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, String>> invalidRequest(IllegalArgumentException exception) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(Map.of(
                "code", "INVALID_AGENT_REQUEST",
                "message", exception.getMessage()
        ));
    }

    @PostMapping("/chat/stream")
    public ResponseEntity<StreamingResponseBody> streamChat(
            @RequestHeader("X-Account-Id") String accountId,
            @RequestHeader("X-Profile-User-Id") String profileUserId,
            @RequestBody AgentChatRequestDTO request
    ) {
        AgentChatRequestDTO trustedRequest = withTrustedIdentity(request, accountId, profileUserId);
        validateChatRequest(trustedRequest);
        StreamingResponseBody body = outputStream -> {
            OutputStreamWriter writer = new OutputStreamWriter(outputStream, StandardCharsets.UTF_8);
            AtomicReference<String> requestIdRef = new AtomicReference<>("");
            try {
                streamService.streamChat(trustedRequest, event -> {
                    if (requestIdRef.get().isBlank() && event.requestId() != null && !event.requestId().isBlank()) {
                        writeSseEvent(writer, new AgentStreamEventVO("started", event.requestId(), Map.of("request_id", event.requestId())));
                    }
                    requestIdRef.set(event.requestId());
                    streamProjector.project(event).ifPresent(projected -> writeSseEvent(writer, projected));
                });
            } catch (Exception ex) {
                if (!requestIdRef.get().isBlank()) {
                    interrupter.interruptOwned(requestIdRef.get(), accountId, profileUserId, "stream_disconnected");
                }
                writeStreamError(writer, requestIdRef.get(), ex);
            }
        };
        return ResponseEntity.ok()
                .contentType(MediaType.TEXT_EVENT_STREAM)
                .body(body);
    }

    @GetMapping("/sessions/{sessionId}/history")
    public com.sinrotic.rs.agent.domain.vo.AgentPublicHistoryVO history(
            @RequestHeader("X-Account-Id") String accountId,
            @RequestHeader("X-Profile-User-Id") String profileUserId, @PathVariable String sessionId) {
        var turns = traceService.sessionTurns(sessionId, profileUserId, accountId).turns();
        var result = new java.util.ArrayList<com.sinrotic.rs.agent.domain.vo.AgentPublicHistoryVO.Turn>();
        for (var turn : turns) {
            var blocks = turn.answerBlocks().stream().map(block -> streamProjector.project(
                    new AgentStreamEventVO("answer_block", turn.requestId(), block)).orElseThrow().data()).toList();
            result.add(new com.sinrotic.rs.agent.domain.vo.AgentPublicHistoryVO.Turn(turn.requestId(), result.size() + 1,
                    turn.userMessage(), turn.assistantMessage(), turn.recommendedItemIds(), blocks,
                    turn.finishReason(), turn.cardSetId(), com.sinrotic.rs.agent.service.AgentRecommendationDelivery.publicReasons(turn.degradationReasons())));
        }
        return new com.sinrotic.rs.agent.domain.vo.AgentPublicHistoryVO(sessionId, java.util.List.copyOf(result));
    }

    @GetMapping("/sessions/{sessionId}/turns")
    public com.sinrotic.rs.agent.domain.vo.AgentPublicHistoryVO sessionTurns(
            @RequestHeader("X-Account-Id") String accountId,
            @RequestHeader("X-Profile-User-Id") String profileUserId,
            @PathVariable String sessionId
    ) {
        return history(accountId, profileUserId, sessionId);
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

    @PostMapping("/requests/{requestId}/interrupt")
    public AgentInterruptVO interrupt(
            @PathVariable String requestId,
            @RequestHeader("X-Account-Id") String accountId,
            @RequestHeader("X-Profile-User-Id") String profileUserId,
            @RequestBody(required = false) AgentInterruptRequestDTO request
    ) {
        String reason = request == null ? "user_interrupt" : request.resolvedReason();
        boolean interrupted = interrupter.interruptOwned(requestId, accountId, profileUserId, reason);
        return new AgentInterruptVO(requestId, interrupted, reason);
    }

    private AgentChatRequestDTO withTrustedIdentity(
            AgentChatRequestDTO request,
            String accountId,
            String profileUserId
    ) {
        if (request == null) {
            throw new IllegalArgumentException("request body is required");
        }
        Map<String, Object> context = new HashMap<>(request.resolvedContext());
        context.put("authenticated_account_id", accountId);
        context.put("authenticated_profile_user_id", profileUserId);
        return new AgentChatRequestDTO(
                request.sessionId(),
                profileUserId,
                request.userMessage(),
                request.limit(),
                Map.copyOf(context)
        );
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

    private void writeStreamError(OutputStreamWriter writer, String requestId, Exception ex) {
        int status = ex instanceof org.springframework.web.server.ResponseStatusException response
                ? response.getStatusCode().value()
                : ex instanceof com.sinrotic.rs.agent.service.AgentSessionNotFoundException ? 404
                : ex instanceof com.sinrotic.rs.agent.service.AgentBusyException ? 503 : 500;
        String code = switch (status) {
            case 409 -> "TURN_CONFLICT";
            case 410 -> "SESSION_ENDED";
            case 404 -> "SESSION_NOT_FOUND";
            case 503, 429 -> "AGENT_BUSY";
            default -> "AGENT_STREAM_FAILED";
        };
        writeSseEvent(writer, new AgentStreamEventVO("error", requestId, Map.of(
                "message", "agent stream failed",
                "error_code", code, "status", status, "retryable", status >= 500 || status == 429
        )));
        writeSseEvent(writer, new AgentStreamEventVO("done", requestId, Map.of(
                "done", true,
                "finish_reason", "error"
        )));
    }
}
