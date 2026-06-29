# rs-service-model Controller 设计文档

## 1. Controller 分层

`rs-service-model` 第一版建议按能力拆成四类 Controller：

```text
com.sinrotic.rs.model.controller
├── registry
│   └── ModelRegistryController.java
├── inference
│   ├── ModelInferenceController.java
│   └── ModelChatController.java
└── health
    └── ModelHealthController.java
```

| Controller | 面向对象 | 核心职责 | MVP |
| --- | --- | --- | --- |
| `ModelRegistryController` | 内部服务、平台 | 查看模型清单、版本、runtime、启用状态 | 是 |
| `ModelInferenceController` | 推荐、RAG | 推荐小模型、embedding 模型、rerank 模型推理 | 是 |
| `ModelChatController` | Agent | 4B LLM 对话生成、流式输出入口 | 是 |
| `ModelHealthController` | 网关、平台、运维 | 检查 manifest、Triton、vLLM、关键模型状态 | 是 |

---

## 2. ModelRegistryController

基础路径：

```text
/api/model
```

### 2.1 查询模型注册表

```http
GET /api/model/registry
```

响应示例：

```json
{
  "models": [
    {
      "model_key": "recommend_coarse_rank",
      "type": "ranking",
      "runtime": "triton_onnx",
      "version": "v1",
      "enabled": true,
      "device": "cpu",
      "timeout_ms": 80
    },
    {
      "model_key": "agent_4b",
      "type": "llm",
      "runtime": "vllm",
      "version": "v1",
      "enabled": true,
      "device": "gpu",
      "timeout_ms": 30000
    }
  ]
}
```

用途：

- 推荐服务启动时检查依赖模型是否存在。
- Agent 服务检查 `agent_4b` 是否可用。
- 平台观察台展示当前启用模型。

### 2.2 查询单个模型

```http
GET /api/model/{model_key}
```

响应示例：

```json
{
  "model_key": "recommend_fine_rank",
  "type": "ranking",
  "runtime": "triton_onnx",
  "version": "v1",
  "artifact_uri": "minio://rs-models/rank/fine/v1/model.onnx",
  "endpoint": "http://triton-rank:8000/v2/models/fine_rank/infer",
  "timeout_ms": 150,
  "batch_size": 100,
  "device": "cpu_or_gpu",
  "enabled": true
}
```

注意：

- 内部接口可以返回 `artifact_uri` 和 `endpoint`。
- 如果后续暴露给平台外部，需要隐藏 runtime endpoint。

---

## 3. ModelInferenceController

基础路径：

```text
/api/model
```

### 3.1 通用推理接口

```http
POST /api/model/infer
```

请求示例：

```json
{
  "model_key": "recommend_coarse_rank",
  "request_id": "rec_req_001",
  "inputs": {
    "profile_user_id": "A1XYZ",
    "candidate_item_ids": ["B001", "B002", "B003"],
    "features": [
      {
        "item_id": "B001",
        "category_id": "backpack",
        "recall_score": 0.82
      }
    ]
  },
  "options": {
    "top_k": 100,
    "return_scores": true,
    "timeout_ms": 80
  }
}
```

响应示例：

```json
{
  "request_id": "rec_req_001",
  "model_key": "recommend_coarse_rank",
  "model_version": "v1",
  "runtime": "triton_onnx",
  "latency_ms": 37,
  "outputs": {
    "items": [
      {
        "item_id": "B001",
        "score": 0.913,
        "rank": 1
      }
    ]
  }
}
```

服务端流程：

```text
1. 校验 model_key 存在且 enabled=true。
2. 根据 manifest 找到 runtime 和 endpoint。
3. 校验请求 batch size 不超过模型配置。
4. 将业务输入转换成 runtime 输入。
5. 调用 Triton / ONNX / native runtime。
6. 将 runtime 输出转换成统一响应。
7. 记录 request_id、model_key、version、latency、status。
```

适用模型：

- `recommend_coarse_rank`
- `recommend_fine_rank`
- `recommend_user_encoder`
- `rag_embedding`
- 其他非 LLM 推理模型

约束：

- LLM 对话不要走 `/api/model/infer`，走 `/api/model/chat`。
- 推荐排序必须 batch 调用，不允许按 item 循环调用。
- 如果 runtime 超时，返回明确错误码，由上游推荐服务降级。

---

## 4. ModelChatController

基础路径：

```text
/api/model
```

### 4.1 LLM 对话接口

```http
POST /api/model/chat
```

请求示例：

```json
{
  "model_key": "agent_4b",
  "request_id": "agent_req_001",
  "messages": [
    {
      "role": "system",
      "content": "你是推荐系统中的购物助手。"
    },
    {
      "role": "user",
      "content": "帮我找一个便宜一点的通勤背包"
    }
  ],
  "options": {
    "temperature": 0.7,
    "max_tokens": 512,
    "stream": false,
    "timeout_ms": 30000
  }
}
```

响应示例：

