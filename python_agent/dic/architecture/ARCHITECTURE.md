# 架构说明

## 1. 总体结构

本项目采用**Agent 主轴 + 传统推荐 backbone** 的混合架构。当前主线分为三层：

- **传统推荐 backbone**
  - 负责召回、排序和基础规则过滤
  - 目标是先把候选集做稳，再交给上层决策
- **Agent 决策层**
  - 负责理解用户意图、约束和反馈变化
  - 基于候选集做二次决策、重排和解释
- **Agent RAG 增强层**
  - 为 Agent 提供召回前 query planning、商品知识检索、解释 grounding 和幻觉控制
  - 召回前 `query_rag` 只提供 compact query hints；排序后 evidence RAG 只提供候选相关上下文和证据，二者都不替代召回排序主链路
  - P2 执行目标是把 `AgentOrchestrationFacade` 和 `EvidenceRAGFacade` 作为模块化单体 seam 显式落在服务层；它们只做编排与证据适配，不改变 route 形状，也不承担 candidate generation、ranking replacement 或 promotion
- **训练与对齐支撑层**
  - 负责训练数据、对齐目标和模型行为优化
  - 不承担主链路业务定义

当前已经补齐三层产品化与仿真能力的第一版：

- **展示层**：把推荐结果聚合成商品展示卡和可解释推荐回复
- **前端 / 服务层**：提供聊天窗口、商品卡片、结构化反馈按钮、Session Replay 和 API 边界
- **仿真 / 动画层**：用多角色模拟客户生成合成交互、批量评估报告，并将 session / rollout 以安全视图回放

一句话概括：**底层先回答“能推荐什么”，上层决定“最终怎么推荐”，展示与仿真层再负责“如何被用户看到、如何被系统化测试”。**

---

## 2. 分层职责

### 2.1 传统推荐 backbone

这一层承担工业化、结构化、可控的部分：

- 召回：从全量物品中找出候选
- 排序：对候选做打分和排序
- 规则过滤：去重、黑白名单、类目约束、频控、质量约束

这一层的核心价值是：**保证候选质量、保证系统可控、保证推荐链路符合工业推荐的分层方式。**

### 2.2 Agent 决策层

Agent 不替代推荐底座，而是在底座上做决策编排。未来主线固定为 **LLM-orchestrated RecSys**：让大模型作为推荐系统的自动化调度大脑，把召回、排序、广告投放、用户记忆、RAG 解释和反馈闭环封装成可调用、可组合、可验证的工具集合。

当前阶段先站在候选结果之上做决策，后续逐步扩展为对推荐子系统的策略化调度：

- 读取排序后的候选商品
- 结合对话上下文、显式约束、短期会话记忆和长期用户记忆理解需求
- 根据用户意图选择召回工具、排序/重排目标、过滤策略、RAG 证据和解释方式
- 在业务约束允许的范围内平衡推荐相关性、探索性、多样性、广告投放和用户体验
- 结合反馈判断是否改推、补推、追问、更新记忆或重新编排工具
- 在候选之间做最终选择或重排
- 生成推荐理由和下一步交互建议

Agent 的输入通常包括：

1. 排序后的候选商品
2. 用户当前对话与约束
3. 用户偏好和会话反馈
4. RAG 检索返回的商品知识证据和可展示字段

Agent 的输出通常是：

- 最终推荐列表
- 重排后的候选顺序
- 推荐理由
- 追问问题
- 进一步约束建议

### 2.3 Agent RAG 增强层

RAG 是 Agent 的知识增强能力，不是新的主召回路线。

它主要负责：

- 以 `parent_asin` 为主键组织商品标题、类目、描述、卖点、价格、评分和展示字段
- 在用户需求进入、召回生成 query 之前，通过 `query_rag` 按需检索 catalog-level 背景知识，输出 compact semantic query hints、属性扩展和澄清依据
- 在推荐解释、why 问答、澄清追问和 show different 场景中检索候选相关证据
- 控制生成式解释只引用真实商品字段，降低不存在商品或无根据卖点
- 在需要时接入轻量 text / metadata retrieval，后续再评估 FAISS 或本地向量索引

RAG 层分为召回前 planning RAG 和排序后 evidence RAG：前者不直接生成候选，后者不越过候选池取证，二者都不得替代 ranking tool 做最终排序。

