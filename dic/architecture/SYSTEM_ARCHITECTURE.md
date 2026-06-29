# 系统总架构：传统推荐底座 + Agent 编排服务

## 1. 架构定位

本项目不是用 Agent 替代传统推荐系统，而是采用 **Traditional Recommendation Backbone + Agent Orchestration** 的双层架构：

- **传统推荐底座** 保留离线数据处理、召回、候选合并、排序 / rerank、过滤和展示 contract，保证推荐能力可评估、可诊断、可复用。
- **Agent 编排服务** 作为上层增强入口，负责自然语言理解、多轮对话、工具选择、RAG 证据消费、解释和反馈响应。
- **服务层** 同时保留 `/recall`、`/recommend`、`/chat` 等入口，让纯召回、传统推荐完整链路和 Agent 多轮编排各自有清晰职责。

一句话概括：

> 原有推荐流程作为稳定 backbone 保留，Agent 工具编排作为上层交互增强；二者共享底层召回、排序、RAG、display 和 governance 能力，但入口、输出 contract 和职责边界不同。
>
> P2 的执行目标是在不改变 route 形状、不拆微服务的前提下，把 `AgentOrchestrationFacade` 和 `EvidenceRAGFacade` 补成模块化单体中的明确 seam；这两个 seam 仍然只负责编排与证据适配，不承担候选生成、ranking replacement 或 promotion。

---

## 2. 总体结构

```text
                          用户 / React Demo / Simulation
                                      │
                                      ▼
                            FastAPI Serving Layer
                 ┌────────────────────┼────────────────────┐
                 │                    │                    │
                 ▼                    ▼                    ▼
             POST /recall        POST /recommend        POST /chat
           纯召回候选接口        传统推荐完整接口        Agent 编排接口
                 │                    │                    │
                 └────────────┬───────┴────────────┬───────┘
                              ▼                    ▼
                    Shared Recommendation Core    Agent Runtime
                  ┌───────────┼───────────┐       ├── dialogue / intent
                  ▼           ▼           ▼       ├── retrieve_candidates
            Recall Layer  Ranking Layer  RAG      ├── rank_candidates
                  │           │           │       ├── query_rag
                  ▼           ▼           ▼       └── get_item_evidence
           pool500 artifact  rank config  knowledge index
           source indexes    rerank       evidence policy
                  │
                  ▼
          Offline Artifacts / Governance Registry
```

这个结构刻意保留三类入口：

| 入口 | 定位 | 是否 Agent | 是否召回 | 是否排序 | 是否展示 | 主要用途 |
|---|---|---:|---:|---:|---:|---|
| `/recall` | Recall Serving Layer | 否 | 是 | 否 | 否 | 验证离线召回产物和 source index 的在线候选服务化 |
| `/recommend` | Traditional Recommendation Route | 否 | 是 | 是 | 是 | 保留原有推荐流程，输出可展示商品卡 |
| `/chat` | Agent Orchestration Route | 是 | 通过工具 | 通过工具 | 是 | 多轮对话、澄清、解释、反馈响应 |
| `/feedback` | Feedback / Session Layer | 会话相关 | 间接 | 间接 | 是 | 将用户反馈写入 session 并影响后续响应 |
| `/demo/e2e` | Demo Closure | 服务封装 | 是 | 是 | 是 | 快速验证首轮推荐、反馈和第二轮变化 |
| `/simulation/*` | Simulation Evaluation | 是 | 是 | 是 | 是 | 多角色模拟客户和批量仿真评估 |

---

## 3. 离线层：服务可读取 artifact

离线层负责把原始数据、召回方法、排序实验和 RAG 文本组织成在线可加载的 artifact。

```text
行为数据 / 商品数据
        │
        ▼
数据清洗 / 时间窗 / train-only 切分
        │
        ├── Offline Recall Builder
        │     ├── popular / category
        │     ├── ItemCF weak / strong
        │     ├── Swing / UserCF / co-visit
        │     ├── two-tower / semantic
        │     └── pool500 candidates / source indexes
        │
        ├── Ranking / Rerank Experiments
        │     ├── item feature rerank
        │     ├── pool500 ranking adapter
        │     └── DeepFM shadow / diagnostic
        │
        ├── RAG Index Builder
        │     ├── 商品文本组织
        │     ├── BM25 / vector index
        │     └── evidence policy
        │
        └── Governance / Registry
              ├── current route registry
              ├── method registry
              └── promotion / serving gate
```

