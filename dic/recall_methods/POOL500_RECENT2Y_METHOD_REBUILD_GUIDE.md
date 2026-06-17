# Pool500 recent-2y 召回方法重建统一执行文档

日期：2026-06-02

本文档用于给每一种召回方法单独开窗口执行。当前背景是：项目已切换到 `recent_2y_1m_3m` 数据基础，旧 full-data 派生 artifact 只能作为历史参考，不能继续作为当前 pool500 召回方法的正式输入或效果结论。

本轮目标不是“把旧脚本重新跑一遍”，而是针对每种召回方法的归纳偏置，重新完成：

1. SciOMC 调查：调研该方法在推荐系统中的最佳实践，尤其是数据预处理、样本选择、训练/构建方式、评估口径。
2. RALPLAN 计划：把调查结果转成可执行计划，明确 smoke/formal 数据集、训练/构建策略、验证指标、风险门禁。
3. 执行落地：为该方法形成两套 recent-2y 方法数据集：`smoke` 与 `formal`。
4. 效果验证：在 train-only governance 边界内构建 source artifact，跑出可复核效果，并更新方法文档和配置。

---

## 1. 当前方法范围

当前按召回 source 计算，共 10 种方法。`user_quality` 不算召回方法，它是 eligibility policy / 用户质量分层，供 UserCF、ItemCF、Swing、Two Tower 等方法选择训练或构建对象。

| 方法 | 当前状态 | 方法定位 | 本轮重建重点 |
|---|---:|---|---|
| `category` | READY | 类目偏好 / 类目覆盖召回 | 类目字段清洗、用户类目画像、fallback 类目覆盖 |
| `popular` | READY | 热门与兜底召回 | 时间窗热度、冷启动覆盖、去泄漏统计口径 |
| `swing_recall` | READY | Swing 行为协同召回 | 共现图质量、热门惩罚、用户行为门槛、formal 无固定小 cap |
| `usercf_recall` | DIAGNOSTIC_ONLY | 用户相似度召回 | 高质量用户筛选、相似度可靠性、邻居召回覆盖 |
| `itemcf_weak` | DIAGNOSTIC_ONLY | 宽覆盖 ItemCF | medium/heavy 用户覆盖、弱边保留、长尾覆盖与噪声控制 |
| `itemcf_strong` | DIAGNOSTIC_ONLY | 高置信 ItemCF | heavy 用户、强边阈值、共现置信度、候选质量 |
| `semantic` | DEFERRED | 文本/元数据语义召回 | 文本字段组织、编码/检索策略、RAG 证据层边界 |
| `semantic_title_category_expansion` | DEFERRED | title + category 语义扩展 | title/category 组合、语义漂移控制、扩展范围门禁 |
| `co_visit_fallback_repair` | DEFERRED | 共访 fallback 修复 | 缺口诊断、补洞策略、避免冒充主力召回 |
| `two_tower` | DEFERRED | 双塔 embedding / ANN 召回 | 训练样本、负采样、item universe、ANN 构建与离线评估 |

参考登记位置：

- `configs/recall/pool500_method_registry.json`
- `rs_core/recsys/recall_sources/registry.py`
- `dic/recall_methods/<method>/METHOD.md`
- `configs/recall/full_data_pool500/<method>/source_config.yaml`

---

## 2. 全局数据与治理边界

### 2.1 当前唯一正式数据基础

所有方法都应以 recent-2y 数据为当前正式基础：

- 数据根：`data/processed/amazon_2023_recall_recent_2y_1m_3m/`
- 主 manifest：`data/processed/amazon_2023_recall_recent_2y_1m_3m/manifest.json`
- train-only governance：`data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json`

### 2.2 允许输入

原则上只允许使用 train 可见输入：

- `canonical_interactions.train.jsonl`
- `user_sequences.train.jsonl`
- `canonical_items.jsonl`
- `train_only_governance/*`
- 方法自己基于上述输入派生的 smoke/formal method dataset manifest

### 2.3 禁止输入

