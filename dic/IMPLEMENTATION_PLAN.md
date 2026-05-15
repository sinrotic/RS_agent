# 实施计划

## 总体目标

用最小但完整的工程范围，搭出一个**面试友好**的混合推荐系统：

- 底层保留传统推荐 backbone
- 中间层完成召回与排序
- 上层由 Agent 负责决策和解释
- 训练层作为支撑，不作为主叙事
- 已补商品展示、前端交互、Session Replay、多角色模拟客户和批量仿真评估第一版

---

## 长期路线图

### 1. 数据

- 统一用户、物品、行为、反馈、会话上下文的数据结构
- 保留可追溯的候选、曝光、点击、拒绝、追问记录
- 为后续离线评估和训练样本构造提供稳定输入

### 2. 召回与排序

- 先做可解释、可拆分的召回与排序链路
- 再逐步补充更多召回通道与更稳的排序策略
- 保持“召回负责覆盖、排序负责优先级”的边界清晰

### 3. Agent

- 让 Agent 站在候选结果之上做决策
- 负责重排、过滤、追问和推荐解释
- 不直接替代召回和排序

### 4. 反馈闭环

- 记录点击、跳过、拒绝、追问等反馈
- 把反馈用于短期偏好更新和下一轮决策
- 沉淀可复现实验和案例分析入口

### 5. 训练

- 路线固定为 `Qwen3.5-4B + 8-bit QLoRA SFT + GRPO`
- 目标是补强输出格式、工具使用、多轮交互和偏好对齐
- 训练服务于系统，不替代系统主线

### 6. 评估

- 看召回覆盖、排序区分度、Agent 决策合理性、反馈响应情况
- 重点保留可讲清楚的案例，而不是只堆指标

### 7. 展示与前端

- 定义商品展示卡 contract，把 `parent_asin` 关联到标题、类目、价格、评分、卖点和描述
- 让推荐结果输出可被聊天窗口、商品卡和反馈按钮直接消费
- 前端只消费服务层和展示层接口，不直接依赖召回、排序或 reward 的内部字段

### 8. 多角色仿真与动画回放

- 构建多个由模型 API 驱动的模拟客户 persona，用来与推荐系统 Agent 自动交互
- 把模拟客户产生的 session / rollout 与真实用户行为分开标记
- 动画层用于展示或回放角色状态、商品曝光、反馈变化和推荐调整过程
- 仿真和动画是展示与评估层，不参与线上推荐决策

---

## 当前执行路线

### Phase 1.5：小样本可验证 hybrid demo，已完成

这一阶段已经完成，说明最小闭环可以跑通：

- recall clean / recall views
- candidate merge
- baseline ranking
- deterministic Agent decision stub
- recommendations + metrics + report

对应入口已沉淀在 `dic/PHASE_1_5_DEMO_SUMMARY.md`。

### Phase 1.6：semantic / text recall 第一版，已完成

这一阶段已经完成，重点是补齐语义召回的第一版实现，为后续排查召回覆盖和排序暴露问题提供基础。

### Phase 1.7：rerank / 排序曝光诊断，已形成阶段性结论

这一阶段完成了排序与曝光链路诊断，关注点是：

- 哪些候选真正进入曝光
- 哪些曝光来自 source-level 调参
- 哪些变化只是表面上的 semantic exposure 波动

当前结论是：**source-level 调参已经接近边界，不应继续盲目调 semantic exposure**，后续应以 item-level feature、Agent 反馈和结构化对照为主。

### CLI Agent feedback canonical demo：已固化

2026-04-28 已完成 CLI 反馈闭环 canonical 固化，说明当前已经具备一个可复现的反馈入口。

当前固定入口：

```bash
./.venv/Scripts/python.exe -m rs_core.rsagent.cli \
  --config configs/hybrid_demo_electronics_1000_lopo_semantic_title.yaml \
  --limit-users 3 \
  --simulate-two-turn \
  --output-dir agent_feedback_demo_canonical \
  --inference-policy off
```

产物：`outputs/agent_feedback_demo_canonical/`

### Conversational Agent MVP：已完成 deterministic 第一版

当前 Agent 已不只是“输出推荐列表”，而是具备 deterministic 多轮对话雏形：

