package com.sinrotic.rs.agent.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.service.AgentSessionAdmissionClient;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.Map;

public final class HttpAgentSessionAdmissionClient implements AgentSessionAdmissionClient {
    private final String baseUrl;
    private final HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(1)).build();
    private final ObjectMapper mapper = new ObjectMapper();
    public HttpAgentSessionAdmissionClient(String baseUrl) { this.baseUrl = baseUrl.replaceAll("/+$", ""); }
    @Override
    public void verifyOwner(String accountId, String profileUserId, String sessionId) {
        try {
            String path = java.net.URLEncoder.encode(sessionId, java.nio.charset.StandardCharsets.UTF_8).replace("+", "%20");
            var response = client.send(HttpRequest.newBuilder(URI.create(baseUrl + "/api/sessions/" + path))
                    .timeout(Duration.ofSeconds(2)).header("X-Account-Id", accountId).header("X-Profile-User-Id", profileUserId)
                    .GET().build(), HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() == 404 || response.statusCode() == 401 || response.statusCode() == 403)
                throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Session was not found");
            if (response.statusCode() != 200) throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Session validation unavailable");
            var session = mapper.readTree(response.body());
            if (!sessionId.equals(session.path("sessionId").asText()) || !accountId.equals(session.path("accountId").asText())
                    || !profileUserId.equals(session.path("profileUserId").asText()))
                throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Session was not found");
        } catch (ResponseStatusException failure) { throw failure; }
        catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Session validation interrupted");
        } catch (Exception unavailable) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Session validation unavailable");
        }
    }
    @Override
    public void admit(AgentChatRequestDTO request) {
        try {
            String account = String.valueOf(request.resolvedContext().getOrDefault("authenticated_account_id", ""));
            if (account.isBlank()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Session was not found");
            String path = java.net.URLEncoder.encode(request.sessionId(), java.nio.charset.StandardCharsets.UTF_8).replace("+", "%20");
            String body = mapper.writeValueAsString(Map.of("account_id", account, "profile_user_id", request.profileUserId(), "query", request.userMessage()));
            var response = client.send(HttpRequest.newBuilder(URI.create(baseUrl + "/internal/sessions/" + path + "/admit"))
                    .timeout(Duration.ofSeconds(2)).header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(body)).build(), HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() == 410) throw new ResponseStatusException(HttpStatus.GONE, "Session has ended");
            if (response.statusCode() == 404 || response.statusCode() == 401 || response.statusCode() == 403)
                throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Session was not found");
            if (response.statusCode() != 200 || !mapper.readTree(response.body()).path("accepted").asBoolean(false))
                throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Session validation unavailable");
        } catch (ResponseStatusException failure) { throw failure; }
        catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Session validation interrupted");
        } catch (Exception unavailable) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Session validation unavailable");
        }
    }
}