### 2.4 训练与对齐支撑层

训练层是支撑层，不是项目主轴。

它主要负责：

- 让模型更稳定地遵循推荐输出格式
- 让中文表达更自然、更一致
- 让推荐理由更贴近业务语境
- 在需要时做偏好对齐，降低不合适输出

当前路线固定为：

- **Qwen3.5-4B**：作为 Agent 模型的固定选择
- **8-bit QLoRA SFT**：作为推荐任务格式、多轮 Tool-use / ReAct 轨迹和中文表达的训练路线
- **GRPO**：作为后续偏好与策略对齐路线，用于约束 grounded 推荐、工具调用正确性、预算控制和反馈质量

这里需要明确：**这条训练路线是规划和固定方向，不应写成已经完全完成。**

### 2.5 展示层

展示层负责把推荐结果转换成前端和对话模型都能消费的商品卡 contract。

它主要负责：

- 用 `parent_asin` 关联商品标题、类目、价格、评分、卖点和描述
- 输出稳定的商品卡结构，而不是暴露排序内部字段
- 承载推荐理由、风险提示、缺失图片等展示状态
- 为后续聊天前端和动画回放提供统一数据接口

展示层不负责召回、排序或 Agent 策略决策。

### 2.6 前端 / 服务层

前端和服务层负责真实交互入口。

已完成第一版的能力包括：

- React 聊天窗口和商品卡片展示
- 喜欢、不喜欢、换一批、why 等结构化反馈入口
- `/session/start`、`/chat`、`/feedback`、`/recall`、`/recommend`、`GET /session/{session_id}` 和 `/demo/e2e` API 边界
- Session Replay 时间线，用于复盘多轮对话、反馈事件和商品卡变化

前端只消费展示层和服务层 contract，不直接读取推荐内部中间字段。

#### 2.6.1 Recall Serving Layer / API 边界

当前 Recall Serving Layer 是 single-process HTTP 服务内的轻量在线候选获取层，不是独立生产级召回微服务。它通过 `/recall` 提供纯召回接口：输入用户行为序列、可选 `user_id`、已曝光 item 和 `candidate_pool_size`，内部复用 `OnlinePool500Recommender.tool_retrieve_candidates(...)` 读取 pool500 artifact 与 source-index lookup，并返回候选 item id 列表。

这层的职责是把离线构建好的召回产物封装成可服务、可测试、可治理的候选接口；它不调用排序、不构建商品卡、不生成最终推荐话术，也不暴露 source lineage、score trace、manifest path、diagnostics、label / oracle 或训练样本字段。完整推荐展示仍由 `/recommend`、`/chat` 和 display contract 承担。

治理边界保持不变：`/recall` 只表示服务可以读取受治理约束的候选来源；不代表召回主路 promotion，不替换当前 ranking input，不开放 pool1000。pool500 ready 语义仍只代表 recall artifact / source-index readiness。

### 2.7 仿真 / 动画层

仿真层已经具备多角色模拟客户场景的第一版能力。

它主要负责：

- 维护多个 persona、角色状态、购物目标、偏好、预算敏感度和反馈风格
- 通过 deterministic policy 或模型 API 驱动角色提出需求、追问、接受、拒绝和换榜反馈
- 与推荐系统 Agent 交互并产出安全 session export、simulation scene 和 batch metrics
- 将合成交互数据与真实用户行为分开标记

动画 / replay 层只负责可视化展示和回放，例如角色状态、商品曝光、满意度变化和反馈过程，不参与推荐决策或 reward 定义。

---

## 3. 当前实现状态

### 已实现第一版

