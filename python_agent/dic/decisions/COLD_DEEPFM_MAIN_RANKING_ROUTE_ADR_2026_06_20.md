# COLD→DeepFM 当前工程主排序路线 ADR

- 日期：2026-06-20
- 状态：Accepted
- 决策范围：当前 Agent/前端闭环阶段的工程主排序路线固定

## 背景

项目当前主线已经从继续扩展排序实验，转向 `pool500 排序链路 → Agent → 前端展示 → 行为反馈闭环`。召回侧以 pool500 作为当前候选池底座；排序侧此前存在 baseline、COLD、DeepFM、XGBoost/GBDT/LightGBM/LambdaMART 等多种候选方向。

COLD 已在远程完成 full/formal streaming 训练，DeepFM 已有 full/formal 训练产物；二者可以组成粗排/精排两阶段排序链路。最新冻结候选评估显示候选内指标有诊断性改善，但 frozen eval 的候选覆盖不足，因此不把本决策包装成“严格整体排序效果显著提升”的结论。

## 决策

固定当前工程主排序路线为：

```text
pool500 recall candidates
    ↓
COLD coarse rank / candidate compression
    ↓
DeepFM fine rank / feature-cross scoring
    ↓
baseline / cached / popular fallback
```

具体口径：

1. `pool500` 固定为当前阶段主召回候选池。
2. `COLD` 固定为当前工程粗排 / candidate compression 模块。
3. `DeepFM` 固定为当前工程精排 / feature-cross ranking 模块。
4. `baseline` 保留为工程 fallback/champion fallback，不再作为排序研究主方向。
5. `XGBoost`、`LightGBM LambdaMART`、`GBDT`、shallow LTR、rule rerank 等路线暂停，保留为 historical / diagnostic / future work。

## 证据摘要

### COLD full/formal 训练

产物目录：

```text
outputs/ranking/cold_full_formal_20260620_existing_deepfm/
```

关键训练证据：

- `model_type = cold_pointwise_logistic_ranker_v1`
- `role = coarse_rank`
- `base_model_type = pointwise_logistic_ltr_v1`
- `training.status = trained`
- `rows = 45,655,785`
- `positive_rows = 9,131,157`
- `positive_users = 5,375,378`
- `epochs = 5`
- `updates = 228,278,925`
- `average_loss = 0.3391834313`
- `training_mode = streaming_full_formal`

### COLD→DeepFM 诊断评估

同一产物目录中 `comparison.json` 显示：

- baseline in-candidate positive recall@20：`0.071429`
- COLD→DeepFM in-candidate positive recall@20：`0.142857`
- baseline positive hits@20：`1 / 14`
- COLD→DeepFM positive hits@20：`2 / 14`

边界：

- `candidate_coverage_hard_gate_status = STOP_FOR_RANKING_EFFECT`
- `ranking_effect_conclusion_allowed = false`

因此该证据用于工程主路固定和候选内诊断，不用于夸大整体效果提升声明。

## 为什么选择该路线

1. **分层合理**：COLD 轻量、稳定、适合粗排压缩；DeepFM 能表达二阶和非线性特征交叉，适合精排。
2. **训练已补齐**：COLD 和 DeepFM 都已有 full/formal 训练产物，不再停留在 smoke 或 limited run。
3. **工程闭环优先**：当前阶段更需要稳定主路支撑 Agent、前端和行为反馈闭环，而不是继续扩展排序模型分支。
4. **叙事清晰**：两阶段排序结构比继续堆 XGBoost/GBDT/LambdaMART 更贴近工业推荐系统的召回→粗排→精排分层。

## 明确边界

- 可以说：`COLD→DeepFM 已晋升为当前工程主排序链路`。
- 不说：`COLD→DeepFM 已严格证明整体排序效果显著优于 baseline`。
- 进一步效果提升的主要约束是召回覆盖和候选池质量，而不是继续增加排序模型数量。
- baseline fallback 不删除，用于 artifact 缺失、模型加载失败、候选为空、服务超时等工程兜底。

## 后续执行口径

- Agent 和前端默认围绕 `pool500 + COLD→DeepFM` 叙事继续推进。
- 首页 `FeedRefreshAgent` 决定 rerank_existing / rerecall_pool500 时，以该排序主路作为工程目标链路；若线上 adapter 未就绪或不可用，必须 public-safe fallback。
- 对话式 `ConversationalRSAgent` 使用相同推荐底座，但不把模型分数、diagnostics、source trace 暴露给用户。

## 面试可讲点

这段可以讲成“推荐排序主路的工程晋升取舍”：先用 pool500 固定召回候选，再用 COLD 做粗排压缩、DeepFM 做精排交叉建模；当 full/formal 训练和候选内诊断验证完成后，为了推进 Agent 与前端闭环，将 COLD→DeepFM 晋升为工程主路，同时保留 baseline fallback 和效果声明边界，避免把候选覆盖不足下的诊断指标包装成整体提升。