离线层的输出不是直接面向用户的结果，而是在线服务可读取的：

- pool500 candidates artifact
- source-index manifest
- recall sidecar / embedding index / text index
- ranking config 或模型 artifact
- RAG knowledge index
- governance registry 与 route config

---

## 4. 在线层：三入口一底座

### 4.1 `/recall`：纯召回服务入口

`/recall` 是当前新增的轻量 Recall Serving Layer。它运行在 single-process demo/local serving layer 中，不是独立生产级召回微服务：

```text
user_sequence / user_id / prior_turn_items
        │
        ▼
RecommendationService.recall()
        │
        ▼
OnlinePool500Recommender.tool_retrieve_candidates()
        │
        ├── pool500 artifact
        ├── source indexes
        ├── seen item filtering
        └── candidate_pool_size cap
        │
        ▼
candidate_item_ids / candidate_count / retrieval_summary
```

职责边界：

- 只返回候选 item id。
- 不排序、不构建商品卡、不生成自然语言解释。
- 不暴露 score、source lineage、manifest path、diagnostics、label、oracle 或训练样本字段。
- 不代表独立生产级 recall microservice。
- 不代表 ranking input replacement、pool1000 或 promotion。

### 4.2 `/recommend`：保留原有推荐流程

`/recommend` 是传统推荐完整链路入口：

```text
user_sequence
        │
        ▼
召回 / 候选补充
        │
        ▼
merge_for_user / feedback filtering / rerank
        │
        ▼
rank_candidates
        │
        ▼
DisplayResponse 商品卡
```

它用于保留和验证原有推荐 backbone。和 `/recall` 的区别是：

- `/recall` 只返回候选；
- `/recommend` 返回排序和展示后的商品卡。

### 4.3 `/chat`：Agent 工具编排入口

`/chat` 是 Agent 多轮服务入口：

```text
用户自然语言
        │
        ▼
Agent dialogue / planner
        │
        ├── retrieve_candidates
        ├── rank_candidates
        ├── query_rag
        └── get_item_evidence
        │
        ▼
推荐 / 解释 / 追问 / 反馈响应
```

Agent 的定位是编排，不是替代：

- Agent 不直接扫描全量商品空间。
- Agent 不直接替代召回和排序模型。
- Agent 通过高层工具使用推荐系统能力。
- Agent 前台只暴露自然对话和展示安全结果，底层 source、score、diagnostics 和 governance 状态留在服务端。

---

## 5. Shared Recommendation Core

三类服务入口共享同一个推荐底座：

```text
Shared Core
  ├── recall source loading
  ├── candidate merge
  ├── feedback filtering
  ├── ranking / rerank
  ├── RAG evidence retrieval
  ├── display builder
  └── governance guardrails
```

共享底座的好处是：

- 原有流程不被 Agent 重写。
- `/recall`、`/recommend`、`/chat` 能复用同一套 artifact、配置和测试口径。
- 新能力可以先作为 side lane / shadow / diagnostic 接入，再由 governance 判断是否进入后续评审。
- 前端和 simulation 只消费稳定 contract，不依赖内部字段。

---

## 6. Agent 与传统流程的关系

本项目的核心关系不是“Agent vs 传统推荐”，而是：

```text
传统推荐 backbone 提供稳定候选、排序和展示底座；
Agent orchestration 在其上增加自然语言交互、工具选择、RAG grounding 和反馈响应。
```

推荐流程可以不经过 Agent：

```text
/recommend -> 召回 -> 排序 -> 展示
```

Agent 流程可以调用同一套底层能力：

```text
/chat -> Agent planner -> retrieve_candidates -> rank_candidates -> display / explanation
```

纯召回能力也可以单独验证：

```text
/recall -> candidate_item_ids
```

因此，系统不是二选一，而是“双轨兼容”：

- 传统推荐链路保留，承担稳定 backbone。
- Agent 工具编排保留，承担交互增强。
- 两者共享底层能力，但不互相替代。

---

## 7. Governance 边界

当前系统强调服务可读与主路晋升分离。

### 7.1 `/recall` 的 ready 语义