- 召回清洗与 views 相关链路
- popular / category / ItemCF recall
- semantic / text recall 第一版
- item-level feature rerank 第一版
- DSSM-style / YouTubeDNN-style 双塔向量召回旁路第一版：PyTorch 训练 artifact、向量索引、默认关闭配置和 strict promotion gate 已接入；当前只有训练 `limit_users=10`、评估 `limit_users=30` 的 smoke 证据，尚无完整 10k 双塔晋升结论
- Swing recent-window 2y 路线已新增 SciOMC 预处理与 train-only formal sidecar：先从 `data/processed/amazon_2023_recall_recent_2y_1m_3m/manifest.json` 生成 `data/processed/amazon_2023_sciomc_swing_recent2y/` 下的 `user_sequences.train.jsonl`、`swing_valid_in_universe.jsonl`、`swing_test_in_universe.jsonl`，再只用 `train_user_sequences_path` 构建 `full_train_swing_sidecar_v1`；该路线保持 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`、`promotion_allowed=false`，旧 smoke/10k/full 样本 cap 不再作为正式训练约束。
- deterministic conversational Agent MVP
- CLI feedback canonical demo 与训练样本 `training_samples` contract
- `DisplayResponse` 商品卡 contract 和前端安全展示层
- single-process HTTP 服务：`/session/start`、`/chat`、`/feedback`、`/recall`、`/recommend`、`GET /session/{session_id}`、`/demo/e2e`
- React Web Demo：聊天窗口、商品卡、结构化反馈、Session Replay 和一键 E2E 闭环
- 多角色 Simulation：角色内在模型、Simulation Scene、批量 Evaluation 和模型驱动模拟用户策略

### 进行中

- 将 Web Demo、feedback、session replay 和 simulation batch 轨迹整理成可校验训练样本
- 将现有评估产物收敛成阶段性报告和面试演示主入口

### 尚未完成 / 不应夸大

- Qwen3.5-4B + 8-bit QLoRA SFT + GRPO 尚未完整训练落地
- 当前服务是 single-process demo，不是全量工业化在线服务
- 当前 React Web Demo 和 Simulation 是展示 / 仿真评估第一版，不代表生产级前端、真实用户实验或完整动画系统
- 复杂 Tool-use / ReAct 训练仍是后续增强方向

### 阶段边界

当前双塔只作为默认关闭的向量召回旁路：DSSM-style 和 YouTubeDNN-style 都可以产出可追溯 artifact 并接入本地向量索引，但是否晋升主路必须由 valid/test 主口径、LOPO sanity、source contribution / overlap 和 candidate generation p95 strict gate 共同决定。当前只跑过 paired smoke：训练 `limit_users=10`，评估 `limit_users=30`；DSSM / YouTubeDNN valid/test smoke 均 `hit_rate_at_k=0.0` 且 latency 超过 `0.05s` gate 预算，因此保持 `default_off_side_lane_only`。Node2Vec / DeepWalk 图召回、MIND / SDM 多兴趣召回、TDM、DeepFM / NCF 暂不在本批实现，避免同时扩张多个高成本召回和粗排方向。

---

## 4. 数据流

### 4.1 在线数据流

```text
用户输入 / 对话
    ↓
前端 / 服务层
    ↓
用户画像 + 历史行为 + 当前约束
    ↓
召回模块
    ↓
排序模块
    ↓
Top-K 候选商品
    ↓
Agent 决策层
    ↓
最终推荐 / 重排 / 追问 / 解释
    ↓
展示层聚合商品卡
    ↓
前端商品展示 / 用户反馈
    ↓
反馈进入后续策略或离线训练
```

### 4.2 离线数据流

```text
行为日志 / 物品信息 / 用户特征
    ↓
数据清洗与特征整理
    ↓
召回与排序训练数据
    ↓
评估集 / 案例集 / 偏好数据
    ↓
训练与对齐流程
    ↓
