# 长期排序路线探索计划

本文档用于指导 Agent 长时间、连续地探索排序方法。它不是一次性阶段清单，也不是“跑完某个 Phase 就停止”的任务列表，而是一个可被 Team+Ralph 持续执行、持续修正、持续保留有效方法的排序实验路线。

核心策略：**先建设统一排序实验底座，再在同一底座上分阶段系统实验主流排序方法；每阶段都可以多轮迭代，效果好的进入 champion/challenger registry，效果差或不可验证的方法进入 diagnostic / blocked / no-promote，不因单阶段完成而停止。**

## 1. 长期目标与当前边界

### 1.1 长期目标

在已经晋升的 frozen pool200 召回候选池上，建立一个可持续运行的排序实验体系：

1. 固定候选池边界，避免把召回变化误判为排序收益。
2. 用统一 registry、artifact equality、same-run baseline、status machine 和 report schema 管理每次排序实验。
3. 从规则排序、线性模型、树模型、LambdaMART、神经排序、序列/注意力排序，到未来线上 bandit/RL/Agent feedback，按证据成熟度分阶段推进。
4. 每个方法族都要实验、测试、记录、比较；效果好的保留，效果差的淘汰或降级为诊断。
5. 不把任何单个阶段、单个模型或单次 smoke 结果当作终点；阶段完成后进入下一轮优化或下一阶段。

长期理想终局是形成一条证据充分、可解释、可维护、可扩展的排序路线；如果当前 frozen-pool 离线证据不足以晋升复杂模型，则保留 baseline/champion，并把下一步问题定位到特征、标签、样本量、依赖或线上反馈闭环。

### 1.2 当前固定召回底座说明

当前排序实验可以建立在已经固定的召回底座上，即使该召回底座还不是长期最优召回方案。这样做的目的不是宣称召回已经完成，而是为排序侧提供一个稳定、可复验、可对照的输入边界。

执行含义：

- 当前 fixed recall base 是排序实验的 versioned input substrate。
- 排序实验只比较同一召回底座内的 Top-K 排序变化。
- 当前排序结论只对该 frozen recall base 生效，不外推到未来召回底座。
- 如果后续召回底座升级，需要重新冻结 candidate pool，并重跑 champion/challenger 排序复验。
- 不因召回底座尚未完全优化而阻塞排序实验；但所有报告必须说明“排序收益是在当前固定召回底座上得到的”。

### 1.3 当前不可突破边界

除非另开召回阶段并重新批准，否则排序 Agent 必须遵守：

- 不修改当前固定召回底座的召回语义。
- 不修改 `candidate_pool_size=200`。
- 不修改 `top_k=5`。
- 不把 LOPO 结果作为 valid/test promotion evidence。
- 不把线上 CTR、CVR、GMV、dwell time、add-to-cart、retention、A/B uplift、P95/SLO 作为当前离线晋升依据。
- 不让 LTR、深度模型、Agent feedback 或任何未来线上信号绕过 frozen candidate equality gate。
- 不提前绑定 serving/frontend/display contract。
- 所有命令使用项目默认 `.venv`：`./.venv/Scripts/python.exe`。

## 2. 排序实验底座优先级

后续所有主流方法实验必须建立在统一底座上。没有底座，不进入大规模模型堆叠。

### 2.1 底座必须提供的能力

1. **统一输入**
   - frozen pool200 candidates。
   - same-run baseline。
   - 固定 `candidate_pool_size=200`、`top_k=5`。
   - 明确 config snapshot 与 command_text。

2. **统一 artifact**
   - `metrics.json`。
   - `recommendations.jsonl`。
   - `ranking_hit_cases.jsonl`。
   - `ranking_case_summary.json`。
   - `frozen_candidates.jsonl`。
   - `comparison.json`。
   - `comparison.md`。

3. **统一 registry**
   - method_id / candidate_id。
   - method_family。
   - lane：promotion / diagnostic / future-online。
   - promotion_eligible。
   - diagnostic_only。
   - config hash / frozen candidate hash。
   - feature contract version。
   - leakage gate summary。
   - status machine result。
   - champion/challenger relation。

4. **统一门禁**
   - frozen candidate artifact equality。
   - candidate pool size equality。
   - top_k equality。
   - fallback rate 不增加。
   - hit rate practical lift。
   - missed topK user reduction。
   - NDCG/MRR/MAP 不回退。
   - minimum runs / consistency gate。
   - segment underpowered diagnostic-only。
   - invalid/stop evidence exclusion。

5. **统一方法保留机制**
   - `champion`：当前最强可上线候选或当前最终离线路线。
   - `challenger`：通过基础门禁但仍需更多稳定性证据的方法。
   - `diagnostic`：有解释价值但不可晋升的方法。
   - `blocked`：依赖、样本、特征或实现条件不足的方法。
   - `retired`：多轮证据显示无收益且继续实验边际价值低的方法。

### 2.2 底座相关当前状态

已具备的基础包括：

- normalized-additive ranking diagnostics。
- frozen candidate hash/count gate。
- `strict_ranking_promotion_status()`。
- `ranking_experiment_registry`。
- feature/leakage gate 基础。
- lightweight LTR diagnostic runner。
- terminal route runner 初版。

后续 Team+Ralph 的第一优先级不是继续散跑模型，而是把这些能力整理成可复用、可扩展、可批量调度的排序实验底座。

## 3. 持续执行总流程

每一个方法族、每一次参数变体、每一轮复验都必须进入同一闭环：

```text
选择方法族
→ 检查进入条件
→ 生成候选配置
→ 运行 same-run baseline
→ 运行 variant/challenger
→ 写 registry
→ 检查 artifact equality
→ 检查 leakage/feature gate
→ 计算 metrics/segments/stability
→ status machine 判定
→ 更新 champion/challenger registry
→ 更新中文叙事和方法矩阵
→ 决定继续迭代、保留、降级、淘汰或进入下一阶段
```