构建召回方法数据集、训练 artifact、source index 时，不得读取或注入：

- holdout / valid / test 作为训练或召回构建输入
- clean_10000 旧诊断集
- LOPO label / eval label / oracle label
- pool1000 诊断产物
- 旧 full-data-derived method dataset
- 任何把 label 正样本直接塞回召回候选池的 artifact

验证阶段可以使用评估集计算指标，但必须保证评估 label 只用于评估，不得反向参与候选生成、训练输入或 source index。

### 2.4 user_quality 的定位

`user_quality` 是 policy，不是 recall source。它可以用于：

- 判断哪些用户进入重资源召回方法。
- 区分 `heavy_cf_eligible`、`medium_behavior`、`fallback_only` 等用户桶。
- 作为 UserCF / ItemCF / Swing / Two Tower 的训练或构建筛选条件。

它不能用于：

- 生成候选 source。
- 直接替换 ranking input。
- 宣称 final pool500 ready。

---

## 3. 每个方法窗口的统一执行流程

每个窗口只负责一个 `<method>`，不要顺手改其他方法。推荐执行顺序如下。

### 3.0 `goal` 命令适配说明

如果使用 `goal` 命令驱动执行，不建议把 10 种方法塞进同一个 goal。本机可以承受 10 个窗口并行推进调研、计划、文档和轻量 smoke；真正需要避免的是多个窗口同时在本机运行耗费 CPU、内存、磁盘 I/O、GPU、网络传输或长时间占用资源的任务。因此，所有明显耗费资源的构建、训练、评估和大规模数据处理都应迁移到 server 远程服务器，并按资源队列分批运行。推荐拆成：

1. 一个前置治理 goal：只检查 recent-2y train-only governance 与 `user_quality` policy。
2. 十个单方法 goal：每个 goal 只负责一个 `<method>`。
3. 一个全局主路收口 goal：等单方法 goal 都完成或明确停止原因后，再判断哪些方法进入主路。

每个单方法 goal 的内容应包含：

- 目标方法名 `<method>`。
- 必读文件清单。
- 旧配置不能直接当作新结论的提醒。
- SciOMC 调查要求，其中必须包含论文/经典方法/工业实践调研。
- RALPLAN 计划要求。
- smoke/formal 数据集构建要求。
- 本地 `.venv` 与 server 远程资源任务执行要求。
- 必须更新的文档和配置。
- 明确停止条件：完成、保持 DIAGNOSTIC_ONLY / DEFERRED、或因数据/资源/指标门禁失败而停止。

`goal` 执行时要把“长期目标”理解为完成该窗口的全部交付物，而不是只完成第一轮调查或第一条命令。若某一步无法继续，必须写清 blocker、证据、未完成项和下一步，不要把 partial artifact 误报为完成。

### Phase A：读取现状

必须先读下列文件，但要注意：除本文档外，其余方法文档、方法配置、registry 和 dataset policy 很可能仍是旧配置或旧结论。它们在本阶段的作用是“读取旧现状、识别需要更新的字段”，不是直接当作 recent-2y 重建后的事实。

1. 本文档：`dic/recall_methods/POOL500_RECENT2Y_METHOD_REBUILD_GUIDE.md`
2. 旧方法文档：`dic/recall_methods/<method>/METHOD.md`
3. 旧方法配置：`configs/recall/full_data_pool500/<method>/source_config.yaml`
4. 旧总 registry：`configs/recall/pool500_method_registry.json`
5. 如存在，旧 dataset policy：`configs/recall/full_data_pool500/<method>/dataset_policy.yaml`
6. 与方法相关的脚本和测试。

输出一段简短现状判断：

- 当前方法状态是 READY / DIAGNOSTIC_ONLY / DEFERRED 哪一种。
- 当前 artifact 是否来自旧 full-data 或 legacy 路径。
- 是否已有 recent-2y smoke/formal 产物。
- 当前最大风险是数据泄漏、旧 artifact 回流、低质量用户、噪声边、训练资源，还是评估口径不清。

