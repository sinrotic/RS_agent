# Agent Chat Wire Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 让 Java 同步聊天接口与 React 前端共享同一套 snake_case JSON 契约，并用可观察的 TDD 循环落实服务端 turn_index、请求校验和前端运行时映射。

**Architecture:** java_agent/contracts/agent-chat 保存唯一 request/response 示例；Java MockMvc 严格比较 JSON 树，React 在 agentContract.ts 中隔离 wire model 与页面 model。AgentChatController 只负责边界校验，InMemoryAgentOrchestrationService 负责按 session 产生从 1 开始的 turn_index，agentClient 负责构建请求、校验响应并映射为现有页面类型。

**Tech Stack:** Java 21、Spring Boot 4.0.3、Maven 3.9.9、JUnit Jupiter、Mockito、MockMvc、Jakarta Bean Validation、React 18、TypeScript、Vite 4、Vitest 0.34.6、Node 22。

## Global Constraints

- HTTP request/response JSON 必须使用 snake_case；React 页面内部继续使用 camelCase。
- POST /api/agent/chat 的请求固定包含 session_id、profile_user_id、user_message、limit: 5、context.scene: "agent_chat"。
- session_id、profile_user_id 和去除首尾空白后的 user_message 必须非空；非法请求返回 HTTP 400，且不得调用 AgentChatService。
- 正式响应必须包含 request_id、session_id、profile_user_id、turn_index、assistant_message、recommended_items、tool_calls。
- turn_index 由服务端按 session 已记录的同步 turn 数计算，从 1 开始；前端不得猜测或生成替代轮次。
- 前端收到缺失或非法 request_id、turn_index、assistant_message 时必须抛出明确的契约错误；不得生成假 request id。
- recommended_items 映射为 RecommendItemVO：rank 为数组下标加一，source_tags 固定为 ["agent_recommendation"]，store 与 image_url 暂为空字符串。
- 不修改 /api/agent/chat/stream、Gateway、Session、Recommend、RAG、Catalog、Cloudflare Tunnel 或远程 Compose。
- 不把本切片扩展为“同步 chat 接入真实 AgentLoop”；该行为属于后续 No-Mock Golden Path 切片。
- 每个 RED 都必须先运行并确认是预期业务缺口，再写对应的最小生产代码。
- 在 RED、GREEN、相关回归三个位置暂停，展示命令、失败或通过证据与局部 diff。
- 当前主工作区已有大量用户改动。执行前必须使用 superpowers:using-git-worktrees 创建 codex/agent-chat-wire-contract 隔离工作树；不得在当前脏工作树直接实施或整文件覆盖。
- 本计划完成后只做本地验证，不执行远程部署；远程 smoke 属于黄金链路后续切片。

---

## File Map

- Create: java_agent/contracts/agent-chat/request.json — canonical request fixture。
- Create: java_agent/contracts/agent-chat/response.json — canonical response fixture。
- Modify: java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/domain/vo/AgentChatVO.java — 增加 turnIndex wire 字段。
- Modify: java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/InMemoryAgentOrchestrationService.java:133-160 — 记录并返回 session turn index。
- Create: java_agent/rs-service-agent/src/test/java/com/sinrotic/rs/agent/service/AgentChatTurnIndexTest.java — 独立验证每个 session 的轮次。
- Modify: java_agent/rs-service-agent/src/test/java/com/sinrotic/rs/agent/controller/app/AgentChatControllerTest.java:145-196 — 使用共享 fixture 严格验证 wire JSON。
- Modify: java_agent/rs-service-agent/pom.xml:15-25 — 增加 Bean Validation starter。
- Modify: java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/domain/dto/AgentChatRequestDTO.java:7-18 — 标注三个必填字段。
- Modify: java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/controller/app/AgentChatController.java:55-58 — 只对同步 chat 启用 @Valid。
- Modify: java_agent/frontend/package.json — 固定 Vitest 并增加 test script。
- Modify: java_agent/frontend/package-lock.json — 锁定 Vitest 依赖图。
- Create: java_agent/frontend/src/api/agentContract.ts — wire types、request builder、runtime response mapper。
- Create: java_agent/frontend/src/api/agentContract.test.ts — 共享 fixture 驱动的纯映射与 client 契约测试。
- Modify: java_agent/frontend/src/types/agent.ts — 保留 camelCase 页面模型并令 requestId 必填。
- Modify: java_agent/frontend/src/api/agentClient.ts:6-56 — 三参数 API、canonical request、unknown response 映射。
- Modify: java_agent/frontend/src/views/AgentChat.tsx:76-78,146-148 — 传 profileUserId，并移除假 request id fallback。

