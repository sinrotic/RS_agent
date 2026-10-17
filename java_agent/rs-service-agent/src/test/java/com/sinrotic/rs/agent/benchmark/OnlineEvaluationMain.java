package com.sinrotic.rs.agent.benchmark;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentRecommendedItemVO;
import com.sinrotic.rs.agent.service.impl.HttpAgentOnlineEvaluationObserver;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentOrchestrationService;
import java.net.URI;
import java.util.List;
import java.util.Map;

/** Test-only real orchestration/export harness; model and products are controlled fixtures. */
public final class OnlineEvaluationMain {
    public static void main(String[] args) throws Exception {
        var mapper = new ObjectMapper();
        var input = mapper.readValue(System.in.readAllBytes(), Map.class);
        String baseUrl = (String) input.get("base_url");
        if (!"127.0.0.1".equals(URI.create(baseUrl).getHost()))
            throw new IllegalArgumentException("Test harness only accepts loopback");
        var observer = new HttpAgentOnlineEvaluationObserver(true, baseUrl, "test-token",
                (String) input.get("outbox"), "shopping-v1", "controlled-recommendation-model");
        try {
            var service = new InMemoryAgentOrchestrationService();
            service.setOnlineEvaluationObserver(observer);
            service.setRecommendationService(request -> List.of(
                    new AgentRecommendedItemVO("pen", "Gel Pen 0.7mm", "Gel Ink Rollerball Pens", .9, "目录候选")));
            for (int i = 0; i < 3; i++) service.chat(new AgentChatRequestDTO(
                    "online-session-" + i, "online-profile-" + i, "想买笔，预算20元，帮我挑一款", 1, Map.of()));
            long deadline = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(10);
            while ((long) observer.diagnostics().get("delivered") < 3 && System.nanoTime() < deadline)
                Thread.sleep(10);
            if ((long) observer.diagnostics().get("delivered") != 3)
                throw new IllegalStateException("Shadow export failed");
            System.out.println(mapper.writeValueAsString(observer.diagnostics()));
        } finally { observer.close(); }
    }
}
