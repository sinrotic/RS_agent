# Recall Methods Experiment Log（RALPLAN-DR v3）

> 版本：RALPLAN-DR v3
>
> 记录原则：只收录可核验的实验契约、方法边界、迁移后的结论与占位型工件索引；不写未验证结果，不用单点最优伪装成方法结论。

## 1. 固定合同

| 项 | 约束 |
| --- | --- |
| 研究对象 | 只讨论召回方法与召回相关的候选池构造，不把排序结果、前端展示或对话行为混入结论 |
| 评估边界 | 只在固定输入、固定切分、固定参数空间下比较；默认以 frozen pool / frozen split 为主，不允许随意扩池后直接对比 |
| 证据要求 | 每个结论都要能回指到 artifact、配置、脚本或表格；没有 artifact 的结论只能标为 `legacy_migrated_without_artifact` 或 `needs_rerun` |
| 结论粒度 | 结论必须写成“方法 + 证据级别 + 作用范围”，禁止只写“提升/没提升” |
| 迁移规则 | 旧文档中的结论只能按 `evidence_level` 迁移，不能在新文档里补写未验证结果 |
| 默认态度 | 没有足够证据时，一律记为 `defer`、`document_only` 或 `needs_rerun`，不要硬写成 `promote` |

## 2. Forbidden Metrics

以下指标或读法**不能作为召回方法晋升依据**，只能作为辅助诊断项或其他阶段指标：

| 类别 | 禁止项 | 原因 | 允许用途 |
| --- | --- | --- | --- |
| 排序指标 | `hit_rate_at_k` / `ndcg` / `mrr` / `map` | 这些指标受排序器影响，不能证明召回 source 本身可晋升 | 只用于排序阶段或端到端诊断 |
| Top-K 派生指标 | `topk_hit_rate` / `topk_hit_users` | Top-K 表现混入排序截断，不等价于候选池召回收益 | 只作为候选命中后的位置诊断 |
| 排序 gap 指标 | `ranking_gap_pool_has_target` | 只能说明候选池有目标但排序未命中，不能单独晋升召回 source | 用于定位排序问题 |
| 学习排序分数 | `ltr_score` / `rerank_score` | 分数来自排序模型，不是召回阶段证据 | 用于排序模型诊断 |
| 线上业务指标 | `ctr` / `cvr` / `gmv` | 当前离线召回实验没有线上曝光和转化闭环 | 后续线上实验单独记录 |
| LOPO 独立晋升 | 只凭 LOPO 结果判断方法可晋升 | 泛化诊断不能替代主评估 | 作为补充稳定性信号 |
| 非冻结池对比 | 输入池变化后直接比较召回指标 | 会把池变化误当方法收益 | 只用于另起一轮实验 |
| 只看覆盖率 | 只看 coverage / pool size / candidate count | 覆盖率上升不等于有效命中 | 需要结合候选池命中与边际命中证据 |
| 仅看 legacy 文本 | 把旧报告里的文字结论当成新证据 | 旧结论可能没有 artifact 支撑 | 只能作为迁移候选，不可直接晋升 |

## 3. Decision Rules

| 决策 | 判定规则 | 输出标签 |
| --- | --- | --- |
| 晋升 | `experiment_scope` 为 `fixed_contract_candidate_eval` 或 `production_scale_candidate_eval`，相对 `semantic_title_category_expansion` 有正向 `marginal_candidate_hit_users`，`pool_displacement_risk` 不是 `high` 或 `unknown`，且不使用 forbidden metrics | `promote` |
| 拒绝 | 固定合同下没有边际候选命中收益，或收益被池截断/替换风险抵消 | `reject` |
| 延后 | 方法需要 GPU、额外依赖、全量索引或更大实验合同，当前无法在轻量固定合同下验证 | `defer` |
| 兜底 | 方法单独有稳定候选供给价值，但相对 canonical baseline 没有边际命中收益 | `fallback` |
| 只记录 | 只有历史文字、外部调研或实现映射，没有当前可核验实验 artifact | `document_only` |

### 决策顺序

1. 先确认输入是否满足固定合同。
2. 再确认指标是否属于 forbidden metrics。
3. 再看是否有可回指 artifact。
4. 最后才写方法结论。

## 4. Baseline Semantics

| 基线名 | 语义 | 使用方式 | 不允许的误读 |
| --- | --- | --- | --- |
| `no_recall_baseline` | 不做额外召回增强，仅保留最基本链路 | 作为最底线参考 | 不能拿来和不同输入池混比 |
| `legacy_baseline` | 旧实验中已有的历史基线 | 只用于迁移旧结论 | 不能直接视为当前最优 |
| `frozen_pool_baseline` | 冻结候选池上的方法对照 | 作为方法比较主基线 | 不能混入扩池后的新候选 |
| `same_run_baseline` | 同一轮实验内的对照方法 | 适合方法间 A/B 比较 | 不能跨轮次直接推导长期结论 |
| `lopo_sanity_baseline` | 用于检查泛化稳定性 | 只做 sanity / drift 诊断 | 不能独立决定晋升 |

### 基线语义补充

- 基线的职责是定义“比较谁”，不是定义“谁更重要”。
- 同一个方法在不同基线上可以有不同结论，但只有满足固定合同的那一条结论才能进入正式迁移区。
- 若基线语义不清，先补充说明，不写结论。

## 5. Coverage Matrix

| 覆盖维度 | 已覆盖 | 当前作用 | 备注 |
| --- | --- | --- | --- |
| 冻结合同 | 是 | 保证可比性 | 作为所有方法卡默认前提 |
| forbidden metrics 过滤 | 是 | 避免误判晋升 | 作为 review checklist |
| 决策规则 | 是 | 统一 promotion / stop 口径 | 需要后续和 worker-verify 对齐 |
| baseline semantics | 是 | 统一基线命名与使用范围 | 防止跨轮次混读 |
| legacy conclusion migration | 部分 | 迁移旧结论，但按证据级别分层 | 仍需 worker-map 提供完整证据表 |
| method card template | 是 | 让每个方法都可复述、可比较 | 仅模板，不是结果 |
| Phase 5 deferred backlog | 是 | 记录暂不做事项 | 防止未来重复展开 |
| artifact index placeholders | 是 | 预留工件入口 | 仅占位，不宣称存在 |

## 6. Legacy Conclusion Migration

### 6.1 证据级别定义

| evidence_level | 含义 | 迁移方式 |
| --- | --- | --- |
| `same_contract_verified` | 在当前固定合同下有可回指的配置、脚本和结果 artifact | 可以进入正式方法卡结论 |
| `legacy_migrated_with_artifact` | 旧结论能回指到历史结果文件、配置或脚本，但合同可能不是当前固定合同 | 迁移为历史证据，并标注适用范围 |
| `legacy_migrated_without_artifact` | 旧结论只有文本叙述，没有足够 artifact | 只能作为历史备注，不进入晋升判断 |
| `needs_rerun` | 方法方向存在，但当前证据链缺失或实验合同不满足 | 记录为待重跑 |

### 6.2 迁移表

| 旧来源 | 旧结论摘要 | evidence_level | 新状态 | 迁移说明 |
| --- | --- | --- | --- | --- |
| `dic/OPTIMIZATION_NARRATIVE.md` | 旧优化记录中的阶段性判断 | `legacy_migrated_without_artifact` 或 `legacy_migrated_with_artifact`，按对应条目单独判定 | `document_only` / `defer` / `fallback` | 仅在能回指到具体 artifact 时提升证据级别 |
| `dic/ENGINEERING_NARRATIVE_LOG.md` | 工程叙事中的问题-方案-验证链 | 取决于条目是否附带结果文件 | `document_only` | 作为叙事来源，不自动升级为方法证据 |
| `dic/experiments/ranking/phase_1_25/PHASE_1_25_INDUSTRIAL_RANKING_RESEARCH.md` | 排序侧研究结论 | 不直接迁移到召回结论 | `document_only` | 仅可作为方法边界参考，不混入召回结论 |
| 其他历史草稿 | 仅有口头式结论 | `needs_rerun` | `defer` | 需要 worker-map / worker-verify 补证 |

### 6.3 迁移原则

- 只迁移“可复述且可核验”的句子。
- 如果旧结论没有 artifact 支撑，只保留“历史上曾这样认为”，不写成当前事实。
- 如果旧结论与当前证据冲突，以当前证据为准。

## 7. Method Card Template

> 下面是每个召回方法必须填写的卡片模板。当前文档只提供模板，不预填未验证结果。

| 字段 | 内容要求 |
| --- | --- |
| 方法名 | 明确到实现级别，例如算法名 + 配置变体 |
| 目标 | 这条方法想解决什么召回问题 |
| 输入合同 | 固定池、固定切分、固定参数范围 |
| 关键旋钮 | 能调的核心参数 |
| 适用范围 | 只适用于哪些场景或数据子集 |
| 主要风险 | 容易引入的误判、漂移或过拟合 |
| 诊断指标 | 只列辅助诊断指标，不把 forbidden metrics 放进晋升位 |
| artifact | 结果文件、配置文件、脚本、图表 |
| evidence_level | `same_contract_verified` / `legacy_migrated_with_artifact` / `legacy_migrated_without_artifact` / `needs_rerun` |
| decision | `promote` / `reject` / `defer` / `fallback` / `document_only` |