## Execution Preflight

- [ ] **Step 1: Create an isolated worktree**

Use superpowers:using-git-worktrees and create branch:

~~~text
codex/agent-chat-wire-contract
~~~

Expected: the new worktree starts from commit b08a6daa or a direct descendant, and git status is clean. Do not copy the current working tree's uncommitted Java changes into it.

- [ ] **Step 2: Confirm toolchain from the isolated worktree**

Run from the isolated repository root:

~~~powershell
mvn -version
node --version
npm --version
git status --short
~~~

Expected: Maven uses Java 21, Node is 22.x, npm is 10.x, and git status prints nothing.

### Task 1: Canonical Java Response and Session Turn Index

**Files:**
- Create: java_agent/contracts/agent-chat/request.json
- Create: java_agent/contracts/agent-chat/response.json
- Modify: java_agent/rs-service-agent/src/test/java/com/sinrotic/rs/agent/controller/app/AgentChatControllerTest.java
- Modify: java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/domain/vo/AgentChatVO.java
- Create: java_agent/rs-service-agent/src/test/java/com/sinrotic/rs/agent/service/AgentChatTurnIndexTest.java
- Modify: java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/InMemoryAgentOrchestrationService.java

**Interfaces:**
- Consumes: POST /api/agent/chat and the existing AgentChatService.chat(AgentChatRequestDTO) boundary.
- Produces: AgentChatVO.turnIndex(): int and two shared JSON fixtures used later by TypeScript.

- [ ] **Step 1: Add the canonical request fixture**

Create java_agent/contracts/agent-chat/request.json:

~~~json
{
  "session_id": "sess_001",
  "profile_user_id": "A1XYZ",
  "user_message": "想要一个通勤背包",
  "limit": 5,
  "context": {
    "scene": "agent_chat"
  }
}
~~~

- [ ] **Step 2: Add the canonical response fixture**

Create java_agent/contracts/agent-chat/response.json:

~~~json
{
  "request_id": "agent_req_001",
  "session_id": "sess_001",
  "profile_user_id": "A1XYZ",
  "turn_index": 1,
  "assistant_message": "我会优先推荐通勤背包，并补充可解释证据。",
  "recommended_items": [
    {
      "item_id": "B001",
      "title": "Commuter Backpack",
      "category": "Backpacks",
      "score": 0.91,
      "reason": "匹配通勤、轻量和中价位偏好"
    }
  ],
  "tool_calls": [
    {
      "tool_call_id": "toolu_001",
      "tool_name": "recommend_candidates",
      "service": "rs-service-recommend",
      "status": "SUCCESS",
      "metadata": {
        "limit": 5
      }
    }
  ]
}
~~~

- [ ] **Step 3: Replace the existing synchronous controller assertion with a strict fixture test**

In AgentChatControllerTest.java, add imports for JsonNode, Files, Path, StandardCharsets, MvcResult, and AssertJ. Add these helpers inside the test class:

~~~java
private String readContract(String fileName) throws Exception {
    Path path = Path.of(System.getProperty("basedir"))
            .resolve("../contracts/agent-chat")
            .resolve(fileName)
            .normalize();
    return Files.readString(path, StandardCharsets.UTF_8);
}

private JsonNode readContractJson(String fileName) throws Exception {
    return objectMapper.readTree(readContract(fileName));
}
~~~

Replace chatReturnsAssistantMessageRecommendationsAndToolTrace() with:

~~~java
@Test
void chatMatchesSharedWireContract() throws Exception {
    AgentChatVO response = new AgentChatVO(
            "agent_req_001",
            "sess_001",
            "A1XYZ",
            "我会优先推荐通勤背包，并补充可解释证据。",
            List.of(new AgentRecommendedItemVO(
                    "B001",
                    "Commuter Backpack",
                    "Backpacks",
                    0.91,
                    "匹配通勤、轻量和中价位偏好"
            )),
            List.of(new AgentToolCallVO(
                    "toolu_001",
                    "recommend_candidates",
                    "rs-service-recommend",
                    "SUCCESS",
                    Map.of("limit", 5)
            ))
    );
    when(chatService.chat(argThat(request ->
            "sess_001".equals(request.sessionId())
                    && "A1XYZ".equals(request.profileUserId())
                    && "想要一个通勤背包".equals(request.userMessage())
                    && request.limit() == 5
                    && "agent_chat".equals(request.context().get("scene"))
    ))).thenReturn(response);

    MvcResult result = mockMvc.perform(post("/api/agent/chat")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(readContract("request.json")))
            .andExpect(status().isOk())
            .andReturn();

    assertThat(objectMapper.readTree(
            result.getResponse().getContentAsString(StandardCharsets.UTF_8)
    )).isEqualTo(readContractJson("response.json"));

    verify(chatService).chat(argThat(request ->
            "sess_001".equals(request.sessionId())
                    && request.resolvedLimit() == 5
    ));
}
~~~

Add:

~~~java
import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.test.web.servlet.MvcResult;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;
~~~

- [ ] **Step 4: Run the response contract test and verify RED**

Run from the isolated repository root:

~~~powershell
mvn -f java_agent/pom.xml -pl rs-service-agent -am "-Dtest=AgentChatControllerTest#chatMatchesSharedWireContract" "-Dsurefire.failIfNoSpecifiedTests=false" test
~~~

Expected: FAIL in the JsonNode equality assertion because the actual response has no turn_index. The fixture must load successfully and the failure must not be a path, encoding, Spring context, or Mockito setup error.

Pause and show the user the failing assertion plus the request/actual/expected JSON.

- [ ] **Step 5: Add the minimal turn_index field needed by the response contract**

Replace AgentChatVO.java with:

~~~java
package com.sinrotic.rs.agent.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

public record AgentChatVO(
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("session_id")
        String sessionId,
        @JsonProperty("profile_user_id")
        String profileUserId,
        @JsonProperty("turn_index")
        int turnIndex,
        @JsonProperty("assistant_message")
        String assistantMessage,
        @JsonProperty("recommended_items")
        List<AgentRecommendedItemVO> recommendedItems,
        @JsonProperty("tool_calls")
        List<AgentToolCallVO> toolCalls
) {
}
~~~

In the controller test response constructor, insert 1 after "A1XYZ".

In InMemoryAgentOrchestrationService.chat(), use the minimal temporary value 1 so the new record constructor compiles:

~~~java
return new AgentChatVO(
        requestId,
        request.sessionId(),
        request.profileUserId(),
        1,
        assistantMessage,
        recommendations,
        toolCalls
);
~~~

- [ ] **Step 6: Run the response contract test and verify GREEN**

Run:

~~~powershell
mvn -f java_agent/pom.xml -pl rs-service-agent -am "-Dtest=AgentChatControllerTest#chatMatchesSharedWireContract" "-Dsurefire.failIfNoSpecifiedTests=false" test
~~~

Expected: PASS and BUILD SUCCESS.

- [ ] **Step 7: Write the failing per-session turn calculation test**

Create AgentChatTurnIndexTest.java:

~~~java
package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentOrchestrationService;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class AgentChatTurnIndexTest {

    @Test
    void chatNumbersTurnsFromOneWithinEachSession() {
        InMemoryAgentOrchestrationService service = new InMemoryAgentOrchestrationService();

        assertThat(service.chat(request("sess_001")).turnIndex()).isEqualTo(1);
        assertThat(service.chat(request("sess_001")).turnIndex()).isEqualTo(2);
        assertThat(service.chat(request("sess_002")).turnIndex()).isEqualTo(1);
    }

    private AgentChatRequestDTO request(String sessionId) {
        return new AgentChatRequestDTO(
                sessionId,
                "A1XYZ",
                "想要一个通勤背包",
                5,
                Map.of("scene", "agent_chat")
        );
    }
}
~~~

- [ ] **Step 8: Run the turn calculation test and verify RED**

Run:

~~~powershell
mvn -f java_agent/pom.xml -pl rs-service-agent -am "-Dtest=AgentChatTurnIndexTest" "-Dsurefire.failIfNoSpecifiedTests=false" test
~~~

Expected: FAIL on the second assertion: expected 2 but was 1.