```json
{
  "request_id": "agent_req_001",
  "model_key": "agent_4b",
  "model_version": "v1",
  "runtime": "vllm",
  "latency_ms": 1280,
  "message": {
    "role": "assistant",
    "content": "可以，我会优先考虑价格更低、适合通勤、容量够用的背包。"
  },
  "usage": {
    "prompt_tokens": 120,
    "completion_tokens": 36,
    "total_tokens": 156
  }
}
```

服务端流程：

```text
1. 校验 model_key 是 llm 类型。
2. 根据 manifest 找到 vLLM endpoint。
3. 将请求转换成 OpenAI-compatible chat completions 请求。
4. 调用 vLLM。
5. 转换响应并记录 latency、usage、status。
```

### 4.2 LLM 流式接口

```http
POST /api/model/chat/stream
```

第一版可以直接透传 vLLM streaming response。

注意：

- 流式接口应独立于普通 `/chat`，避免普通 Controller 处理复杂 SSE 逻辑。
- 上游 Agent 服务可以选择先只接非流式，后续再接 streaming。
- 4B 模型必须有较长超时，但不能无限等待。

---

## 5. ModelHealthController

基础路径：

```text
/api/model
```

### 5.1 服务健康检查

```http
GET /api/model/health
```

响应示例：

```json
{
  "status": "UP",
  "manifest": {
    "status": "UP",
    "model_count": 4,
    "enabled_model_count": 4
  },
  "runtimes": [
    {
      "name": "triton-rank",
      "type": "triton",
      "status": "UP",
      "loaded_models": ["coarse_rank", "fine_rank", "user_encoder"]
    },
    {
      "name": "vllm-agent",
      "type": "vllm",
      "status": "UP",
      "loaded_models": ["agent_4b"]
    }
  ]
}
```

状态规则：

| 状态 | 条件 |
| --- | --- |
| `UP` | manifest 可读，关键 runtime 可用，关键模型 loaded |
| `DEGRADED` | 非关键模型不可用，但推荐或 Agent 主链路仍可降级 |
| `DOWN` | manifest 不可读，或核心 runtime 不可用 |

### 5.2 模型健康检查

```http
GET /api/model/{model_key}/health
```

响应示例：

```json
{
  "model_key": "agent_4b",
  "status": "UP",
  "runtime": "vllm",
  "endpoint": "http://vllm-agent:8000/v1/chat/completions",
  "last_check_at": "2026-06-28T12:00:00+08:00",
  "latency_ms": 18
}
```

---

## 6. DTO / VO 建议

请求 DTO：

```text
ModelInferRequestDTO
  modelKey
  requestId
  inputs
  options

ModelChatRequestDTO
  modelKey
  requestId
  messages
  options

ModelMessageDTO
  role
  content

ModelOptionsDTO
  topK
  returnScores
  temperature
  maxTokens
  stream
  timeoutMs
```

响应 VO：

```text
ModelRegistryVO
  models

ModelDefinitionVO
  modelKey
  type
  runtime
  version
  artifactUri
  endpoint
  timeoutMs
  batchSize
  device
  enabled

ModelInferVO
  requestId
  modelKey
  modelVersion
  runtime
  latencyMs
  outputs

ModelChatVO
  requestId
  modelKey
  modelVersion
  runtime
  latencyMs
  message
  usage

ModelHealthVO
  status
  manifest
  runtimes
```

---

## 7. 错误码建议

| 错误码 | HTTP | 含义 | 上游处理 |
| --- | ---: | --- | --- |
| `MODEL_NOT_FOUND` | 404 | model_key 不存在 | 配置错误，阻断 |
| `MODEL_DISABLED` | 409 | 模型未启用 | 切换 fallback 模型 |
| `MODEL_BATCH_TOO_LARGE` | 400 | batch 超过配置上限 | 上游拆批或降低候选数 |
| `MODEL_RUNTIME_TIMEOUT` | 504 | runtime 超时 | 推荐服务降级 |
| `MODEL_RUNTIME_UNAVAILABLE` | 503 | Triton/vLLM 不可用 | 降级或返回重试 |
| `MODEL_BAD_INPUT` | 400 | 输入字段不符合模型要求 | 上游修正特征 |
| `MODEL_OUTPUT_INVALID` | 502 | runtime 输出无法解析 | 记录告警并降级 |

---

## 8. 第一版实现顺序

```text
1. Model manifest 加载
2. GET /api/model/registry
3. GET /api/model/{model_key}
4. GET /api/model/health
5. GET /api/model/{model_key}/health
6. POST /api/model/infer mock runtime
7. POST /api/model/chat mock runtime
8. TritonInferenceClient
9. VllmChatClient
10. chat streaming
```

第一版可以先实现 mock runtime，确保推荐服务和 Agent 服务能稳定对接协议。随后再接 Triton 和 vLLM。

---

## 9. 调用边界

推荐服务只调用：

```text
POST /api/model/infer
```

Agent 服务只调用：

```text
POST /api/model/chat
POST /api/model/chat/stream
```

平台观察台调用：

```text
GET /api/model/registry
GET /api/model/{model_key}
GET /api/model/health
GET /api/model/{model_key}/health
```

业务服务不直接访问 MinIO、Triton、vLLM endpoint。这样后续替换 runtime 时，业务服务不用改。
