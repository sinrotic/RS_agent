# Model Service Controller MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first compilable `rs-service-model` Spring Boot module with internal model gateway controllers and platform/app observation controllers.

**Architecture:** Keep controllers thin and route all behavior through service interfaces. Use an in-memory mock implementation for registry, inference, chat, health, and trace responses so upstream services can integrate against stable contracts before Triton/vLLM are wired.

**Tech Stack:** Java 21, Maven, Spring Boot Web, JUnit 5, MockMvc.

---

### Task 1: Maven Module and Controller Contracts

**Files:**
- Create: `java_agent/rs-service-model/pom.xml`
- Modify: `java_agent/pom.xml`
- Create: `java_agent/rs-service-model/src/test/java/com/sinrotic/rs/model/controller/internal/InternalModelControllerTest.java`
- Create: `java_agent/rs-service-model/src/test/java/com/sinrotic/rs/model/controller/platform/PlatformModelControllerTest.java`
- Create: `java_agent/rs-service-model/src/test/java/com/sinrotic/rs/model/controller/app/ModelHealthControllerTest.java`

- [ ] **Step 1: Write controller tests**

Add MockMvc tests for `/internal/model/registry`, `/internal/model/infer`, `/internal/model/chat`, `/api/platform/models`, `/api/platform/models/health`, `/api/platform/models/requests/{requestId}/trace`, and `/api/model/health`.

- [ ] **Step 2: Run tests and verify RED**

Run: `mvn -pl rs-service-model test`
Expected: compilation fails because model controller and service classes do not exist yet.

### Task 2: Domain DTO/VO and Services

**Files:**
- Create: `java_agent/rs-service-model/src/main/java/com/sinrotic/rs/model/domain/dto/*.java`
- Create: `java_agent/rs-service-model/src/main/java/com/sinrotic/rs/model/domain/vo/*.java`
- Create: `java_agent/rs-service-model/src/main/java/com/sinrotic/rs/model/service/*.java`
- Create: `java_agent/rs-service-model/src/main/java/com/sinrotic/rs/model/service/impl/*.java`

- [ ] **Step 1: Implement records for request/response contracts**

Use snake_case JSON property names via `@JsonProperty` so API shape matches existing Java services.

- [ ] **Step 2: Implement mock services**

Return deterministic model registry, health, inference, chat, and trace data.

### Task 3: Controllers and Verification

**Files:**
- Create: `java_agent/rs-service-model/src/main/java/com/sinrotic/rs/model/ModelServiceApplication.java`
- Create: `java_agent/rs-service-model/src/main/java/com/sinrotic/rs/model/controller/internal/*.java`
- Create: `java_agent/rs-service-model/src/main/java/com/sinrotic/rs/model/controller/platform/*.java`
- Create: `java_agent/rs-service-model/src/main/java/com/sinrotic/rs/model/controller/app/*.java`

- [ ] **Step 1: Implement thin controllers**

Controllers delegate to services and do not call runtime clients directly.

- [ ] **Step 2: Run tests and verify GREEN**

Run: `mvn -pl rs-service-model test`
Expected: all model service tests pass.

- [ ] **Step 3: Build module**

Run: `mvn -pl rs-service-model -DskipTests package`
Expected: module compiles and packages successfully.