Pause and show the user that the fixture contract is green while the generalized session behavior is still red.

- [ ] **Step 9: Calculate turn_index from the recorded session list**

In InMemoryAgentOrchestrationService.chat(), replace the existing one-line add and temporary constant with:

~~~java
List<AgentTurnVO> turns = sessionTurns.computeIfAbsent(
        request.sessionId(),
        ignored -> new ArrayList<>()
);
int turnIndex;
// The sync endpoint may be called concurrently for one session.
synchronized (turns) {
    turns.add(turn);
    turnIndex = turns.size();
}

return new AgentChatVO(
        requestId,
        request.sessionId(),
        request.profileUserId(),
        turnIndex,
        assistantMessage,
        recommendations,
        toolCalls
);
~~~

- [ ] **Step 10: Run the Java response and turn tests**

Run:

~~~powershell
mvn -f java_agent/pom.xml -pl rs-service-agent -am "-Dtest=AgentChatControllerTest,AgentChatTurnIndexTest" "-Dsurefire.failIfNoSpecifiedTests=false" test
~~~

Expected: PASS and BUILD SUCCESS.

- [ ] **Step 11: Review and commit Task 1**

Run:

~~~powershell
git diff --check
git diff -- java_agent/contracts java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/domain/vo/AgentChatVO.java java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/InMemoryAgentOrchestrationService.java java_agent/rs-service-agent/src/test/java/com/sinrotic/rs/agent/controller/app/AgentChatControllerTest.java java_agent/rs-service-agent/src/test/java/com/sinrotic/rs/agent/service/AgentChatTurnIndexTest.java
git add java_agent/contracts java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/domain/vo/AgentChatVO.java java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/InMemoryAgentOrchestrationService.java java_agent/rs-service-agent/src/test/java/com/sinrotic/rs/agent/controller/app/AgentChatControllerTest.java java_agent/rs-service-agent/src/test/java/com/sinrotic/rs/agent/service/AgentChatTurnIndexTest.java
git commit -m "feat(agent): add canonical chat turn index"
~~~

Expected: diff contains only Task 1 files and the commit succeeds.

### Task 2: Reject Invalid Synchronous Chat Requests

**Files:**
- Modify: java_agent/rs-service-agent/src/test/java/com/sinrotic/rs/agent/controller/app/AgentChatControllerTest.java
- Modify: java_agent/rs-service-agent/pom.xml
- Modify: java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/domain/dto/AgentChatRequestDTO.java
- Modify: java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/controller/app/AgentChatController.java

**Interfaces:**
- Consumes: AgentChatRequestDTO JSON binding.
- Produces: HTTP 400 for missing session_id, missing profile_user_id, or blank user_message without invoking AgentChatService.

- [ ] **Step 1: Write the failing validation test**

Add these imports to AgentChatControllerTest.java:

~~~java
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import static org.mockito.Mockito.verifyNoInteractions;
~~~

Add:

~~~java
@ParameterizedTest
@ValueSource(strings = {"session_id", "profile_user_id", "user_message"})
void chatRejectsMissingIdentityOrBlankMessage(String field) throws Exception {
    ObjectNode request = (ObjectNode) readContractJson("request.json");
    if ("user_message".equals(field)) {
        request.put(field, "   ");
    } else {
        request.remove(field);
    }

    mockMvc.perform(post("/api/agent/chat")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(objectMapper.writeValueAsBytes(request)))
            .andExpect(status().isBadRequest());

    verifyNoInteractions(chatService);
}
~~~

- [ ] **Step 2: Run the validation test and verify RED**

Run:

~~~powershell
mvn -f java_agent/pom.xml -pl rs-service-agent -am "-Dtest=AgentChatControllerTest#chatRejectsMissingIdentityOrBlankMessage" "-Dsurefire.failIfNoSpecifiedTests=false" test
~~~

Expected: FAIL because the endpoint currently accepts at least one invalid request and returns 200 instead of 400. The fixture must bind successfully.

Pause and show the user which invalid payload entered the controller.

- [ ] **Step 3: Add Bean Validation and annotate only the synchronous boundary**

In rs-service-agent/pom.xml, immediately after spring-boot-starter-web add:

~~~xml
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-validation</artifactId>
</dependency>
~~~

Replace AgentChatRequestDTO.java with:

