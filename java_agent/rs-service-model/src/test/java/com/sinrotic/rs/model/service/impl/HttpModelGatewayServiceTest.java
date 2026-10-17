package com.sinrotic.rs.model.service.impl;

import com.sinrotic.rs.model.domain.dto.*;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import org.springframework.web.server.ResponseStatusException;
import java.util.*;
import java.io.IOException;
import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.*;
import static org.springframework.test.web.client.response.MockRestResponseCreators.*;

class HttpModelGatewayServiceTest {
    @Test
    void readOnlyInferenceRetriesOneConnectionFailureWithIdenticalInput() {
        var builder = RestClient.builder();
        var server = MockRestServiceServer.bindTo(builder).build();
        var service = new HttpModelGatewayService(builder, "http://runtime", "http://runtime");
        server.expect(requestTo("http://runtime/internal/model/embed"))
                .andExpect(jsonPath("$.request_id").value("retry"))
                .andExpect(jsonPath("$.inputs.texts[0]").value("mouse"))
                .andRespond(withException(new IOException("connection reset")));
        server.expect(requestTo("http://runtime/internal/model/embed"))
                .andExpect(jsonPath("$.request_id").value("retry"))
                .andExpect(jsonPath("$.inputs.texts[0]").value("mouse"))
                .andRespond(withSuccess("{\"request_id\":\"retry\",\"model_key\":\"bge-m3\",\"latency_ms\":1,\"vectors\":[{\"id\":\"text_0\",\"vector\":[0.5,0.7],\"metadata\":{}}],\"usage\":{}}", MediaType.APPLICATION_JSON));
        assertEquals(List.of(0.5,0.7), service.embed(new ModelEmbedRequestDTO("bge-m3","retry",
                Map.of("texts",List.of("mouse")),Map.of())).vectors().getFirst().vector());
        assertEquals("SUCCESS", service.getTrace("retry").status());
        server.verify();
    }

    @Test
    void repeatedConnectionFailureIsBoundedAndRecorded() {
        var builder = RestClient.builder();
        var server = MockRestServiceServer.bindTo(builder).build();
        var service = new HttpModelGatewayService(builder, "http://runtime", "http://runtime");
        for (int i = 0; i < 2; i++) server.expect(requestTo("http://runtime/internal/model/rank"))
                .andRespond(withException(new IOException("connection reset")));
        assertEquals(503, assertThrows(ResponseStatusException.class, () -> service.rank(new ModelRankRequestDTO(
                "bge-reranker-v2-m3","bounded",Map.of(),Map.of()))).getStatusCode().value());
        assertEquals("FAILED", service.getTrace("bounded").status());
        server.verify();
    }

    @Test
    void httpFailuresAreNotRetriedAsTransportFailures() {
        var builder = RestClient.builder();
        var server = MockRestServiceServer.bindTo(builder).build();
        var service = new HttpModelGatewayService(builder, "http://runtime", "http://runtime");
        server.expect(requestTo("http://runtime/internal/model/rank")).andRespond(withServerError());
        assertEquals(503, assertThrows(ResponseStatusException.class, () -> service.rank(new ModelRankRequestDTO(
                "bge-reranker-v2-m3","http-error",Map.of(),Map.of()))).getStatusCode().value());
        server.verify();
    }
    @Test
    void productionContextSelectsRealAdaptersAndMocksRequireExplicitProfile() {
        for (boolean mock : List.of(false, true)) {
            try (var context = new org.springframework.context.annotation.AnnotationConfigApplicationContext()) {
                if (mock) context.getEnvironment().setActiveProfiles("mock-models");
                context.registerBean(RestClient.Builder.class, () -> RestClient.builder());
                context.register(HttpModelGatewayService.class, HttpModelHealthService.class,
                        ConfiguredModelRegistryService.class, MockModelGatewayService.class,
                        MockModelHealthService.class, MockModelTraceService.class, InMemoryModelRegistryService.class);
                context.refresh();
                var gateway = context.getBean(com.sinrotic.rs.model.service.ModelGatewayService.class);
                assertEquals(mock ? MockModelGatewayService.class : HttpModelGatewayService.class, gateway.getClass());
                assertNotNull(context.getBean(com.sinrotic.rs.model.service.ModelHealthService.class));
                assertNotNull(context.getBean(com.sinrotic.rs.model.service.ModelTraceService.class));
                assertNotNull(context.getBean(com.sinrotic.rs.model.service.ModelRegistryService.class));
            }
        }
    }
    @Test
    void embeddingOnlyRuntimeDoesNotReportRerankingAsHealthy() {
        var builder = RestClient.builder();
        var server = MockRestServiceServer.bindTo(builder).build();
        var health = new HttpModelHealthService(builder, "http://runtime", "http://runtime");
        server.expect(requestTo("http://runtime/health"))
                .andRespond(withSuccess("{\"status\":\"UP\",\"capabilities\":[\"embed\"]}", MediaType.APPLICATION_JSON));
        assertEquals("DOWN", health.getModelHealth("bge-reranker-v2-m3").status());
        assertEquals("UNCONFIGURED", health.getModelHealth("agent_4b").status());
        assertEquals("DOWN", new HttpModelHealthService(builder, "", "").getHealth().status());
        server.verify();
    }
    @Test
    void configuredEmbeddingUsesRuntimeAndMissingRerankerReturns503() {
        var builder = RestClient.builder();
        var server = MockRestServiceServer.bindTo(builder).build();
        var service = new HttpModelGatewayService(builder, "http://embedding", "");
        server.expect(requestTo("http://embedding/internal/model/embed"))
                .andExpect(jsonPath("$.inputs.texts[0]").value("headphones"))
                .andRespond(withSuccess("{\"request_id\":\"request\",\"model_key\":\"bge-m3\",\"model_version\":\"local\",\"runtime\":\"sentence_transformers\",\"latency_ms\":1,\"vectors\":[{\"id\":\"text_0\",\"vector\":[0.5,0.7],\"metadata\":{}}],\"usage\":{}}", MediaType.APPLICATION_JSON));
        var result = service.embed(new ModelEmbedRequestDTO("bge-m3", "request", Map.of("texts", List.of("headphones")), Map.of()));
        assertEquals(List.of(0.5, 0.7), result.vectors().getFirst().vector());
        assertEquals("SUCCESS", service.getTrace("request").status());
        assertEquals(404, assertThrows(ResponseStatusException.class, () -> service.getTrace("unknown")).getStatusCode().value());
        assertEquals(503, assertThrows(ResponseStatusException.class,
                () -> service.rank(new ModelRankRequestDTO("bge-reranker-v2-m3", "request", Map.of(), Map.of())))
                .getStatusCode().value());
        server.verify();
    }
}