阶段不是停止点。Phase 0 完成后必须自动进入 Phase 1，Phase 1 完成后自动进入 Phase 2，后续阶段同理；除非用户明确停止、硬边界被破坏、或某阶段被证据化标记为 blocked，否则 Team+Ralph 不应在阶段完成处停下等待确认。

每个阶段内部可以持续迭代：

- 如果有提升但不稳定：继续 multi-run、segment 和 ablation。
- 如果有稳定提升：进入 challenger，再与 champion 做更严格对照。
- 如果无提升但诊断价值高：保留 diagnostic 记录并进入下一方法族。
- 如果不可实现：更新计划，把原因标记为 blocked，并给出恢复条件，然后进入下一个可执行阶段。
- 如果继续实验没有新增决策价值：阶段收口，进入下一阶段，而不是停止整个长期任务。

## 4. 晋升状态机

### BASELINE

同跑 frozen baseline，不参与 promotion，只作为比较锚点。

### INVALID/STOP

出现以下任一情况，实验无效并停止进入 promotion 判断：

- frozen candidate hash/count drift。
- `candidate_pool_size` drift。
- `top_k` drift。
- `fallback_rate` 增加。
- `candidate_hit_rate_at_pool` 或 `candidate_count_avg` 漂移超过 tolerance。
- runner 没有写出 registry entry。
- 实验产物缺失关键 metrics。
- 使用 forbidden feature、future interaction、holdout target 或 valid/test label leakage。
- 把 diagnostic / LOPO / online-only evidence 伪装成当前离线 promotion evidence。

### PARTIAL diagnostic-only

出现以下情况时，只作为诊断保留：

- 二级指标提升但 `hit_rate_at_k` 没有达到实用阈值。
- LOPO 提升但 valid/test 或 same-run frozen evidence 未提升。
- LTR 或深度模型启用但没有完成泄漏/稳定性门禁。
- 指标持平但 case study、near-miss、segment diagnostics 有解释价值。
- 当前依赖不足，只能实现 deterministic stand-in 或 toy prototype。

### CHALLENGER

满足基本有效性，但还没足够晋升：

- frozen candidate equality 通过。
- `candidate_pool_size=200`、`top_k=5`。
- feature/leakage gate 通过。
- 至少一个关键指标不差于 champion。
- 需要更多 runs、segments 或 ablation 才能判断是否 Promote。

### Promote

必须同时满足：

- frozen candidate artifact equality 匹配。
- `fallback_rate` 不增加。
- `candidate_pool_size` 和 `top_k` 不变。
- `hit_rate_at_k` 绝对提升 `>= 0.001`。
- `hit_rate_at_k` 相对提升 `>= 3%`。
- `candidate_hit_missed_topk_users` 至少减少 1。
- `ndcg_at_k`、`mrr_at_k`、`map_at_k` 不回退。
- 至少 2/3 个 split 或 run 方向一致。
- 复杂模型相对简单模型的收益足够覆盖复杂度；若复杂模型 lift `< 0.001` 且二级指标没有明显优势，选择简单模型。

## 5. 分阶段持续路线图

### Phase 0：排序实验底座固化

目标：把现有分散 runner、registry、门禁、artifact schema 整理成所有排序方法共享的实验底座。

实验内容：

1. 统一 comparison schema。
2. 统一 method registry / champion registry。
3. 统一 config generation / override 机制。
4. 统一 artifact inspection。
5. 统一 No-Promote / blocked / diagnostic-only reason schema。
6. 统一 report markdown 模板。
7. 统一 smoke / full-run 命令模板。

完成标准：

- 新增或扩展一个可复用 ranking experiment runner scaffold。
- 所有候选方法都能注册 method_family、lane、promotion eligibility 和 output_dir。
- 测试覆盖 pool200/top_k/frozen equality/lane separation/artifact inspection。
- 文档记录如何新增一个排序方法。

不停止条件：

- Phase 0 完成后不结束长期任务；进入 Phase 1 方法族实验。

### Phase 1：规则与可解释排序基线

目标：建立强且可解释的非学习排序 champion。

方法族：

- normalized additive。
- source-aware fusion。
- item feature rerank。
- freshness / quality / popularity calibration。
- near-miss rescue / tie-breaker。
- finite grid / coordinate search。

保留标准：

- 若稳定优于 baseline，进入 champion 或 challenger。
- 若只解释了 near-miss case 但指标不足，进入 diagnostic。
- 若多轮无收益，retire 对应参数区间，而不是删除历史证据。

继续迭代方向：

- source 权重分段。
- user history length segment。
- candidate hit rank bucket。
- source contribution ablation。

### Phase 2：fine_rank 线性与浅层学习排序

目标：在 fine_rank full-pool scoring 底座上验证 linear / pointwise / pairwise 是否能稳定提供可学习信号。

方法族：

- linear ranker。
- logistic regression style pointwise ranker。
- pairwise perceptron / pairwise linear ranker。
- calibrated linear scoring。
- small feature interaction model。

进入条件：

- Phase 0 底座可复用。
- feature contract 与 leakage gate 已启用。
- label/split 来源可审计。

职责边界：

- fine_rank 负责 full-pool scoring；当前这一层可以产出 linear / LTR / tree 的统一算法入口，但只有 same-run valid/test 证据才进入 promotion 讨论。
- pointwise / pairwise 在当前 batch 只保留 diagnostic-only 角色，不再写成 promotion-capable。

保留标准：

- valid frozen same-run evidence 达到 CHALLENGER 才能继续考虑 promotion。
- LOPO 只能作为诊断，不作为 promotion。
- 如果只在训练/LOPO 上提升，降级为 diagnostic。

### Phase 3：fine_rank 树模型与 LambdaMART 路线

目标：在同一个 fine_rank full-pool scoring 入口上验证树模型与 LambdaMART 是否具备真实训练依赖和分组目标支持。

方法族：

- decision stump / rule ensemble diagnostic。
- GBDT。
- XGBoost / LightGBM style ranker。
- LambdaMART。
- pairwise/listwise tree ranker。

进入条件：

