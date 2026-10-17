# Agent Virtual Thread Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run agent turns on virtual-thread-friendly request paths while protecting model, tool, and session resources with explicit limits.

**Architecture:** Keep `AgentLoop` as a single-turn synchronous state machine. Add small limiter/scheduler components around the existing orchestration path: global active-loop permits, model-stream permits, tool-call permits, and per-session serial execution.

**Tech Stack:** Java 21 virtual threads, Spring Boot 4, Spring MVC `StreamingResponseBody`, JUnit 5, AssertJ.

---

### Task 1: Execution Limits

**Files:**
- Create: `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/config/AgentExecutionProperties.java`
- Create: `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/AgentExecutionLimiter.java`
- Create: `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/AgentBusyException.java`
- Test: `java_agent/rs-service-agent/src/test/java/com/sinrotic/rs/agent/service/AgentExecutionLimiterTest.java`

- [ ] Write failing tests for permit acquisition, timeout/busy, and release on exception.
- [ ] Implement `Semaphore`-based permits for active loops, model streams, and tools.
- [ ] Expose conservative default values from `rs.agent.execution`.

### Task 2: Session Serial Scheduler

**Files:**
- Create: `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/AgentSessionTurnScheduler.java`
- Create: `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/InMemoryAgentSessionTurnScheduler.java`
- Test: `java_agent/rs-service-agent/src/test/java/com/sinrotic/rs/agent/service/AgentSessionTurnSchedulerTest.java`

- [ ] Write failing tests showing same-session turns run serially and different-session turns can overlap.
- [ ] Implement per-session fair semaphore plus bounded in-flight queue accounting.
- [ ] Release session accounting on success, failure, and timeout.

### Task 3: Wire Into Agent Runtime

**Files:**
- Modify: `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/InMemoryAgentOrchestrationService.java`
- Modify: `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/AgentLoop.java`
- Modify: `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/VirtualThreadAgentToolUseExecutor.java`
- Modify: `java_agent/rs-service-agent/src/main/resources/application.yml`
- Test: existing service tests plus new limiter/scheduler tests.

- [ ] Wrap streaming turns with `sessionScheduler.runExclusive()` and `executionLimiter.runWithActiveLoop()`.
- [ ] Wrap model streaming with `executionLimiter.runWithModelStream()`.
- [ ] Wrap tool execution with `executionLimiter.callWithToolPermit()`.
- [ ] Enable Spring virtual threads through configuration.
- [ ] Run focused tests, then the service module test set.

### Self-Review

- The plan covers virtual-thread enablement, explicit resource limits, and per-session ordering.
- There are no intentionally deferred requirements in this first slice.
- The implementation does not pool `AgentLoop` objects and does not make shared turn state mutable across threads.