### Method Card 示例骨架

| 项 | 填写示例占位 |
| --- | --- |
| 方法名 | `method_name_here` |
| 目标 | `goal_here` |
| 输入合同 | `frozen_pool + fixed_split` |
| 关键旋钮 | `param_a / param_b` |
| 适用范围 | `scope_here` |
| 主要风险 | `risk_here` |
| 诊断指标 | `diag_metric_a / diag_metric_b` |
| artifact | `outputs/...` |
| evidence_level | `needs_rerun` |
| decision | `defer` |

## 8. Phase 5 Deferred Backlog

> 这一栏只记“现在不做、以后再说”的内容，避免把范围越滚越大。

| Deferred item | 原因 | 复启条件 |
| --- | --- | --- |
| 全量召回方法大扫一轮 | 当前优先冻结合同和方法卡，不先扩大战场 | 等基础证据链稳定后再开新轮 |
| 额外的复杂融合策略 | 目前还没有足够的对照证据 | 先补齐方法卡与 baseline 语义 |
| 仅凭文本复盘补结论 | 风险是把历史记忆当成证据 | 必须先补 artifact |
| 非冻结池下的横向比较 | 会破坏可比性 | 只有另起一轮实验才允许 |
| 把所有历史草稿统一重写 | 成本高且容易混入未验证内容 | 先迁移高证据级别条目 |

## 9. Artifact Index Placeholders

> 这里先占位，等 worker-map / worker-verify 补全后再替换为真实工件索引。

| Artifact ID | 路径 / 位置 | 当前状态 | 备注 |
| --- | --- | --- | --- |
| `artifact-01` | `outputs/<todo>/comparison.json` | `placeholder` | 待补真实路径 |
| `artifact-02` | `outputs/<todo>/comparison.md` | `placeholder` | 待补真实路径 |
| `artifact-03` | `outputs/<todo>/metrics.json` | `placeholder` | 待补真实路径 |
| `artifact-04` | `configs/<todo>.yaml` | `placeholder` | 待补真实配置 |
| `artifact-05` | `scripts/<todo>.py` | `placeholder` | 待补真实脚本 |
| `artifact-06` | `dic/<todo>.md` | `placeholder` | 待补真实文档 |

## 10. 当前结论边界

- 这份日志的作用是统一召回方法的记录口径，而不是宣布某个方法已经赢了。
- 在没有补齐 artifact 之前，所有方法结论默认保持 `defer` 或 `document_only`，不得写成 `promote`。
- 以后新增方法卡时，先填模板，再填证据，再写结论。

## 11. CPU-bound CF / Hybrid Sweep（2026-05-13）

### 11.1 固定合同运行

| 项 | 结果 |
| --- | --- |
| 运行命令 | `.venv/Scripts/python.exe scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py --config configs/recall/phase_1_21/phase_1_21_recall_coverage_pool200_experimental.yaml --output-dir outputs/recall/phase_1_21_recall_coverage/source_family/worker_cpu_itemcf_covisit_hybrid_pool200 --mode baseline --limit-users 500` |
| scope | `fixed_contract_candidate_eval` / `recall_only` |
| split | `valid_test` |
| users_total / users_with_holdout | `500 / 138` |
| candidate_pool_size | `200` |
| holdout_user_ids_hash | `927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2` |
| artifact 根目录 | `outputs/recall/phase_1_21_recall_coverage/source_family/worker_cpu_itemcf_covisit_hybrid_pool200/` |
| 关键 artifact | `metrics.json`、`manifest.json`、`source_coverage.csv`、`source_family_observation_benchmarks.json`、`frozen_candidates.jsonl` |

本次运行是 CPU 侧可执行的 ItemCF/co-visit + hybrid source blending 固定合同候选池评估；`manifest.json` 中 `ranking_rerank_disabled_checks` 显示 `ltr_model.enabled=false`、`ranking_v2.enabled=false`、`item_feature_rerank.enabled=false`、`source_aware_fusion.enabled=false`，因此只作为召回候选池证据，不使用排序或业务指标晋升。

### 11.2 指标摘要

| 指标 | 值 |
| --- | --- |
| `candidate_hit_users` | `19` |
| `candidate_hit_rate_at_pool` | `0.137681` |
| `recall_at_pool` | `0.06971` |
| `candidate_count_avg` | `157.112` |
| `empty_candidate_rate` | `0.0` |
| `itemcf_weak` user / item / hit users | `210 / 2538 / 1` |
| `itemcf_strong` user / item / hit users | `202 / 2255 / 1` |
| `co_visit_fallback_repair` user / item / hit users | `224 / 2441 / 1` |

`source_family_observation_benchmarks.json` 中 `itemcf_covisit_observation` 标记为 `EXECUTED_PASS`；按 v3 方法卡口径，本轮可映射为 `same_contract_verified` 证据，但 `exclusive_hit_users=0`，且当前没有 dedicated ablation 证明它相对 canonical baseline 有边际召回收益，因此不得晋升。

### 11.3 方法卡结论

| 方法 | 当前状态 | evidence_level | decision | 证据/原因 |
| --- | --- | --- | --- | --- |
| ItemCF/co-visit（`itemcf_weak`、`itemcf_strong`、`co_visit_fallback_repair`） | `EXECUTED_PASS` | `same_contract_verified` | `fallback` | 固定合同下有完整候选池 artifact，能提供候选覆盖，但本轮 `exclusive_hit_users=0`，不满足晋升条件 |
| UserCF | `not_implemented_current_entrypoint` | `document_only` | `defer` | 代码检索未发现成熟 `UserCF`/`usercf` 召回入口；旧日志也记录 Swing/UserCF 没有成熟入口，不能伪造结果 |
| ALS / BPR / implicit MF | `missing_implementation_or_dependency` | `document_only` | `defer` | 代码和依赖检索未发现 ALS/BPR/implicit MF 召回入口；`requirements-training.txt` 仅声明 `torch`，未声明 `implicit`、LightFM、Surprise、Cornac 等可直接复用的 CPU MF 库 |
| hybrid/source blending | `EXECUTED_PASS` | `same_contract_verified` | `document_only` | 本次 pool200 experimental baseline 同时启用 co-visit、category long-tail、semantic title/category 等 source blending，但这是组合候选池评估，不是单独融合策略晋升证据 |

### 11.4 下一步

- 若要把 ItemCF/co-visit 从 `fallback` 提升为可晋升候选，需要补 dedicated ablation、pool displacement risk 和 verifier approval。
- 若要覆盖 UserCF/ALS/BPR/implicit MF，需要先新增可复用召回入口、依赖声明、训练/索引 artifact 和 no-leakage contract，再进入 fixed-contract candidate eval。

## 12. Lightweight Source Sweep（2026-05-13）

### 12.1 固定合同运行

| 项 | popular/category baseline | ItemCF/co-visit pool200 observation |
| --- | --- | --- |
| 运行命令 | `.venv/Scripts/python.exe scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py --config configs/recall/phase_1_21/phase_1_21_recall_coverage_baseline.yaml --output-dir outputs/recall/phase_1_21_recall_coverage/worker_light_20260513/baseline_popular_category --mode baseline --limit-users 500` | `.venv/Scripts/python.exe scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py --config configs/recall/phase_1_21/phase_1_21_recall_coverage_pool200_experimental.yaml --output-dir outputs/recall/phase_1_21_recall_coverage/worker_light_20260513/itemcf_covisit_pool200 --mode baseline --limit-users 500` |
| scope | `fixed_contract_candidate_eval` / `recall_only` | `fixed_contract_candidate_eval` / `recall_only` |
| split | `valid_test` | `valid_test` |
| users_total / users_with_holdout | `500 / 138` | `500 / 138` |
| candidate_pool_size | `100` | `200` |
| holdout_user_ids_hash | `927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2` | `927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2` |
| artifact 根目录 | `outputs/recall/phase_1_21_recall_coverage/worker_light_20260513/baseline_popular_category/` | `outputs/recall/phase_1_21_recall_coverage/worker_light_20260513/itemcf_covisit_pool200/` |
| 关键 artifact | `metrics.json`、`manifest.json`、`source_coverage.csv`、`source_family_observation_benchmarks.json`、`frozen_candidate_artifact.json` | `metrics.json`、`manifest.json`、`source_coverage.csv`、`source_family_observation_benchmarks.json`、`frozen_candidate_artifact.json` |

两次运行都使用项目 `.venv`，并由 `manifest.json` 记录 `ranking_rerank_disabled_checks`：`ltr_model.enabled=false`、`ranking_v2.enabled=false`、`item_feature_rerank.enabled=false`、`source_aware_fusion.enabled=false`。本节只记录召回候选池证据，不使用 `hit_rate_at_k`、`ndcg`、`mrr`、`map` 等 forbidden ranking metrics 做晋升判断。

