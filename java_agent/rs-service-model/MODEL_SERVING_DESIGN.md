# rs-service-model 模型服务设计文档

## 1. 服务定位

`rs-service-model` 是推荐系统和 Agent 系统共享的模型网关与模型注册服务。它不直接承载所有模型推理计算，而是统一管理模型版本、模型路由、运行时 endpoint、健康检查、超时、降级和调用协议。

第一版目标：

- 推荐小模型可以通过统一接口完成粗排、精排、embedding 推理。
- Agent 4B 模型可以通过统一接口完成对话生成和流式输出。
- 模型文件统一存储在 MinIO。
- 推荐服务和 Agent 服务不直接关心 MinIO 路径、Triton 路径、vLLM 路径。
- 后续从 ONNX Runtime 升级到 TensorRT，或从 vLLM 升级到 TensorRT-LLM 时，上游业务服务尽量不改。

不建议把该能力放进 `rs-service-recommend`，因为 Agent、RAG、推荐排序都会依赖模型服务。模型服务应该是独立微服务。

---

## 2. 总体架构

```text
rs-service-recommend
rs-service-agent
        |
        v
rs-service-model
  - Model Registry
  - Model Gateway
  - Runtime Router
  - Health Check
  - Timeout / Fallback
  - Manifest Resolver
        |
        +--> Triton Inference Server
        |      - ONNX Runtime backend
        |      - TensorRT backend
        |      - Python backend optional
        |
        +--> vLLM
        |      - Agent 4B LLM
        |      - OpenAI-compatible API
        |      - streaming
        |
        +--> Milvus / Faiss
        |      - item embedding retrieval
        |      - RAG vector retrieval
        |
        +--> MinIO
               - model artifact
               - tokenizer
               - TensorRT engine
               - ONNX model
               - model manifest
```

核心原则：

- MinIO 是模型 artifact store，不是在线推理服务。
- Triton / vLLM 是真正的推理 runtime。
- `rs-service-model` 是网关和注册中心，不应该在第一版里自己实现复杂推理引擎。
- 简单模型和复杂模型共享 registry、manifest、health、metrics，但使用不同 runtime 和资源池。

---

## 3. 模型类型和运行时

| 模型类型 | 典型用途 | 推荐 runtime | 第一版建议 |
| --- | --- | --- | --- |
| LightGBM / XGBoost | 粗排、规则增强排序 | native runtime / ONNX Runtime / Triton | 优先 ONNX 或 native |
| DeepFM / DNN 排序 | 精排 | ONNX Runtime / Triton | Triton ONNX backend |
| Two Tower user encoder | 语义召回 user embedding | ONNX Runtime / Triton | Triton ONNX backend |
| item embedding | 向量召回索引 | Milvus / Faiss | Milvus |
| Agent 4B LLM | 对话、意图理解、解释生成 | vLLM | vLLM |
| 后续大模型高性能版本 | Agent / RAG 生成 | TensorRT-LLM | 第二阶段再考虑 |

推荐第一版组合：

```text
推荐小模型：Triton + ONNX Runtime backend
Agent 4B 模型：vLLM
模型存储：MinIO
模型注册：model_manifest.yaml 或 MySQL 表
Java 入口：rs-service-model
```

---

## 4. 推荐小模型链路

推荐链路目标是低延迟、高吞吐、批量推理：

```text
rs-service-recommend
  -> rs-service-model POST /api/model/infer
  -> Triton coarse_rank model
  -> 500 candidates batch score
  -> 返回 top100 分数

rs-service-recommend
  -> rs-service-model POST /api/model/infer
  -> Triton fine_rank model
  -> 100 candidates batch score
  -> 返回 top50 分数
```

性能要求：

- 不允许一个 item 调一次模型。
- 粗排一次请求应该支持 300-500 个候选。
- 精排一次请求应该支持 50-100 个候选。
- 模型必须常驻 runtime 内存，不允许请求时从 MinIO 下载。
- MinIO 只在启动、热更新或版本切换时参与。
- Java 调用 runtime 时要有超时和降级。

第一版建议超时：

| 阶段 | 默认超时 | 降级策略 |
| --- | ---: | --- |
| coarse_rank | 80 ms | 使用召回分数或热门分补齐 |
| fine_rank | 150 ms | 使用粗排分数继续最终重排 |
| embedding | 100 ms | 使用历史画像 embedding 或 category fallback |

---

## 5. Agent 4B 模型链路

Agent 4B 模型关注 GPU、量化、KV cache、流式输出和并发调度：

```text
rs-service-agent
  -> rs-service-model POST /api/model/chat
  -> vLLM /v1/chat/completions
  -> streaming or normal response
```

第一版建议使用 vLLM：

- 支持 OpenAI-compatible API。
- 支持 streaming。
- 支持 continuous batching。
- 适合 4B / 7B 级别开源模型部署。
- 比自己用 FastAPI + Transformers 手写推理稳定。

Agent 4B 模型建议策略：

| 项 | 建议 |
| --- | --- |
| runtime | vLLM |
| quantization | INT8 或 INT4，按显存决定 |
| max_tokens | 默认 1024 |
| timeout | 30 秒 |
| streaming | 支持 |
| resource pool | 独立 GPU pool，不和推荐排序模型混用 |
| fallback | 规则回复、较小模型、或返回可重试错误 |

