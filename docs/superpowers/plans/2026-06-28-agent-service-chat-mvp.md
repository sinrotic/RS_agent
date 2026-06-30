# Agent Service Chat MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first usable `rs-service-agent` Spring Boot module with chat, session turn history, and platform trace endpoints backed by deterministic in-memory orchestration.

**Architecture:** Keep controllers thin and route behavior through service interfaces. The MVP does not call downstream recommend/rag/model services yet; it returns stable mock orchestration artifacts that match the future service boundary.

**Tech Stack:** Java 21, Maven, Spring Boot Web, JUnit 5, MockMvc.

---

### Task 1: Controller Contract Tests

**Files:**
- Modify: `java_agent/rs-service-agent/pom.xml`
- Create: `java_agent/rs-service-agent/src/test/java/com/sinrotic/rs/agent/controller/app/AgentChatControllerTest.java`
- Create: `java_agent/rs-service-agent/src/test/java/com/sinrotic/rs/agent/controller/platform/PlatformAgentTraceControllerTest.java`

- [ ] **Step 1: Add test dependency**

Add `spring-boot-starter-test` to `rs-service-agent` so MockMvc tests compile.

- [ ] **Step 2: Write failing app controller tests**

Cover `POST /api/agent/chat` and `GET /api/agent/sessions/{sessionId}/turns`. Assert snake_case fields: `request_id`, `session_id`, `assistant_message`, `recommended_items`, `tool_calls`, and `turns`.

- [ ] **Step 3: Write failing platform trace test**

Cover `GET /api/platform/agent/{sessionId}/turns`. Assert it delegates to the same trace service and returns session-level tool call evidence.

- [ ] **Step 4: Run RED**

Run `mvn -pl rs-service-agent test`. Expected: compilation fails because controller, DTO, VO, and service classes do not exist.

### Task 2: Agent DTO/VO and Service Contracts

**Files:**
- Create: `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/domain/dto/AgentChatRequestDTO.java`
- Create: `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/domain/vo/AgentChatVO.java`
- Create: `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/domain/vo/AgentRecommendedItemVO.java`
- Create: `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/domain/vo/AgentSessionTraceVO.java`
- Create: `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/domain/vo/AgentToolCallVO.java`
- Create: `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/domain/vo/AgentTurnVO.java`
- Create: `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/AgentChatService.java`
- Create: `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/AgentTraceService.java`

- [ ] **Step 1: Implement records with `@JsonProperty`**

Use Java records and explicit snake_case JSON names to match adjacent services.

- [ ] **Step 2: Define service interfaces**

Expose `AgentChatService.chat(AgentChatRequestDTO)`, `AgentTraceService.sessionTurns(String)`, and `AgentTraceService.platformSessionTrace(String)`.

- [ ] **Step 3: Run compile check**

Run `mvn -pl rs-service-agent test`. Expected: tests still fail because implementations and controllers are missing.

### Task 3: In-Memory Agent Orchestration

**Files:**
- Create: `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/InMemoryAgentOrchestrationService.java`

- [ ] **Step 1: Implement deterministic chat response**

Return a generated `request_id`, user/session echo fields, one assistant message, two recommended item placeholders, and three tool calls: `recommend_candidates`, `rag_support`, and `model_chat`.

- [ ] **Step 2: Store turns by session**

Keep an in-memory session map so chat calls are visible through both app and platform trace endpoints.

- [ ] **Step 3: Run service-backed tests**

Run `mvn -pl rs-service-agent test`. Expected: tests still fail only because controllers/application are missing.

### Task 4: Controllers and Application

**Files:**
- Create: `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/AgentServiceApplication.java`
- Create: `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/controller/app/AgentChatController.java`
- Create: `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/controller/platform/PlatformAgentTraceController.java`

- [ ] **Step 1: Implement thin controllers**

`AgentChatController` delegates chat and session turns to services. `PlatformAgentTraceController` delegates platform trace to the trace service.

- [ ] **Step 2: Run GREEN**

Run `mvn -pl rs-service-agent test`. Expected: all `rs-service-agent` tests pass.

- [ ] **Step 3: Build module**

Run `mvn -pl rs-service-agent -DskipTests package`. Expected: module packages successfully.