### 12.2 recall-only 指标摘要

| 指标 | popular/category baseline | ItemCF/co-visit pool200 observation |
| --- | --- | --- |
| `candidate_hit_users` | `14` | `19` |
| `candidate_hit_rate_at_pool` | `0.101449` | `0.137681` |
| `recall_at_pool` | `0.060709` | `0.06971` |
| `candidate_count_avg` | `97.82` | `157.112` |
| `empty_candidate_rate` | `0.0` | `0.0` |
| `source_candidate_count_before_cap` | `48910` | `78556` |
| `source_candidate_count_after_cap` | `48910` | `78556` |
| `pool_displacement_risk` | `unknown` | `unknown` |
| `method_card_decision_status` | `needs_rerun` | `needs_rerun` |

### 12.3 方法卡结论

| 方法 | 当前状态 | evidence_level | decision | 证据/原因 |
| --- | --- | --- | --- | --- |
| popularity / popular fallback（`popular`） | `EXECUTED_PASS` | `same_contract_verified` | `document_only` | `source_family_observation_benchmarks.json` 中 `popular_category_observation` 为 `EXECUTED_PASS`；`popular` 覆盖 `493` users、`50` items、`3` hit users、`1` exclusive hit user，但 promotion manifest 仍缺 ablation/overlap/latency/fallback required artifacts，不能晋升 |
| category lightweight baseline（`category`） | `EXECUTED_PASS` | `same_contract_verified` | `document_only` | 与 popular 同合同运行；`category` 覆盖 `423` users、`267` items、`2` hit users、`0` exclusive hit users，仅作为基础补足源记录 |
| ItemCF standard forms（`itemcf_weak`、`itemcf_strong`） | `EXECUTED_PASS` | `same_contract_verified` | `fallback` | baseline 中 `itemcf_weak`/`itemcf_strong` 分别覆盖 `210/202` users、`2537/2254` items、各 `1` hit user；pool200 observation 中继续保留，适合作为候选覆盖 fallback，不单独晋升 |
| co-visit fallback repair（`co_visit_fallback_repair`） | `EXECUTED_PASS` | `same_contract_verified` | `fallback` | pool200 固定合同评估中 `itemcf_covisit_observation` 为 `EXECUTED_PASS`，`co_visit_fallback_repair` 覆盖 `224` users、`2441` items、`1` hit user；与 ItemCF overlap 较高，当前缺 dedicated ablation 和 pool displacement risk 证明 |
| hot / trending | `not_implemented_current_entrypoint` | `document_only` | `defer` | 代码检索未发现独立 `hot` / `trending` 召回入口；当前只能用 `popular` 作为可执行 popularity 类 baseline，不能伪造热度趋势结果 |
| Swing | `not_implemented_current_entrypoint` | `document_only` | `defer` | 代码检索未发现成熟 `swing` / `Swing` 召回实现；不在本轮临时新增算法，避免破坏固定合同 |
| session / recency transition | `template_only_or_non_source_weight` | `document_only` | `defer` | `sequence_multi_interest_observation` 在脚本中为 `TEMPLATE_ONLY`，现有 `recency_decay` 只作为 co-visit/two-tower/graph seed 权重旋钮，不是独立 session transition recall source |

### 12.4 下一步

- 若要晋升 popularity 或 co-visit，需要补 dedicated ablation、source overlap、latency、fallback stability、pool displacement risk，并由 verifier 复核。
- 若要覆盖 hot/trending、Swing、session transition，需要先新增稳定 source tag、训练/索引 artifact、no-leakage contract 和固定配置，再进入同一 evaluation contract。

## 13. Previously Deferred Behavior / MF Recall Sweep（2026-05-13）

### 13.1 固定合同运行

| 项 | 结果 |
| --- | --- |
| 运行命令 | `.venv/Scripts/python.exe scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py --config configs/recall/phase_1_21/phase_1_21_recall_coverage_behavior_untried.yaml --output-dir outputs/recall/phase_1_21_recall_coverage/source_family/worker_behavior_untried_pool200 --mode baseline --limit-users 500` |
| scope | `fixed_contract_candidate_eval` / `recall_only` |
| split | `valid_test` |
| users_total / users_with_holdout | `500 / 138` |
| candidate_pool_size | `200` |
| holdout_user_ids_hash | `927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2` |
| artifact 根目录 | `outputs/recall/phase_1_21_recall_coverage/source_family/worker_behavior_untried_pool200/` |
| 配置 | `configs/recall/phase_1_21/phase_1_21_recall_coverage_behavior_untried.yaml` |
| 关键 artifact | `metrics.json`、`manifest.json`、`source_coverage.csv`、`source_family_observation_benchmarks.json`、`frozen_candidates.jsonl` |

本轮把上一节标为未跑的轻量行为方法补成训练期 source：`usercf_recall`、`swing_recall`、`session_transition_recall`，并补了无新增依赖的 `implicit_svd_recall` 作为矩阵分解类轻量近似。所有索引都只由 `user_sequences.train.jsonl` 构建，不读取 `valid/test` holdout 或 `miss_targets.csv`。

### 13.2 recall-only 指标摘要

| 指标 | 值 |
| --- | --- |
| `candidate_hit_users` | `17` |
| `candidate_hit_rate_at_pool` | `0.123188` |
| `recall_at_pool` | `0.064151` |
| `candidate_count_avg` | `132.066` |
| `empty_candidate_rate` | `0.0` |
| `pool_displacement_risk` | `unknown` |
| `method_card.can_promote` | `false` |
| `method_card.decision_hint` | `defer` |

对比同合同下此前 CPU-bound ItemCF/co-visit hybrid pool200 的 `candidate_hit_users=19`、`candidate_hit_rate_at_pool=0.137681`、`recall_at_pool=0.06971`，本轮补跑方法没有产生可晋升的整体提升。

### 13.3 source 级覆盖

| source | user_coverage | item_coverage | candidate_hit_source_coverage |
| --- | ---: | ---: | ---: |
| `usercf_recall` | `210` | `2867` | `1` |
| `swing_recall` | `209` | `2112` | `1` |
| `session_transition_recall` | `244` | `699` | `0` |
| `implicit_svd_recall` | `499` | `685` | `0` |

`source_family_observation_benchmarks.json` 中 `usercf_observation`、`swing_observation`、`sequence_transition_observation`、`implicit_svd_observation` 均为 `EXECUTED_PASS` / `same_contract_verified`，说明这些方法已经补跑并进入固定合同 artifact。

### 13.4 方法卡结论

| 方法 | 当前状态 | evidence_level | decision | 证据/原因 |
| --- | --- | --- | --- | --- |
| UserCF（`usercf_recall`） | `EXECUTED_PASS` | `same_contract_verified` | `fallback` | 有训练期用户相似度索引与固定合同 artifact，覆盖 `210` users / `2867` items，但仅 `1` 个 candidate-hit source 覆盖，不满足晋升条件 |
| Swing（`swing_recall`） | `EXECUTED_PASS` | `same_contract_verified` | `fallback` | 有训练期 item-pair swing 近似索引，覆盖 `209` users / `2112` items，但命中贡献很小，且与 ItemCF overlap 明显，只适合候选补充 |
| session transition（`session_transition_recall`） | `EXECUTED_PASS` | `same_contract_verified` | `reject` | 有相邻行为转移索引，覆盖 `244` users / `699` items，但本轮没有 candidate-hit source 覆盖 |
| implicit SVD MF（`implicit_svd_recall`） | `EXECUTED_PASS` | `same_contract_verified` | `reject` | 纯 numpy SVD 近似覆盖 `499` users / `685` items，但本轮没有 candidate-hit source 覆盖；可作为 MF smoke，不作为晋升候选 |
| ALS / BPR / LightFM 类 MF | `blocked_missing_dependency` | `needs_rerun` | `defer` | `.venv` 依赖检查显示 `scipy=False`、`sklearn=False`、`implicit=False`、`lightfm=False`，当前不能可靠跑 ALS/BPR 训练；如要补正式 MF，需要先声明依赖和训练 artifact 合同 |

### 13.5 下一步

- UserCF/Swing 已经从“没跑”变成固定合同 `EXECUTED_PASS`，但当前只能归为 `fallback`。
- session transition 和 implicit SVD 已经补跑，当前结论为 `reject`，不建议继续投入调参，除非换更大合同或更长序列数据。
- ALS/BPR 不再写成“未检查”，而是明确 blocked 在依赖和训练链路上。

## 14. Source-aware Fusion / Truncation Observation（2026-05-13）

### 14.1 固定合同运行