- 依赖存在或允许添加训练依赖。
- 特征矩阵导出稳定。
- query/user group 信息可用于 ranking objective。
- evaluation split 不泄漏。

如果依赖不足：

- 可以导出训练数据、group label 或特征矩阵，但必须标记为 diagnostic / blocked / preparation。
- 不得声称 deterministic stand-in 等价于真实 LightGBM/LambdaMART。
- 计划中记录恢复条件：依赖、训练数据格式、group label、测试门禁。

保留标准：

- 与 Phase 2 最强 champion 比较。
- 稳定 lift 且复杂度收益合理才进入 Promote。
- 微弱提升但维护成本高时保留为 challenger，不替换 champion。

### Phase 4：神经排序原型

目标：验证深度排序是否能从更丰富特征中获得额外收益。

方法族：

- MLP ranker。
- RankNet。
- LambdaRank。
- ListNet / ListMLE prototype。
- Wide & Deep。
- DeepFM。
- DCN / DCNv2。
- xDeepFM。

默认 lane：diagnostic。

进入条件：

- 训练依赖明确。
- 特征规模和标签规模足够。
- 有稳定 validation protocol。
- 有与浅层 champion 的 same-run 对照。

保留标准：

- 如果只证明“可训练”，不保留为 challenger。
- 如果提升不稳定或样本不足，保留为 diagnostic。
- 若要从 diagnostic 转 promotion，必须单独 ADR 批准，并补齐稳定性、复杂度和可维护性评估。

### Phase 5：用户行为序列与注意力排序

目标：为更接近工业推荐排序的行为序列模型建立路线，但不在数据不足时硬做。

方法族：

- DIN。
- DIEN。
- BST。
- SIM。
- session-aware reranker。
- attention over user history。

进入条件：

- 用户行为序列足够长。
- 时间顺序可靠。
- 有 session 或 history window 定义。
- 不使用未来交互。

当前默认状态：future / blocked-until-data-ready。

保留标准：

- 如果当前数据只支持 toy prototype，标记 diagnostic。
- 如果行为序列不足，更新计划为 blocked，不硬实现。

### Phase 6：语义/双塔特征与 Top-K rerank 约束层

目标：在不改变召回语义的前提下，验证语义或双塔分数作为排序特征的价值；Top-K rerank 只作为本地 diagnostic / constraint 层，不作为 fine_rank 的替代入口，除非另行批准。

方法族：

- DSSM rerank。
- two-tower score feature。
- semantic-title score feature。
- vector similarity feature。
- cross-feature fusion with itemcf/source/popularity。

边界：

- 不能混入新的召回候选。
- 只能使用 frozen candidate 内已有或可审计的特征。
- rerank 只对 frozen candidate 的 Top-K 做本地约束、解释或诊断，不承担 full-pool scoring。
- 如果双塔改变候选池，必须另开召回阶段，不属于当前排序 promotion。

### Phase 7：多目标排序与业务目标预留

目标：为未来线上阶段预留多目标排序路线，但不把线上指标写成当前离线证据。

方法族：

- ESMM。
- MMoE。
- PLE。
- multi-task learning。
- diversity / novelty / calibration objective。
- constrained ranking。

当前状态：future-online。

进入条件：

- 有 CTR/CVR/GMV 或其他业务 label。
- 有线上或准线上评估链路。
- 有 serving/monitoring contract。

当前离线阶段处理方式：

- 只写路线图和接口预留。
- 不参与 frozen-pool offline promotion。

### Phase 8：在线学习、Bandit、RL 与 Agent feedback

目标：未来把推荐 Agent 的多轮反馈、澄清和用户偏好纳入排序闭环。

方法族：

- contextual bandit。
- Thompson sampling / UCB。
- learning-to-rank from feedback。
- RL / GRPO preference optimization。
- conversational rerank policy。

当前状态：future-agent-online。

进入条件：

- 有交互日志。
- 有安全的探索策略。
- 有离线 replay 或在线 A/B。
- 有反馈 reward schema。

当前限制：

- 不作为当前 frozen pool200 离线 promotion 证据。
- 只在后续 Agent/线上阶段实现。

## 6. 主流方法矩阵

| 方法族 | 代表方法 | 当前动作 | 默认 lane | 是否可晋升 | 保留/淘汰规则 |
| --- | --- | --- | --- | --- | --- |
| 规则排序 | normalized additive, source-aware fusion, item feature rerank | 继续作为强 baseline/champion 候选 | promotion | 可 | 稳定提升保留；无提升但可解释则 diagnostic |
| 参数搜索 | finite grid, coordinate search | 在规则排序内持续迭代 | promotion | 可 | 只保留稳定权重区间 |
| 线性模型 | linear ranker, calibrated linear | fine_rank full-pool scoring baseline | diagnostic/challenger | 需 same-run valid/test 证据，当前不按 promotion-capable 叙事 |
| Pointwise | logistic regression style | fine_rank diagnostic-only | diagnostic | 默认不晋升；LOPO-only 不晋升 |
| Pairwise | pairwise perceptron, pairwise linear | fine_rank diagnostic-only | diagnostic | 默认不晋升；缺同跑证据不晋升 |
| 树模型 | GBDT, XGBoost, LightGBM | fine_rank tree prep / blocked | diagnostic/blocked | 依赖不足或无真实 adapter 时 blocked，不用 deterministic stand-in 冒充收益 |
| LambdaMART | LambdaMART, LambdaRank tree | fine_rank tree prep / blocked | diagnostic/blocked | 需要真实 ranking objective、group/split 和 adapter；否则 blocked |
| 神经 pairwise | RankNet, LambdaRank | Phase 4 | diagnostic | 默认不可 | 转 promotion 需 ADR |
| 神经 listwise | ListNet, ListMLE | Phase 4 | diagnostic | 默认不可 | 样本不足则 blocked |
| Wide/Deep | Wide&Deep, DeepFM, DCN, xDeepFM | Phase 4 | diagnostic | 默认不可 | 需要更完整特征体系 |
| 行为序列 | DIN, DIEN, BST, SIM | Phase 5 | future/diagnostic | 当前不可 | 无可靠序列则 blocked |
| 语义/双塔 rerank | DSSM, two-tower feature rerank | Phase 6 | diagnostic/promotion | 条件可 | 不得改变候选池 |
| 多目标 | ESMM, MMoE, PLE | Phase 7 | future-online | 当前不可 | 需要业务 label 与线上链路 |
| 在线探索 | bandit, RL, GRPO, Agent feedback | Phase 8 | future-agent-online | 当前不可 | 需要交互日志与安全探索 |

