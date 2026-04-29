# 实施计划

## 总体目标

用最小但完整的工程范围，搭出一个**面试友好**的混合推荐系统：

- 底层保留传统推荐 backbone
- 中间层完成召回与排序
- 上层由 Agent 负责决策和解释
- 训练层作为支撑，不作为主叙事
- 后期补商品展示、前端交互、多角色模拟客户和动画回放能力

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

### Phase 2：展示 contract 与训练前闭环，规划中

这一阶段的重点不是先做完整前端，而是先稳定推荐结果到商品展示卡的接口：

- 定义 `ItemDisplayCard` 或等价结构
- 用 `parent_asin` join 商品 metadata，补齐 title、price、store、rating、features、description 等字段
- 允许 `image_url` 暂时为空，后续再补真实图片数据源
- 让 session / rollout 同时保留推荐诊断字段和前端展示字段

这一阶段完成后，再进入轻量 API、Web Demo 或 Qwen / QLoRA / GRPO 的小样本训练闭环。

### Phase 3：前端与多角色模拟客户沙盒，规划中

这一阶段面向产品化展示和交互评估：

- 前端提供聊天窗口、商品卡片和反馈按钮
- 多个模拟客户 persona 由模型 API 驱动，与推荐系统 Agent 自动对话
- 动画层读取 session / rollout 进行可视化回放
- 合成客户数据与真实用户数据分开标记，避免评估污染

这一阶段可以作为后期亮点，不应打断当前推荐、Agent feedback、reward 和 rollout contract 的主线。

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

这些入口用于做对照、诊断和阶段性展示，不默认承诺同一组指标的最终最优结果。

---

## 诊断说明

- `semantic_only_penalty` 是诊断工具，不是推荐默认配置
- 它的作用是帮助判断语义路径在曝光、排序和对照中的影响
- 不应把它当成主流程的默认策略

---

## 当前不做

- 第一阶段不做双塔
- 不把项目直接推进到全量工业化服务
- 不把训练路线写成已经落地完成的能力
- 不把前端、动画或多角色仿真写成已经完成的能力
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