| 项 | 结果 |
| --- | --- |
| baseline 命令 | `.venv/Scripts/python.exe scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py --config configs/recall/phase_1_21/phase_1_21_recall_coverage_source_aware.yaml --output-dir outputs/recall/phase_1_21_recall_coverage/source_aware/baseline --mode baseline --limit-users 500` |
| comparison 命令 | `.venv/Scripts/python.exe scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py --config configs/recall/phase_1_21/phase_1_21_recall_coverage_source_aware.yaml --output-dir outputs/recall/phase_1_21_recall_coverage/source_aware/comparison --mode source-aware --limit-users 500 --holdout-user-ids outputs/recall/phase_1_21_recall_coverage/source_aware/baseline/holdout_user_ids.json` |
| scope | `recall_only_observation` |
| split | `valid_test` |
| users_total / users_with_holdout | `500 / 138` |
| candidate_pool_size | `200` |
| holdout_user_ids_hash | `927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2` |
| artifact 根目录 | `outputs/recall/phase_1_21_recall_coverage/source_aware/` |
| 当前主路复验输出 | `outputs/recall/phase_1_21_recall_coverage/current_main_route_pool200_source_balanced/` |
| 当前主路配置 | `configs/recall/phase_1_21/phase_1_21_recall_coverage_pool200_experimental.yaml` |
| 对照配置 | `configs/recall/phase_1_21/phase_1_21_recall_coverage_source_aware.yaml` |

本轮不是新增召回算法，而是观察 `semantic_title_category_expansion + co_visit_fallback_repair + UserCF + Swing` 在不同候选截断策略下的稳定性。对照组 `score_sorted_all_sources` 使用默认分数排序截断；实验组 `source_balanced_fallback_preserving` 使用 `balanced_source_budget`，为 semantic / co-visit / UserCF / Swing 设置最小保留，并限制 `popular` 上限。

### 14.2 指标摘要

| 指标 | score-sorted all sources | source-balanced fallback preserving |
| --- | ---: | ---: |
| `candidate_hit_users` | `19` | `19` |
| `candidate_hit_rate_at_pool` | `0.137681` | `0.137681` |
| `recall_at_pool` | `0.068502` | `0.069227` |
| `candidate_count_avg` | `136.214` | `126.972` |
| `candidate_count_p50` | `132.5` | `122.5` |
| `candidate_count_p90` | `193.0` | `184.0` |
| `candidate_hit_rate_at_100` | `0.123188` | `0.130435` |
| `candidate_recall_at_100` | `0.05884` | `0.066811` |
| `baseline_displacement_users` | `0` | `0` |
| `empty_candidate_rate` | `0.0` | `0.0` |

### 14.3 结论

| 策略 | 当前状态 | evidence_level | decision | 证据/原因 |
| --- | --- | --- | --- | --- |
| 默认 score-sorted 截断 | `EXECUTED_PASS` | `same_contract_verified` | `superseded_baseline` | 固定合同下保持 `19` 个 candidate-hit users，但 pool@100、平均命中位置、p90 命中位置和候选量均弱于 source-balanced |
| source-balanced fallback-preserving 截断 | `EXECUTED_PASS` | `same_contract_verified` | `current_main_route` | 不新增 hit users，但在不产生 displacement 的前提下把 `candidate_count_avg` 从 `136.214` 降到 `126.972`，把 `candidate_hit_rate_at_100` 从 `0.123188` 提到 `0.130435`，并把 `candidate_hit_rank_avg/p90` 从 `34.526316/73.0` 改善到 `31.315789/64.0`，因此固定为当前混合召回默认截断策略 |

### 14.4 下一步

- 当前固定主路采用 `semantic_title_category_expansion` / semantic 作为主增量，`itemcf_weak`、`itemcf_strong`、`co_visit_fallback_repair`、UserCF、Swing 作为行为补充，`popular` / `category` 作为兜底，保留 existing two-tower artifact 旁路。
- 截断策略固定为 `source_balanced_fallback_preserving`：它不牺牲 `candidate_hit_users=19`，同时让命中目标更靠前、候选池更小。
- graph、vector/two-tower 新 observation、MF、sequence/multi-interest 等后续实验均未超过该混合主路；除非更大样本或新 artifact 重新证明，否则不进入当前主路。

## 15. Remaining Recall Families Fixed-contract Sweep（2026-05-13）

### 15.1 固定合同运行

| 方法族 | 配置 | 输出目录 |
| --- | --- | --- |
| graph | `configs/recall/phase_1_21/phase_1_21_recall_coverage_graph.yaml` | `outputs/recall/phase_1_21_recall_coverage/source_family/graph_observation_pool200/` |
| vector / two-tower | `configs/recall/phase_1_21/phase_1_21_recall_coverage_vector.yaml` | `outputs/recall/phase_1_21_recall_coverage/source_family/vector_two_tower_observation_pool200/` |
| MF | `configs/recall/phase_1_21/phase_1_21_recall_coverage_mf.yaml` | `outputs/recall/phase_1_21_recall_coverage/source_family/mf_observation_pool200/` |
| sequence / multi-interest | `configs/recall/phase_1_21/phase_1_21_recall_coverage_sequence.yaml` | `outputs/recall/phase_1_21_recall_coverage/source_family/sequence_multi_interest_observation_pool200/` |

共同合同：`valid_test`、`limit_users=500`、`users_with_holdout=138`、`candidate_pool_size=200`、`holdout_user_ids_hash=927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2`。所有运行都使用 `.venv/Scripts/python.exe` 串行执行，且 `ranking_rerank_disabled_checks` 保持关闭排序 / rerank 路由。

### 15.2 recall-only 指标摘要

| 方法族 | `candidate_hit_users` | `candidate_hit_rate_at_pool` | `recall_at_pool` | `candidate_count_avg` | `candidate_count_p50` | `candidate_count_p90` | `empty_candidate_rate` | `fallback_rate` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| graph | `17` | `0.123188` | `0.064151` | `128.808` | `126.0` | `168.0` | `0.0` | `0.0` |
| vector / two-tower | `17` | `0.123188` | `0.064151` | `126.88` | `126.0` | `160.0` | `0.0` | `0.0` |
| implicit SVD MF | `17` | `0.123188` | `0.064151` | `154.782` | `155.0` | `186.0` | `0.0` | `0.0` |
| sequence / multi-interest | `17` | `0.123188` | `0.064151` | `128.142` | `126.0` | `164.0` | `0.0` | `0.0` |

对比当前 source-aware / semantic 主路的 `candidate_hit_users=19`、`candidate_hit_rate_at_pool=0.137681`，本轮 graph、vector/two-tower、implicit SVD MF、sequence/multi-interest 都没有产生可晋升的召回收益。

### 15.3 方法卡结论

| 方法 | 当前状态 | evidence_level | decision | 证据/原因 |
| --- | --- | --- | --- | --- |
| graph（`item_graph`，`graph_walk_seed` disabled） | `EXECUTED_PASS` | `same_contract_verified` | `reject` | 固定合同下 `candidate_hit_users=17`，低于当前主路；`item_graph` 仅贡献 `1` 个 candidate-hit source 覆盖，`graph_walk_seed` 因缺 validated sidecar 保持关闭 |
| vector / two-tower | `EXECUTED_PASS` | `same_contract_verified` | `reject` | 使用现有本地 two-tower/YouTubeDNN artifact 路径，`candidate_hit_users=17`，未超过主路；ANN 服务或外部向量索引未接入，因此 ANN 仍为后续工程项 |
| implicit SVD MF | `EXECUTED_PASS` | `same_contract_verified` | `reject` | 纯 numpy SVD smoke 可运行，但固定合同下整体仍为 `17` hit users，没有边际晋升证据 |
| ALS MF | `blocked_missing_dependency` | `dependency_gate` | `defer` | 缺 `implicit` 依赖，`source_family_observation_benchmarks.json` 标记 `missing_dependency:implicit` |
| BPR MF | `blocked_missing_dependency` | `dependency_gate` | `defer` | 缺 `implicit` 依赖，不能伪造成已执行 BPR 结果 |
| LightFM MF | `blocked_missing_dependency` | `dependency_gate` | `defer` | 缺 `lightfm` 依赖，需先补依赖、训练脚本和 artifact 合同 |
| sequence / multi-interest | `EXECUTED_PASS` | `same_contract_verified` | `reject` | 基于训练期相邻行为构造多兴趣近似，`candidate_hit_users=17`，未覆盖当前主路 miss；短序列数据下不建议继续调参 |

### 15.4 当前主路结论

- 当前没有新的召回方法值得晋升；主路继续保持 `semantic_title_category_expansion` / source-aware score-sorted 口径。
- 行为侧 `co_visit_fallback_repair`、UserCF、Swing 只作为 fallback / candidate supplement。
- graph、vector/two-tower、implicit SVD、sequence/multi-interest 在该轮轻量固定合同下全部 `reject`；ALS/BPR/LightFM 当时因依赖和训练链路不足继续 `defer`，后续依赖解锁结果见第 16 节。

## 16. Dependency-unlocked ALS/BPR MF Sweep（2026-05-14）

### 16.1 依赖与实现状态