离线评估与案例分析
```

---

## 5. Agentic Candidate Acquisition 工具定义

传统推荐漏斗默认从大规模商品空间出发，先用多路召回缩小池子，再排序和重排。Agent 场景下，用户意图、会话状态和长期记忆已经被显式化，因此需要新增一层 **Agentic Candidate Acquisition**：由 Agent 根据当前任务选择候选获取策略，并为每一路工具分配候选预算。

这一层不是让 LLM 编造商品，也不是无约束绕过推荐 backbone；它只允许 Agent 通过受控工具从真实 catalog、索引、候选池或广告库存中取物品，并继续经过过滤、排序、去重、质量门禁和展示安全检查。

### 5.1 候选获取策略族（非正式 manifest）

下表描述的是 `retrieve_candidates` 内部可编排的候选获取策略，不是正式暴露给 Agent 的 `AGENT_TOOL_MANIFEST` 工具。正式 Agent-facing 工具以 5.2 的 7 个隐藏业务工具为准。

| 策略 | 触发场景 | 核心输入 | 核心输出 | 边界 |
|------|----------|----------|----------|------|
| `traditional_recall` | 用户意图模糊、需要保留历史个性化或大范围覆盖 | `user_id`、历史行为、类目、`limit`、召回源配比 | 多路传统召回候选与 source metadata | 不负责理解自然语言，不直接生成解释 |
| `constraint_catalog_search` | 用户给出明确硬约束，如价格、类目、品牌、评分、关键词 | 结构化 `ProductSearchRequest`、`PriceConstraint`、`CategoryConstraint`、`BrandConstraint`、`KeywordConstraint`、`limit` | 满足约束的真实商品、匹配原因、过滤诊断 | 只能查真实商品库，不能放宽 hard constraint |
| `semantic_intent_search` | 用户用自然语言描述需求，但没有明确商品锚点 | intent query、类目范围、属性词、`limit` | 语义匹配候选、语义分数、命中字段 | 只做候选获取，不替代最终排序 |
| `similar_item_search` | 用户围绕某个商品要求“类似的”“同类的” | `reference_item_id`、相似字段、类目/品牌约束、`limit` | 与参考商品相似的候选和相似原因 | 必须有真实参考商品，不允许凭空构造锚点 |
| `cheaper_alternative_search` | 用户反馈“太贵了”“找便宜点但差不多的” | `reference_item_id`、`price < reference_price` 或 `price_ratio`、同类约束、保留/排除品牌、`limit` | 更低价替代品、价格差、相似原因 | 价格缺失商品不得通过“更便宜”筛选 |
| `attribute_intent_search` | 用户强调属性，如续航、轻便、降噪、材质、适用场景 | 属性词、required/preferred/disliked keywords、类目、`limit` | 属性命中候选、字段证据、匹配强度 | required 属性不可被 soft relaxation 放宽 |
| `memory_personalized_search` | 用户说“按我之前喜欢的风格”或当前意图需要长期偏好补充 | 长期用户记忆、短期会话记忆、负偏好、`limit` | 个性化候选、记忆命中原因 | 长期记忆只能影响候选和权重，不能覆盖当前显式 hard constraint |
| `ad_eligible_candidate_search` | 需要平衡商业投放与用户体验 | 广告库存、投放约束、用户意图、频控、`limit` | 可投放候选、投放原因、约束诊断 | 广告候选必须通过相关性、质量和展示安全门禁 |

### 5.2 核心工具 contract

当前正式的 Agent-facing 工具不再暴露底层召回/排序方法名，而是收敛为 7 个隐藏业务级工具。底层 `catalog_constraint_search`、`agentic_recall_candidates`、`deepfm_rank_candidates` 等函数继续作为后端 helper 存在，但不进入正式 `AGENT_TOOL_MANIFEST`。`query_rag` 只用于推荐前的 query planning / 商品知识提示，不替代召回、排序或候选内取证。

| 工具 | 阶段 | 默认推荐流程 | public payload | 作用 | 输出边界 |
|------|------|--------------|----------------|------|----------|
| `get_user_context` | context | 是，pre | 否 | 汇总 session、最近 turn、显式偏好、已展示/喜欢/不喜欢 item | compact 上下文摘要，不输出 runtime trace |
| `query_rag` | query_planning | 可选，pre | 否 | 基于商品知识生成 query hint / 约束提示，辅助理解自然语言需求 | 只输出 query planning 提示，不返回推荐 slate，不替代召回或排序 |
| `retrieve_candidates` | candidate_generation | 是，pre | 否 | 从真实 catalog / recall index / candidate pool 获取候选 | 只输出 candidate item ids、数量和召回摘要，不输出 raw source score/path 细节 |
| `rank_candidates` | ranking | 是，post | 否 | 对候选池排序，内部可复用 DeepFM / hybrid ranker | 只输出 ranked item ids、数量和排序摘要，不输出 `score_trace` / `feature_rows` |
| `get_item_evidence` | evidence | 是，post；解释请求也可用 | 否 | 为当前候选抽取 RAG/display-safe 商品证据 | 输出候选内证据，不改变 candidates/ranking/final_items |
| `record_user_feedback` | feedback | 否 | 否 | 显式反馈写入 session constraints | 只在显式反馈入口调用，避免普通推荐重复写入 |
| `build_recommendation_slate` | response_composition | 是，post | 是 | 生成展示安全 slate | 必须复用 display builder 和 public payload validator |

#### 5.2.1 推荐 turn 的默认工具链

```text
get_user_context
  ↓