~~~java
package com.sinrotic.rs.agent.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;

import java.util.Map;

public record AgentChatRequestDTO(
        @NotBlank(message = "session_id must not be blank")
        @JsonProperty("session_id")
        String sessionId,
        @NotBlank(message = "profile_user_id must not be blank")
        @JsonProperty("profile_user_id")
        String profileUserId,
        @NotBlank(message = "user_message must not be blank")
        @JsonProperty("user_message")
        String userMessage,
        @JsonProperty("limit")
        Integer limit,
        @JsonProperty("context")
        Map<String, Object> context
) {

    public int resolvedLimit() {
        if (limit == null || limit <= 0) {
            return 5;
        }
        return limit;
    }

    public Map<String, Object> resolvedContext() {
        if (context == null) {
            return Map.of();
        }
        return context;
    }
}
~~~

In AgentChatController.java add:

~~~java
import jakarta.validation.Valid;
~~~

Change only the synchronous method signature:

~~~java
@PostMapping("/chat")
public AgentChatVO chat(@Valid @RequestBody AgentChatRequestDTO request) {
    return chatService.chat(request);
}
~~~

Do not add @Valid to streamChat() in this slice.

- [ ] **Step 4: Run validation and focused Java regression**

Run:

~~~powershell
mvn -f java_agent/pom.xml -pl rs-service-agent -am "-Dtest=AgentChatControllerTest,AgentChatTurnIndexTest" "-Dsurefire.failIfNoSpecifiedTests=false" test
~~~

Expected: all focused tests PASS and BUILD SUCCESS.

- [ ] **Step 5: Review and commit Task 2**

Run:

~~~powershell
git diff --check
git diff -- java_agent/rs-service-agent/pom.xml java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/domain/dto/AgentChatRequestDTO.java java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/controller/app/AgentChatController.java java_agent/rs-service-agent/src/test/java/com/sinrotic/rs/agent/controller/app/AgentChatControllerTest.java
git add java_agent/rs-service-agent/pom.xml java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/domain/dto/AgentChatRequestDTO.java java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/controller/app/AgentChatController.java java_agent/rs-service-agent/src/test/java/com/sinrotic/rs/agent/controller/app/AgentChatControllerTest.java
git commit -m "feat(agent): validate chat wire requests"
~~~

Expected: the commit contains only validation behavior and its test.

### Task 3: Pure Frontend Wire Builder and Runtime Mapper

**Files:**
- Modify: java_agent/frontend/package.json
- Modify: java_agent/frontend/package-lock.json
- Create: java_agent/frontend/src/api/agentContract.test.ts
- Create: java_agent/frontend/src/api/agentContract.ts
- Modify: java_agent/frontend/src/types/agent.ts

**Interfaces:**
- Consumes: the two shared JSON fixtures from Task 1.
- Produces: buildAgentChatWireRequest(sessionId, profileUserId, message): AgentChatWireRequest and mapAgentChatWireResponse(value: unknown): AgentChatResponse.

- [ ] **Step 1: Install the minimal test runner**

Run:

~~~powershell
npm --prefix java_agent/frontend install --save-dev --save-exact vitest@0.34.6
~~~

Replace the scripts object in java_agent/frontend/package.json with:

~~~json
"scripts": {
  "dev": "vite",
  "build": "tsc && vite build",
  "lint": "tsc --noEmit",
  "test": "vitest run",
  "preview": "vite preview"
}
~~~

Run:

~~~powershell
npm --prefix java_agent/frontend test -- --passWithNoTests
~~~

Expected: Vitest exits successfully with no tests. Do not change vite.config.ts or add jsdom.

- [ ] **Step 2: Write the failing pure contract tests**

Create agentContract.test.ts:

~~~typescript
import { describe, expect, it } from 'vitest';
import requestFixture from '../../../contracts/agent-chat/request.json';
import responseFixture from '../../../contracts/agent-chat/response.json';
import {
  buildAgentChatWireRequest,
  mapAgentChatWireResponse,
} from './agentContract';