用户要求补齐依赖后继续实验。本轮在项目 `.venv` 中安装并验证 `implicit==0.7.3` 可用；LightFM 1.17 的 PyPI sdist 在当前 Windows / Python 3.13 环境下先卡在 metadata/build 阶段，随后通过 patched source、重新 Cythonize 和无 OpenMP 单线程 wheel 安装修复。真实矩阵测试显示 LightFM 的 WARP/BPR/WARP-KOS ranking loss 在当前 native 扩展上会 access violation，logistic loss 可稳定训练，因此本轮只把 LightFM 作为可执行 logistic MF observation，不把 WARP/BPR 结果伪造成已跑。

代码侧把 ALS/BPR/LightFM 从纯 registry dependency gate 改成真实 train-only source：`als_mf_recall`、`bpr_mf_recall`、`lightfm_recall` 只从 `user_sequences.train.jsonl` 构建 user-item CSR matrix，并分别通过 `implicit` ALS/BPR 与 LightFM logistic 模型生成候选，不读取 holdout 或 `miss_targets.csv`。

### 16.2 固定合同运行

| 项目 | 内容 |
| --- | --- |
| 配置 | `configs/recall/phase_1_21/phase_1_21_recall_coverage_mf.yaml` |
| 输出目录 | `outputs/recall/phase_1_21_recall_coverage/source_family/mf_implicit_als_bpr_lightfm_pool200/` |
| 合同 | `valid_test`、`limit_users=500`、`users_with_holdout=138`、`candidate_pool_size=200` |
| holdout hash | `927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2` |

### 16.3 recall-only 指标摘要

| 指标 | 结果 |
| --- | ---: |
| `candidate_hit_users` | `17` |
| `candidate_hit_rate_at_pool` | `0.123188` |
| `recall_at_pool` | `0.064151` |
| `candidate_count_avg` | `192.548` |
| `candidate_count_p50` | `200.0` |
| `candidate_count_p90` | `200.0` |
| `empty_candidate_rate` | `0.0` |
| `fallback_rate` | `0.0` |

Source 级诊断：`als_mf_recall` 覆盖 `500` users / `1207` items，但没有 candidate-hit source 覆盖；`bpr_mf_recall` 覆盖 `500` users / `39` items，只贡献 `1` 个 candidate-hit source 覆盖；`lightfm_recall` 覆盖 `454` users / `34` items，贡献 `4` 个 candidate-hit source 覆盖，但主要与 `popular` 高重叠（pair jaccard `0.647059`）。整体仍为 `17` hit users，低于当前 source-aware / semantic 主路的 `19` hit users。

### 16.4 方法卡结论

| 方法 | 当前状态 | evidence_level | decision | 证据/原因 |
| --- | --- | --- | --- | --- |
| ALS MF（`als_mf_recall`） | `EXECUTED_PASS` | `same_contract_verified` | `reject` | 依赖解锁后已真实训练和产候选，但固定合同下无边际 candidate-hit source 覆盖，且整体 hit users 仍为 `17` |
| BPR MF（`bpr_mf_recall`） | `EXECUTED_PASS` | `same_contract_verified` | `reject` | 真实执行后只贡献 `1` 个 candidate-hit source 覆盖，未提升整体候选池命中，不满足晋升条件 |
| LightFM MF（`lightfm_recall`） | `EXECUTED_PASS` | `same_contract_verified` | `reject` | 安装修复后 logistic loss 可真实训练并产候选，但 WARP/BPR native loss 在当前 Windows/Python 3.13 上 access violation；logistic 固定合同只贡献 `4` 个 candidate-hit source 覆盖，整体 hit users 仍为 `17`，不满足晋升条件 |

### 16.5 当前结论

依赖解锁后的 ALS/BPR/LightFM 已经从“没跑/blocked”变成固定合同 `EXECUTED_PASS`，但结果不支持晋升；当前召回主路仍保持 `semantic_title_category_expansion` / source-aware score-sorted 口径。MF 方向后续如果继续推进，应优先换更强的离线训练样本、负采样/特征设计、兼容的 Linux/Python 编译环境或可复现 artifact 合同，而不是在当前轻量合同上继续调 ALS/BPR/LightFM 超参。

## 17. Representative full-lightweight E2E 与方法预检（2026-05-16）

### 17.1 固定合同运行

| 项 | 结果 |
| --- | --- |
| 运行结果 | 代表性 full-lightweight E2E 成功 |
| 输出目录 | `outputs/recall/full_main_route_other_methods/lightweight_representative_e2e` |
| 用户数 | `500` |
| candidate rows | `75,866` |
| empty users | `0` |
| enabled sources | `popular`、`category`、`semantic` |
| disabled sources | `ItemCF`、`graph`、`two_tower`、`UserCF`、`Swing`、`MF`、`sequence`、`pool500`、`pool1000` |
| heavy outputs | 未生成 `itemcf` / `graph` / `pool` 输出文件 |
| 10k source path | 未进入本轮代表性路径 |

本轮只把 Popular / Category / Semantic 的轻量候选生成跑通并完成清单审计；其余方法族在 manifest 中保持 disabled 或仅保留为后续检查项，没有被伪装成已执行结果。

### 17.2 方法预检结论

| 方法 / 家族 | 当前状态 | evidence_level | decision | 证据 / 说明 |
| --- | --- | --- | --- | --- |
| ItemCF / co-visit sidecar | `not_enabled_in_representative_e2e` | `document_only` | `defer` | 本轮代表性 E2E 未启用 ItemCF / co-visit sidecar，且输出目录中没有对应产物；仅保留为后续受控回跑项 |
| UserCF | `default_off_fallback_observation` | `document_only` | `defer` | 已在清单中显式关闭，当前只作为 fallback 观察位，不进入本轮代表性 E2E 的 promoted 路径 |
| Swing | `default_off_fallback_observation` | `document_only` | `defer` | 已在清单中显式关闭，和 UserCF 一样只保留为 fallback 观察位 |
| graph_walk | `checklist_only_deferred` | `document_only` | `defer` | 已作为后续检查项保留，但本轮没有进入代表性轻量 E2E |
| two_tower | `checklist_only_deferred` | `document_only` | `defer` | 清单中为 disabled，且没有对应输出文件 |
| MF | `checklist_only_deferred` | `document_only` | `defer` | 清单中为 disabled，当前代表性路径不把 MF 当作已跑方法 |
| sequence | `checklist_only_deferred` | `document_only` | `defer` | 清单中为 disabled，未进入本轮代表性 E2E |

### 17.3 当前结论

- 这轮代表性 E2E 只确认了 Popular / Category / Semantic 的轻量候选生成链路可用。
- ItemCF/co-visit、UserCF、Swing、graph_walk、two_tower、MF、sequence 都保持 conservative 的 `defer` / `document_only` 口径，不写成 `promote`。
- 后续如果要推进其他方法族，必须先补对应 sidecar、依赖、索引或验证合同，再重新进入固定合同评估。

## 18. Bounded ItemCF / co-visit sidecar dry-run 预检（2026-05-16）

### 18.1 预检合同

| 项 | 结果 |
| --- | --- |
| 输出目录 | `outputs/recall/full_main_route_other_methods/bounded_itemcf_covisit_dry_run_estimate` |
| 输入 | `data/processed/amazon_2023_recall_clean_full/user_sequences.train.jsonl` |
| train_only | `true` |
| limit_users | `1000` |
| sampled_users / users_scanned | `1000 / 1000` |
| estimated_pair_rows | `10528` |
| bounded_pair_updates | `5264` |
| pairs_dropped_by_cap | `0` |
| planned_shard_count | `32` |
| disk_free_bytes | `225294610432` |
| source rows | `18103384` |
| source sha256 | `d47c9a3476f35f0c8bd88947b58f8a3f0ef83383f587d8d0e3102b6dbf1baf07` |

### 18.2 安全边界

本轮只执行 dry-run estimate，不构建邻居 sidecar，不写 shard 文件，不生成 pool500/pool1000，也不读取 valid/test/holdout。输出目录只包含 `manifest.json`，manifest 中 `disabled_outputs.neighbor_sidecar_build=true`、`disabled_outputs.shard_files=true`、`safety_flags.forbidden_10k_paths_rejected=true`、`safety_flags.disk_free_enforced=true`。

### 18.3 当前结论

- ItemCF / co-visit 仍保持 `defer`，本轮证据只证明 full clean 上的 bounded dry-run 预检可执行、可审计。
- 如果后续要进入真实 sidecar build，需要单独审批 pair/shard 预算、hot item 处理策略和 representative merge/eval 合同，不能把本轮 dry-run 写成召回效果提升。

## 19. Bounded ItemCF / co-visit representative sidecar 构建（2026-05-16）

### 19.1 构建合同

