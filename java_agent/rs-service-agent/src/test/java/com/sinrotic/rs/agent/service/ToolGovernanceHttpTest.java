package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.config.*;
import com.sinrotic.rs.agent.domain.*;
import com.sinrotic.rs.agent.service.impl.*;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.*;

@Timeout(8)
class ToolGovernanceHttpTest {
    @Test
    void actualHttp503RetriesAnAllowedReadBut401AndMalformedResponsesDoNot() throws Exception {
        var calls = new AtomicInteger(); var mode = new AtomicInteger();
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/support", exchange -> {
            exchange.getRequestBody().readAllBytes(); int current = calls.incrementAndGet();
            int status = mode.get() == 1 ? 401 : mode.get() == 0 && current == 1 ? 503 : 200;
            byte[] body = (mode.get() == 2 ? "malformed-json" : "{\"item_support\":{}}").getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(status, body.length); exchange.getResponseBody().write(body); exchange.close();
        });
        server.start();
        var properties = new AgentDelegateProperties(); properties.ragAgent().setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
        properties.ragAgent().setSupportPath("/support");
        var runtime = new InMemoryAgentRuntimeConfigurationService();
        var settings = new AgentToolGovernanceProperties(); settings.setRetryDelayMs(0);
        var event = AgentModelStreamEvent.toolUse("call_agent", Map.of("agent_name", "rag_agent", "query", "背包"));
        try (var raw = new VirtualThreadAgentToolUseExecutor(runtime, new HttpAgentDelegateService(properties, new JavaNetAgentModelProviderHttpClient()));
             var governed = new GovernedAgentToolUseExecutor(new AgentCapabilityToolUseExecutor(raw, new InMemoryAgentCapabilityRegistry(), runtime),
                     settings, runtime, new InMemoryAgentCapabilityRegistry())) {
            var result = governed.execute(event).join();
            assertThat(result).containsEntry("status", "SUCCESS"); assertThat(calls.get()).isEqualTo(2);
            mode.set(1); calls.set(0);
            result = governed.execute(event).join();
            assertThat(result).containsEntry("error_code", "TOOL_AUTHORIZATION"); assertThat(calls.get()).isEqualTo(1);
            mode.set(2); calls.set(0);
            result = governed.execute(event).join();
            assertThat(result).containsEntry("error_code", "TOOL_INVALID_RESPONSE"); assertThat(calls.get()).isEqualTo(1);
        } finally { server.stop(0); }
    }

    @Test
    void capabilityErrorClassificationSurvivesTheRegistryAndEveryRetryIsReauthorized() {
        var calls = new AtomicInteger(); var audits = new AtomicInteger(); var runtime = new InMemoryAgentRuntimeConfigurationService();
        var registry = new InMemoryAgentCapabilityRegistry(event -> audits.incrementAndGet());
        registry.register(new AgentCapability() {
            @Override public AgentCapabilityDescriptor descriptor() { return new AgentCapabilityDescriptor("recommend", "test read", Map.of(), true, false); }
            @Override public AgentCapabilityResult execute(AgentCapabilityRequest request) {
                if (calls.incrementAndGet() == 1) throw new IllegalStateException("wrapped", new AgentToolDependencyException(503));
                return AgentCapabilityResult.success("recommend", Map.of("items", java.util.List.of()));
            }
        });
        var settings = new AgentToolGovernanceProperties(); settings.setRetryDelayMs(0);
        try (var raw = new VirtualThreadAgentToolUseExecutor();
             var governed = new GovernedAgentToolUseExecutor(new AgentCapabilityToolUseExecutor(raw, registry, runtime), settings, runtime, registry)) {
            assertThat(governed.execute(AgentModelStreamEvent.toolUse("recommend_candidates", Map.of())).join()).containsEntry("status", "SUCCESS");
            assertThat(calls.get()).isEqualTo(2); assertThat(audits.get()).isEqualTo(2);
        }
    }
}