## 7. GPU 实验资源策略

需要 GPU 的排序实验应调用 GPU，不要为了迁就 CPU 环境而把需要 GPU 的主流方法降级成无意义 toy run。

适用方法族：

- RankNet / LambdaRank / ListNet / ListMLE。
- Wide&Deep / DeepFM / DCN / xDeepFM。
- DIN / DIEN / BST / SIM。
- DSSM / two-tower rerank 训练或大规模 embedding 特征计算。
- bandit / RL / GRPO / Agent feedback 中需要神经网络训练或大规模 replay 的实验。

执行规则：

1. 在进入 GPU 方法阶段前，先检查 GPU 可用性、CUDA/PyTorch 或对应训练依赖、显存与 batch size。
2. 如果 GPU 可用，真实训练实验优先走 GPU，并把 device、依赖版本、batch size、训练时长和随机种子写入 artifact。
3. 如果 GPU 不可用，不要把 CPU toy result 包装成真实模型收益；只能标记为 `blocked-gpu-unavailable`、`diagnostic-cpu-smoke` 或导出训练数据等待 GPU 环境。
4. GPU 实验仍必须遵守 frozen pool200、`candidate_pool_size=200`、`top_k=5`、不改召回语义、leakage gate 和 same-run baseline 对照。
5. GPU 只解决训练资源问题，不降低 promotion 门禁；没有稳定离线 lift 的 GPU 模型仍然 no-promote。

## 8. Champion / Challenger 管理规则

每轮实验结束后必须更新方法状态：

```text
candidate → INVALID/STOP | diagnostic | blocked | retired | challenger | champion
```

规则：

1. 当前 champion 不因新方法出现而自动失效。
2. challenger 必须和 champion 做 same-run 对照。
3. Promote 后才允许替换 champion。
4. 效果好的方法保留配置、artifact、报告和适用边界。
5. 效果差的方法保留 no-promote reason，避免重复浪费实验。
6. blocked 方法必须写清恢复条件，例如依赖、数据、标签、序列、线上反馈或工程接口。
7. 每次 Team+Ralph 继续执行时，优先读取 champion/challenger registry，而不是从头试错。

## 9. Team+Ralph 执行协议

推荐用 Team+Ralph 长时间执行，每次围绕一个阶段或一个方法族创建 PRD，但不把阶段完成当作长期任务结束。

每个 PRD 必须包含：

1. 实验底座或方法族的明确用户故事。
2. 具体可验证的 acceptance criteria。
3. 是否允许修改计划本身。
4. 方法进入/退出条件。
5. 测试和 runner smoke。
6. verifier / architect 复核。
7. 中文叙事更新。

推荐执行节奏：

```text
Batch 0: 实验底座固化
Batch 1: 规则排序 champion/challenger registry
Batch 2: 线性 + pointwise + pairwise learned baseline
Batch 3: GBDT + LambdaMART 真实依赖评估与实现
Batch 4: 神经排序 diagnostic prototypes
Batch 5: 行为序列 / 语义 rerank / 双塔特征融合
Batch 6: 多目标与线上 Agent feedback 路线预留
Batch N: 持续回看 champion、补实验、清理 retired/blocked 方法
```

如果 verifier 或 architect FAIL：

```text
进入 fix-loop → 修复 blocker → 重跑验证 → 重新复核 → 直到 PASS、blocked 或计划修正完成
```

## 10. 计划自我修正规则

执行过程中如果发现原计划存在不合理、不可验证、不可完成或会破坏排序边界的问题，Agent 不应机械继续，而应优化计划本身：

- 将错误假设、阻塞原因和证据写入 ADR、阶段叙事或本计划。
- 调整候选路线、门禁阈值、artifact 要求或验证顺序，使其继续服务于长期排序优化。
- 如果某个方法因依赖、数据、样本量、标签或泄漏风险无法完成，应标记为 `blocked` / `diagnostic-only` / `no-promote`，而不是硬凑结果。
- 如果某阶段继续实验已经无法增加离线决策价值，应收口该阶段并进入下一阶段，而不是停止整个长期任务。
- 如果当前 frozen-pool 离线边界已经无法回答问题，应明确转入 future-online / Agent-feedback 阶段，而不是把线上目标伪装成离线 promotion。
- 所有计划修正都必须保持 frozen pool200、`candidate_pool_size=200`、`top_k=5`、不改召回语义、不提前绑定 serving/frontend/display 的硬边界，除非用户明确批准新阶段。

## 11. 推荐命令模板

所有命令默认使用：

```bash
./.venv/Scripts/python.exe
```

基础验证：

```bash
./.venv/Scripts/python.exe -m compileall rs_core scripts tests
./.venv/Scripts/python.exe -m pytest tests/test_evaluation.py tests/test_hybrid_demo.py tests/test_ltr.py
```

终局/底座 runner smoke：

```bash
./.venv/Scripts/python.exe scripts/experiments/ranking/run_phase_1_29_terminal_ranking_route.py --output-dir outputs/ranking/phase_1_29_terminal_ranking_route_smoke --limit-users 20 --runs 1
```

后续方法族 runner 命名建议：

```text
scripts/experiments/ranking/run_phase_<phase>_<method_family>_pool200_ranking.py
outputs/ranking/phase_<phase>_<method_family>_pool200_ranking/comparison.json
outputs/ranking/phase_<phase>_<method_family>_pool200_ranking/comparison.md
```

## 12. 文档与面试叙事要求

每个阶段或方法族收口后更新：