| 项 | 结果 |
| --- | --- |
| 输出目录 | `outputs/recall/full_main_route_other_methods/bounded_itemcf_covisit_sidecar_representative` |
| 输入 | `data/processed/amazon_2023_recall_clean_full/user_sequences.train.jsonl` |
| train_only | `true` |
| limit_users | `1000` |
| users_scanned / processed_users | `1000 / 363` |
| pair_updates | `5264` |
| pairs_dropped_by_cap | `0` |
| shard_count | `32` |
| output file_count | `34` |
| disk_free_bytes | `225296961536` |
| source rows | `18103384` |
| source sha256 | `d47c9a3476f35f0c8bd88947b58f8a3f0ef83383f587d8d0e3102b6dbf1baf07` |

### 19.2 产物与安全边界

本轮已从 dry-run 推进到 representative sidecar 真实产物，但仍限定在 `<=1000` users，不做全量 sidecar、不做 pool500/pool1000、不生成 recall views。输出目录只包含 `manifest.json`、`source_audit.json` 和 `32` 个 `neighbors_shard_*.jsonl`；source audit 的 `read_files` 只包含 full clean 的 `user_sequences.train.jsonl`，未读取 valid/test/holdout，也没有 10k source path。

### 19.3 当前结论

- ItemCF / co-visit sidecar 当前状态从 `dry_run_only` 推进到 `representative_sidecar_built`，但 evidence 仍是工程产物与安全边界验证，不是召回效果提升验证。
- 后续如要接入 candidate merge/eval，需要单独做 representative merge、dedup 后贡献、overlap、empty users、candidate inflation 和 pool displacement risk 审计，再决定是否从 `defer` 进入 fallback 或 promoted 候选。

## 20. Phase 0 召回方法合同预检与安全阻断（2026-05-16）

### 20.1 预检合同

| 项 | 结果 |
| --- | --- |
| 脚本 | `scripts/experiments/recall/run_phase0_contract_precheck.py` |
| 输出目录 | `outputs/recall/full_main_route_other_methods/phase0_contract_precheck/` |
| 必要产物 | `manifest.json`、`source_audit.json`、`resolved_inputs.json` |
| 真实状态 | `INVALID_SCOPE_DRIFT` |
| 阻断原因 | graph、two_tower、ranking pool200 具体 config 内容仍引用 `amazon_2023_recall_clean_10000` / `amazon_2023_recall_views_10000` |
| allowed train inputs | full clean `user_sequences.train.jsonl`、`canonical_interactions.train.jsonl`、`canonical_items.jsonl`、full lightweight views、bounded ItemCF sidecar manifest |
| forbidden candidate inputs | valid/test/holdout 文件只允许出现在 forbidden/evaluation-only 合同字段，不得出现在 `read_files` |

### 20.2 验证证据

- `.venv/Scripts/python.exe -m pytest tests/test_phase0_contract_precheck.py`：`5 passed`。
- `.venv/Scripts/python.exe -m ruff check scripts/experiments/recall/run_phase0_contract_precheck.py tests/test_phase0_contract_precheck.py`：`All checks passed`。
- 独立 verifier 结论：`APPROVE`，确认 Phase 0 三份产物、scope drift 阻断、no holdout candidate read、`.venv` 测试证据满足 US-001。

### 20.3 当前结论

Phase 0 的目标是合同预检，不是运行召回方法。当前正确结论是：full clean / full lightweight / bounded ItemCF sidecar 输入可解析，但 graph、two_tower 与 ranking pool200 相关配置仍带历史 10k 路径，因此后续 Phase 1+ 不应继续执行，必须先补 full-clean-safe config 或调整 resolver 输入，再重新通过 Phase 0。

## 21. Full-safe 召回方法全家桶 Phase 0-6 收口（2026-05-16）

### 21.1 执行合同

| 阶段 | 输出目录 | 状态 | 决策 |
| --- | --- | --- | --- |
| Phase 0 contract precheck | `outputs/recall/full_main_route_other_methods/phase0_contract_precheck/` | `PASS` | 修复 full-safe config 后通过 gate |
| Phase 1 ItemCF/co-visit merge/eval | `outputs/recall/full_main_route_other_methods/itemcf_covisit_representative_merge_eval/` | `EXECUTED_PASS_OBSERVATION_ONLY` | observation-only，不晋升 |
| Phase 2 UserCF bounded observation | `outputs/recall/full_main_route_other_methods/usercf_bounded_observation/` | `rejected` | 无正向 observation lift，拒绝晋升 |
| Phase 3 Swing + session transition | `outputs/recall/full_main_route_other_methods/swing_sequence_session_observation/` | `EXECUTED_PASS_OBSERVATION_ONLY` | observation-only，不晋升 |
| Phase 4 graph + MF contract | `outputs/recall/full_main_route_other_methods/graph_mf_contract_validation/` | `EXECUTED_PASS_CONTRACT_ONLY` | 只做合同验证，训练延后 |
| Phase 5 two_tower + pool readiness | `outputs/recall/full_main_route_other_methods/two_tower_pool_readiness/` | `EXECUTED_PASS_FEASIBILITY_ONLY` | 只做 feasibility/readiness，训练延后 |
| Phase 6 final matrix | `outputs/recall/full_main_route_other_methods/final_method_matrix_pass/` | `PASS` | 汇总 Phase 0-5 artifact 与 source audit |

本轮是在第 20 节的 `INVALID_SCOPE_DRIFT` 基础上继续推进：保留历史 10k 配置不动，新增 full-safe graph/two_tower/ranking pool200 配置副本，并把 Phase 0 resolver 指向 full clean / full lightweight views。后续 Phase 1-5 均遵守 train-only candidate generation，valid/test 只在 evaluation-only 或合同字段中出现，holdout 不参与候选生成。

### 21.2 关键指标与边界

| 方法族 | 关键结果 | 解释 |
| --- | --- | --- |
| ItemCF/co-visit | `candidate_hit_users_delta=0`、`recall_at_pool_delta=0.0`、`source_marginal_hit=0` | 有代表性 merge/eval 产物，但没有相对 lightweight baseline 的边际命中收益 |
| UserCF | `failure_reason=no_positive_observation_lift`、`no_dense_user_user_matrix=true` | 有 bounded observation，但不构建 dense user-user matrix，结果为 rejected |
| Swing/session | `source_marginal_hit=0`、`no_unbounded_global_pair_counter=true` | 只记录 bounded pair/transition sidecar 证据，最高状态限制为 observation-only |
| graph/MF | `training_disabled=true`、`ranking_default_input_disabled=true` | full-safe config 与输入可追踪，但本轮不做全量 graph/MF 训练 |
| two_tower/pool | `training_default_action=defer_until_explicit_gpu_training_approval`、`pool500/pool1000=READINESS_ONLY_NOT_RANKING_INPUT` | two_tower 不训练不晋升，pool500/pool1000 不替代 ranking frozen pool200 |
| final matrix | `phase_count=6`、`failures=[]` | 所有正式阶段 required artifacts present，并带 hash / row count / source audit 汇总 |

### 21.3 验证证据

- Phase 3：`.venv/Scripts/python.exe -m pytest tests/test_phase3_swing_sequence_session_observation.py`，`3 passed`；ruff 通过。
- Phase 4：`.venv/Scripts/python.exe -m pytest tests/test_phase4_graph_mf_contract_validation.py`，`3 passed`；ruff 通过。
- Phase 5：`.venv/Scripts/python.exe -m pytest tests/test_phase5_two_tower_pool_readiness.py`，`3 passed`；ruff 通过。
- Phase 6：`.venv/Scripts/python.exe -m pytest tests/test_phase6_final_method_matrix.py`，`2 passed`；ruff 通过。
- Phase 6 汇总产物：`outputs/recall/full_main_route_other_methods/final_method_matrix_pass/final_method_matrix.json`，`status=PASS`、`phase_count=6`、`failures=[]`。

### 21.4 当前结论

- 本轮没有新的召回方法族获得晋升；ItemCF/co-visit、UserCF、Swing/session 都没有产生正向边际 lift。
- graph/MF/two_tower 已从“路径/依赖/训练风险不清”推进到可审计的 full-safe contract / feasibility 产物，但默认不训练、不晋升。
- ranking frozen pool200 与 recall promotion gate 继续分离；pool500/pool1000 只保留为 readiness，不进入当前 ranking 默认输入。
- 后续如果要复启更重的方法，应另起 GPU/全量训练审批和新合同，而不是把本轮 observation/feasibility 证据误写成 promotion evidence。

## 22. Representative pool500 recall-only 试验与 Promote/Stop Gate（2026-05-17）

### 22.1 执行合同

本轮承接第 21 节的结论：此前 pool500 只做到 readiness，状态为 `READINESS_ONLY_NOT_RANKING_INPUT`。本节新增独立的 representative pool500 recall-only 分支，只验证召回侧扩池价值，不替代 frozen pool200 ranking input，不进入 ranking，不生成 pool1000，不训练 graph/MF/two_tower。