describe('Agent Chat wire contract', () => {
  it('builds the canonical request fixture', () => {
    expect(buildAgentChatWireRequest(
      'sess_001',
      'A1XYZ',
      '  想要一个通勤背包  '
    )).toEqual(requestFixture);
  });

  it('maps the canonical response into the page model', () => {
    expect(mapAgentChatWireResponse(responseFixture)).toEqual({
      requestId: 'agent_req_001',
      sessionId: 'sess_001',
      assistantMessage: '我会优先推荐通勤背包，并补充可解释证据。',
      turnIndex: 1,
      items: [{
        item_id: 'B001',
        rank: 1,
        score: 0.91,
        reason: '匹配通勤、轻量和中价位偏好',
        source_tags: ['agent_recommendation'],
        display: {
          title: 'Commuter Backpack',
          category: 'Backpacks',
          store: '',
          image_url: '',
        },
      }],
    });
  });

  it.each(['request_id', 'turn_index', 'assistant_message'])(
    'rejects a response without %s',
    (field) => {
      const invalid: Record<string, unknown> = {...responseFixture};
      delete invalid[field];

      expect(() => mapAgentChatWireResponse(invalid))
        .toThrow('Agent Chat contract violation: invalid or missing ' + field);
    }
  );
});
~~~

- [ ] **Step 3: Run the frontend contract test and verify RED**

Run:

~~~powershell
npm --prefix java_agent/frontend test -- src/api/agentContract.test.ts
~~~

Expected: FAIL because ./agentContract does not exist. Fixture imports must resolve; if they do not, fix only the relative path before continuing.

Pause and show the user the module-not-found RED.

- [ ] **Step 4: Implement wire types, request builder, and strict mapper**

Create agentContract.ts:

~~~typescript
import { AgentChatResponse } from '../types/agent';
import { RecommendItemVO } from '../types/recommend';

export interface AgentChatWireRequest {
  session_id: string;
  profile_user_id: string;
  user_message: string;
  limit: number;
  context: { scene: 'agent_chat' };
}

export interface AgentRecommendedItemWire {
  item_id: string;
  title: string;
  category: string;
  score: number;
  reason: string;
}

export interface AgentToolCallWire {
  tool_call_id: string;
  tool_name: string;
  service: string;
  status: string;
  metadata: Record<string, unknown>;
}

export interface AgentChatWireResponse {
  request_id: string;
  session_id: string;
  profile_user_id: string;
  turn_index: number;
  assistant_message: string;
  recommended_items: AgentRecommendedItemWire[];
  tool_calls: AgentToolCallWire[];
}

type JsonObject = Record<string, unknown>;

export class AgentChatContractError extends Error {
  constructor(detail: string) {
    super('Agent Chat contract violation: ' + detail);
    this.name = 'AgentChatContractError';
  }
}

function invalid(path: string): never {
  throw new AgentChatContractError('invalid or missing ' + path);
}

function requireObject(value: unknown, path: string): JsonObject {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return invalid(path);
  }
  return value as JsonObject;
}

function requireString(object: JsonObject, key: string, path = key): string {
  const value = object[key];
  if (typeof value !== 'string' || value.trim().length === 0) {
    return invalid(path);
  }
  return value;
}

function requireNumber(object: JsonObject, key: string, path = key): number {
  const value = object[key];
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return invalid(path);
  }
  return value;
}

function requirePositiveInteger(object: JsonObject, key: string): number {
  const value = requireNumber(object, key);
  if (!Number.isInteger(value) || value < 1) {
    return invalid(key);
  }
  return value;
}

function requireArray(object: JsonObject, key: string): unknown[] {
  const value = object[key];
  if (!Array.isArray(value)) {
    return invalid(key);
  }
  return value;
}

function mapRecommendedItem(value: unknown, index: number): RecommendItemVO {
  const path = 'recommended_items[' + index + ']';
  const item = requireObject(value, path);
  return {
    item_id: requireString(item, 'item_id', path + '.item_id'),
    rank: index + 1,
    score: requireNumber(item, 'score', path + '.score'),
    reason: requireString(item, 'reason', path + '.reason'),
    source_tags: ['agent_recommendation'],
    display: {
      title: requireString(item, 'title', path + '.title'),
      category: requireString(item, 'category', path + '.category'),
      store: '',
      image_url: '',
    },
  };
}

export function buildAgentChatWireRequest(
  sessionId: string,
  profileUserId: string,
  message: string
): AgentChatWireRequest {
  return {
    session_id: sessionId,
    profile_user_id: profileUserId,
    user_message: message.trim(),
    limit: 5,
    context: {scene: 'agent_chat'},
  };
}