### Phase B：SciOMC 调查

每个方法必须先做调查，再写计划。调查不是泛泛讲算法原理，而是服务于本项目 recent-2y 重建。调查阶段要多查论文和经典方法资料，优先覆盖该方法的原始论文、改进论文、工业实践文章和可复现实现经验；如果论文结论与本项目数据规模、Amazon 行为数据、train-only governance 或资源约束不完全匹配，需要写明取舍，而不是直接照搬。

调查问题模板：

```text
请针对 <method> 在推荐系统召回中的最佳实践做调查，必须多查相关论文、经典方法和工业实践资料，并重点回答：
1. 该方法有哪些关键论文、经典变体和工业实践？每篇/每类资料对数据预处理、训练/构建、评估指标有什么启发？
2. 该方法最依赖什么数据质量条件？用户行为数、item 频次、类目字段、文本字段、时间窗、共现密度分别有什么要求？
2. 该方法应该如何做数据预处理？包括用户过滤、item 过滤、去噪、去重、时间窗、字段清洗、样本构造、负采样或共现边构造。
3. smoke 数据集应该如何设计，才能快速验证代码路径和 schema，但不被误当正式效果？
4. formal 数据集应该如何设计，才能发挥该方法效果，并符合 train-only governance？
5. 如果该方法需要训练或索引构建，训练/构建策略、超参、资源控制、早停或质量门禁应该如何设置？
6. 该方法应该如何评估？需要看 Recall@K、覆盖率、候选数、用户桶分层、item universe 内召回、长尾覆盖、source overlap 中的哪些指标？
7. 该方法最常见的失败模式是什么？本项目应该如何设置 gate 防止错误晋升？
```

建议把调查结论写入：

`dic/recall_methods/<method>/RECENT2Y_SCIOMC_RESEARCH.md`

如果该文件已存在，应更新而不是重复创建。调查文档需要保留：

- 论文/经典方法/工业实践资料清单，至少记录标题或来源、核心结论和对本项目的启发。
- 最佳实践摘要。
- 对本项目数据的适配判断。
- smoke/formal 数据集设计建议。
- 训练/构建建议。
- 评估建议。
- 风险与门禁。

### Phase C：RALPLAN 计划

在调查完成后，再用 RALPLAN 把结论转成实施计划。计划不能只写“运行脚本”，必须拆清楚数据、构建、训练、评估、文档和门禁。

计划至少包含：

1. 当前现状和缺口。
2. smoke dataset contract。
3. formal dataset contract。
4. 训练/构建 source artifact 的步骤。
5. 资源控制策略。
6. 验证命令与预期指标。
7. 需要更新的文件。
8. 不允许做的事情。
9. 完成条件和停止条件。

建议写入：

`dic/recall_methods/<method>/RECENT2Y_REBUILD_PLAN.md`

### Phase D：执行

执行时按计划推进，优先顺序：

1. 固化 dataset policy / manifest contract。
2. 构建 smoke method dataset。
3. 跑 smoke source 构建或训练链路。
4. 验证 smoke：schema、路径、无泄漏、manifest、最小指标。
5. 构建 formal method dataset。
6. 跑 formal source 构建或训练。
7. 验证 formal：效果、覆盖、资源、门禁。
8. 根据 SciOMC 调查、RALPLAN 计划和实际验证结果，更新方法文档、方法配置、dataset policy 和 registry；不得继续保留与 recent-2y 重建结论冲突的旧配置。