- `dic/OPTIMIZATION_NARRATIVE.md`
- `dic/ENGINEERING_NARRATIVE_LOG.md`

记录格式：

- 任务。
- 遇到的问题。
- 定位方式。
- 解决方式。
- 验证结果。
- 面试可讲点。

表达原则：

- 有提升才说提升。
- 无提升就写诊断价值。
- 不把平台能力包装成模型收益。
- 不把线上指标写成离线晋升证据。
- 不把 LOPO sanity 写成 valid/test promotion。
- 不把 stand-in 包装成真实工业 LightGBM/LambdaMART。

## 13. 当前下一步推荐

下一次 Team+Ralph 执行建议进入 **Phase 1.31：统一算法实验 scaffold**，随后进入 **Phase 1.32：第一批主流排序算法实验**。Phase 1.30 已经证明物理 `coarse → fine → rerank` 链路可审计，下一步不应继续只做平台检查，也不应直接跳到深度模型，而是先把“可重复新增算法、训练、推理、对照、登记、判定”的 runner 能力固化。

### 13.1 Phase 1.30 收口说明

- Phase 1.30 smoke 证明的是物理流水线证据：`candidate_pool_size=200`、`top_k=5`、`artifact_inspection=PASS`、`physical_pipeline_inspection=PASS`、`frozen_candidate_match=true`，以及 coarse/fine/rerank stage counts 均为 3225。
- 这些证据只说明 `recall → coarse → fine → rerank` 链路可复验，不等于 promotion evidence。
- `online_metric_claims=[]`，因此线上 CTR/CVR/GMV 等指标仍然是 future-only，不能写入当前离线晋升。
- Phase 1.26 regression 继续保持 `LTR LOPO diagnostic-only`、`promotion_eligible=false`，tree/LambdaMART blocked；LOPO / gate / smoke 都只作诊断收口。

### 13.2 Phase 1.31：统一算法实验 scaffold

目标：把 Phase 1.26 的真实训练能力和 Phase 1.30 的物理 stage artifact 合并成可复用算法实验底座，而不是每个方法族各写一套孤立 runner。

Team+Ralph 第一批任务：

1. 新增或抽象 `ranking_algorithm_experiment` scaffold，统一处理 baseline、variant、training artifact、stage artifact、frozen candidate equality、feature/leakage gate、method registry、experiment registry、comparison report。
2. 给 Phase 1.30 runner 补齐 deterministic seed 记录；如果 CLI 不接收 `--seed`，要么实现，要么在计划中明确它为何不影响 inspection-only 结论。
3. 统一算法候选描述 schema：`method_id`、`method_family`、`stage_target`、`requires_training`、`requires_gpu`、`dependency`、`promotion_lane`、`blocked_recovery_condition`。
4. 统一 evidence 判定：valid/test frozen same-run evidence 才能进入 challenger/promotion；LOPO、gate、smoke、stage trace、training loss 只能作为 diagnostic/supporting evidence。
5. 新增测试覆盖：新增方法必须写 registry；缺依赖/GPU 必须 blocked；stage artifact 与 frozen pool200/top_k=5 必须保留；线上指标字段出现时必须拒绝。

完成标准：

- 一个新算法只需要声明 method spec 和训练/推理 adapter，就能进入相同 comparison schema。
- baseline、variant、blocked 方法共用 method registry 与 report 模板。
- 所有产物仍保持 `candidate_pool_size=200`、`top_k=5`、frozen candidate match。
- 不修改召回语义，不把平台证据包装成模型效果。

Phase 1.31 最小可交付合同：

- 至少有一个稳定入口，例如 `rs_core/workflow/ranking_experiments.py`，或一个脚本内可复用公共函数；不能只复制一份一次性 runner。
- method spec 必须包含 `method_id`、`method_family`、`stage_target`、`requires_training`、`requires_gpu`、`dependency`、`promotion_lane`、`blocked_recovery_condition`。
- run row schema 必须覆盖 baseline、variant、diagnostic、blocked 四类方法。
- 必须复用或兼容 `build_ranking_experiment_registry_entry()` 与 `build_ranking_method_registry_entry()`，禁止另造不兼容 registry。
- blocked method row 必须包含 dependency/GPU 状态、blocked reason 和恢复条件。
- 测试必须断言一个 dummy/spec-only blocked method 不复制新 runner 也能进入 method registry。

### 13.3 Phase 1.32：第一批主流算法实验

**本次 Team+Ralph 批准执行范围只包含前三项**，其余方法族只记录路线和 blocked 条件，不在本轮训练或晋升。

1. **规则/可解释 champion 复验**：先复跑当前 baseline/champion，再只做小网格 sanity 的 normalized additive、source-aware fusion、item-feature rerank、finite grid / coordinate search。目标是确认强非学习 champion，给学习模型提供真实对照，避免一开始扩大成大规模调参。
2. **浅层 learned fine-ranker**：pointwise logistic、pairwise perceptron、calibrated linear ranker。复用 Phase 1.26 训练链路，但必须补 valid/test frozen same-run evidence；LOPO 只保留为 sanity/diagnostic。
3. **树模型准备，不硬跑 promotion**：只做 feature matrix / group export、sklearn GBDT dependency check、XGBoost/LightGBM/LambdaMART dependency + GPU check，以及 blocked registry row。若 ranking objective、依赖、GPU 或 adapter 不完整，标记 diagnostic/blocked，不写 toy promotion。

**本轮明确不做：**

- GPU-required LambdaMART / neural ranker 训练：XGBoost/LightGBM GPU、RankNet、LambdaRank、DeepFM、DIN 等只记录后续进入条件；无真实 GPU 验证即 blocked。
- 语义/双塔 rerank 训练或候选池变更：只能记录为未来 frozen-candidate 内排序特征路线；如果改变候选池，必须转召回阶段。
- future-online / Agent feedback promotion：CTR/CVR/GMV/P95/SLO、bandit、RL、GRPO、Agent online feedback 只写路线，不进入当前离线 promotion。