| 阶段 | 输出目录 | 状态 | 决策 |
| --- | --- | --- | --- |
| P0-P2 contract + same-scope pool200/pool500 | `outputs/recall/pool500_representative/contract_precheck_or_p0_p2/` | `PASS` | 固定 500 representative users，生成同 scope pool200 与 pool500 recall-only 候选 |
| P3-P4 same-scope comparison + audits | `outputs/recall/pool500_representative/p3_p4_audit/` | `PASS` | 计算 pool500 vs pool200 增量，并完成 leakage/resource/ranking isolation 审计 |
| P5 method observations | `outputs/recall/pool500_representative/p5_method_observations/` | `PASS` | 只基于已生成 pool500 候选做方法贡献观察，不新增候选生成/训练/ranking |
| P6 Promote/Stop Gate | `outputs/recall/pool500_representative/p6_promote_stop_gate/` | `PASS` | representative pool500 允许进入后续 recall-only continuation，但不代表 ranking 替换 |

### 22.2 关键指标

| 指标 | pool200 | pool500 | 变化 |
| --- | ---: | ---: | ---: |
| representative users | 500 | 500 | same-scope |
| candidate rows | 100,000 | 193,824 | +93,824 |
| users_with_holdout | 82 | 82 | same denominator |
| candidate_hit_users | 4 | 6 | +2 |
| recall_at_pool | 0.042683 | 0.055459 | +0.012776 |
| empty_candidate_rate | 0.0 | 0.0 | 不恶化 |
| fallback_rate | 0.0 | 0.0 | 不恶化 |
| duplicate_candidate_rows | 0 | 0 | 不恶化 |
| exclusive_hit_users_201_500 | - | 2 | category=1、popular=1 |

P5 方法观察显示，201-500 区间新增命中来自现有 lightweight source：`category=1`、`popular=1`；`semantic=0`。ItemCF/UserCF/Swing/session 不在本轮 P0-P2 pool500 候选 artifact 中贡献新增命中；graph/MF/two_tower 继续保持 contract/deferred，不训练。

### 22.3 审计与 Gate 结果

- `leakage_audit.json`：`PASS`，candidate generation 未读取 valid/test/holdout，valid/test 只作为 evaluation-only。
- `resource_audit.json`：`PASS`，D 盘剩余空间高于 50GiB，未复制 full clean，未生成 pool1000。
- `ranking_isolation_audit.json`：`PASS`，`pool500_as_ranking_input=false`，`frozen_pool200_ranking_baseline_replaced=false`。
- `promote_stop_gate.json`：`status=PASS`、`decision=PASS`、`p7_allowed=true`，但 `p7_allowed_scope` 限定为 recall-only continuation，不是 ranking input replacement。
- P6 执行边界：`no_candidate_generation_executed=true`、`no_full_pool500_executed=true`、`no_ranking_executed=true`、`no_model_training_executed=true`。

### 22.4 验证证据

- `.venv/Scripts/python.exe -m pytest tests/test_pool500_representative.py`：`5 passed`。
- `.venv/Scripts/python.exe -m ruff check scripts/experiments/recall/run_pool500_representative_p0_p2.py scripts/experiments/recall/run_pool500_representative_p3_p4_audit.py scripts/experiments/recall/run_pool500_representative_p5_method_observations.py scripts/experiments/recall/run_pool500_representative_p6_promote_stop_gate.py tests/test_pool500_representative.py`：`All checks passed`。
- 独立 verifier 只读复核：`APPROVED`，0 blockers；确认 P0-P6 artifacts、审计、P6 Gate 与测试证据一致。

### 22.5 当前结论

- representative pool500 已经从 readiness 推进到真实 recall-only 试验，并在同一 500 用户样本上相对 pool200 产生可解释增量：`exclusive_hit_users_201_500=2`、`recall_at_pool_delta=0.012776`。
- 该增量来自 lightweight `category` 与 `popular` 扩池后的 201-500 区间，不是 ItemCF/UserCF/Swing/session 或重模型贡献。
- 当前结论只批准后续 recall-only continuation / full pool500 规划入口；仍不允许自动替代 frozen pool200 ranking input。如需进入 ranking 或 full pool500 全量，应另起 P7/full 阶段并保留本节 Gate 条件。

## 23. Representative pool500 全方法 custom-index 试验与 Final Gate（2026-05-17）

### 23.1 执行合同

本节承接第 22 节的 Gate 结果：representative pool500 已证明扩池有召回侧增量，但第 22 节实际候选主要覆盖 lightweight source。根据“重方法用定制数据集索引先试验”的边界，本轮新增 `pool500_all_methods_representative` 分支，在 500 representative users 与 custom item index 内补齐主路方法族观察；仍不做 full pool500、不进入 ranking、不生成 pool1000、不训练 graph/MF/two_tower。

| 阶段 | 输出目录 | 状态 | 决策 |
| --- | --- | --- | --- |
| custom index | `outputs/recall/pool500_all_methods_representative/custom_index/` | `PASS` | 固定 500 users、10739 items、1289 train events，建立 custom user/item index |
| lightweight + CF | `outputs/recall/pool500_all_methods_representative/lightweight_cf_methods/` | `PASS` | 复用 lightweight pool500，并补齐 bounded ItemCF/UserCF observation |
| sequence/session | `outputs/recall/pool500_all_methods_representative/sequence_session_methods/` | `EXECUTED_PASS_OBSERVATION_ONLY` | 补齐 bounded Swing 与 session transition observation |
| heavy indexed probes | `outputs/recall/pool500_all_methods_representative/heavy_indexed_probes/` | `PASS` | graph/MF/two_tower 仅做 custom-index feasibility/proxy probe，不训练 |
| final Gate | `outputs/recall/pool500_all_methods_representative/final_gate/` | `PASS` | `decision=CONTINUATION_ONLY`，只允许后续 recall-only full pool500 continuation |

### 23.2 方法族覆盖与关键指标

| 方法族 | 方法 | 观察结果 |
| --- | --- | --- |
| lightweight | popular / category / semantic | lightweight pool500 `candidate_rows=193824`，`candidate_hit_users=6`，`recall_at_pool=0.055459` |
| bounded CF | ItemCF/co-visit | 335 rows、41 users 覆盖、`candidate_hit_users=0`，无边际 lift |
| bounded CF | UserCF | 14 rows、3 users 覆盖、`candidate_hit_users=0`，无边际 lift，`no_dense_user_user_matrix=true` |
| sequence/session | Swing | 301 rows、40 users 覆盖，observation-only |
| sequence/session | session transition | 68 rows、35 users 覆盖，observation-only |
| heavy probe | graph | 1289 bipartite edges、5397 projected item cooccurrence edges、789 directed transitions，probe-only |
| heavy probe | MF | custom sparse matrix `[500, 10739]`、nnz=1289、density=0.000240059596，probe-only |
| heavy probe | two_tower | 500 nonempty users、444 positive users、422 strong-positive users，no GPU/no training |

合并观察中，`merged_lightweight_cf` 相对 lightweight 的 `candidate_hit_users_delta_vs_lightweight=0`、`recall_at_pool_delta_vs_lightweight=0.0`；sequence/session 新增 320 条方法候选，306 条保留在 merged pool500 中，但本轮不读取 valid/test/holdout 做新增命中评分。

### 23.3 审计与 Gate 结果

- `source_audit.json`：Final Gate 只聚合 compact JSON artifacts；candidate generation read files 不包含 valid/test/holdout，lightweight 的 valid/test 读取仅作为 evaluation-only。
- `resource_audit.json`：D 盘水位高于 50GiB；无 full clean copy；ItemCF/Swing/session 无 full global counter；UserCF 无 dense all-user matrix。
- `promote_stop_gate.json`：`status=PASS`、`decision=CONTINUATION_ONLY`、`full_pool500_continuation_allowed=true`；但 `ranking_input_replacement_allowed=false`、`heavy_model_training_allowed_by_this_gate=false`、`pool1000_allowed=false`。
- `final_method_matrix.json`：覆盖 popular/category/semantic、bounded ItemCF、bounded UserCF、Swing/session-transition、graph probe、MF probe、two_tower probe。

### 23.4 验证证据

- `.venv/Scripts/python.exe -m pytest tests/test_pool500_all_methods_representative.py`：`5 passed in 0.09s`。
- `.venv/Scripts/python.exe -m ruff check scripts/experiments/recall/build_pool500_all_methods_custom_index.py scripts/experiments/recall/run_pool500_all_methods_lightweight_cf.py scripts/experiments/recall/run_pool500_all_methods_heavy_indexed_probes.py scripts/experiments/recall/run_pool500_all_methods_gate.py tests/test_pool500_all_methods_representative.py`：`All checks passed`。
- 独立 verifier：`APPROVED`，0 blockers；确认 no 10k、no full clean copy、no pool1000、no ranking replacement、no heavy training、bounded resource invariants 均成立。

### 23.5 当前结论