所有本地命令默认使用项目 `.venv`：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m <module> ...
```

凡是会明显耗费 CPU、内存、磁盘 I/O、GPU、网络传输或长时间运行的任务，原则上都使用 server 远程服务器运行，不在本机硬跑。包括但不限于全量 formal 构建、embedding 训练/编码、ANN 构建、ItemCF/UserCF/Swing 大图构建、全量 source artifact 生成、全量评估和大规模合并。远程执行前必须确认资源策略，按限流、分批、监控执行；完成后把 manifest、stats、评估报告和必要 artifact 拉回本地复核。本机只承担轻量 smoke、配置/文档更新、小规模 schema 校验和必要的 focused tests。

### Phase E：验证与记录

完成前必须给出证据：

- smoke dataset manifest 路径。
- formal dataset manifest 路径。
- source artifact manifest 路径。
- 评估报告或指标路径。
- 测试命令和结果。
- 是否仍为 READY / DIAGNOSTIC_ONLY / DEFERRED。
- 是否允许 candidate generation。
- 是否允许 ranking input replacement，默认不允许。

若任务明显影响架构、模型策略、评估结果或数据链路，应追加简短中文条目到：

`dic/ENGINEERING_NARRATIVE_LOG.md`

### Phase F：主路并入与全局收口

单方法 formal 跑通不等于自动并入主路。每个方法窗口完成后，只能给出“是否建议晋升”的证据；真正并入 pool500 主路需要单独经过全局收口和 route gate。

方法允许进入主路候选生成，至少需要满足：

- `status` 从 DEFERRED / DIAGNOSTIC_ONLY 调整为 READY 时，有 formal 评估证据支撑。
- source artifact manifest 明确 `candidate_generation_allowed=true`，且 `promotion_allowed` / `ranking_input_replacement_allowed` 的语义与当前阶段一致。
- 通过 source loader、candidate merge、route gate 和相关 regression tests。
- 与已 READY 方法做 source overlap / coverage / Recall@K / 用户桶分层对比，证明新增方法有互补价值或明确的 fallback 价值。
- 没有使用旧 full-data artifact、oracle label、eval label 或 smoke 结果作为晋升依据。
- 更新 `configs/recall/pool500_method_registry.json`、`rs_core/recsys/recall_sources/registry.py`、对应 `source_config.yaml`，并保证三者状态一致。

所有方法都完成单窗口后，需要再做一次“全局主路收口”任务：汇总 10 种方法的 readiness、artifact、覆盖、Recall@K、资源成本和互补性，决定哪些方法进入主路、哪些保持 diagnostic/shadow、哪些继续 deferred。主路并入的最终完成标准以后续全局收口文档和 route gate 验证为准。

---

## 4. smoke / formal 数据集统一 contract

### 4.1 smoke dataset

smoke 只用于快速验证链路，不作为正式效果结论。

必须满足：

- 输入来自 recent-2y train-only governance。
- 规模小或边界受控，能快速本地运行。
- deterministic：同一配置重复运行结果稳定。
- 产物包含 manifest、stats、input hash、过滤规则。
- 明确写入 `purpose=program_and_schema_validation_only` 或等价字段。
- 明确写入 `promotion_allowed=false`。
- 不允许替换 ranking input。

smoke 可验证：

- schema 是否正确。
- source index / builder 是否能跑通。
- path / manifest / gate 是否拦截 forbidden input。
- 基础候选数、覆盖率是否非零。

smoke 不可宣称：

- 方法正式达标。
- ranking 效果提升。
- 可替换主路。

### 4.2 formal dataset

formal 是该方法在 recent-2y train-only 口径下的正式方法数据集。

必须满足：

- 输入仍然只来自 train-visible 数据。
- 数据选择逻辑按方法特点定制，而不是所有方法共用同一个粗暴 cap。
- 规模策略由方法和资源共同决定；不要在方法侧写死无解释的小 cap。
- manifest 记录完整 lineage、hash、过滤规则、用户/item 数、边数或样本数。
- 训练型方法必须记录训练配置、seed、负采样、item universe、模型/索引参数。
- 非训练型方法必须记录统计窗口、共现/热度/类目/文本索引构建规则。

formal 可用于：

- 方法正式召回效果评估。
- 与旧 artifact 做历史对比。
- 决定是否从 DEFERRED / DIAGNOSTIC_ONLY 推进到更高 readiness。

formal 仍默认不意味着：

- 自动替换 ranking input。
- 自动进入线上主路。
- 自动晋升 pool1000 或 final pool500 ready。

---

## 5. 方法特化执行提示

### 5.1 `popular`

核心问题：热度统计必须使用 train-visible 时间窗，不能看评估期热度。

重点调查：

- 短期热度 vs 全 train 热度。
- 类目内热门 vs 全局热门。
- 冷启动用户和 fallback 用户覆盖。
- 热门召回对长尾覆盖的副作用。

smoke：少量用户 + train 热度 topN，验证兜底链路。

formal：完整 train 统计，可考虑全局热门、类目热门、时间衰减热门的对照，但默认不要引入没有调查依据的复杂衰减。

### 5.2 `category`

核心问题：类目字段质量和用户类目画像决定效果。

重点调查：

- item 类目字段清洗和层级选择。
- 用户历史类目偏好构建。
- 类目内热门与个性化类目覆盖。
- 行为稀疏用户如何 fallback。

smoke：少量用户 + 类目字段完整性检查 + 类目候选非零。

formal：完整 train 用户画像，按 medium/fallback 用户桶报告覆盖。

### 5.3 `swing_recall`

核心问题：共现结构、热门惩罚和用户行为质量。

重点调查：

- Swing 权重公式和热门用户/item 惩罚。
- 用户行为长度门槛。
- 共现边过滤。
- heavy/medium 用户是否分层构图。

smoke：deterministic first-N 或 bounded user_quality subset，只验证构图与 source adapter。

formal：完整 recent-2y train-only 输入，资源受控构图，不把 smoke first-N 当正式结论。

### 5.4 `usercf_recall`

核心问题：用户相似度对低行为用户非常敏感。

重点调查：

- 用户相似度计算：Jaccard、cosine、BM25-like、IUF 惩罚等。
- 用户行为数门槛。
- 邻居数、候选扩展数。
- 如何避免热门 item 主导相似度。

smoke：heavy_cf_eligible 小样本，验证相似用户和候选生成。

formal：以 heavy_cf_eligible 为主，必要时单独报告 medium 用户 fallback，不要强行让冷用户进入 UserCF。

### 5.5 `itemcf_weak`

核心问题：覆盖优先，但要控制噪声。

重点调查：

- 宽松共现边阈值。
- medium + heavy 用户输入。
- 长尾 item 保留策略。
- item universe 内正样本召回分母。

smoke：medium/heavy 混合小样本，验证边数、候选数、覆盖率。

formal：面向覆盖的 item-item 图，报告 coverage、Recall@K、source overlap、in-universe recall。

### 5.6 `itemcf_strong`

核心问题：高置信边和候选质量。

重点调查：

- 强边阈值：共现次数、共同用户数、相似度下限。
- heavy 用户训练输入。
- 热门 item 惩罚。
- strong 与 weak 的分工和 overlap。

smoke：heavy 用户 + 强边小样本，验证强边非零和质量。

formal：不要追求最大覆盖，重点报告高置信候选质量、Recall@K、与 weak 的互补性。

### 5.7 `semantic`

核心问题：文本组织、编码/检索策略和 candidate source 边界。

重点调查：

- title、category、brand、store、description、features 如何组织为文档。
- BM25 / dense embedding / hybrid 的适用性。
- RAG evidence 与 recall source 的边界。
- 如何避免语义漂移和不可解释候选。

smoke：小 item corpus + 文档字段质量 + 检索可用性。

formal：按 recent-2y item universe 构建文本索引；如果只是 RAG evidence，要明确 `candidate_generation_allowed=false`。

### 5.8 `semantic_title_category_expansion`

核心问题：用 title/category 扩展召回，但要控制漂移。

重点调查：

- title token 清洗。
- 类目层级作为约束还是加权字段。
- 相似 item 扩展半径。
- 是否按用户历史 seed item 扩展。

smoke：少量 seed item 验证扩展候选不为空且类目合理。

formal：按用户历史 item 或类目偏好扩展，报告语义候选覆盖、类目一致性、与 category/semantic 的 overlap。

### 5.9 `co_visit_fallback_repair`

核心问题：它是缺口修复，不应冒充主力召回。

重点调查：

- 哪些用户或场景需要 fallback repair。
- 共访边如何构建。
- 与 popular/category 的补位关系。
- 如何度量“修复”而不是整体 Recall。

smoke：选择 fallback_only 或召回不足用户，验证 repair 能补出候选。

formal：面向召回缺口用户构建，不追求全用户主召回；报告缺口用户覆盖改善和新增候选质量。

### 5.10 `two_tower`

核心问题：训练样本、负采样、item universe 和 ANN 评估。

重点调查：

- 用户塔输入：序列、聚合 embedding、用户画像。
- item 塔输入：id、category、文本、频次特征。
- 正负样本构造与时间切分。
- in-batch negatives / sampled negatives / hard negatives。
- ANN 索引构建、召回 K、embedding 归一化。
- GPU/远程资源控制。

smoke：极小训练或 embedding/index smoke，只验证训练入口、loss 下降、ANN 查询可用。

formal：recent-2y train-only 样本，明确 item universe 和负采样；评估时报告 Recall@K、用户桶分层、in-universe denominator。

---

## 6. 每个窗口的建议交付物

每个方法窗口完成后，必须把旧文档和旧配置更新成 recent-2y 重建后的当前事实。下面这些不是只读参考，而是调研、计划、执行和验证完成后的更新目标：

- `dic/recall_methods/<method>/METHOD.md`：更新方法定位、数据集策略、训练/构建策略、当前 readiness、效果结论和下一步。
- `configs/recall/full_data_pool500/<method>/source_config.yaml`：更新 source 输入、artifact 路径、权限位、ready/diagnostic/deferred 状态和门禁字段。
- `configs/recall/pool500_method_registry.json`：更新该方法的 registry 条目，包括 dataset contract、latest artifact、row count、status 和 notes。
- `configs/recall/full_data_pool500/<method>/dataset_policy.yaml`：如存在则更新；如方法需要独立 dataset policy 但不存在，应按计划新增。

每个方法窗口完成后，至少应交付：

```text
dic/recall_methods/<method>/RECENT2Y_SCIOMC_RESEARCH.md
dic/recall_methods/<method>/RECENT2Y_REBUILD_PLAN.md
dic/recall_methods/<method>/METHOD.md                    # 更新当前结论
configs/recall/full_data_pool500/<method>/dataset_policy.yaml  # 如适用
configs/recall/full_data_pool500/<method>/source_config.yaml
outputs/recall/pool500_method_datasets/recent_2y/<method>/smoke/.../method_dataset_manifest.json
outputs/recall/pool500_method_datasets/recent_2y/<method>/formal/.../method_dataset_manifest.json
outputs/recall/pool500_method_sources/recent_2y/<method>/.../source_index_manifest.json
```

如果某方法不需要训练，应把“训练方法”替换成“构建/索引/统计方法”。

如果某方法仍不适合晋升 READY，也要明确写出原因和下一步，而不是强行包装成完成。

---

## 7. 每个窗口可直接使用的 `goal` 提示词

把下面 `<method>` 替换成具体方法名。若使用 `goal` 命令，可直接把整段作为该窗口的 goal 内容；不要只复制前半段，否则容易停在调查或计划阶段。

```text
你负责 pool500 recent-2y 召回方法重建中的 `<method>` 单方法窗口。这是一个完整 goal：不要在只完成调查、计划或 smoke 后停止，必须推进到该方法的完成标准，或在被数据、资源、指标、门禁阻塞时写清停止原因和下一步。