`/recall` 可用只表示：

- serving runtime 能读取受治理约束的 pool500 artifact 或 source indexes；
- 候选生成接口能返回候选 ID；
- schema 和测试阻止 evaluation-only / oracle 字段进入 public serving 请求。

它不表示：

- 召回主路已经 promotion；
- pool500 可以替代当前 ranking input；
- pool1000 已开放；
- DeepFM / shadow source 可以影响线上排序；
- 当前服务已经达到生产级微服务要求。

### 7.2 配置职责

```text
configs/serving/
  描述服务运行时加载什么、允许读取哪些 online_route/source_index。

configs/governance/
  描述 route 是否 current/provisional、是否允许 candidate generation、ranking replacement、pool1000、promotion。
```

服务配置不能单独替代治理注册表的晋升语义。

### 7.3 Public payload 边界

Public response 不应泄露：

- label / target_item / ground_truth / holdout
- training_samples
- source / sources / source_scores
- score / final_score / rerank_score / score_trace
- diagnostics / manifest path / tool trace
- ranking internals

这些边界通过 schema、display validator 和 serving tests 固化。

---

## 8. 当前阶段与大厂架构的对应关系

| 大厂推荐系统能力 | 当前项目对应 |
|---|---|
| 数据清洗与样本构建 | `rs_core/data/pipelines/`、`configs/recall/*/dataset_policy.yaml` |
| 离线召回构建 | `rs_lab/experiments/recall/`、`outputs/recall/`、source indexes |
| Artifact / route registry | `configs/governance/current_route_registry.yaml`、method registry |
| 在线召回服务 | `POST /recall` + `OnlinePool500Recommender.tool_retrieve_candidates()` |
| 传统推荐接口 | `POST /recommend` |
| Agent 编排服务 | `POST /chat`、`rs_core/agent/`、tool runtime |
| RAG / evidence | `rs_core/agent/rag/`、`query_rag`、`get_item_evidence` |
| 展示 contract | `rs_core/display/`、React Demo |
| 反馈闭环 | `/feedback`、Session Replay、simulation |
| 评估与治理 | pytest、route gate、simulation batch、工程叙事日志 |

当前仍未声明具备：

- 独立多实例 recall service；
- 独立 ranking service；
- 统一 feature store；
- 真实线上 A/B 平台；
- 生产级监控、限流、熔断和 SLA；
- 完整模型注册平台。

这些是后续演进方向，不是当前已完成能力。

---

## 9. 后续演进路径

在不推翻现有流程的前提下，可以按以下顺序演进：

1. **架构文档收口**：保持三入口一底座，持续更新接口职责矩阵。
2. **Recall Serving Layer 稳定化**：补充更多 artifact readiness、fallback ratio、empty recall ratio 和 latency 指标。
3. **Ranking Serving Layer 抽象**：在不替换主路的前提下，把 ranking/rerank contract 单独整理出来。
4. **RAG / Evidence Service 边界强化**：区分召回前 query planning RAG 与推荐后 item evidence。
5. **Feedback / Session Log 标准化**：把真实 Web Demo、simulation 和 replay 轨迹整理成可校验训练样本。
6. **独立服务化预留**：当接口稳定、artifact registry 明确、监控指标齐备后，再考虑拆独立 recall-service / ranking-service。

---

## 10. 面试表达版本

可以这样讲：

> 我的系统采用 Traditional Recommendation Backbone + Agent Orchestration 的双层架构。底层保留传统推荐系统的离线数据处理、召回、排序、过滤和展示链路，保证推荐能力可评估、可诊断、可复用；上层引入 Agent 编排服务，通过自然语言对话、工具调用、RAG 证据和反馈记忆增强用户交互体验。
>
> 在线服务层保留三个主要入口：`/recall` 是纯召回服务化接口，只读取 pool500 artifact 和 source index 并返回候选 item ids；`/recommend` 是传统推荐完整链路接口，返回排序和展示后的商品卡；`/chat` 是 Agent 多轮编排入口，通过高层工具调用召回、排序和 RAG 能力。
>
> 为避免实验产物被误用为线上主路，我在 governance 层区分 serving readiness 和 route promotion：pool500 ready 只表示召回 artifact 可被服务读取，不代表 ranking input replacement、pool1000 或生产级 promotion。