export function mapAgentChatWireResponse(value: unknown): AgentChatResponse {
  const response = requireObject(value, 'response');
  const requestId = requireString(response, 'request_id');
  const sessionId = requireString(response, 'session_id');
  requireString(response, 'profile_user_id');
  const turnIndex = requirePositiveInteger(response, 'turn_index');
  const assistantMessage = requireString(response, 'assistant_message');
  const items = requireArray(response, 'recommended_items')
    .map(mapRecommendedItem);
  requireArray(response, 'tool_calls');

  return {
    requestId,
    sessionId,
    assistantMessage,
    items,
    turnIndex,
  };
}
~~~

Replace types/agent.ts with:

~~~typescript
import { RecommendItemVO } from './recommend';

export interface AgentChatResponse {
  requestId: string;
  sessionId: string;
  assistantMessage: string;
  items: RecommendItemVO[];
  evidence?: unknown[];
  turnIndex: number;
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  items?: RecommendItemVO[];
  turnIndex?: number;
}
~~~

The evidence field is intentionally transitional for this green checkpoint because the existing mock client still returns it. Task 4 removes the field and its only producer in the same tested change.

- [ ] **Step 5: Run pure frontend tests and typecheck**

Run:

~~~powershell
npm --prefix java_agent/frontend test -- src/api/agentContract.test.ts
npm --prefix java_agent/frontend run lint
~~~

Expected: one test file with five tests PASS; TypeScript exits 0.

- [ ] **Step 6: Review and commit Task 3**

Run:

~~~powershell
git diff --check
git diff -- java_agent/frontend/package.json java_agent/frontend/package-lock.json java_agent/frontend/src/api/agentContract.ts java_agent/frontend/src/api/agentContract.test.ts java_agent/frontend/src/types/agent.ts
git add java_agent/frontend/package.json java_agent/frontend/package-lock.json java_agent/frontend/src/api/agentContract.ts java_agent/frontend/src/api/agentContract.test.ts java_agent/frontend/src/types/agent.ts
git commit -m "feat(frontend): map agent chat wire contract"
~~~

Expected: only test harness, contract layer, test, lockfile, and page type are committed.

### Task 4: Send the Canonical Request from the Real Frontend Client

**Files:**
- Modify: java_agent/frontend/src/api/agentContract.test.ts
- Modify: java_agent/frontend/src/api/agentClient.ts
- Modify: java_agent/frontend/src/types/agent.ts
- Modify: java_agent/frontend/src/views/AgentChat.tsx

**Interfaces:**
- Consumes: Task 3 builder and mapper.
- Produces: sendChat(sessionId: string, profileUserId: string, message: string): Promise<AgentChatResponse>.

- [ ] **Step 1: Add the failing real-client contract test**

Extend the Vitest import:

~~~typescript
import { beforeEach, describe, expect, it, vi } from 'vitest';
~~~

Add this import:

~~~typescript
import { sendChat } from './agentClient';
~~~

Add this mock setup at module scope:

~~~typescript
const sharedMocks = vi.hoisted(() => ({
  postJson: vi.fn(),
}));

vi.mock('./shared', () => ({
  isMockMode: () => false,
  mockDelay: vi.fn(),
  postJson: sharedMocks.postJson,
}));
~~~

Add:

~~~typescript
describe('sendChat', () => {
  beforeEach(() => {
    sharedMocks.postJson.mockReset();
  });

  it('posts the canonical request and maps the raw response', async () => {
    sharedMocks.postJson.mockResolvedValue(responseFixture);

    const result = await sendChat(
      'sess_001',
      'A1XYZ',
      '想要一个通勤背包'
    );

    expect(sharedMocks.postJson).toHaveBeenCalledWith(
      '/agent/chat',
      requestFixture
    );
    expect(result).toEqual(mapAgentChatWireResponse(responseFixture));
  });
});
~~~

- [ ] **Step 2: Run the client test and verify RED**

Run:

~~~powershell
npm --prefix java_agent/frontend test -- src/api/agentContract.test.ts
~~~

Expected: FAIL because the old two-argument sendChat posts {sessionId, message} and returns the raw snake_case fixture instead of the mapped page model.

Pause and show the actual postJson call beside the canonical fixture.