- 模糊推荐请求触发澄清问题
- 用户回答澄清后更新偏好/厌恶约束并推荐
- 用户询问 why 时解释上一轮推荐
- 用户要求 show different 时过滤上一轮已曝光 item
- unsupported 自由文本保留到 session / rollout，避免胡编成偏好

固定入口：

```bash
./.venv/Scripts/python.exe -m rs_core.rsagent.cli \
  --config configs/hybrid_demo_electronics_1000_lopo_semantic_title.yaml \
  --limit-users 3 \
  --simulate-conversation \
  --output-dir agent_conversation_demo_canonical \
  --inference-policy off
```

产物：`outputs/agent_conversation_demo_canonical/`

当前 conversational 能力仍是规则版 dialogue manager，不代表完整 LLM chatbot 或 Qwen / QLoRA / GRPO 训练已落地。

### Phase 1.8：item-level feature rerank 第一版，已完成

在 Phase 1.7 证明 source-level boost / penalty 到达边界后，新增默认关闭的 `item_feature_rerank`：

- 输出 `feature_score`、`item_features` 和 item_feature rerank events
- 支持 `multi_source`、`popular_only`、`semantic_only`、feedback category/source/keyword match 等可解释特征
- valid/test 与 LOPO 均保留对照配置：
  - `configs/hybrid_demo_electronics_1000_semantic_title_item_feature.yaml`
  - `configs/hybrid_demo_electronics_1000_lopo_semantic_title_item_feature.yaml`

当前结论：item-feature rerank 没有提升 Top-K hit，但改善了 LOPO target 的候选池内排名分布，适合作为后续 Agent 反馈和学习排序的特征接口。

### Phase 1.9：双塔向量召回旁路，已完成第一版

这一阶段把复杂召回从 token overlap POC 推进到默认关闭的双塔向量召回实验链路：

- 已实现 DSSM-style 与 YouTubeDNN-style 两类 U2I 双塔训练入口，分别输出独立 variant / model type。
- 训练 artifact 合约包含 `train_config`、`model`、`item_embeddings`、`user_embeddings`、`item_id_map`、`user_id_map`、`train_metrics`、`recall_index` 和 `artifact_manifest`。
- 当前环境中 PyTorch 可用时训练 backend 为 `pytorch`；`backend: python_fallback` 不能在 torch 可导入时绕过 PyTorch，只有 `_import_torch()` 返回空时才进入 no-torch fallback。
- candidate merge 支持从 manifest 加载本地向量索引，保留 seen-item filtering、per-user limit、source/model metadata 和默认关闭行为。
- valid/test 与 LOPO 配置已拆分为 DSSM / YouTubeDNN 旁路实验；LOPO 只作为 sanity，不单独触发晋升。
- `strict_promotion_gate` 会读取 paired valid/test 与 paired LOPO metrics；要求 valid/test 的候选池命中、召回、Top-K 命中、candidate hit users、LOPO sanity 和 candidate generation p95 同时达标，不达标时继续作为 default-off side lane。

已验证证据是 smoke 级别：训练 smoke 使用 `limit_users=10`、`epochs=1`、`negative_samples=1`、`embedding_dim=8`、`hidden_dim=8`，评估 smoke 使用 `limit_users=30`。这不是完整 10k 双塔评估，不能据此宣称双塔可晋升。当前 smoke valid/test 中 DSSM 与 YouTubeDNN 的 `candidate_hit_rate_at_pool=0.111111`、`recall_at_pool=0.111111`、`hit_rate_at_k=0.0`、`candidate_hit_users=1`；DSSM `candidate_generation_p95_seconds=0.270462`，YouTubeDNN `candidate_generation_p95_seconds=0.246153`，均因 latency gate 等条件保持 `promotable=false` / `default_off_side_lane_only`。

### Phase 2：展示 contract、服务层与 Web Demo，已完成第一版

这一阶段已经把 Agent 推荐结果稳定封装为前端安全展示接口，并接入轻量交互入口：

- 已定义 `ItemDisplayCard` / `DisplayResponse` contract，只暴露商品卡、推荐文案和展示状态
- 已实现 single-process HTTP 服务，包含 `/session/start`、`/chat`、结构化 `/feedback` 和 `GET /session/{session_id}`
- 已接入 React Web Demo，支持聊天输入、商品卡展示、具体商品喜欢/不喜欢反馈和 Session Replay
- 已新增 `/demo/e2e` 一键闭环入口，用于演示首轮推荐、结构化反馈、第二轮推荐变化和安全字段边界