请先阅读：
1. dic/recall_methods/POOL500_RECENT2Y_METHOD_REBUILD_GUIDE.md
2. dic/recall_methods/<method>/METHOD.md
3. configs/recall/full_data_pool500/<method>/source_config.yaml
4. configs/recall/pool500_method_registry.json
5. data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json

注意：第 2-4 项很可能仍是旧配置/旧结论。它们需要在 SciOMC 调查、RALPLAN 计划、smoke/formal 构建和验证完成后被对应更新，不要直接当作 recent-2y 重建后的最终事实。

任务目标：
- 不复用旧 full-data artifact 作为当前结论。
- 先用 SciOMC 调查 `<method>` 的最佳实践，必须多查相关论文、经典方法和工业实践资料，重点是数据预处理、smoke/formal 数据集设计、训练/构建方法和评估口径。
- 再用 RALPLAN 把调查结果形成可执行计划。
- 最后按计划为 `<method>` 构建 recent-2y smoke/formal 方法数据集，训练或构建 source artifact，并完成验证。

强约束：
- 构建和训练只能使用 recent-2y train-visible 数据与 train-only governance。
- 不得使用 holdout/valid/test/LOPO/oracle/eval label 作为候选生成或训练输入。
- smoke 只验证链路，不得宣称正式效果。
- formal 才能作为正式方法效果评估依据。
- 默认不允许 ranking_input_replacement，不允许 pool1000 自动晋升。
- 本地命令必须使用项目默认 .venv。
- 凡是会明显耗费 CPU、内存、磁盘 I/O、GPU、网络传输或长时间运行的程序，都优先使用 server 远程服务器执行；远程完成后拉回 manifest、stats、评估报告和必要 artifact 本地复核。本机只做轻量 smoke、配置/文档更新、小规模 schema 校验和必要 focused tests。