第一批选择规则 champion 复验 + 浅层 learned ranker valid/test evidence，是因为它们复杂度最低、最容易验证 leakage/frozen equality，也最适合判断当前特征是否真的有排序信号。

### 13.4 待批准的 Team+Ralph 执行边界

下一次执行提示建议：

```text
/team ralph 执行 Phase 1.31/1.32：在 Phase 1.30 物理 coarse→fine→rerank 平台上，先实现统一算法实验 scaffold，再跑规则 champion 复验和浅层 learned fine-ranker 第一批真实实验；同时只做树模型 feature/group export、dependency/GPU check 和 blocked registry，不做树模型/神经/GPU promotion。保持 frozen pool200/candidate_pool_size=200/top_k=5，不改召回语义；LOPO/gate/smoke/stage trace 不作为 promotion evidence；GPU-required 方法无真实 GPU 验证则 blocked；完成后更新 comparison、registry、测试和中文叙事，不 commit。
```

验收命令仍必须使用 `.venv`，至少包含：

```bash
./.venv/Scripts/python.exe -m py_compile rs_core/recsys/ranking.py rs_core/recsys/evaluation.py rs_core/workflow/hybrid_demo.py scripts/experiments/ranking/run_phase_1_30_physical_ranking_pipeline.py scripts/experiments/ranking/run_phase_1_26_real_ranking_experiments.py
./.venv/Scripts/python.exe -m pytest tests/test_evaluation.py tests/test_hybrid_demo.py tests/test_ltr.py -q
./.venv/Scripts/python.exe scripts/experiments/ranking/run_phase_1_30_physical_ranking_pipeline.py --output-dir outputs/ranking/phase_1_30_physical_ranking_pipeline_regression --limit-users 20
./.venv/Scripts/python.exe scripts/experiments/ranking/run_phase_1_26_real_ranking_experiments.py --output-dir outputs/ranking/phase_1_26_real_ranking_experiments_regression --limit-users 20 --seed 20260513
```

Phase 1.31/1.32 runner 完成后，必须新增并执行对应 smoke，不能只跑旧 Phase 1.30/1.26 回归就宣称完成：

```bash
./.venv/Scripts/python.exe scripts/experiments/ranking/run_phase_1_31_ranking_algorithm_scaffold.py --output-dir outputs/ranking/phase_1_31_ranking_algorithm_scaffold_smoke --limit-users 20 --seed 20260513
```

新 runner smoke 必须断言：

- `method_registry` 同时包含 baseline、至少一个可执行 variant、至少一个 blocked method。
- `comparison.json` 中 LOPO/gate/smoke/stage trace 没有被标记为 promotion evidence。
- blocked GPU/dependency 方法包含 dependency/GPU 状态、blocked reason 和恢复条件。
- 所有可执行 run 都保持 `candidate_pool_size=200`、`top_k=5`、frozen candidate match 和 stage artifact。

### 13.5 Phase 1.31/1.32 执行结果回填

- Phase 1.31 已把排序算法实验收敛成可复用 scaffold：`method_id`、`method_family`、`stage_target`、`requires_training`、`requires_gpu`、`dependency`、`promotion_lane`、`blocked_recovery_condition` 与 comparison/report schema 进入同一底座。
- Phase 1.32 已跑完首批诊断范围：规则 champion 复验、浅层 learned fine-ranker 变体与树模型准备均按 diagnostic-only / blocked 收口；tree/LambdaMART 仍停留在依赖、group export 与 GPU 准备，不具备 promotion evidence。
- 全部运行继续保持 `frozen pool200`、`candidate_pool_size=200`、`top_k=5`，`online_metric_claims=[]`，因此 CTR/CVR/GMV/P95 仍只属于 future-only。
- 已核验证据：`./.venv/Scripts/python.exe -m py_compile rs_core/recsys/ranking.py rs_core/recsys/evaluation.py rs_core/workflow/hybrid_demo.py scripts/experiments/ranking/run_phase_1_30_physical_ranking_pipeline.py scripts/experiments/ranking/run_phase_1_26_real_ranking_experiments.py` PASS；`./.venv/Scripts/python.exe -m pytest tests/test_evaluation.py tests/test_hybrid_demo.py tests/test_ltr.py tests/test_phase_1_31_ranking_scaffold.py -q` 135 passed in 2.31s；`outputs/ranking/phase_1_30_physical_ranking_pipeline_regression/comparison.json`、`outputs/ranking/phase_1_26_real_ranking_experiments_regression/comparison.json`、`outputs/ranking/phase_1_31_ranking_algorithm_scaffold_smoke/comparison.json` 均保留。
- 后续只继续做更稳定的 rule / LTR / 树模型准备，不把 scaffold 或 smoke 结果写成模型晋升。

### 13.6 Phase 2 fine-rank batch 执行结果回填

- 已新增 `scripts/experiments/ranking/run_phase_2_fine_rank_algorithm_batch.py` 与 `tests/test_phase_2_fine_rank_algorithm_batch.py`，把 fine_rank 的 linear / pointwise / pairwise / tree / LambdaMART 批量运行收敛到同一入口。
- 验证命令 `./.venv/Scripts/python.exe -m py_compile scripts/experiments/ranking/run_phase_2_fine_rank_algorithm_batch.py tests/test_phase_2_fine_rank_algorithm_batch.py` 与 `./.venv/Scripts/python.exe -m pytest tests/test_phase_2_fine_rank_algorithm_batch.py -q` 通过，后者结果 `3 passed`。
- learned rows 当前只保留为 diagnostic-only；linear / pointwise / pairwise 只验证 full-pool scoring 证据，不写 promotion 结论。
- tree / LambdaMART 仍是 blocked / preparation：缺真实依赖或 adapter 时必须 blocked，不能用 deterministic stand-in 冒充工业模型收益。
- 全部运行仍保持 `frozen pool200`、`candidate_pool_size=200`、`top_k=5`，不改召回语义。

### 13.7 Phase 3 tree / LambdaMART 执行回填