这一阶段的边界是：服务与前端只消费展示 contract，不读取 `ranking`、`diagnostics`、`reward`、`score` 等内部训练/诊断字段。

### Phase 3：多角色模拟客户沙盒，已完成第一版

这一阶段已经从展示 demo 扩展到可复现的合成交互评估：

- 已实现角色画像、角色状态、反馈风格和 deterministic 行为策略
- 已实现 Simulation Scene，让单个 persona 驱动真实 Agent session 并导出安全 scene contract
- 已实现批量 Simulation Evaluation，输出 `simulation_batch.json`、`metrics.json` 和中文评估报告
- 已接入模型驱动模拟用户策略，外部模型只生成受约束的用户侧 action，并保留 deterministic fallback
- 合成客户数据与真实用户行为仍需分开标记，不能直接等同真实用户评估

下一步应把 Web Demo 和 Simulation 轨迹整理为可校验训练样本，而不是继续扩张展示功能。

---

## 当前推荐入口

### 早期 smoke 入口

`configs/hybrid_demo_small.yaml` 仍然保留，作为早期 smoke / 小样本验证入口。

### 当前推荐入口

下面这些配置是当前更推荐的观察入口：

- `configs/hybrid_demo_electronics_1000.yaml`
- `configs/hybrid_demo_electronics_1000_no_injection.yaml`
- `configs/hybrid_demo_electronics_1000_lopo.yaml`
- `configs/hybrid_demo_electronics_1000_semantic_title.yaml`
- `configs/hybrid_demo_electronics_1000_lopo_semantic_title.yaml`
- `configs/hybrid_demo_electronics_1000_semantic_title_item_feature.yaml`
- `configs/hybrid_demo_electronics_1000_lopo_semantic_title_item_feature.yaml`

双塔向量召回旁路观察入口：

- `configs/hybrid_demo_electronics_10000_semantic_title_two_tower_dssm.yaml`
- `configs/hybrid_demo_electronics_10000_lopo_semantic_title_two_tower_dssm.yaml`
- `configs/hybrid_demo_electronics_10000_semantic_title_two_tower_youtube_dnn.yaml`
- `configs/hybrid_demo_electronics_10000_lopo_semantic_title_two_tower_youtube_dnn.yaml`

这些入口用于做对照、诊断和阶段性展示，不默认承诺同一组指标的最终最优结果。

---

## 诊断说明

- `semantic_only_penalty` 是诊断工具，不是推荐默认配置
- 它的作用是帮助判断语义路径在曝光、排序和对照中的影响
- 不应把它当成主流程的默认策略

---

## 当前不做

- 不把双塔向量召回默认并入主路；DSSM / YouTubeDNN 只有通过 strict promotion gate 后才进入人工晋升评审
- 不在本批实现 Node2Vec / DeepWalk；图召回成本更高，后续更适合作为 item graph 补充旁路或第二阶段召回源
- 不在本批实现 MIND / SDM；多兴趣召回需要更完整的用户兴趣拆分、兴趣数选择和线上向量索引策略，先保留路线规划
- 不在本批实现 TDM；树构建、层级召回和训练闭环成本较高，暂不打断当前双塔验证主线
- 不把 DeepFM / NCF 直接当高效 Top-N 主召回；它们更偏打分 / 粗排 / 重排，若召回化需要离线批量打分、向量化近似或先召回后重排
- 不把当前 single-process demo 写成全量工业化服务
- 不把训练路线写成已经完整训练落地的能力
- 不把当前 React Demo / Simulation 第一版写成生产级前端、真实用户评估或完整动画系统
- 不让模拟客户数据直接等同真实用户反馈
- 不依赖 `old_dic` 作为当前规划依据

---

## 最小闭环判断

如果只看当前阶段，最重要的是确认四件事：

1. 召回能稳定产出候选
2. 排序能解释曝光差异
3. Agent 能在候选之上做决策与解释
4. 反馈能进入下一轮诊断和展示

这四件事成立，项目就已经具备“Agent 主轴 + 传统推荐 backbone”的主叙事。