完成/停止条件：
- 完成 SciOMC 调查文档、RALPLAN 执行计划、smoke/formal 数据集、source artifact、评估报告、方法文档和配置更新后，才算该单方法 goal 完成。
- 如果 formal 指标、数据质量、资源成本或 route gate 证据不足，不要强行晋升 READY；应保持 DIAGNOSTIC_ONLY / DEFERRED，并写清原因和下一步。
- 单方法完成不等于自动进入主路；是否并入主路留给全局主路收口 goal 判断。

请先输出你对 `<method>` 当前状态、风险和调查问题的理解，然后开始 SciOMC 调查。
```

---

## 8. 完成标准

这里的“完成”分为两层：

- 单方法完成：该方法已经完成 recent-2y 调查、计划、smoke/formal 数据集、source artifact、评估和文档配置更新。
- 主路并入完成：该方法已经通过全局 route gate，被允许进入 pool500 主路候选生成。

一个方法窗口只有同时满足以下条件，才算单方法完成：

1. 已有 SciOMC 调查文档。
2. 已有 RALPLAN 执行计划。
3. smoke dataset 构建成功并通过 schema/path/gate 验证。
4. formal dataset 构建成功，manifest 记录完整 lineage 和过滤规则。
5. 训练型方法完成训练或明确停止原因；非训练型方法完成 source index / 统计构建。
6. 评估报告给出 Recall@K、覆盖、候选数、用户桶分层等与方法相关的指标。
7. 明确当前 readiness：READY / DIAGNOSTIC_ONLY / DEFERRED。
8. 更新方法文档和配置。
9. 如果产生重要工程结论，更新 `dic/ENGINEERING_NARRATIVE_LOG.md`。
10. 没有把旧 full-data artifact、oracle label 或 smoke 结果误晋升为正式结论。
11. 如果建议并入主路，必须明确列出主路并入证据；如果证据不足，应保持 DIAGNOSTIC_ONLY / DEFERRED，并写清下一步。

---

## 9. 面试叙事口径

这轮工作可以统一讲成：

> 数据基础从旧 full-data 切换到 recent-2y 后，不能直接复用旧召回产物。于是我把召回系统重建成“方法特化的数据治理 + smoke/formal 双层验证”流程：每种召回方法先调查最佳实践，再按方法特点定制训练/构建数据集，最后用 train-only governance、manifest lineage、资源门禁和分层指标验证效果。这样不仅能让不同召回方法发挥各自优势，也避免了数据泄漏、旧 artifact 回流和用诊断结果冒充正式效果的问题。