- representative pool500 已从“只验证扩池价值”推进到“全主路方法族 custom-index 观察”，所有方法族都有可回指 artifact。
- 当前最确定的召回增量仍来自 lightweight pool500；CF、sequence/session 在代表性 custom index 内补齐了 bounded observation，但没有形成可晋升的新增 recall lift 证据。
- graph/MF/two_tower 只证明 custom-index feasibility/proxy 可行，不构成训练或晋升批准。
- Final Gate 只批准后续 recall-only full pool500 continuation；不允许自动替代 frozen pool200 ranking input，不允许 pool1000，不允许重模型训练。若继续，应另起 full pool500 recall-only 阶段并继承本节审计条件。

## 24. Pool200 promoted main route 权威口径固定（2026-05-17）

### 24.1 固定结论

本节用于固定后续 P7 / pool500 continuation 的 route authority：当前排序侧使用的 pool200 promoted main route 是 Phase 1.21 `source_balanced_fallback_preserving`，不是后续 representative pool500 或 all-method custom-index 结果重新选出的路线。pool500 只能在这条 pool200 主路上做 `candidate_pool_size 200→500` 的 recall-only continuation，不能静默删减主路方法。

权威 artifact：

| 项目 | 路径 |
| --- | --- |
| pool200 frozen candidates | `outputs/recall/phase_1_21_recall_coverage/current_main_route_pool200_source_balanced/frozen_candidates.jsonl` |
| route manifest | `outputs/recall/phase_1_21_recall_coverage/current_main_route_pool200_source_balanced/manifest.json` |
| route metrics | `outputs/recall/phase_1_21_recall_coverage/current_main_route_pool200_source_balanced/metrics.json` |
| Phase 1.21 主路配置 | `configs/recall/phase_1_21/phase_1_21_recall_coverage_pool200_experimental.yaml` |
| 继承 baseline | `configs/ranking/phase_1_15/phase_1_15_frozen_youtubednn_pool100.yaml` |
| YouTubeDNN artifact | `outputs/training/two_tower/two_tower_training/youtube_dnn/artifact_manifest.json` |

### 24.2 pool200 frozen candidate source 清单

`frozen_candidates.jsonl` 共 `63,486` 条候选行，覆盖 `500` 个用户；其中 `16,885` 条为 multi-source 合并候选。实际 source 分布如下：

| source | rows | users | items | 口径 |
| --- | ---: | ---: | ---: | --- |
| `popular` | `20,000` | `500` | `50` | 热门兜底，来自 Phase 1.15 baseline 的 popularity fallback |
| `two_tower` | `14,611` | `499` | `7,432` | YouTubeDNN 双塔向量召回，继承自 Phase 1.15 frozen YouTubeDNN baseline |
| `category` | `13,649` | `453` | `423` | 类目召回，继承自 baseline |
| `semantic` | `13,560` | `454` | `6,629` | 文本语义召回，继承自 baseline |
| `semantic_title_category_expansion` | `7,328` | `454` | `4,648` | Phase 1.21 新增标题 + 类目语义扩展 |
| `usercf_recall` | `4,502` | `210` | `2,944` | Phase 1.21 新增 UserCF 行为召回 |
| `itemcf_weak` | `4,234` | `210` | `2,537` | baseline ItemCF 弱行为召回 |
| `itemcf_strong` | `3,994` | `202` | `2,254` | baseline ItemCF 强行为召回 |
| `co_visit_fallback_repair` | `3,973` | `224` | `2,488` | Phase 1.21 新增 co-visit fallback repair |
| `swing_recall` | `3,751` | `209` | `2,137` | Phase 1.21 新增 Swing 行为召回 |

因此，pool200 promoted main route 的方法组成固定为：`popular`、`category`、`semantic`、`semantic_title_category_expansion`、`itemcf_weak`、`itemcf_strong`、`co_visit_fallback_repair`、`usercf_recall`、`swing_recall`、`two_tower` / YouTubeDNN。

### 24.3 YouTubeDNN / two_tower 继承口径

此前日志中“保留 existing two-tower artifact 旁路”容易造成误解；复核 frozen candidates 后，`two_tower` 不是单纯旁路统计或 observation 产物，而是实际进入 pool200 主路 frozen candidates 的有效 source。样例 candidate metadata 包含：`two_tower_source_name=two_tower_youtube_dnn`、`two_tower_variant=youtube_dnn`、`model_type=youtube_dnn_two_tower_v1`、`two_tower_score_mode=vector_dot`。

继承链路如下：

1. Phase 1.21 主路配置 `phase_1_21_recall_coverage_pool200_experimental.yaml` 指向 `phase_1_15_frozen_youtubednn_pool100.yaml`。
2. Phase 1.15 baseline 中 `two_tower_enabled=true`、`two_tower_variant=youtube_dnn`、`two_tower_artifact_path=outputs/training/two_tower/two_tower_training/youtube_dnn/artifact_manifest.json`。
3. Phase 1.21 runner 先加载 baseline config，再叠加 phase config；Phase 1.21 config 未关闭 `two_tower_enabled`，因此 YouTubeDNN/two_tower 保留进 pool200 主路。
4. `current_main_route_pool200_source_balanced/frozen_candidates.jsonl` 中存在 `14,611` 条 `two_tower` source 候选，覆盖 `499` 个用户。

### 24.4 source-balanced 截断策略

主路截断策略固定为 `balanced_source_budget` / `source_balanced_fallback_preserving`：

```yaml
candidate_source_minimums:
  semantic_title_category_expansion: 40
  co_visit_fallback_repair: 20
  usercf_recall: 10
  swing_recall: 10
candidate_source_maximums:
  popular: 40
candidate_fill_order:
  - semantic_title_category_expansion
  - co_visit_fallback_repair
  - usercf_recall
  - swing_recall
  - itemcf
  - category
  - popular
candidate_multi_source_boost: 0.1
```

该策略在不牺牲 `candidate_hit_users=19` 的前提下，把命中位置和候选规模优于默认 score-sorted 截断，因此是当前主路的固定截断方式。

### 24.5 P7 / pool500 继承要求

后续 P7 full pool500 recall-only continuation 必须继承本节固定的 pool200 主路：

- 只允许把 `candidate_pool_size` 从 `200` 改为 `500`，以及更新 output/run/audit metadata。
- 不允许用 representative pool500 lightweight 结果冒充 full P7。
- 不允许用 all-method custom-index observation 重新选择主路。
- 不允许静默移除 YouTubeDNN/two_tower、ItemCF、UserCF、Swing、co-visit repair 或 source-balanced 截断。
- P7 route gate 必须把 YouTubeDNN/two_tower artifact、sidecar/schema/hash/freshness 纳入 route signature；若 artifact 校验失败，应阻塞为 `BLOCKED_TWO_TOWER_ARTIFACT`，而不是降级为 probe 或禁用双塔。

## 25. P7 route precheck / gate 实现与阻断（2026-05-17）

### 25.1 变更范围

本轮补齐 P7 route precheck / gate 逻辑，新增 `scripts/experiments/recall/run_p7_full_pool500_route_gate.py` 与 `tests/test_p7_full_pool500_route_gate.py`。gate 只负责校验主路继承关系与路由签名，不替代 full pool500 召回实验本身；当前只允许 `STOP`、`DIAGNOSTIC_ONLY`、`PASS_CONTINUATION` 三态决策。

### 25.2 当前权威阻断

| 项 | 结果 |
| --- | --- |
| gate 当前状态 | `STOP / BLOCKED_TWO_TOWER_ARTIFACT` |
| 直接原因 | YouTubeDNN manifest 内部路径仍指向旧目录，路由签名未通过 |
| 处理方式 | 未绕过、未降级、未关闭双塔、未启动 full pool500 |
| 允许范围 | 仅保留 diagnostic 复核与后续 continuation 入口 |

### 25.3 验证证据

- `tests/test_p7_full_pool500_route_gate.py` 对 gate 三态与阻断条件做了覆盖。
- `.venv/Scripts/python.exe -m pytest tests/test_p7_full_pool500_route_gate.py`：`7 passed`。
- `.venv/Scripts/python.exe -m ruff check scripts/experiments/recall/run_p7_full_pool500_route_gate.py tests/test_p7_full_pool500_route_gate.py`：`All checks passed`。
- `.venv/Scripts/python.exe -m pytest tests -k "pool500 or p7"`：`18 passed`。

### 25.4 当前结论

- P7 现在是“先证实路由签名可用，再决定是否 continuation”，不是直接宣称 full pool500 已完成。
- 当前最重要的边界是：双塔权威 artifact 仍未通过旧目录路径校验，因此 gate 停在 `BLOCKED_TWO_TOWER_ARTIFACT`。
- 后续只有在 artifact 路径与签名一致后，才允许进入 `PASS_CONTINUATION`；在此之前不能把 gate 结果写成 full pool500 已跑通。

### 25.5 面试可讲点

这次的重点不是“把实验跑完”，而是把 P7 的路由前置检查做成了可验证的安全闸门：先用单测和 lint 把三态决策、双塔 artifact 校验、阻断语义固定下来，再用验证命令确认 gate 能稳定拦住旧目录路径问题，避免把错误的双塔继承关系带进后续 pool500 扩池。
