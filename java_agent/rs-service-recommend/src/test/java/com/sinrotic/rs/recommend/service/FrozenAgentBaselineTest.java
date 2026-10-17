package com.sinrotic.rs.recommend.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.recommend.controller.agent.AgentRecommendController;
import com.sinrotic.rs.recommend.controller.app.RecommendFeedbackController;
import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import com.sinrotic.rs.recommend.service.impl.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.springframework.http.HttpStatus;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.server.ResponseStatusException;

import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;

/** 固定商品与身份 Adapter；通过真实 Java 控制器/偏好/交付/反馈验证，不调用模型。 */
class FrozenAgentBaselineTest {
    private static final ObjectMapper JSON = new ObjectMapper().findAndRegisterModules();
    private static final Path SNAPSHOT = snapshotPath();

    static Stream<Arguments> scenarios() throws Exception {
        var tasks = JSON.readTree(SNAPSHOT.toFile()).get("tasks");
        var cases = new ArrayList<Arguments>();
        for (var task : tasks) for (int repeat = 0; repeat < 2; repeat++) cases.add(Arguments.of(task, repeat));
        return cases.stream();
    }

    @ParameterizedTest(name = "冻结场景 {index}，重复 {1}")
    @MethodSource("scenarios")
    void recommendationFeedbackAndReversalReplayThroughJavaApi(JsonNode task, int repeat) throws Exception {
        var fixture = new Fixture(task);
        var steps = new ArrayList<Map<String, Object>>();
        String requestId = "", feedbackId = "";
        for (var turn : task.get("turns")) {
            if (turn.has("before")) {
                var action = turn.get("before");
                boolean reversal = action.get("action").asText().equals("reversal");
                var payload = reversal ? Map.of("feedback_event_id", feedbackId) : Map.of(
                        "request_id", requestId, "session_id", fixture.session,
                        "item_id", action.get("item_id").asText(), "event_type", "dislike");
                String path = "/api/recommend/feedback/" + (reversal ? "reversal" : "event");
                var ack = fixture.call(path, payload);
                assertThat(ack.path("accepted").asBoolean()).isTrue();
                assertThat(ack.path("application_status").asText()).isEqualTo("APPLIED");
                assertThat(ack.path("duplicate").asBoolean()).isFalse();
                long version = ack.path("preference_version").asLong();
                var duplicate = fixture.call(path, payload);
                assertThat(duplicate.path("duplicate").asBoolean()).isTrue();
                assertThat(duplicate.path("preference_version").asLong()).isEqualTo(version);
                assertThat(duplicate.path("feedback_id").asText()).isEqualTo(ack.path("feedback_id").asText());
                feedbackId = ack.path("feedback_id").asText();
                steps.add(Map.of("action", action.get("action").asText(), "ack", ack,
                        "duplicate_ack", duplicate));
            }
            var response = fixture.recommend(turn);
            requestId = response.path("request_id").asText();
            var actualIds = new ArrayList<String>();
            for (var item : response.get("candidates")) actualIds.add(item.get("item_id").asText());
            var expectedIds = new ArrayList<String>();
            turn.get("expected_item_ids").forEach(item -> expectedIds.add(item.asText()));
            assertThat(actualIds).containsExactlyElementsOf(expectedIds);
            assertThat(actualIds).doesNotContain("pen-unknown", "pen-100");
            steps.add(Map.of("action", "recommend", "query", turn.get("user_message").asText(),
                    "expected_item_ids", expectedIds, "response", response));
        }
        var report = Map.of(
                "schema_version", "rs-agent-api-baseline/1", "task_id", task.get("task_id").asText(),
                "repeat", repeat, "fixture_sha256", HexFormat.of().formatHex(
                        MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(SNAPSHOT))),
                "scope", "Java Controller + 推荐约束/偏好/交付/反馈；合成目录/身份；非模型或真实数据库验收",
                "model_called", false, "steps", steps);
        Path output = Path.of("target/agent-baseline", task.get("task_id").asText() + "-" + repeat + ".json");
        Files.createDirectories(output.getParent());
        JSON.writerWithDefaultPrettyPrinter().writeValue(output.toFile(), report);
    }

    @Test
    void foreignAccountCannotReadCandidatePathOrSubmitFeedback() throws Exception {
        var task = JSON.readTree(SNAPSHOT.toFile()).get("tasks").get(1);
        var fixture = new Fixture(task);
        var first = fixture.recommend(task.get("turns").get(0));
        var payload = fixture.recommendationPayload(task.get("turns").get(0));
        payload.put("account_id", "foreign-account");
        fixture.mvc.perform(post("/agent/recommend/semantic-recall").contentType("application/json")
                .content(JSON.writeValueAsBytes(payload)))
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.status().isForbidden());
        fixture.mvc.perform(post("/api/recommend/feedback/event").contentType("application/json")
                .header("X-Account-Id", "foreign-account").header("X-Profile-User-Id", fixture.profile)
                .content(JSON.writeValueAsBytes(Map.of("request_id", first.path("request_id").asText(),
                        "session_id", fixture.session, "item_id", "pen-10", "event_type", "dislike"))))
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.status().isForbidden());
        assertThat(fixture.recommend(task.get("turns").get(0)).get("candidates").get(0).get("item_id").asText())
                .isEqualTo("pen-10");
    }

    private static Path snapshotPath() {
        for (Path root = Path.of("").toAbsolutePath(); root != null; root = root.getParent()) {
            Path path = root.resolve("python_agent/benchmarks/skill_benchmark/agent-baseline-v1.json");
            if (Files.isRegularFile(path)) return path;
        }
        throw new IllegalStateException("缺少冻结的跨语言验收快照");
    }

    private static final class Fixture {
        final String account, profile, session;
        final MockMvc mvc;

        Fixture(JsonNode task) throws Exception {
            var identity = task.get("trusted_identity");
            account = identity.get("account_id").asText();
            profile = identity.get("profile_user_id").asText();
            session = identity.get("session_id").asText();
            var clock = Clock.fixed(Instant.parse("2026-10-18T00:00:00Z"), ZoneOffset.UTC);
            var items = new ArrayList<ItemEmbeddingText>();
            for (var item : JSON.readTree(SNAPSHOT.toFile()).get("catalog")) {
                items.add(new ItemEmbeddingText(item.get("item_id").asText(), item.get("title").asText(),
                        item.get("title").asText(), item.get("category").asText(), item.get("category").asText(),
                        item.get("brand").asText(), item.get("price").isNull() ? null : item.get("price").decimalValue(),
                        Map.of("currency", item.get("currency").asText())));
            }
            CatalogEmbeddingTextClient catalog = new CatalogEmbeddingTextClient() {
                public List<ItemEmbeddingText> fetchActiveItemEmbeddingTexts(String cursor, int limit) {
                    return cursor.isEmpty() ? List.copyOf(items) : List.of();
                }
                public List<ItemEmbeddingText> fetchItemEmbeddingTexts(List<String> ids) {
                    return items.stream().filter(item -> ids.contains(item.itemId())).toList();
                }
            };
            RecommendationSessionValidator sessions = new RecommendationSessionValidator() {
                public void requireActive(String a, String p, String s) { activeUntil(a, p, s); }
                public Instant activeUntil(String a, String p, String s) {
                    if (!account.equals(a) || !profile.equals(p) || !session.equals(s))
                        throw new ResponseStatusException(HttpStatus.FORBIDDEN);
                    return clock.instant().plus(Duration.ofHours(24));
                }
            };
            var traces = new InMemoryRecommendTraceService();
            var events = new InMemoryRecommendationFeedbackEventStore();
            var preferences = new InMemoryOnlinePreferenceStore(clock);
            var reader = new SessionPreferenceReader(events, preferences, sessions);
            var adjustment = new PreferenceAwareFinalReranker(clock, 30);
            var deliveries = new DefaultRecommendationDeliveryService(
                    new InMemoryRecommendationDeliveryStore(), clock, Duration.ofHours(24));
            var home = new DefaultHomeRecommendService(traces, catalog, deliveries, preferences, adjustment);
            home.setSessionPreferenceReader(reader);
            var ranker = new TrainedAgentCandidateRanker(null, (id, query, candidates) -> Map.of(),
                    catalog, preferences, adjustment, deliveries, traces);
            ranker.setSessionPreferenceReader(reader);
            var agent = new DefaultAgentRecommendService(home, (id, query, limit) -> List.copyOf(items));
            agent.setTrainedAgentRanker(ranker);
            var feedback = new DefaultRecommendFeedbackService(deliveries, events, preferences, clock);
            mvc = MockMvcBuilders.standaloneSetup(new AgentRecommendController(agent, null),
                    new RecommendFeedbackController(feedback, sessions)).build();
        }

        java.util.HashMap<String, Object> recommendationPayload(JsonNode turn) {
            return new java.util.HashMap<>(Map.of("account_id", account, "profile_user_id", profile,
                    "session_id", session, "task_id", session, "agent_id", "baseline-agent",
                    "query", turn.get("user_message").asText(), "return_count", turn.get("limit").asInt(),
                    "recall_limit", 20, "constraints", turn.get("constraints")));
        }

        JsonNode recommend(JsonNode turn) throws Exception {
            return call("/agent/recommend/semantic-recall", recommendationPayload(turn));
        }

        JsonNode call(String path, Object payload) throws Exception {
            var response = mvc.perform(post(path).contentType("application/json")
                    .header("X-Account-Id", account).header("X-Profile-User-Id", profile)
                    .content(JSON.writeValueAsBytes(payload))).andReturn().getResponse();
            assertThat(response.getStatus()).as(path).isEqualTo(200);
            return JSON.readTree(response.getContentAsByteArray());
        }
    }
}