- [ ] **Step 3: Wire the real client through the contract layer**

In agentClient.ts, add:

~~~typescript
import {
  buildAgentChatWireRequest,
  mapAgentChatWireResponse,
} from './agentContract';
~~~

Change the signature:

~~~typescript
export async function sendChat(
  sessionId: string,
  profileUserId: string,
  message: string
): Promise<AgentChatResponse> {
~~~

Keep the existing mock reply selection, and replace its final return object with:

~~~typescript
return {
  requestId: 'agent_req_' + Date.now() + '_' + Math.floor(Math.random() * 1000),
  sessionId,
  assistantMessage: reply,
  items,
  turnIndex: Math.floor(Math.random() * 5) + 1,
};
~~~

In types/agent.ts, remove the transitional line:

~~~typescript
evidence?: unknown[];
~~~

Replace the real branch with:

~~~typescript
const request = buildAgentChatWireRequest(
  sessionId,
  profileUserId,
  message
);
const response = await postJson<unknown>('/agent/chat', request);
return mapAgentChatWireResponse(response);
~~~

In AgentChat.tsx, change both calls:

~~~typescript
const chatRes = await sendChat(sessionId, profileUserId, userMsg);
~~~

~~~typescript
const chatRes = await sendChat(sessionId, profileUserId, actionMessage);
~~~

At both call sites replace the fallback with:

~~~typescript
const resolvedRequestId = chatRes.requestId;
~~~

- [ ] **Step 4: Run the client test and verify GREEN**

Run:

~~~powershell
npm --prefix java_agent/frontend test -- src/api/agentContract.test.ts
npm --prefix java_agent/frontend run lint
~~~

Expected: one test file with six tests PASS; TypeScript exits 0. There must be no remaining sendChat(sessionId, message) call and no chat-req fallback.

- [ ] **Step 5: Review and commit Task 4**

Run:

~~~powershell
git diff --check
git diff -- java_agent/frontend/src/api/agentContract.test.ts java_agent/frontend/src/api/agentClient.ts java_agent/frontend/src/types/agent.ts java_agent/frontend/src/views/AgentChat.tsx
git add java_agent/frontend/src/api/agentContract.test.ts java_agent/frontend/src/api/agentClient.ts java_agent/frontend/src/types/agent.ts java_agent/frontend/src/views/AgentChat.tsx
git commit -m "fix(frontend): send canonical agent chat requests"
~~~

Expected: only the client integration test, client, final page type cleanup, and its two UI call sites are committed.

### Task 5: Related Regression and Evidence Handoff

**Files:**
- Verify only; do not add production scope.

**Interfaces:**
- Consumes: all four implementation commits.
- Produces: local verification evidence and a reviewed diff ready for the user; no remote deployment.

- [ ] **Step 1: Run the complete Agent service regression**

Run:

~~~powershell
mvn -f java_agent/pom.xml -pl rs-service-agent -am test
~~~

Expected: BUILD SUCCESS. If an unrelated pre-existing test fails, stop and use superpowers:systematic-debugging before changing code.

- [ ] **Step 2: Run the complete frontend regression**

Run:

~~~powershell
npm --prefix java_agent/frontend test
npm --prefix java_agent/frontend run lint
npm --prefix java_agent/frontend run build
~~~

Expected: all Vitest tests PASS, TypeScript exits 0, and Vite build succeeds.

- [ ] **Step 3: Verify scope and repository hygiene**

Run:

~~~powershell
git diff --check HEAD~4..HEAD
git status --short
git log --oneline -5
git diff HEAD~4..HEAD -- java_agent/contracts java_agent/rs-service-agent java_agent/frontend
~~~

Expected: the isolated worktree is clean; exactly four feature commits follow the planning commit; no stream, Gateway, Session, Recommend, RAG, Catalog, deployment, or tunnel files changed.

- [ ] **Step 4: Pause for the final user review**

Show:

- the first Java RED and its missing turn_index evidence；
- the per-session 1,2,1 GREEN evidence；
- the validation 400/no-service-call evidence；
- the frontend old camelCase request RED and canonical request GREEN；
- the four commit summaries and final scoped diff；
- the explicit statement that remote deployment has not started。

Recommend the next slice as Session API contract and gateway route, but do not begin it until the user approves this slice.