- 已新增 `scripts/experiments/ranking/run_phase_3_tree_ranking_experiments.py`，并补齐 `tests/test_phase_3_tree_ranking_experiments.py`。
- smoke 产物落在 `outputs/ranking/phase_3_tree_ranking_experiments_smoke/comparison.json`，验证口径继续固定 `candidate_pool_size=200`、`top_k=5`。
- 训练行导出显示 `training rows=2217`、`positive=16`、`negative=2201`；`sklearn` GBDT 只保留为 diagnostic-only。
- 即使依赖或 GPU 可用，LambdaMART 仍因 serving adapter、valid-test promotion gate 和 objective recovery condition 不完整而 blocked。
- 本轮没有任何 online promotion evidence，`merge_for_user` 和召回语义保持不改；后续只补训练依赖、group/objective 与恢复条件，不把 tree smoke 写成晋升结论。

### 13.8 Phase 4 三阶段实验计划：coarse shadow / fine / rerank / future-online

**为什么 Top-5 不能单独作为唯一信号：**

- `top_k=5` 的命中天然稀疏，单个位置波动会被放大成“成败结论”。
- coarse/fine/rerank 的收益通常先体现在 `rank movement`、`near-miss rescue`、`source coverage`、`score_trace` 和 `candidate_hit_rate_at_pool`，不是一开始就体现在 Top-5 全胜。
- 因此新增弱指标只作诊断和选路，不作当前 promotion evidence。

**三阶段主线：**

1. **coarse shadow 主路**：`coarse_rank` 不再只是 pass-through 占位符，而是 shadow coarse main lane。它继续在 frozen pool200 上产出 coarse score / trace / rank movement，但不缩池、不改 `candidate_pool_size=200`、不改 `top_k=5`，也不改变召回语义。
2. **fine 主路**：保持 learned fine ranker、pointwise / pairwise / calibrated linear 的真实训练入口，继续把 LOPO、valid/test、same-run smoke 分开。当前只能把 learned fine ranker 当作 diagnostic/challenger 收口，不能把训练跑通直接写成 promotion。
3. **rerank + future-online 主路**：rerank 只保留 bounded rerank trace、局部约束和解释能力；CTR/CVR/GMV、bandit、RL、Agent feedback 全部留在 future-online / future-agent-online 门禁外。

**算法主路矩阵与当前状态：**

| 主路 | 代表算法 / 职责 | 当前实现状态 | 已有测试 / 证据 | 当前结论 |
| --- | --- | --- | --- | --- |
| coarse | `coarse_rank` shadow、source-aware fusion、normalized additive、item feature rerank | 已从 pass-through 占位改成 shadow 主路，只记录 score_trace / rank movement，不 shrink pool | `outputs/ranking/phase_1_26_real_ranking_experiments_smoke/comparison.json`、`outputs/verification/verification_phase_1_30_smoke/comparison.json`，artifact inspection PASS、frozen candidate match=true | diagnostic / shadow only |
| fine | pointwise logistic、pairwise perceptron、calibrated linear、tree prep | 已有真实训练入口和算法 scaffold，但 promotion 仍要看 valid/test same-run 证据 | `tests/test_hybrid_demo.py`、`outputs/ranking/phase_1_31_ranking_algorithm_scaffold_smoke/comparison.json`、`outputs/recall/phase_1_21_recall_coverage/phase_1_32_*` 回填 | learned fine 先按 diagnostic/challenger 收口 |
| rerank | bounded rerank trace、局部约束、解释与诊断 | 保持 rerank 只做 trace 和约束，不接未来在线指标 | `outputs/verification/verification_phase_1_30_smoke/comparison.json`、`outputs/ranking/phase_1_26_real_ranking_experiments_smoke/comparison.json` | diagnostic only |
| future-online | CTR/CVR/GMV、bandit、RL、Agent feedback | 仅保留路线与门禁，不进入当前离线晋升 | `outputs/ranking/phase_7_8_future_online_gate_smoke/comparison.json` | future-only |

**当前执行口径：**

- 继续保持 `candidate_pool_size=200`、`top_k=5`、frozen candidate equality、artifact equality 和 same-run baseline。
- 弱指标只能解释“为什么值得继续跑”或“为什么只能诊断”，不能替代 promotion evidence。
- 如果 coarse/fine/rerank 任一主路的证据不足，先把它降级为 diagnostic / blocked，而不是为了补齐矩阵强行晋升。

### 13.9 Phase 4 stage shadow metrics 回填结果

- 已新增 `scripts/experiments/ranking/run_phase_4_stage_shadow_metrics.py` 与 `tests/test_phase_4_stage_shadow_metrics.py`，专门验证弱指标和 coarse shadow 口径。
- 验证命令 `./.venv/Scripts/python.exe -m py_compile scripts/experiments/ranking/run_phase_4_stage_shadow_metrics.py tests/test_phase_4_stage_shadow_metrics.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_phase_1_31_ranking_scaffold.py tests/test_phase_3_tree_ranking_experiments.py tests/test_phase_4_stage_shadow_metrics.py -q` 共 `11 passed`。
- smoke 产物落在 `outputs/ranking/phase_4_stage_shadow_metrics_smoke/comparison.json`，comparison 继续固定 `candidate_pool_size=200`、`top_k=5`，`artifact_inspection=PASS`。
- 弱指标只保留为 diagnostic/supporting，不触发 promotion；`coarse shadow retention` 与 `would_drop_positive` 被记录为诊断信号。
- stage main-lane matrix 已被回填，且 `frozen match/hash`、recall 语义与 `merge_for_user` 均保持不变；当前没有任何 online promotion evidence.

### 13.10 Phase 5 行为序列 / 注意力排序回填结果