optional query_rag
  ↓
retrieve_candidates
  ↓
后端 recommendation backbone 生成 / 更新 turn
  ↓
rank_candidates
  ↓
get_item_evidence
  ↓
build_recommendation_slate
```

这一链路的关键点是：Agent 看到的是推荐任务语义，而不是 ItemCF、Semantic、DeepFM、RAG index 等工程细节。后端仍然可以复用既有召回、排序、RAG 和 display 代码，但工具输出必须经过 compact / display-safe 收敛。

#### 5.2.2 工具 contract 示例

`retrieve_candidates` 输出示例：

```json
{
  "candidate_item_ids": ["I001", "I002"],
  "candidate_count": 2,
  "retrieval_summary": {
    "target_pool_size": 100,
    "path_count": 3
  },
  "diagnostics": {
    "compact": true
  }
}
```

`rank_candidates` 输出示例：

```json
{
  "ranked_item_ids": ["I002", "I001"],
  "ranked_item_count": 2,
  "ranking_summary": {
    "ranker": "hybrid_or_deepfm",
    "candidate_count": 2,
    "return_top_k": 20
  },
  "diagnostics": {
    "compact": true
  }
}
```

`get_item_evidence` 输出示例：

```json
{
  "evidence": {
    "I002": [
      {"field": "title", "text": "..."},
      {"field": "features", "text": "..."}
    ]
  },
  "item_count": 1,
  "diagnostics": {
    "compact": true,
    "used_rag_context": true
  }
}
```

`build_recommendation_slate` 输出示例：

```json
{
  "display": {
    "schema_version": "rs_agent_display_v1",
    "session_id": "S456",
    "user_id": "U123",
    "turn_index": 1,
    "assistant_message": "...",
    "items": [
      {
        "parent_asin": "I002",
        "title": "...",
        "category": "...",
        "price": "$49.99",
        "rating": "4.5",
        "store": "...",
        "features": ["..."],
        "description": "...",
        "image_url": null,
        "badges": ["matches_feedback"],
        "summary": "..."
      }
    ],
    "feedback_actions": [
      {"type": "like", "label": "喜欢"},
      {"type": "dislike", "label": "不喜欢"},
      {"type": "show_different", "label": "换一批"},
      {"type": "why", "label": "为什么推荐"}
    ],
    "ui_state": {"image_fallback_enabled": true, "can_request_more": true}
  },
  "item_count": 1,
  "diagnostics": {"compact": true, "public_safe": true}
}
```

边界：

- `diagnostics`、`score`、`score_trace`、`feature_rows`、`source`、`ranking`、`reward`、training/evaluation 字段不能进入 public display。
- `build_recommendation_slate` 是唯一允许输出 public payload 的核心工具，并且仍需通过 `validate_public_display_payload()`。
- `record_user_feedback` 只作为显式反馈写入工具，不参与普通推荐 turn 的默认工具链。
- LLM 负责调用顺序和对话策略，推荐 backbone 负责产生真实、可追溯、可评估的候选和排序。

### 5.3 与现有代码的关系

当前代码中的旧底层工具函数仍保留为内部实现：`catalog_constraint_search` 可服务约束检索、相似替代和低价替代；`agentic_recall_candidates` 可服务候选获取；`deepfm_rank_candidates` 可服务排序。正式 Agent 工具 manifest 只暴露 7 个隐藏业务工具，避免前台 Agent 和前端 payload 直接耦合到底层召回/排序/RAG artifact。

### 5.4 目标条件化商品描述

如果后续排序模型使用文本特征，Agent 不应把自由对话式推荐理由直接替代原始商品文本。更稳的方向是生成 **target-conditioned catalog text**：保持原始 Amazon listing 的商品中心风格，但根据当前用户目标重组商品事实。

它的目标不是写“这款很适合你”，而是把商品字段改写成类似训练分布的标准商品描述：

```text
Product: {title}
Category: {category_path}
Brand/Store: {store}
Price: {price}
Rating: {average_rating} from {rating_number} reviews
Targeted features: {与当前意图相关、且有商品字段证据的 features}
Description: {围绕当前目标的商品事实摘要，不引入无证据卖点}
```

与普通 Agent 推荐文案的区别：

| 文本类型 | 是否商品中心 | 是否贴近历史训练文本 | 是否包含用户目标 | 是否适合直接做排序文本特征 |
|----------|--------------|----------------------|------------------|----------------------------|
| 原始 `item_text` | 是 | 是 | 否 | 稳定 baseline |
| 自由推荐理由 | 否 | 否 | 是 | 不建议直接替代 |
| 目标条件化商品描述 | 是 | 尽量接近 | 是，但以商品事实表达 | 可作为 shadow feature / ablation |

后续如果做 DeepFM / reranker 文本特征，应优先比较：原始 `item_text`、目标条件化商品描述、两者并行、以及仅使用结构化 Agent 特征，避免未经验证就用 Agent 文本替换训练分布。

---

## 6. 模块边界

| 模块 | 负责内容 | 不负责内容 |
|------|----------|------------|
| 召回 | 找候选 | 最终决策 |
| 排序 | 候选打分与排序 | 对话理解 |
| 规则层 | 过滤与约束 | 解释生成 |
| Agent | 需求理解、编排、重排、解释 | 从全量库直接端到端替代召回排序 |
| Agent RAG | 商品知识检索、解释 grounding、候选相关证据注入 | 越过候选池生成新商品、替代召回排序 |
| 训练层 | 表达、格式、偏好对齐 | 定义系统主轴 |
| 展示层 | 商品卡 contract、展示字段聚合、推荐理由承载 | 召回、排序、策略决策 |
| 前端 / 服务层 | 聊天入口、商品卡展示、反馈按钮、API 边界 | 直接依赖推荐内部字段 |
| 仿真 / 动画层 | 多角色合成交互、session / rollout 可视化回放 | 代表真实用户评估、参与线上决策 |

这个边界是当前架构叙事的关键点。

- 传统推荐模块擅长处理规模、排序和可控性
- Agent 擅长处理语言、上下文、意图变化和多轮交互
- RAG 擅长把推荐解释和多轮问答 grounded 到真实商品知识，但不替代候选生成

#### 双 lane 边界

- **Lane A：rag_evidence**。只承担候选内证据检索、解释 grounding 和 undercoverage 诊断，不把“证据更全”写成“召回更强”。该 lane 的 `artifact_role=rag_evidence`，`candidate_scoped=true`，`candidate_generation_allowed=false`，`ranking_input_replacement_allowed=false`，`promotion_allowed=false`。
- **Lane B：diagnostic_only / recall_candidate_source**。只允许作为候选来源诊断与覆盖分析的受控输入，任何晋升都必须先通过 train-visible-only 全过程约束、冻结编码器可复现性检查、远程重放可复现性门禁，以及 dirty artifact no-promotion 规则；未通过门禁的产物只能停留在 diagnostic_only。
- 冻结编码器可复现性至少要记录：`model_name`、`checkpoint_sha`、`tokenizer_sha`、`corpus_hash`、`index_hash`、`seed`、`build_command`、`build_env`。
- 若产物存在未提交改动、未追踪数据、哈希不一致或远程重放失败，则视为 dirty artifact，禁止 promotion.

- 训练层擅长改善模型行为，但不替代系统结构
- 展示与前端层擅长产品化呈现，但不应反向污染推荐内部字段
- 仿真与动画层擅长生成演示和压力测试场景，但合成客户不能直接等同真实用户

所以更合理的表达是：**底层做推荐，顶层做决策，RAG 做知识 grounding，中间用训练增强表达，外围用展示和仿真验证交互体验。**

---

## 7. 面试表达重点

面试时可以这样概括：

> 我们没有让 Agent 直接替代推荐系统，而是保留传统推荐 backbone 作为召回和排序底座，再让 Agent 基于候选集、用户对话、反馈和 RAG 商品知识证据做上层决策。RAG 负责解释 grounding 和幻觉控制，训练层只负责支撑输出质量和偏好对齐，项目重点是分层架构与模块边界。

这句话可以同时回答：

- 系统是什么
- Agent 在哪一层
- 传统推荐做什么
- 训练为什么只是支撑层