---

## 6. Model Manifest

第一版可以先用 YAML 文件，后续再迁移到 MySQL 表或配置中心。

示例：

```yaml
models:
  recommend_coarse_rank:
    type: ranking
    runtime: triton_onnx
    artifact_uri: minio://rs-models/rank/coarse/v1/model.onnx
    endpoint: http://triton-rank:8000/v2/models/coarse_rank/infer
    timeout_ms: 80
    batch_size: 500
    device: cpu
    enabled: true

  recommend_fine_rank:
    type: ranking
    runtime: triton_onnx
    artifact_uri: minio://rs-models/rank/fine/v1/model.onnx
    endpoint: http://triton-rank:8000/v2/models/fine_rank/infer
    timeout_ms: 150
    batch_size: 100
    device: cpu_or_gpu
    enabled: true

  recommend_user_encoder:
    type: embedding
    runtime: triton_onnx
    artifact_uri: minio://rs-models/embedding/user_encoder/v1/model.onnx
    endpoint: http://triton-rank:8000/v2/models/user_encoder/infer
    timeout_ms: 100
    batch_size: 64
    device: cpu_or_gpu
    enabled: true

  agent_4b:
    type: llm
    runtime: vllm
    artifact_uri: minio://rs-models/llm/agent-4b/v1/
    endpoint: http://vllm-agent:8000/v1/chat/completions
    timeout_ms: 30000
    max_tokens: 1024
    quantization: int4_or_int8
    device: gpu
    streaming: true
    enabled: true
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `model_key` | 上游服务调用时使用的稳定模型标识 |
| `type` | `ranking`、`embedding`、`llm`、`rerank` 等 |
| `runtime` | `triton_onnx`、`triton_tensorrt`、`vllm`、`native` |
| `artifact_uri` | MinIO 中的模型 artifact 位置 |
| `endpoint` | 实际 runtime endpoint |
| `timeout_ms` | 网关调用 runtime 的超时时间 |
| `batch_size` | 推荐小模型批量推理上限 |
| `device` | `cpu`、`gpu`、`cpu_or_gpu` |
| `enabled` | 是否允许线上路由 |

---

## 7. Service 分层

建议 Java 内部分层：

```text
controller
  ModelRegistryController
  ModelInferenceController
  ModelChatController
  ModelHealthController

service
  ModelRegistryService
  ModelGatewayService
  ModelHealthService
  ModelManifestService
  RuntimeRoutingService

client
  TritonInferenceClient
  VllmChatClient
  MinioArtifactClient
  MilvusVectorClient

domain
  ModelDefinition
  ModelRuntime
  ModelRoute
  ModelHealthStatus
  InferenceRequest
  InferenceResult
```

Controller 不直接调用 Triton 或 vLLM，统一走 `ModelGatewayService`。

---

## 8. 健康检查和就绪判断

`rs-service-model` 的 readiness 不只看自己是否启动，还要看关键模型 runtime 是否可用。

健康检查分三层：

```text
service health
  rs-service-model 自身是否正常

registry health
  manifest 是否可读取
  启用模型是否有 endpoint

runtime health
  Triton 是否 ready
  vLLM 是否 ready
  关键模型是否 loaded
```

建议状态：

| 状态 | 含义 |
| --- | --- |
| `UP` | 服务和关键模型都可用 |
| `DEGRADED` | 部分非关键模型不可用，服务可降级 |
| `DOWN` | manifest 不可读或核心 runtime 不可用 |

---

## 9. 第一版落地范围

第一版不要做完整 AIInfra，只做最小高性能模型网关：

```text
1. model_manifest.yaml
2. ModelRegistryService
3. ModelGatewayService
4. TritonInferenceClient
5. VllmChatClient
6. /api/model/registry
7. /api/model/health
8. /api/model/infer
9. /api/model/chat
```

暂不做：

- KServe。
- MLflow。
- 自动灰度发布。
- 自动模型训练发布流水线。
- TensorRT-LLM engine 构建。
- 多租户资源调度。

这些能力可以放到第二阶段。

---

## 10. 和业务服务的关系

推荐服务调用：

```text
rs-service-recommend
  -> POST /api/model/infer model_key=recommend_coarse_rank
  -> POST /api/model/infer model_key=recommend_fine_rank
```

Agent 服务调用：

```text
rs-service-agent
  -> POST /api/model/chat model_key=agent_4b
```

Search RAG 服务调用：

```text
rs-service-recommend
  -> POST /api/model/infer model_key=recommend_user_encoder
  -> Milvus vector search
```

上游服务只认 `model_key`，不直接关心模型部署在哪个 runtime。

---

## 11. 后续升级路径

第一阶段：

```text
MinIO + model_manifest.yaml + rs-service-model + Triton ONNX + vLLM
```

第二阶段：

```text
MySQL Model Registry
Triton TensorRT backend
vLLM 多副本
Prometheus metrics
模型版本灰度
```

第三阶段：

```text
KServe
TensorRT-LLM
MLflow / 内部 Model Registry
自动模型发布流水线
特征平台和 AB 实验联动
```

第一版重点是把边界做对：模型存储归 MinIO，模型推理归 Triton/vLLM，模型路由归 `rs-service-model`，业务编排归推荐和 Agent 服务。