- Phase 5 继续只把行为序列与注意力排序放在 frozen pool200 的诊断边界内，`session_aware_reranker_short_history_diagnostic` 与 `attention_over_user_history_diagnostic` 仍然只做 diagnostic，DIN / DIEN / BST / SIM 继续标记为 blocked。
- 验证命令 `./.venv/Scripts/python.exe -m py_compile scripts/experiments/ranking/run_phase_5_sequence_ranker.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_phase_5_fine_rank_positive_push.py -q` 通过 `7 passed`。
- smoke 产物 `outputs/ranking/phase_5_fine_rank_positive_push_smoke/comparison.json` 通过 contract 检查：`candidate_pool_size=200`、`top_k=5`、`frozen_candidate_comparison.match=true`、`case_diagnostic_success=true`、`promotion_success=false`、`online_claims=[]`、`artifact_inspection=PASS`。
- 这一轮确认的是“数据与证据门禁先行”：在当前序列覆盖与合同边界下，可以稳定产出诊断结果，但不能把 Phase 5 写成 promotion。
- 后续如果要推进行为序列路线，优先补长历史覆盖、时间顺序稳定性和 serving adapter，不改当前 frozen candidate 边界.

### 13.11 Phase 6 工业式默认全链路回填结果

- 已新增 `scripts/experiments/ranking/run_phase_6_industrial_ranking_chain.py` 与 `tests/test_phase_6_industrial_ranking_chain.py`，把工业常见链路显式放到同一个 frozen pool200 诊断 runner：`coarse_rank` 使用 source-weighted metadata shadow score，`fine_rank` 使用 normalized additive + source-aware fusion + item-feature full-pool scoring，`rerank` 使用 Top-5 source minimum 与 stable tie-break 的局部约束。
- 当前仍不替换 champion，不真实缩池，不改召回语义，不改 `merge_for_user`；`GBDT/LambdaMART fine_rank`、神经序列排序和 Agent/online feedback rerank 继续作为 future blocked route，等待真实 adapter、valid/test 与 future-online 合同。
- 验证命令 `./.venv/Scripts/python.exe -m py_compile scripts/experiments/ranking/run_phase_6_industrial_ranking_chain.py tests/test_phase_6_industrial_ranking_chain.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_phase_6_industrial_ranking_chain.py -q` 通过 `4 passed`。
- 真实 smoke `./.venv/Scripts/python.exe scripts/experiments/ranking/run_phase_6_industrial_ranking_chain.py --output-dir outputs/ranking/phase_6_industrial_ranking_chain_smoke --limit-users 5 --seed 20260513` 通过，`comparison.json` 显示 `candidate_pool_size=200`、`top_k=5`、`artifact_inspection=PASS`、baseline 与工业链路 `frozen_candidate_match=true`、`promotion_success=false`、`promotion_eligible=false`。
- smoke 期间发现 normalized additive 权重必须落在 Phase 1.25 有限网格内，已把 `source_signal` 与 `item_feature` 从越界值收回到允许的 `0.2`；这说明当前链路已经受实验底座约束，而不是任意调参。

### 13.12 Phase C 先行、Phase A 收口与 learned/tree/neural 路线

- Phase C 是 tuning 前的诊断门：先跑 Phase C diagnostic runner，在 frozen pool200、`candidate_pool_size=200`、`top_k=5` 下只看 `oracle@5`、`target rank percentile`、`duplicate-source balance` 和 `win/tie/loss`，先回答“值不值得调”，不直接写 promotion。
- Phase A 是合同稳定层：在 Phase C 通过后，再把候选快照、registry、schema、artifact equality 和 ablation/frozen evidence 固化成可持续合同；Phase A 只确认边界，不把 frozen snapshot 直接解释成模型收益。
- learned route 的顺序是 pointwise/pairwise/calibrated linear → GBDT/LambdaMART → neural rerank（RankNet、LambdaRank、ListNet、DeepFM 等）；tree / neural 只有在 same-run frozen valid/test 证据通过后，才进入 challenger / promotion 讨论。
- `oracle@5` 指现有冻结候选与可见特征下的 Top-5 理想上界，用来对照真实 rerank 的差距，不作为晋升证据。
- `target rank percentile` 按 `target_rank / input_candidate_count` 归一化，便于比较不同用户、不同候选规模下的位次分布。
- `duplicate-source balance` 主要看 `source_overlap.multi_source_candidate_rate`、`source_pair_counts` 和 `source_pair_jaccard`，衡量同一候选被多源共同覆盖的密度与均衡性。
- `win/tie/loss` 按 baseline vs challenger 的 target rank 改变量统计：改善记 win，持平记 tie，变差记 loss；只作为 diagnostic/supporting evidence。
- 诊断与晋升边界保持不变：LOPO、stage trace、training loss、oracle、target rank percentile、duplicate-source balance、win/tie/loss，以及任何线上指标都只作 diagnostic / future-only 证据；真正可晋升的仍然只有 same-run frozen valid/test evidence。

### 13.13 默认离线 mainline 收口与 Agent 系统手递

- 当前排序工作收口为可交给 Agent 系统直接复用的默认离线 mainline，而不是无限扩展方法族的长期探索；默认主线固定为 `coarse → fine → rerank`，其中 coarse 负责候选侧 shadow / 规则约束，fine 负责 full-pool scoring 与 learned diagnostics，rerank 负责 Top-K 局部约束与可解释诊断。
- 硬边界继续保持不变：`frozen pool200`、`candidate_pool_size=200`、`top_k=5`、召回语义不改、线上指标不作为当前离线晋升证据、LOPO / stage trace / training loss 只作诊断证据。
- learned/tree/neural 的后续位置保持为 future/blocked 路线：pointwise / pairwise / calibrated linear 仍可作为当前默认主线内的 learned baseline，GBDT / LambdaMART / neural rerank 仅在真实 same-run frozen valid/test 证据与额外门禁通过后再进入单独讨论，不纳入当前默认主线的完成标准。
- 完成标准不是“把所有算法都跑完”，而是“默认主线稳定可用、证据口径稳定、比较合同稳定、可由 Agent 系统直接交接”：新任务到来时，Agent 直接复用这条主线做排序、诊断和收口，不再把方法族扩展当作默认目标。
- Agent-system handoff 边界只覆盖这条已收口的 offline mainline；若要进入更激进的方法族探索，必须另开明确任务或 ADR，而不是在默认主线里继续发散。