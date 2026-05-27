# 工程叙事日志

本文档用于记录本项目中具有复盘价值的工程过程，目标是把开发、调试、优化和验证过程沉淀成适合面试表达的中文材料。

记录重点不是流水账，也不是私有思维链，而是可验证的工程叙事：问题是什么、如何定位、为什么这样解决、如何证明有效、面试时怎么讲。

## 记录原则

- 默认使用中文。
- 每条记录保持简洁，优先写事实和证据。
- 引用具体文件、命令、测试、指标或输出路径。
- 不记录无意义的中间尝试，不堆 raw log。
- 简单机械修改不需要单独记录。

### 2026-05-26 - 推荐 Agent 内部工具 schema 与灵活查库能力

**任务：**
把推荐 Agent 的后台能力从简单 manifest 推进到更接近 Claude Code Tool 思路的 internal tool spec，并实现一个能处理“这件太贵了，找更便宜但类似商品”的灵活商品库约束检索工具。

**遇到的问题：**
如果为每种导购需求单独做工具，会很快膨胀成 `find_cheaper_item`、`find_similar_item`、`find_better_rating_item` 等大量分支；但只做简单关键词搜索又无法表达相对价格、同类相似、品牌排除、required/preferred/disliked keyword 等真实对话需求。首次独立 code review 还发现价格缺失、默认类目/品牌约束、required keyword 放宽等硬约束语义存在风险。

**定位方式：**
围绕 `rs_core/rsagent/tools.py` 和新增 `tests/test_agent_tools.py` 做 focused review：用“参考商品更便宜替代品”“默认类目过滤”“品牌/店铺不同”“required keyword 不可放宽”“preferred keyword 可放宽”等用例验证约束语义；独立 reviewer 对 missing price、category/brand default mode、keyword relaxation 和 schema name mismatch 做阻塞检查。

**解决方式：**
在 `rs_core/rsagent/tools.py` 中新增 `AgentToolSpec`、`UnderstandUserNeedInput/Output`、`DisplayResponseDraft`、`ProductSearchRequest`、`PriceConstraint`、`KeywordConstraint`、`CategoryConstraint`、`RatingConstraint`、`BrandConstraint` 和 `CatalogConstraintSearchOutput` 等内部 schema；`AGENT_TOOL_MANIFEST` 固定六个核心工具：`understand_user_need`、`rerank_for_browsing`、`match_specific_need_in_pool`、`catalog_constraint_search`、`build_product_reasoning`、`compose_shopping_response`。实现 `catalog_constraint_search` 的规则版，支持参考商品、相对价格、同类过滤、关键词正反向、品牌/店铺排除、soft constraint relaxation 和 grounded match reasons；修复 review 发现的硬约束问题，确保缺价商品不会通过“更便宜”筛选，required keyword 不被放宽。

**验证结果：**
使用项目默认 `.venv` 运行 `tests/test_agent_tools.py tests/test_agent_capability_manifest.py tests/test_serving_smoke.py tests/test_display_contract.py -q`，结果 `49 passed in 0.93s`；ruff 检查 `rs_core/rsagent/tools.py tests/test_agent_tools.py tests/test_agent_capability_manifest.py` 为 `All checks passed!`。独立 code review 复核后确认此前 HIGH 阻塞均已解决；剩余 schema-name 提醒已通过新增本地 dataclass 和 grep 当前 manifest 消除。

**面试可讲点：**
这段可以讲成“把推荐 Agent 的工具系统做成少量工具 + 灵活约束 schema”：不把工具暴露给用户，也不急着 MCP/skill 化，而是在 Python 内部建立 ToolSpec、输入输出契约和可测试的 catalog constraint search。这样既能支持自然导购里的相对需求（更便宜、类似、不同品牌），又能守住候选/商品真实性、解释 grounding 和 public payload 防泄露边界。

### 2026-05-26 - pool500 主路 fallback 补满与配比边界修复

**任务：**
在已固定 pool500 召回主路配比后，修复 hot7/warm3 10 用户评估中候选池 underfill 的问题，让个性化召回不足 500 时能由兜底链路补满，同时不使用 valid/test label 或 oracle 注入。

**遇到的问题：**
主路初次评估虽然启用了 fallback，但 10 个用户只有 2 个达到 500，`underfilled_user_count=8`，fallback 审计只出现 `fallback_seed_category_sibling` 和 `fallback_seed_metadata_neighbor`。进一步修完全局 popular 生成器后仍未补满，原因是主路在 fallback 后又执行 `category/popular <= 175` 的硬裁剪，把兜底补进去的候选再次裁掉。

**定位方式：**
先看 `fallback_completion_audit.json`、`source_audit.json` 和 `fallback_completion_resource_audit.json`，确认全局 popular 资源存在但未进入最终池；再审计 `rs_lab/experiments/recall/pool500/fallback_completion/sources.py`、`rs_core/recsys/recall/merge.py` 和 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py`，定位到全局 popular 的类目多样性前缀会因去重提前耗尽，以及 fallback 后二次 `_enforce_popular_category_cap` 会破坏“兜底补满 500”的设计。

**解决方式：**
调整 `fallback_global_diversity_popular`：先按类目多样性优先产出，再用 deferred rows 回填，避免真实 popular 前 2000 行类目集中时被生成器提前截断；同时把 `category/popular` 上限限定在 fallback 前的主路配比阶段，fallback 后不再二次裁剪，让 `category/popular` 真正作为最后兜底补满低供给用户。

**验证结果：**
使用项目默认 `.venv` 运行 `tests/test_full_data_pool500_recall_only.py tests/test_pool500_fallback_completion_route.py`，结果 `26 passed in 1.00s`。重跑 `outputs/eval/pool500_current_route_hot7_warm3_10users_20260526.py` 后，`source_audit.json` 显示 `candidate_row_count=5000`、`average_candidates_per_user=500.0`、`underfilled_user_count=0`、`duplicate_user_item_count=0`；`fallback_completion_audit.json` 显示 `users_with_target_candidates=10`、`underfilled_user_count=0`、`average_fallback_ratio=0.4178`。召回指标仍为 `Recall@500=0.0`，说明本次修复解决的是候选池完整性和主路兜底能力，不把补满误宣称为效果提升。

**面试可讲点：**
这段可以讲成“推荐召回主路的低供给兜底治理”：先用 hot/warm 小样本暴露候选池 underfill，再从资源审计、生成器、merge 和主路 cap 多层定位；最终把上层个性化配比和底层冷启动/低历史兜底解耦，保证排序前每个用户有稳定 500 候选，同时守住 no-oracle、no-promotion 和 ranking input replacement 边界。

### 2026-05-26 - Agent RAG 结构占位与边界收口

**任务：**
在不实现完整 RAG、不改变召回排序结果的前提下，先为后续商品知识检索和 Agent grounding 放好代码位置与文档边界。

**遇到的问题：**
当前还没有独立外部文档库，如果直接把 RAG 做成新召回源或让模型自由补商品卖点，容易混淆“候选生成”和“解释 grounding”，也可能形成 oracle/label 注入式的伪效果。

**定位方式：**
核对 `rs_core/recsys/vector_index.py`、`rs_core/rsagent/explanation.py`、`rs_core/rsagent/schema.py`、`dic/architecture/IMPLEMENTATION_PLAN.md` 和 `dic/PROJECT_STRUCTURE.md`，确认现有 Phase 4 已把 RAG 定位为 Agent 增强层，而不是召回主路。

**解决方式：**
新增 `rs_core/recsys/rag/`，只定义 `RagEvidence`、`RagContext` 和 `build_empty_rag_context`，作为商品知识证据 contract；在 `AgentTurn` 预留默认关闭的 `rag_context` 字段，`None` 时不改变现有序列化输出；文档中明确 RAG 负责商品知识上下文和解释证据，不直接参与召回、排序或候选集合决策。

**验证结果：**
使用项目默认 `.venv` 运行 `py_compile rs_core/recsys/rag/__init__.py rs_core/recsys/rag/schema.py rs_core/recsys/rag/context.py rs_core/rsagent/schema.py` 通过；focused tests `tests/test_agent_feedback.py tests/test_agent_dialogue.py tests/test_display_contract.py -q` 结果 `37 passed in 0.31s`。额外尝试跑 `tests/test_hybrid_demo.py` 时有 3 个旧配置路径缺失失败，集中在 `configs/phase_1_15_*.yaml`、`configs/phase_1_17_rank_weight_*.yaml` 和 `configs/hybrid_demo_electronics_10000_*_two_tower_*.yaml` 的历史路径断言，不属于本次 RAG 改动引入。

**面试可讲点：**
这段可以讲成“先定义 RAG 的工程边界，而不是急着堆向量库”：推荐结果仍由受治理的候选池和排序链路产生，RAG 只提供商品知识证据、解释 grounding 和幻觉控制入口，后续再逐步讨论 item knowledge card、候选内检索和评估门禁。

### 2026-05-26 - Agent RAG SQLite BM25 第一版可用化

**任务：**
把前一版候选卡片证据选择器扩展为最小可用的经典检索 RAG：支持商品字段 chunk、SQLite FTS5/BM25 建库，并通过 `rag.index_path` 接入 Agent 解释链路。

**遇到的问题：**
如果直接把 BM25 做成新的召回源，会破坏“推荐候选由召回/排序决定，RAG 只负责解释证据”的边界；同时完整向量库、服务化索引和复杂 chunk pipeline 对当前 demo 过重。

**定位方式：**
沿用 `rs_core/recsys/rag/`、`rs_core/workflow/hybrid_environment.py` 和 `rs_core/rsagent/explanation.py` 的既有边界，只检查 RAG 是否在候选 item 范围内取证、是否保留 provenance gate、是否不修改 `candidates` / `ranking` / `final_items` / `scores`。

**解决方式：**
新增 `chunking.py` 与 `bm25.py`：title/category/summary 保持短字段整体 chunk，description 按句子和长度切分，features 按 bullet 切分；`build_sqlite_bm25_index()` 写入 `rag_chunks` 与 `rag_chunk_fts`，`SQLiteBM25CandidateRetriever` 在候选 item id 范围内执行 FTS5 MATCH + BM25 排序。Agent 配置中如存在 `rag.index_path` 或 `rag.bm25_index_path` 且文件存在，则使用 SQLite BM25；否则回退原有 in-memory candidate card retriever。

**验证结果：**
使用项目默认 `.venv` 运行 `py_compile rs_core/recsys/rag/chunking.py rs_core/recsys/rag/bm25.py rs_core/recsys/rag/retriever.py rs_core/recsys/rag/__init__.py rs_core/workflow/hybrid_environment.py tests/test_rag_core.py` 通过；`pytest tests/test_rag_core.py -q` 结果 `7 passed in 0.28s`；`pytest tests/test_agent_dialogue.py tests/test_display_contract.py -q` 结果 `35 passed in 0.35s`。随后补充 `scripts/recall/build_rag_bm25_index.py` 建库入口，`pytest tests/test_rag_core.py -q` 更新为 `8 passed in 0.22s`；真实小批命令生成 `outputs/agent/rag_bm25_demo.sqlite`，manifest 显示 `indexed_item_count=16753`、`chunk_count=33276`、`candidate_scoped=true`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`。

**面试可讲点：**
这段可以讲成“用轻量 BM25 把 RAG 从字段注入推进到可检索证据层”：不引入重依赖，不让 RAG 改推荐结果，只在已有候选池内通过 SQLite FTS5 找最相关的商品证据，再交给 Agent 做解释 grounding。

### 2026-05-26 - Agent RAG Hybrid 检索第一版

**任务：**
在候选内 BM25 RAG 的基础上补充 Hybrid 检索方式，让证据选择同时参考关键词匹配和轻量向量相似度。

**遇到的问题：**
直接引入外部 embedding 模型、FAISS 或新的召回源会扩大工程范围，也容易让 RAG 从解释证据层越界成候选生成层；但只用 BM25 又对同义表达和近似文本不够友好。

**定位方式：**
复查 `rs_core/recsys/rag/bm25.py`、`rs_core/recsys/rag/retriever.py` 和 `rs_core/workflow/hybrid_environment.py`，确认可在现有 SQLite `rag_chunks` 表上增加第二路分数，并继续复用 `build_rag_context_for_ranked_candidates()` 的候选池过滤、字段过滤和 provenance gate。

**解决方式：**
新增 `rs_core/recsys/rag/hybrid.py`：BM25 分支复用 `SQLiteBM25CandidateRetriever`，向量分支对 query 和候选 chunk 文本构造 deterministic hashed text vector 并计算 cosine，相同 `(item_id, field, text)` 的 evidence 做 min-max 归一化后按 `bm25_weight` 与 `vector_weight` 融合。`rag.retriever=hybrid` 且 `rag.index_path` 存在时启用 Hybrid，否则保留 BM25 或 in-memory fallback；建库 manifest 增加 `hybrid_supported=true` 和 `hybrid_vector_method=hashed_text_vector_v1`。

**验证结果：**
使用项目默认 `.venv` 运行 `py_compile rs_core/recsys/rag/hybrid.py rs_core/recsys/rag/bm25.py rs_core/recsys/rag/retriever.py rs_core/recsys/rag/__init__.py rs_core/workflow/hybrid_environment.py scripts/recall/build_rag_bm25_index.py tests/test_rag_core.py` 通过；`pytest tests/test_rag_core.py -q` 结果 `10 passed in 0.45s`；`pytest tests/test_agent_dialogue.py tests/test_display_contract.py -q` 结果 `35 passed in 0.39s`。真实小批索引重建后 manifest 显示 `indexed_item_count=16753`、`chunk_count=33276`、`hybrid_supported=true`，且 `ranking_input_replacement_allowed=false`、`promotion_allowed=false`。

**面试可讲点：**
这段可以讲成“先用无重依赖 Hybrid 验证 RAG 融合检索边界”：BM25 负责精确词命中，hashed vector cosine 补充近似文本相似度，融合只影响 Agent 解释证据，不影响推荐候选池和排序；后续如果要接真实 embedding，只替换向量分支即可。

### 2026-05-26 - pool500 全召回源主路接入与排序 shadow 诊断

**任务：**
确认 TwoTower formal full 产物可用后，把当前已完成的 pool500 召回源全部接入 recall-only 主路，并做最小排序侧 shadow 调整。

**遇到的问题：**
召回主路 5 用户 smoke 已能生成完整 2500 行候选，但排序 fixed comparison 一开始被 gate 拦截；blocker 不是排序算法失败，而是召回主路 `manifest.json` 顶层缺少 `ranking_replacement_allowed=false` 和 `promotion_allowed=false`，无法证明排序诊断不替换线上输入、不做 promotion。独立 review 还发现 TwoTower source manifest 与 full derived index audit 需要显式保留 `ranking_replacement_allowed=false`，并且 audit 应记录真实 `index_path` 而不是退回 source manifest 路径或旧 `recall_index` 元数据。

**定位方式：**
读取 `outputs/recall/full_data_pool500_recall_only_all_sources_smoke_20260526/manifest.json`、`source_contribution_audit.json`、`full_derived_index_manifests.json` 和排序 fixed comparison blocker，确认 all-source 候选生成成功：`candidate_rows=2500`、`underfilled_user_count=0`，实际贡献包括 category、semantic、semantic_title_category_expansion、co_visit_fallback_repair、itemcf_weak、itemcf_strong、swing_recall、two_tower；usercf artifact 已加载但该 5 用户样本无命中。

**解决方式：**
在 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 的主 manifest、recall config、readiness/audit 透传中补齐 no-ranking-replacement/no-promotion 字段；在 `rs_core/recsys/two_tower_source_manifest.py` 和 `scripts/recall/build_two_tower_source_index.py` 中把 `ranking_replacement_allowed=false` 纳入 TwoTower source index 生成与校验；排序侧将 D2 shadow-only top-k source minimums 扩展到 itemcf、semantic、semantic_title_category_expansion、two_tower、usercf_recall、swing_recall、category；同时让 full derived index audit 优先使用 source manifest 顶层 `index_path`。

**验证结果：**
使用项目默认 `.venv` 运行 `tests/test_pool500_two_tower_source_manifest.py tests/test_full_data_pool500_recall_only.py tests/test_pool500_shadow_ranking.py`，结果 `135 passed in 2.06s`；重新跑 5 用户 all-source smoke，输出 `candidate_rows=2500`、`underfilled_user_count=0`，顶层 `ranking_replacement_allowed=false`、`promotion_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`；随后生成 `pool500_fixed_ranking_comparison_report.json`，fixed configs `B0/D1/D2/A1/A2/R1/R2/R3` 全部通过，报告 `status=PASS`、`blocker_count=0`，D2 top-k mix 覆盖 category、co_visit、itemcf、popular、semantic、semantic_title_category_expansion、swing、two_tower。独立 reviewer 复核后确认无剩余 HIGH/MEDIUM governance 问题。

**面试可讲点：**
这段可以讲成“从多召回源接入到排序诊断的治理闭环”：不仅证明多路召回能填满 pool500，还把模型源、规则源、协同过滤源统一进 frozen candidate pool；排序优化先以 shadow fixed comparison 观察机制差异，不急于宣称 READY 或替换线上输入，用 manifest contract、gate blocker 和独立 review 防止 diagnostic 产物越权晋升。

### 2026-05-26 - TwoTower 工业化训练采样优化

**任务：**
按 YouTubeDNN/DSSM 工业实践优化双塔训练样本生成和负采样策略，目标是提升 validation/test 泛化召回，而不是继续复用已有效果较差的 formal artifact。

**遇到的问题：**
此前双塔已经修复了 label 泄漏和在线投影一致性，但 100 用户 raw eval 仍 `hit_at_500=0`，说明问题不只是在线检索路径，而是训练阶段样本分布和负采样过弱：高活跃用户可贡献过多样本，均匀随机负采样难以让模型学会区分真实偏好与全局热门，低活用户/低频 item 也会带来稀疏噪声。

**定位方式：**
审计 `rs_core/recsys/two_tower.py` 的 PyTorch batch 生成、负采样和 fallback 训练逻辑，以及 `rs_core/workflow/two_tower_training.py` 的训练配置入口和 item vocab manifest 读取路径，确认当前只有非对称时序分割，缺少 per-user 样本上限、popularity-power negative sampling 和 K-Core 训练参数默认透传。

**解决方式：**
在 `_torch_example_batches` 引入 `max_samples_per_user`，每个用户只保留最近的有限个时序样本，且所有样本保持 `history=positives[:offset]`；训练前统计 item 频次，按 `frequency ** 0.75` 构造负采样分布并用于 `_negative_indices`，fallback 路径也同步使用流行度加权负样本；workflow 默认补齐 `min_user_positives=3`、`max_samples_per_user=5`、`negative_sampling_power=0.75`，item vocab CLI 默认 `--min-freq=3`，并把相关参数写入 metrics/model payload。

**验证结果：**
使用项目默认 `.venv` 运行 `tests/test_two_tower_training.py -q`，结果 `19 passed in 5.62s`；补跑 `tests/test_recsys_core.py tests/test_full_data_pool500_recall_only.py tests/test_two_tower_source_manifest_guard.py tests/test_pool500_two_tower_method_source.py -q`，结果 `38 passed in 1.58s`；补跑 `tests/test_pool500_two_tower_diagnostic_loop.py -q`，结果 `20 passed in 0.43s`；`py_compile` 检查 `rs_core/recsys/two_tower.py`、`rs_core/workflow/two_tower_training.py`、`scripts/recall/build_two_tower_item_vocab.py` 通过。随后用新策略跑 200 用户 diagnostic training：`training_examples=644`、`users_with_training_rows=197`、`negative_samples=5`、`max_samples_per_user=5`、`min_user_positives=3`、`negative_sampling_power=0.75`，训练内 `recall@100=0.401026`、`hit_rate@100=0.945`；但固定 100 用户 evaluation-only raw eval 仍为 `hit_at_20/50/100/500=0`、`raw_two_tower_unique_positive_hits=0`，说明小规模采样优化尚未转化为 valid/test 命中。

**面试可讲点：**
这段可以讲成“从修泄漏转向优化训练分布”：用户样本均衡解决高活用户支配，非对称时序保证因果训练，流行度加权负采样让模型学习热门商品中的真实偏好差异，K-Core 过滤降低稀疏噪声，是推荐召回模型从可运行到可泛化的关键工程步骤。

### 2026-05-26 - TwoTower 训练泄漏修复与在线用户塔投影

**任务：**
修复 TwoTower/YouTubeDNN 训练样本历史包含当前 label 的泄漏问题，并把在线召回从静态 user embedding 查询切换为实时历史 seed 经 User Tower 投影后的向量检索。

**遇到的问题：**
原 `_torch_example_batches` 在第一个正样本无历史时会回退到完整 positives，导致当前目标和未来正样本进入 history；在线召回路径还会优先使用训练产出的静态 user embedding，在 LOPO/固定评估用户场景下可能混入未来行为表征。切换到实时历史后，一个旧测试暴露出 tiny fixture 只用唯一 seed 且该 seed 被已见集合排除，无法再保证返回候选。

**定位方式：**
对照 `rs_core/recsys/two_tower.py` 的滑窗样本生成、`rs_core/recsys/vector_index.py` 的 artifact/source manifest 加载、`rs_core/recsys/candidate_merge.py` 的 TwoTower 向量召回，以及 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 的批量预计算路径，确认静态 user embedding 和在线 batch path 都需要收口到同一实时历史逻辑。

**解决方式：**
训练侧跳过第一个无历史正样本，并保证 `history = positives[:offset]` 不包含当前 target；向量索引加载和 source index manifest 写入 `model_parameters`；在线召回强制用 `recent_positive_item_sequence` 的 seed item 平均向量，经过 `user_tower.0/2` 权重执行 `Linear -> ReLU -> Linear -> Residual Add -> Normalize` 投影后检索，并让主路 `_precompute_two_tower_recall` 复用同一函数，避免批量路径绕过治理。

**验证结果：**
使用项目默认 `.venv` 运行 `tests/test_two_tower_training.py tests/test_recsys_core.py tests/test_full_data_pool500_recall_only.py -q`，结果 `45 passed in 3.86s`；补跑 `tests/test_two_tower_source_manifest_guard.py tests/test_pool500_two_tower_method_source.py -q`，结果 `10 passed in 0.77s`；补跑 `tests/test_pool500_shadow_ranking.py -q`，结果 `110 passed in 1.03s`。回归测试覆盖了 label 泄漏修复、`model_parameters` 加载、实时历史优先于静态 user embedding、User Tower 投影生效，以及主路预计算路径的一致性。

**面试可讲点：**
这段可以讲成“双塔召回的数据泄漏与线上一致性治理”：不仅修了训练样本目标泄漏，还把评估/在线召回从静态用户向量改为实时行为 seed 投影，保证训练目标、检索空间和 LOPO 评估边界一致，同时用单测和主路相关测试证明没有破坏 pool500 排序入口。

### 2026-05-26 - TwoTower formal full 远端训练产物接入主路

**任务：**
把远端 RTX 4090 完成的 TwoTower/YouTubeDNN formal full train-only artifact 拉回本地，重建 pool500 主路 `source_index_manifest.json`，并验证它能真实进入 recall-only 候选池。

**遇到的问题：**
远端训练产物可以被主路加载并产出候选，但首次 smoke 的 final readiness contract 仍出现 TwoTower blocker：source index manifest 缺少 full-clean gate 需要的 `item_embedding_row_count`、`recall_index_row_count`、clean/train/config/item universe hash，同时 gate 把算法名 `two_tower_youtube_dnn` 误当成非 canonical source 拦截。

**定位方式：**
先读取 `outputs/recall/pool500_recall_only_smoke/two_tower_remote_formal_1user_20260526/` 的 source manifest、source contribution audit 和 final readiness contract，确认 `two_tower.row_count=30`、已进入 500 行候选池，但 blocker 集中在 TwoTower full-clean 字段和别名校验；再对照 `full_data_pool500_route_gate.py` 和 `build_two_tower_source_index.py`，确认 source index 只写了通用 row count，未写 gate 所需字段别名和 hash 证据。

**解决方式：**
扩展 `scripts/recall/build_two_tower_source_index.py`，在重建 source index 时可显式接收 formal config、clean manifest、train sequence，并写入 `item_embedding_row_count`、`recall_index_row_count`、`clean_manifest_sha256`、`train_sequence_sha256`、`model_config_sha256`、`item_universe_sha256`；同时在 `rs_core/workflow/full_data_pool500_route_gate.py` 中使用 canonical source alias 校验 `two_tower_youtube_dnn`，并避免把 `source_name/variant/model_type` 这类算法标签误判为 forbidden artifact scope。

**验证结果：**
重建后的 `outputs/recall/pool500_full_sources/two_tower/index/source_index_manifest.json` 显示 `row_count=268816`、`item_embedding_row_count=268816`、`recall_index_row_count=268816`、`user_embedding_row_count=16639746`，并包含 clean/train/config/item universe hash。focused tests `tests/test_two_tower_source_manifest_guard.py tests/test_pool500_two_tower_source_manifest.py tests/test_pool500_two_tower_method_source.py tests/test_full_data_pool500_recall_only.py -q` 结果 `35 passed in 1.77s`。1 用户主路 smoke 生成 `pool500_rows=500`，TwoTower source 输出 `two_tower_rows=30`，`two_tower_manifest_status=READY`、`two_tower_index_status=INDEX_READY`、`two_tower_index_scope=FULL_DERIVED_INDEX`，final readiness 中 `two_tower_blocker_count=0`；整体仍保持 `decision=STOP`、`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`，没有越过主路晋升边界。

**面试可讲点：**
这段可以讲成“模型训练产物从算力迁移到主路接入的治理闭环”：不仅把远端 GPU 训练出的全量 embedding/index 拉回本地，还补齐 manifest 证据、哈希追溯和 readiness gate，证明模型召回源能贡献候选，同时不会因为单个 source 接入就误宣称全链路 READY 或替换 ranking 输入。

### 2026-05-26 - TwoTower 10 epoch direct eval 与增训取舍

**任务：**
在 5 epoch formal full TwoTower 已接入 pool500 主路后，远端继续训练 10 epoch，并用同一组 10k fixed eval 用户做 TwoTower direct-only 效果评估，判断单纯增加 epoch 是否带来提升。

**遇到的问题：**
完整 pool500 runner 会混入多召回源和 fallback，不适合回答“两塔本身有没有提升”；同时首次自动 watcher 在构建 10 epoch source index 时传入了远端不存在的可选 `train_sequence` hash 路径，导致训练已完成但后续索引构建失败。

**定位方式：**
读取后台输出 `b8ntibd8l.output`，确认失败点是 `FileNotFoundError: .../training/user_sequences.train.jsonl`，不是训练失败；随后去掉可选 hash 参数，重新执行 `scripts/recall/build_two_tower_source_index.py` 和 `rs_lab/experiments/recall/run_pool500_two_tower_direct_eval.py`，评估输入限定为 train sequence + TwoTower recall index，valid/test labels 只用于打分。

**解决方式：**
保留 5 epoch 主路接入不变，单独为 10 epoch run 构建 `outputs/recall/pool500_full_sources/two_tower/index/twotower_formal_full_10epoch_20260526_1115/source_index_manifest.json`，再输出 direct eval manifest：`outputs/recall/pool500_full_sources/two_tower/index/twotower_formal_full_10epoch_20260526_1115/direct_eval_10k_manifest.json`。评估 manifest 明确 `eval_scope=two_tower_direct_only`、`no_oracle_label_injection=true`。

**验证结果：**
10 epoch source index `row_count=268816`，direct eval 覆盖 `user_count=10000`、`query_user_count=8709`、`queryless_user_count=1291`。10 epoch 指标为 `Recall@20=0.005608`、`HitRate@20=0.0104`、`Recall@50=0.009906`、`HitRate@50=0.0183`、`Recall@100=0.017034`、`HitRate@100=0.0306`、`Recall@500=0.04869`、`HitRate@500=0.0819`；低于 5 epoch baseline `Recall@500=0.051552`、`HitRate@500=0.0948`。结论是单纯从 5 epoch 加到 10 epoch 没有提升，下一步不应盲目跑 15 epoch，应优先诊断样本口径、queryless 用户、item universe 和召回目标分布。

**面试可讲点：**
这段可以讲成“模型增训不是越久越好，而要用一致评估口径做 stop-loss”：把 TwoTower 从主路混合召回中拆出来 direct eval，避免 fallback 或其他召回源掩盖模型真实变化；当 10 epoch 低于 5 epoch 时，用证据及时停止盲目加算力，转向数据分布和泛化误差诊断。

### 2026-05-26 - ItemCF strong relaxed seed-src 数据口径与主路验证

**任务：**
把原本几乎不可用的 `itemcf_strong` 从 strict 高置信稀疏矩阵调整为仍偏 strong、但能在 pool500 主路产生稳定贡献的 relaxed diagnostic source。

**遇到的问题：**
strict strong formal 只有 208 条方向边；初版 relaxed strong 即使放宽到 support=1，也只有 56,518 条边，前 100 用户 strong seed 与 source `src_item_id` 仍 0 命中，主路贡献为 0。说明问题不只是边数少，而是 strong 查询 seed 与构建矩阵的 item/user 过滤口径不匹配。

**定位方式：**
先用 seed-hit audit 证明 `source_src_item_count=40629` 但 `strong_seed_hit_count=0`；再统计前 100 用户 strong seed 的质量桶和热度，发现 179 个 unique seed 中 178 个是 hot，且大多是 `embedding_ready`。进一步审计 allowed user 的 positive sequence，确认如果 dst 只允许 `cf_ready`，大多数 strong seed 没有可连接候选。

**解决方式：**
在 `rs_lab/experiments/recall/build_pool500_method_dataset.py` 为 `itemcf_strong` 新增 relaxed seed-src v3 口径：用户仍限制在 `sequence_sufficient/collaborative_rich`，构边改为 `recent_strong_positive_item_sequence -> recent_positive_item_sequence` 的有向边；src strong seed 允许 `cf_ready/embedding_ready` 且允许 hot，dst candidate 允许 `cf_ready/embedding_ready` 但排除 hot，并继续使用 train-only、active-user penalty、weighted cooc cosine score、topK per seed。source 转换使用 128 shard，避免主路一次加载 153 万边。

**验证结果：**
focused 单测 `tests/test_pool500_method_dataset.py` 结果 `23 passed`。v3 smoke method_dataset 输出 `outputs/recall/pool500_method_datasets/itemcf_strong_relaxed_seedsrc_smoke_v3/itemcf_strong/`，`row_count=1,536,320`、`unique_pair_count=1,563,717`、`directed_edge_count_after_topk=1,536,320`，前 100 用户 strong seed 命中恢复到 `149/179`。sharded source 输出 `outputs/recall/pool500_method_sources/itemcf_strong_relaxed_seedsrc_v3_from_method_dataset/itemcf_strong/smoke_sharded/source_index_manifest.json`，`row_count=1,536,320`、`shard_count=128`、`diagnostic_only=true`。100 用户主路 smoke 中 `itemcf_strong.row_count=1,557`、`user_coverage_count=68/100`、`marginal_candidate_share=0.033384`；500 用户受控验证中 `itemcf_strong.row_count=8,198`、`user_coverage_count=369/500`、`marginal_candidate_share=0.03469`。两次 `final_resource_audit.status=PASS`，`promotion_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。

**面试可讲点：**
这段可以讲成“按方法特性调数据口径，而不是盲目放宽过滤”：strong seed 本身常是高热强交互商品，适合作为查询锚点，但不适合直接作为候选输出。因此把 hot 仅放在 src 侧、dst 侧继续排除 hot，在保持 high-confidence/diagnostic 边界的同时恢复主路贡献，体现了推荐召回中 seed 侧与 candidate 侧不同治理策略的工程判断。

### 2026-05-26 - ItemCF strong 三档独立重建与 formal 分片接入

**任务：**
把 relaxed seed-src v3 从单个 formal-like 产物整理成 smoke、diagnostic、local_formal 三档真实数据集，并使用 local_formal 矩阵构建分片 source 接入 pool500 主路验证。

**遇到的问题：**
ItemCF 数据集不能通过从已有 formal 边表抽用户或抽边来派生小档位，因为任一用户变化都会改变 pair support、`weighted_cooc`、`itemcf_score` 和 per-seed topK。三档必须各自从 train-only 原始序列独立重建，否则 smoke/diagnostic 的统计语义不成立。

**定位方式：**
复核 `build_pool500_method_dataset.py` 的构建路径，确认每档读取的是 governance manifest、user/item profile、train item frequency 和 `user_sequences.train.jsonl`，不是读取旧 method_dataset；同时用 manifest 核对三档的 `max_output_users`、`row_count`、`user_count` 和治理 flags。

**解决方式：**
将 relaxed strong v3 参数改为 scale-tier aware：smoke `max_output_users=5000`、diagnostic `80000`、local_formal `160000`，但核心策略不变：`recent_strong_positive_item_sequence -> recent_positive_item_sequence` 有向构边，src 允许 `cf_ready/embedding_ready` 且允许 hot，dst 允许 `cf_ready/embedding_ready` 但排除 hot。local_formal 再通过 adapter 转成 128 shard source，主路按 seed 命中 shard 加载。

**验证结果：**
focused tests 与 lint 通过：`tests/test_pool500_method_dataset.py -q` 为 `24 passed`，默认主路/registry focused tests 为 `39 passed`，ruff `All checks passed!`。三档独立构建均 PASS：smoke `row_count=47615`、`user_count=5000`；diagnostic `row_count=784463`、`user_count=80000`；local_formal `row_count=1536320`、`user_count=160000`。formal sharded source 为 `outputs/recall/pool500_method_sources/itemcf_strong_relaxed_seedsrc_v3_from_method_dataset/itemcf_strong/formal_sharded/source_index_manifest.json`，`row_count=1536320`、`shard_count=128`、`diagnostic_only=true`，并已切换为 pool500 recall-only 主路默认 `itemcf_strong` source manifest。override 验证中，100 用户主路 smoke `itemcf_strong.row_count=1557`、`user_coverage_count=68/100`、`marginal_candidate_share=0.033384`；500 用户验证 `itemcf_strong.row_count=8198`、`user_coverage_count=369/500`、`marginal_candidate_share=0.03469`。默认主路无 override smoke 输出 `itemcf_strong.row_count=941`、`user_coverage_count=68/100`、`marginal_candidate_share=0.019991`，`per_source_output_manifests.json` 确认 `itemcf_strong.source_index_manifest_path` 指向 formal sharded source。三次验证 `final_resource_audit.status=PASS`，`promotion_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。

**面试可讲点：**
这段可以讲成“推荐召回数据集分层不能把聚合矩阵当可抽样明细”：对 ItemCF 这类共现统计方法，小样本档必须重新聚合而不是从大矩阵切片。最终通过三档独立重建、formal 分片和主路 contribution audit，既解决了 strong 可用性，又保住了 train-only、diagnostic-only 和非晋升边界。

### 2026-05-25 - Swing local_formal source index 与主路接入

**任务：**
为 `swing_recall` 按方法特性补齐 `smoke`、`diagnostic(dam)`、`local_formal` 三档 source index，并把 formal 版本接入 pool500 主路。

**遇到的问题：**
`swing_recall` 之前主路默认读取的是 `target_slice_diagnostic_v1`，缺少按 Swing 方法特性定义的 formal/local_formal 构建口径。Swing 需要基于 train-only 用户序列构建 item-item 共现图，同时控制活跃用户和热门 item 噪声，不能简单把旧 diagnostic 产物改名成 formal。

**定位方式：**
对照 Datawhale Swing 方法说明，确认其核心是 item-item 共现关系、共同用户证据、活跃用户降权和 TopK 相似边；再审计 `enhanced_source.py` 的现有 builder，确认它已从 clean full train sequence、eligible users 和旧 swing baseline candidates 生成七件套 artifact，并写出 coverage/resource/no-holdout audit。

**解决方式：**
在 `configs/recall/full_data_pool500/swing_recall/source_config.yaml` 增加 `smoke`、`diagnostic`、`local_formal` tiers、`dam` / `最终数据集(local_formal)` alias、train-only input contract 和 governance 边界；在统一 runner `scripts/experiments/recall/pool500/run_pool500_method_source.py` 接入 `swing_recall`，复用现有 enhanced source builder。`local_formal` 使用 `max_graph_users=120000`、`max_item_user_freq=600`、`min_pair_support=2`，更偏稳定共同用户证据。

**验证结果：**
三档构建均 `PASS`：smoke `candidate_row_count=8614`、diagnostic `candidate_row_count=39637`、local_formal `candidate_row_count=12646`；local_formal 产物路径为 `outputs/recall/pool500_method_sources/swing_recall/local_formal_swing_recall_20260525/source_index_manifest.json`，`edge_count=86748`、`seed_count=14241`、`user_coverage_count=389`、`graph_user_count=120000`、`no_holdout_status=PASS`。focused tests `31 passed`；5 用户主路 smoke 生成 2500 行候选，其中 `swing_recall=143`，final contract 保持 `final_pool500_ready_claimed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。

**面试可讲点：**
这段可以讲成“把 Swing 从诊断 source 推进到可复用 formal 召回源”：先按 Swing 的共同用户和活跃用户抑制机制定义数据层级，再用 train-only 全量序列构建稳定 item-item 边表，最后接入主路并用候选贡献、no-holdout audit 和 final contract 证明它能服务后续排序但不越过晋升边界。

### 2026-05-25 - ItemCF weak full source 分片构建与按需加载

**任务：**
把 `itemcf_weak` 的 full formal source 从单个 4.4GB JSONL 改造成可分片构建、可按 batch seed 加载的 source index；`itemcf_strong` 因 full formal 只有 208 条边，继续保持单文件默认构建。

**遇到的问题：**
`itemcf_weak` coverage formal 有 5,640,872 条方向边，直接用主路一次性加载会把 4.4GB JSONL 膨胀成大量 Python 对象，小批量验证也可能消耗 20GB 级别内存；但此前 seed-hit 诊断已证明 full weak 对目标用户有贡献，不能简单放弃该矩阵。

**定位方式：**
先用 20 用户 seed-hit 审计确认 weak full 中 17/20 用户有 seed 命中，seed-filtered 主路贡献约 487 条候选；再对比 `limit_rows=10000` shard smoke 和 full sharded smoke，确认低贡献来自截断 smoke 覆盖不足，而不是分片加载逻辑丢边。

**解决方式：**
在 `method_dataset_to_itemcf_source.py` 中新增 `--shard-count`，当 `shard_count>1` 时按 `sha256(src_item) % shard_count` 写入 `edges_shards/` 并在 manifest 记录 `sharded=true`、`shard_count`、`shard_key=src_item_sha256_mod`、每个 shard 的 row/hash/size；在 `candidate_merge.py` 新增 manifest-aware loader，根据当前 batch 的 `allowed_src_items` 只加载命中 shard；主路从用户 recent positive sequence 提取 weak/strong seed 后传给 ItemCF loader，同时保留 train-only、diagnostic-only、no promotion、no ranking replacement、no pool1000 边界。

**验证结果：**
聚焦测试 `tests/test_pool500_itemcf_method_dataset_source_adapter.py tests/test_full_data_pool500_recall_only.py` 结果 `23 passed in 0.99s`，相关模块 `compileall` 通过。full weak sharded source 输出 `outputs/recall/pool500_method_sources/itemcf_formal_from_method_dataset_v1/itemcf_weak/sharded_full_v1/source_index_manifest.json`，`row_count=5,640,872`、`shard_count=256`、`edges_path=null`。20 用户主路 smoke 输出 `itemcf_weak.row_count=494`、`user_coverage_count=16/20`、`marginal_candidate_share=0.051165`；100 用户 smoke 输出 `itemcf_weak.row_count=2112`、`user_coverage_count=69/100`、`marginal_candidate_share=0.045021`，`final_resource_audit.status=PASS`，全链路仍保持 `promotion_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。

**面试可讲点：**
这段可以讲成“把大规模协同过滤矩阵从能产出推进到可服务化消费”：先证明 full weak 矩阵确实能为用户补候选，再针对 4.4GB JSONL 的内存瓶颈做 src_item hash 分片和 batch seed 按需加载，让小批量/后续主路验证不用全量加载矩阵，同时用 manifest/audit 保证诊断产物不会被误晋升为正式 ranking 输入。

### 2026-05-25 - pool500 三个 local_formal source index 接入主路

**任务：**
把 `semantic`、`semantic_title_category_expansion`、`co_visit_fallback_repair` 三份已生成的 `local_formal` source index 接入 pool500 主路 recall-only 实验，让主路默认可读取并合并三类候选。

**遇到的问题：**
三份 source index 已经可调用，但如果只按文件存在自动标记，会把 diagnostic/local_formal 证据误写成 `READY`；同时 canonical `semantic` 必须独立进入主路，不能被 `semantic_title_category_expansion` 代替，`co_visit_fallback_repair` 也不能被误解为完整 co-visit graph。

**定位方式：**
审计 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 的默认 source manifest、fill order、pregenerated recall 加载、readiness contract 与 full derived index manifest 写入路径，并补充 `tests/test_full_data_pool500_recall_only.py` 回归锁定默认路径、source identity、非 READY 状态和 co_visit v0 字段。

**解决方式：**
主路默认 manifest 指向 `local_formal_semantic_20260525`、`local_formal_semantic_title_category_20260525`、`local_formal_co_visit_repair_20260525`；新增 canonical `semantic` 的 pregenerated recall 合并入口，把 `semantic` 加入 fill order 但不加 minimum；对 deferred diagnostic source 即使 index 文件存在也保持 `BATCH_SCOPED_DIAGNOSTIC`，并透传 no-promotion/no-ranking-replacement/no-pool1000、`algorithm_scope`、`complete_co_visit_graph_claimed` 等治理字段。

**验证结果：**
使用项目默认 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_recall_only.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_phase_1_21_recall_coverage.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_method_source_runner.py`，结果 `53 passed, 2 warnings`。随后运行 5 用户主路 smoke，输出 `pool500_candidates.jsonl` 共 2500 行，三类新 source 均进入候选：`semantic=563`、`semantic_title_category_expansion=360`、`co_visit_fallback_repair=597`；三者 readiness 与 full derived index status 均为 `BATCH_SCOPED_DIAGNOSTIC`，`semantic.canonical_source=semantic`，co_visit 保留 `algorithm_scope=train_transition_metadata_repair_v0` 与 `complete_co_visit_graph_claimed=false`，final contract 继续保持 `final_pool500_ready_claimed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。

**面试可讲点：**
这段可以讲成“把召回方法产物接入主路但不越过治理边界”：既让真实候选进入 recall merge、可被后续排序/Agent 使用，又用 readiness contract 和 manifest 字段防止 diagnostic source 被包装成 READY 或正式晋升，体现推荐系统实验主路接入中的效果验证与风险隔离。

### 2026-05-25 - pool500 三方法 local_formal source index 生成

**任务：**
为 `semantic`、`semantic_title_category_expansion`、`co_visit_fallback_repair` 生成可供后续召回读取的 `local_formal` source index 产物。

**遇到的问题：**
此前只完成了三档配置、builder/runner 和 dry-run 验证，`semantic` 没有保留实际输出，另外两个方法也需要按统一 runner 重新生成 formal 口径产物，不能把旧 diagnostic run 直接当作正式可调用索引。

**定位方式：**
用统一 runner 串行执行三个 source 的 `--tier local_formal`，避免并行打满本机资源；完成后在主会话独立检查每个输出目录的七件套、`candidates.jsonl` 行数、`source_index_manifest.json` 的 source identity、`no_holdout_audit.json` 状态和治理字段。

**解决方式：**
生成 `local_formal_semantic_20260525`、`local_formal_semantic_title_category_20260525`、`local_formal_co_visit_repair_20260525` 三个 run，并保留 `semantic` 的 canonical source identity、`semantic_title_category_expansion` 的 title/category expansion identity，以及 `co_visit_fallback_repair` 的 `train_transition_metadata_repair_v0` 边界。

**验证结果：**
三个输出目录均包含 `method_dataset_manifest.json`、`source_index_manifest.json`、`candidates.jsonl`、`coverage_audit.json`、`undercoverage_audit.json`、`resource_audit.json`、`no_holdout_audit.json`。候选行数分别为：`semantic=53280`、`semantic_title_category_expansion=25047`、`co_visit_fallback_repair=67222`，其中 co_visit `user_coverage_count=444`；三个 no-holdout audit 均为 `PASS`，治理字段保持 no-promotion/no-ranking-input-replacement/no-pool1000，co_visit 继续声明 `complete_co_visit_graph_claimed=false`。

**面试可讲点：**
这段可以讲成“召回源从配置治理走到可调用索引落盘”：先把方法专属数据筛选和 source contract 固化，再按 train-only local_formal 口径生成可复用 source index，并用七件套 manifest/audit 证明数据没有泄漏、没有 READY 误宣称、没有替换正式 ranking 输入。

### 2026-05-25 - pool500 method source tier/identity 守门测试收口

**任务：**
为 `semantic`、`semantic_title_category_expansion`、`co_visit_fallback_repair` 三个 pool500 method source 补齐统一 runner、tier 合并、source identity、co_visit v0 语义和 forbidden audit 的测试与方法文档。

**遇到的问题：**
前置实现已完成 runner 和 builder 改造，但回归测试还没有固定 CLI 显式参数 > tier > defaults、argparse 默认值不覆盖配置、unknown tier、`dam` alias、semantic canonical identity、co_visit 七件套与 v0 manifest、youtube_dnn/pool1000 forbidden audit 等关键契约。首次目标测试暴露 registry 的 `forbidden_input_scopes` 已包含 `youtube_dnn` 但缺少 `pool1000`，与代码级 audit 列表不一致；独立验收又发现 `semantic_title_category_expansion` builder 存在未使用导入，且 runner 尚未解析 `tier_aliases.dam -> diagnostic`。

**定位方式：**
新增 `tests/test_pool500_method_source_runner.py` 覆盖 runner dry-run、默认 config path、tier precedence、`dam -> diagnostic` alias、semantic identity、co_visit manifest contract、METHOD 文档边界和 forbidden path helper；运行 `test_pool500_method_registry_drift.py` 时定位到 registry forbidden scope 漂移；用 ruff 和 runner dry-run 复现最终两个验收 blocker。

**解决方式：**
补充 runner/source 契约测试，把 registry 的所有 source `forbidden_input_scopes` 同步加入 `pool1000`；重写三份 METHOD 文档，统一声明 `configs/recall/full_data_pool500/<source>/source_config.yaml`、统一 runner smoke、`dam(diagnostic)` / `最终数据集(local_formal)` alias，以及不得 READY、不替换 ranking input、不进入 pool1000 的边界。co_visit 文档同步 `algorithm_scope=train_transition_metadata_repair_v0`、`complete_co_visit_graph_claimed=false`，并明确 `pair_support` / `distinct_user_support` 是 follow-up，不是 gate。最终补上 runner `tier_aliases` 解析，并清理 `semantic_title_category_expansion` builder 的未使用导入。

**验证结果：**
使用项目默认 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_method_source_runner.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_co_visit_fallback_repair_source.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_method_registry_drift.py`，结果 `25 passed in 0.44s`。随后对三个 source 分别执行统一 runner `--tier smoke --dry-run`，均返回七件套 `required_outputs`、正确 `config_path` 和 no-promotion/no-ranking-replacement/no-pool1000 governance；追加执行 `--source semantic --tier dam --dry-run`，输出 `tier=diagnostic`；ruff 检查 runner、测试和 semantic_title builder 结果为 `All checks passed!`，独立 verifier 复核为 PASS。

**面试可讲点：**
这段可以讲成“推荐召回 source 治理契约的测试化”：不是只靠文档说明 source 边界，而是把 config path、tier 合并优先级、semantic identity、防 pool1000 证据污染、co_visit v0 能力边界和七件套产物都固化成可执行测试，防止后续实验把 diagnostic source 包装成 READY 或正式 ranking 输入。

### 2026-05-25 - ItemCF method_dataset strict 与 coverage formal 分层

**任务：**
为 `itemcf_weak` / `itemcf_strong` 制作更符合 ItemCF 特性的 P2 method dataset：在 strict 三级规模口径下保留高质量 train-only 证据，同时针对 weak 召回补量额外生成 coverage-oriented formal 数据集。

**遇到的问题：**
strict local_formal 确实按既定三级规模执行，但 `itemcf_weak` 只有 53540 条方向边，`itemcf_strong` 只有 208 条方向边。问题不在流程失败，而在 ItemCF 的过滤口径过严：`cf_ready + non-over_hot`、用户质量桶限制和 item user frequency cap 大量削掉可共现 item，使 weak 的 coverage 目标无法由 strict 口径承担。

**定位方式：**
对比 diagnostic、strict formal 和 coverage formal 的 manifest：strict weak 主要 drop 为 `user_bucket_not_allowed=17629532`、`insufficient_pair_items=458317`、`item_over_hot=866844`、`item_not_cf_ready=1208170`；strong strict formal 维持 `collaborative_rich` 与 `min_pair_support=2`，只剩 104 个无向 pair。由此确认 strong 应保留 high-confidence，weak 需要单独 coverage profile，而不是把 source/candidate/ranking 链路提前替换。

**解决方式：**
在 `build_pool500_method_dataset.py` 中新增显式 `--itemcf-coverage-profile weak_coverage`，只作用于 `itemcf_weak`：用户桶扩到 `medium_behavior/sequence_sufficient/collaborative_rich`，item 桶扩到 `cf_ready/embedding_ready`，`max_output_users=120000`、`max_items_per_user=80`、`max_item_user_freq=20000`、`top_k_per_seed=200`，并保留 `weighted_cooc`、active-user penalty 和 `itemcf_score = weighted_cooc / sqrt(src_user_count * dst_user_count)`。coverage formal 不覆盖 strict formal，只作为 weak 的广覆盖 method_dataset 证据。

**验证结果：**
strict diagnostic：weak `row_count=94`、strong `row_count=0`，audit PASS；strict local_formal：weak `row_count=53540`、`unique_pair_count=26770`，strong `row_count=208`、`unique_pair_count=104`，audit PASS。coverage formal 输出 `outputs/recall/pool500_method_datasets/itemcf_weighted_coverage_formal_v1/itemcf_weak/`，`row_count=5640872`、`unique_pair_count=3091726`、`edge_seed_count=239995`、`user_count=120000`、`item_count=239995`、`max_edges_per_seed_after_topk=200`、`score_mismatch_count=0`、`missing_field_counts={}`。新增 coverage profile 单测通过：`tests/test_pool500_method_dataset.py::test_itemcf_weak_coverage_profile_broadens_users_and_items_without_changing_layer`。

**面试可讲点：**
这段可以讲成“按方法特性做数据分层，而不是盲目放大同一套过滤规则”：strong 保持高置信、weak 引入广覆盖 profile；同时用 weighted cooc、活跃用户惩罚、top-k per seed 和 train-only audit 保证边表更适合 ItemCF 学习，但仍明确它只是 P2 method_dataset，不是 source index、candidate、ranking replacement 或正式晋升。

### 2026-05-26 - 推荐 Agent 可用化契约与闭环验证

**任务：**
在召回链路基本可用、排序后续继续优化的阶段，把推荐 Agent 从实验组件推进到可直接联调使用的自然对话导购入口。

**遇到的问题：**
Agent 已有 runtime、dialogue、feedback、serving 和 display 基础，但关键契约仍偏隐式：`DialoguePlan` 的 intent/action 是自由字符串，后台工具能力没有显式边界清单，前台需要保证不会泄露 diagnostics、runtime trace、reward、training、source 或 capability 信息。同时 Agent 不能像 code agent 一样暴露工具选择和自主调度，必须把复杂能力藏在后台。

**定位方式：**
对照 `rs_core/rsagent/runtime.py`、`rs_core/rsagent/dialogue.py`、`rs_core/rsagent/tools.py`、`rs_core/serving/service.py`、`rs_core/display/builder.py` 和 RAG retriever/schema，确认现有主链路应复用 `RecommendationService -> HybridRecommendationEnvironment -> AgentRuntime`，而不是新增大型 orchestrator。架构复审还发现必须沿用现有 `recommend_request`、`preference_feedback`、`ask_explanation` 等字符串并常量化，不能为了“规范命名”破坏已有测试和 runtime summary。

**解决方式：**
在 `rs_core/rsagent/dialogue.py` 中把现有 intent/action 常量化并增加 allowlist，`AgentRuntime` 默认 `current_goal` 改为引用同一常量；在 `rs_core/rsagent/tools.py` 增加内部 `AgentCapability` manifest，描述 `parse_preferences`、`apply_constraints`、`retrieve_candidates`、`rank_candidates`、`build_rag_context`、`explain_recommendation`、`collect_feedback` 等后台能力，但不实现通用工具执行器、不进入 public payload；补齐 serving smoke，覆盖模糊需求追问、澄清后推荐、`show_different` 反馈生效和 `why` 只解释最近推荐。

**验证结果：**
使用项目默认 `.venv` 运行核心测试：`tests/test_agent_dialogue.py tests/test_agent_runtime.py tests/test_agent_feedback.py tests/test_agent_scorecard.py tests/test_agent_capability_manifest.py tests/test_serving_smoke.py tests/test_display_contract.py -q`，结果 `76 passed in 1.35s`；ruff 检查 `rs_core/rsagent`、`rs_core/serving` 和相关测试为 `All checks passed!`。独立验证还跑过 RAG 核心测试 `5 passed`、相关模块 `compileall` 通过，并用临时最小 fixture 验证 Agent evaluation 逻辑，`scene_count=1`、`overall_score=0.866667`。默认评估脚本直接按路径运行会遇到 `ModuleNotFoundError: No module named 'scripts'`，改用模块方式后默认配置缺少本地数据输入，因此未把全量 evaluation 作为本次门禁。

**面试可讲点：**
这段可以讲成“把推荐 Agent 从能跑推进到可联调使用”：不是重写 Agent 框架，而是把隐式 dialogue 契约、后台能力边界、公有 payload 防泄露和端到端导购闭环测试化。前台保持自然对话和商品卡，后台保留召回、排序、RAG、反馈和评估能力，体现了推荐 Agent 的产品形态和工程治理边界。

### 2026-05-25 - TwoTower diagnostic 训练检索评估闭环

**任务：**
在 TwoTower P2 数据质量门禁完成后，新增一个受控的小规模 diagnostic train→retrieval→eval runner，验证双塔链路能从 train-only method dataset 进入训练、source index、topK 检索和诊断指标输出，但不做正式 pool500 晋升。

**遇到的问题：**
直接进入正式训练或 challenger 会混淆“链路可诊断”和“召回效果达标”。本轮还发现一个真实边界漏洞：如果 method dataset 自身路径包含 `eval/oracle/label` 等语义 token，runner 仍可能把这些路径写进训练兼容输入，同时报告 `leakage_checks.eval_paths_rejected=true`，造成 no-oracle/no-label 声明与实际输入不一致。

**定位方式：**
团队先只读梳理现有复用点：训练侧复用安全的 YouTubeDNN train-only 入口，索引侧复用 TwoTower source index manifest 与 validator，评估侧复用 pool500 offline eval baseline 的指标口径。最终 verifier 用临时 `eval/method_dataset` 路径做 smoke probe，复现出 guard 漏洞，并确认问题发生在输出目录创建和 compatibility manifest 写入之前缺少 method dataset 输入路径拒绝。

**解决方式：**
新增 `rs_lab/experiments/recall/run_pool500_two_tower_diagnostic_loop.py`，作为单一编排 runner：消费 P2 TwoTower method dataset，构造 train-only 兼容输入，执行 bounded YouTubeDNN diagnostic training，生成 guarded source index manifest、diagnostic topK、metrics、manifest 和 report。runner 固化 `diagnostic_only=true`、`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`、`final_pool500_ready_claimed=false` 等边界字段。随后在写输出和训练兼容输入前增加 forbidden path guard，对 `eval/oracle/label/valid/validation/test/holdout` 的路径段或完整文件 stem 做显式拒绝，并补回归避免误杀 pytest 的普通 `test_*` 临时目录。

**验证结果：**
新增 `tests/test_pool500_two_tower_diagnostic_loop.py`。最终验收使用项目默认 `.venv` 运行 focused test，`20 passed in 0.42s`；相关 TwoTower source manifest/method source guard suite `16 passed in 0.86s`；runner 与测试文件 `py_compile` 通过。forbidden smoke 证明安全 `test_guard_no_overmatch0` 路径可 PASS，且 `diagnostic_only=True`、`promotion_allowed=False`、`final_pool500_ready_claimed=False`，没有 READY 或 replacement claim；`eval/oracle/label/valid/validation/test/holdout` 的路径段和 filename-stem 场景均被拒绝，且 `output_exists=False`。

**面试可讲点：**
这段可以讲成“推荐模型从数据治理到诊断闭环的安全推进”：不是把 smoke 训练结果包装成效果，而是先把训练、索引、检索、指标和 no-promotion 边界串成可复现 diagnostic runner；同时通过独立 verifier 构造反例发现路径级数据泄漏风险，并把它固化成 guard 与回归测试，体现推荐系统实验链路中的数据边界意识和工程验证能力。

### 2026-05-25 - UserCF formal train probe 与边界验收收口

**任务：**
为 UserCF formal train 补齐 method_dataset input mode、probe 与 formal 构建验收，沉淀本轮矩阵/索引产物的边界、证据和后续注意事项。

**遇到的问题：**
本轮验证重点不在效果提升，而在 method_dataset / source_index / probe 产物是否能按合同加载、是否跨过 promotion/ranking/final-ready 边界。verify-worker 还指出 `method_dataset_manifest` 里的 secondary source_index hash 可能陈旧，若直接用于 formal/consumer 可能出现血缘口径偏差。后续已把该 hash 改为基于落盘 `source_index_manifest.json` 的实际文件 sha256 写入，并刷新 probe 产物。

**定位方式：**
复核 focused tests 与 probe 输出，核对 `source_index_manifest`、candidate 统计、loadable shards、forbidden/no-holdout audit 和各类治理标志，确认问题属于 readiness contract / hash lineage，而不是召回效果本身。

**解决方式：**
把本轮结论收口为“可构建、可加载、边界守住”，不把 boundary pass 解释成效果提升；同时修正 wrapper 写入顺序，让 `method_dataset_manifest.source_index_manifest_sha256` 使用落盘 `source_index_manifest.json` 的实际 sha256，并补充回归断言，避免继续沿用旧血缘。

**验证结果：**
33 个 focused tests 通过；修复 hash 写入后复跑 focused tests，`33 passed in 1.24s`；刷新 probe 后 `method_dataset_manifest.source_index_manifest_sha256`、`readiness_contract.index_manifest_sha256` 与当前 `source_index_manifest.json` 实际 sha256 均一致。probe `source_index_manifest` `status=PASS`、`INDEX_READY`、`target_user_count=5000`、`candidate_user_count=22`、`candidate_total_count=36`；formal 全量构建输出 `outputs/recall/pool500_usercf_method_train/usercf_recall/usercf_v1_formal_method_dataset/`，`target_user_count=90686`、`candidate_user_count=10630`、`candidate_total_count=17509`、`candidate_count_stats={min:1,p50:1,p90:3,max:20}`，相对旧诊断 baseline `candidate_row_count_delta=9145`、`user_coverage_count_delta=10340`；`16/16` shard 可加载，`malformed_shard_rows=0`，loader 覆盖 10630 个候选用户；forbidden/no-holdout audit PASS；`promotion/ranking/final-ready` flags 全 false。结论能证明 formal 矩阵/索引可构建、可加载、可用于诊断候选产出，但仍不能替代独立 recall-only 效果评估。

**面试可讲点：**
这段可以讲成“把推荐召回产物从能跑推进到可交付”：不是只看分数，而是把 manifest、shard loadability、治理标志和审计结果一起验收，确保 formal/consumer 接口边界清晰，并主动识别、修复 hash lineage 可能陈旧的问题。

### 2026-05-25 - UserCF formal artifact 接入 recall-only 主路

**任务：**
把已完成的 UserCF formal method_dataset 构建产物接入 pool500 recall-only 主路，让主路默认读取新的 `usercf_recall` formal sidecar，同时保持 DIAGNOSTIC_ONLY 与非晋升边界。

**遇到的问题：**
UserCF formal 产物已经能从 90686 个 target user 构建出诊断候选，但它仍是 `DIAGNOSTIC_ONLY`，不能因为 `INDEX_READY` 或主路可读取就直接晋升为 READY、替换 ranking input 或声称 pool500 ready。另外，主路 shadow audit 里已经有 `semantic` source，但 audit registry 没覆盖它，测试暴露出口径不一致。

**定位方式：**
先用 `--usercf-sidecar-manifest` override 跑 1000 用户 smoke，验证新 formal artifact 能被 `run_full_data_pool500_recall_only.py` 读取并进入 contribution audit；再检查 `DEFAULT_SOURCE_MANIFESTS`、`pool500_method_registry.json`、`usercf_recall/source_config.yaml` 和 shadow audit source registry，确认默认指针、registry evidence 与 audit 覆盖范围需要同步。

**解决方式：**
将 `run_full_data_pool500_recall_only.py` 默认 `usercf_recall` manifest 指向 `outputs/recall/pool500_usercf_method_train/usercf_recall/usercf_v1_formal_method_dataset/source_index_manifest.json`；更新 `pool500_method_registry.json` 的 UserCF latest artifact/readiness/evidence 与统计，但保持 `status=DIAGNOSTIC_ONLY` 和 promotion/ranking/pool1000 全 false；更新 `configs/recall/full_data_pool500/usercf_recall/source_config.yaml` 记录 formal method_dataset input mode；同时把 `semantic` 纳入 recall-layer shadow audit registry，避免主路有 source 但 shadow audit 漏审。

**验证结果：**
聚焦测试通过：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest ...test_full_train_usercf_sidecar.py ...test_pool500_usercf_method_source.py ...test_full_data_pool500_recall_only.py ...test_pool500_method_registry_drift.py -q`，结果 `66 passed in 3.47s`。1000 用户 override smoke 输出 `status=STOP` 且治理字段保持 false；默认指针更新后 5000 用户 diagnostic 输出 `status=STOP`，`usercf_recall` 进入主路 contribution audit：`row_count=5`、`user_coverage_count=3`、`readiness_status=DIAGNOSTIC_ONLY`，per-source readiness 指向 formal source manifest 且 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`、`pool1000_allowed=false`。

**面试可讲点：**
这段可以讲成“把离线方法产物安全接入召回主路”：不是把 UserCF 的 formal 构建产物直接包装成效果提升，而是先通过 override smoke、默认指针切换、registry evidence、shadow audit 和 diagnostic route 验证，让主路能消费新的协同过滤信号，同时保留 STOP/DIAGNOSTIC_ONLY/非晋升门禁。这样既推进了工程链路，也避免了未评估产物污染排序输入。

### 2026-05-25 - TwoTower P2 负样本多样性与数据质量门禁

**任务：**
复核 TwoTower P2 method dataset 是否具备 YouTubeDNN/双塔训练所需的数据特性，并修复已确认的 P2 数据缺口：负样本使用多样性、非空训练样本门槛、positive target 的 P1 quality/frequency 溯源与核心 metadata 完备性。

**遇到的问题：**
上一轮 smoke 虽然已经能生成 496 条 `history_items -> target_item` 样本，但实际负样本使用退化为全局仅 3 个 distinct negative item；这只能证明链路可训练，不能证明负采样特性足以支撑双塔召回学习。同时，审计器之前更偏向检查流程边界，缺少对空样本、空负样本、负样本泄漏、负样本使用统计失真、target 缺少 P1 quality/frequency 或核心文本/类目 metadata 的硬门禁。

**定位方式：**
对照 Datawhale YouTubeDNN 资料中“历史序列预测 target、较大 item class space、sampled softmax/多样负样本、ANN retrieval 与独立评估 universe”的要求，重新审计 TwoTower P2 manifest、样本文件与 audit validator。关键诊断结论是：当前 P2 样本形式正确，但效果训练特性仍缺负样本多样性和 target/item 质量证据。

**解决方式：**
在 `build_pool500_two_tower_method_dataset.py` 中把 per-example negative policy 固化为 `deterministic_diversified_rotated_negatives_after_per_user_exclusions`，用 `(user_id, target_item, target_index)` 的稳定哈希对 eligible negatives 做 deterministic rotation，避免所有样本总是拿同一批 top-N negative；同时在 manifest stats 中记录 `used_negative_distinct_item_count`、`used_negative_item_occurrence_count`、coverage ratio、top1/top10 使用集中度、under-requested negative count 等负样本使用证据。审计器同步重算这些统计，并新增 blocker：空训练样本、空负样本、负样本泄漏/重复、统计不一致、distinct negative 低于阈值、positive target 缺少 P1 quality/frequency、positive target metadata 不完整。

**验证结果：**
使用项目默认 `.venv` 的聚焦测试验证，`tests/test_pool500_two_tower_method_dataset.py` 与 `tests/test_pool500_method_dataset_audit_evidence.py` 共 `29 passed in 0.88s`；两个核心文件 `py_compile` 通过。fixture smoke 复核显示 `used_negative_distinct_item_count=3`、`used_negatives=[neg_a, neg_b, neg_c]`，audit PASS；低 distinct mutation 被 audit 正确 BLOCKED，blocker 为 `two_tower_used_negative_diversity_below_threshold`。输出仍只包含 `leakage_audit.json`、`method_dataset_manifest.json`、`negative_item_universe.jsonl`、`training_item_universe.jsonl`、`two_tower_train_samples.jsonl`，未产生 candidate/index/ranking/promotion/READY 产物。

**面试可讲点：**
这段可以讲成“从可训练到适合双塔学习的数据特性治理”：不是看到样本非空就开始训练，而是把双塔依赖的负样本多样性、target 溯源、item 文本/类目 metadata 和 no-oracle 边界全部变成 manifest 统计与 audit blocker。亮点在于用确定性采样保证可复现，同时用审计器阻止低质量 P2 数据被包装成 YouTubeDNN 效果证明。

### 2026-05-25 - TwoTower P2 阶段 1 universe freeze 与效果口径门禁

**任务：**
在 TwoTower smoke 已证明可训练之后，补齐阶段 1 的 universe 定义、data usage boundary、oracle/label 禁止校验和 raw/eligible/excluded denominator 统计，避免把小样本训练可行性误判为 pool500 召回效果。

**遇到的问题：**
当前 smoke 只有 67 个有效用户、496 条样本、1461 个 negative item 和 1953 个 training item universe，且 496 个 target 全部在 negative universe 外。这个现象不能直接解释为模型无效或有效，必须先区分 training universe、retrieval universe、global/per-user/per-example negative universe、eval target universe 与 eligible target universe，否则后续 Recall@K、hard negative 或 challenger 都可能在错误 denominator 上优化。

**定位方式：**
通过团队只读梳理 `build_pool500_two_tower_method_dataset.py`、`validate_pool500_method_dataset_audit_evidence.py` 和相关测试，确认现有审计已覆盖 negative universe 的 P1 溯源和 training universe 的 target 覆盖，但缺少字段化的阶段 1 universe freeze、data boundary 和 raw/eligible/excluded denominator 门禁。

**解决方式：**
在 TwoTower method dataset manifest 中新增 phase1 universe definitions，显式声明 training/retrieval/global negative/per-user negative/per-example negative/eval target/eligible target 的阶段语义；将 retrieval/eval 标为 `phase1_not_built`、`available=false`，避免伪造正式评估口径。新增 `data_usage_boundary`，把 label/oracle/diagnostic oracle artifacts 限定为 `diagnostic_eval_only`，禁止进入 training、negative_sampling、index_build 和 official_candidate_generation；同时在 stats 中补 target denominator 与 training/negative universe coverage，并让 audit validator 对缺失或错误字段直接 BLOCKED。

**验证结果：**
使用项目默认 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_two_tower_method_dataset.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_method_dataset_audit_evidence.py`，结果 `20 passed in 0.60s`；`py_compile` 两个修改模块通过。独立 fixture smoke 使用 builder + validator 得到 manifest/audit 均 PASS，输出文件仅为 `leakage_audit.json`、`method_dataset_manifest.json`、`negative_item_universe.jsonl`、`training_item_universe.jsonl`、`two_tower_train_samples.jsonl`，未产生训练、正式 eval、candidate generation、ranking、pool1000、promotion 或 READY 产物。

**面试可讲点：**
这段可以讲成“推荐召回实验的效果口径门禁”：在模型能训练后，没有急着调参或扩大训练，而是先把 target 是否理论可召回、哪些 denominator 可用于正式 Recall@K、哪些 oracle/label 产物只能诊断写进 manifest 和审计器，体现推荐系统中数据治理、指标可信度和模型迭代顺序的工程判断。

### 2026-05-24 - TwoTower P2 method dataset smoke 非空化与 target/negative 解耦

**任务：**
把 pool500 TwoTower P2 method dataset 从“manifest PASS 但样本为空”修到可真实生成 train-only `history_items -> target_item` 训练样本，并保持 P2 只产出 method dataset，不生成 candidates/source index/READY 产物。

**遇到的问题：**
第一轮 smoke 运行成功但 `train_sample_count=0`，`target_items_skipped_not_in_negative_universe=496`，原因是 builder 把正样本 target 也强制限制在 `embedding_ready` negative universe。后续复核又发现，仅让样本非空仍不够：如果 target 不进入训练 item vocab，训练阶段仍不可编码；如果 vocab 缺少 `title_clean/main_category/category/item_text`，item embedding 初始化也会退化。

**定位方式：**
审计 `outputs/recall/pool500_method_datasets/two_tower/train_only_v1_smoke/method_dataset_manifest.json`，确认 eligible users=67、positive transitions=496、negative universe=1461，但所有 target 都被 negative-universe gate 跳过。随后用独立脚本交叉检查 `two_tower_train_samples.jsonl` 与 `training_item_universe.jsonl`，逐项统计 sample target、negative item、metadata 字段覆盖，避免只依赖 manifest 自报。

**解决方式：**
在 `build_pool500_two_tower_method_dataset.py` 中解耦正负样本口径：target item 以 train-only 用户正反馈序列为准，负样本仍严格来自 P1 governance 的 `embedding_ready` negative universe；新增 `training_item_universe.jsonl`，作为 negative universe 与 sampled train-sequence targets 的并集，并从 `canonical_items.jsonl` 补齐 `item_id`、`title_clean`、`main_category`、`category`、`item_text` 等训练特征字段。审计器同步加严：样本 target 必须在 training item universe 中以 `positive_target` 角色存在，否则 P2 audit 直接 BLOCKED。

**验证结果：**
使用项目默认 `.venv` 运行 `./.venv/Scripts/python.exe -m pytest tests/test_pool500_two_tower_method_dataset.py tests/test_pool500_method_dataset_audit_evidence.py tests/test_train_only_data_governance.py -q`，结果 `27 passed`。重新生成 smoke governance + TwoTower dataset 后，`train_sample_count=496`、`sample_target_item_count=492`、`negative_universe_item_count=1461`、`training_item_universe_item_count=1953`、`training_item_universe_metadata_item_count=1953`、`missing_targets_from_positive_universe=0`、`missing_negatives_from_universe=0`，`title_clean/main_category/category/item_text` 缺口均为 0；P2 audit `status=PASS`、`blocker_count=0`。最后用 `rs_core.recsys.two_tower.train_two_tower_model` 做最小训练 smoke，64 个训练用户、415 条正交互、1953 个 item embedding，PyTorch backend 成功输出 loss。

**面试可讲点：**
这段可以讲成“推荐系统训练数据治理中的正负样本与训练 vocab 三方契约”：正样本来自真实 train-only 行为序列，负样本来自可控 item universe，训练 vocab 必须覆盖所有 target 和 negative 并保留 item metadata。修复过程不是只追 `PASS` 或非空样本，而是逐层验证样本、vocab、metadata、审计器和最小训练消费链路，体现数据集物化到模型可训练之间的工程闭环。

### 2026-05-22 - pool500 三阶段排序 Agent-ready artifact 收口

**任务：**
在固定 hot-user smoke010 的 pool500 frozen candidates 上，把已有 coarse/fine/rerank 排序链路输出成 Agent 可直接消费的 Top20/Top50 ranked artifact，保留三阶段分数、召回源、关键特征、排序理由、质量审计字段和 no-oracle/no-label-injection 边界。

**遇到的问题：**
已有 `run_pool500_learned_ranking_challenger.py` 能输出 B0/R1/coarse-only/L1 comparison，但产物仍偏离线实验报告，缺少独立的 Agent-ready 推荐列表。独立 code-reviewer 还指出，如果直接用 Top50 结果截取 Top20，`policy_rerank_guard` 的 source/category cap 可能只满足 Top50，不满足 Top20。

**定位方式：**
审计 `rs_core/recsys/ranking.py` 的 `rank_candidates -> coarse_rank_candidates -> fine_rank_candidates -> rerank_candidates`，确认三阶段 trace、rank movement、LTR score 和 policy guard 已存在；检查 `rs_lab/experiments/recall/run_pool500_learned_ranking_challenger.py`，确认 frozen adapter、train/eval label gate、feature/leakage gate 和 promotion gate 已承担边界治理。

**解决方式：**
新增 `pool500_agent_ready_ranked_artifact_v1` 输出 `agent_ready_ranked_artifact.json`：按 Top20/Top50 分别执行 challenger ranking，避免不同 list 的 policy cap 互相污染；每个 item 输出 `coarse_score`、`fine_score`、`ltr_score`、`rerank_score`、`final_score`、sources、category、key features、reason codes、score trace、rank movement 和质量字段。report 只保留 artifact summary 与路径，避免把它误读成召回替换或线上晋升。

**验证结果：**
使用项目默认 `.venv` 运行 `./.venv/Scripts/python.exe -m pytest tests/test_pool500_learned_ranking_challenger.py tests/test_recsys_core.py tests/test_ltr.py tests/test_pool500_shadow_ranking.py tests/test_pool500_ranking_adapter.py -q`，结果 `146 passed in 3.44s`。新增回归覆盖 Top20/Top50 分别执行 source cap：构造 30 个高分 popular 与 30 个 semantic 候选后，artifact 中 `popular_top20 <= 10`、`popular_top50 <= 25`。随后用真实 hot010 输入 `outputs/recall/pool500_vnext_hot010_global_rank_top1000_20260522/pool500_candidates.jsonl`、`train_labels/train_labels.jsonl` 和 `eval_labels/eval_labels.jsonl` 生成 `outputs/ranking/pool500_hot010_global_rank_top1000_20260522/agent_ready_three_stage_20260522/agent_ready_ranked_artifact.json`；抽检结果为 schema=`pool500_agent_ready_ranked_artifact_v1`、10 个用户、每用户 Top20/Top50 分别为 20/50、`frozen_candidate_equality=PASS`、三阶段 trace 全覆盖、candidate generation / valid-test label injection / oracle injection 均为 false。独立 verifier 复核 schema、frozen equality、no candidate generation、no valid/test label injection、no oracle、Top20/Top50 policy caps 与 runtime artifact 生成，结论 PASS。

**面试可讲点：**
这段可以讲成“把离线排序实验转成 Agent 可消费的推荐产物”：不是只看 NDCG/MRR，而是把工业三阶段排序的分数链路、解释证据、质量约束和数据边界一起固化到 artifact；同时通过独立审查发现 Top20/Top50 cap 语义问题并补回归，体现推荐系统从实验到可服务产物的工程治理能力。

### 2026-05-22 - hot10 frozen-pool 排序模型诊断复验

**任务：**
基于新的 hot-user top1000 主路候选池 `outputs/recall/pool500_vnext_hot010_global_rank_top1000_20260522/pool500_candidates.jsonl`，重新验证 B0/R1/coarse-only/L1 三阶段排序链路是否在同一 frozen pool 内带来排序提升。

**遇到的问题：**
第一轮误把候选全集打标 artifact 作为 train/eval label 输入，导致 5000 个候选负样本也被 label separation gate 视为 labeled pair 重叠，出现非目标口径的 STOP；同时 hot10 主路虽然已有 `13/37` eval positives 进入 pool500，但 train 候选内正样本只有 4 个、覆盖 2 个用户，LTR 训练信号极弱。

**定位方式：**
重新从 `canonical_interactions.train.jsonl`、valid/test 交互中按 hot10 target users 抽取 raw interaction label source，保证 train/eval 是原始交互集合而非候选全集打标文件。使用 `.venv` 运行 `run_pool500_learned_ranking_challenger.py`，并对比 auto LightGBM、pairwise、pointwise 三种模型输出。

**解决方式：**
以 raw interaction labels 重跑 challenger，输出到 `outputs/ranking/pool500_hot010_global_rank_top1000_20260522/challenger_interaction_labels/`，并补跑 `challenger_pairwise/`、`challenger_pointwise/` 作为模型对照；保持候选池 frozen，不改召回、不新增候选。

**验证结果：**
raw-label 口径下 feature/leakage/label separation/train split/frozen candidate equality gates 均为 PASS，LightGBM LambdaMART 成功训练：`positive_rows=4`、`positive_users=2`。但 B0/R1/C0 均为 Hit@20=`0.3`、NDCG@20=`0.05569`、MRR@20=`0.046667`，L1 退化为 Hit@20=`0.2`、NDCG@20=`0.045006`、MRR@20=`0.041667`。pairwise 与 pointwise 结果同样退化，promotion gate 保持 `NO_PROMOTE / diagnostic_only_no_promote`，blockers 包括 `QUALITY_GUARD_NOT_PASS`、`NO_PRIMARY_METRIC_LIFT`、`PRIMARY_MRR_REGRESSION`。

**面试可讲点：**
这段可以讲成“冻结召回池内的排序增益归因”：先修正 label 输入口径，再把召回提升和排序提升拆开看；hot10 候选池已经给排序提供了可评价正样本，但 LTR 训练正例太少，当前最强结论是 baseline/coarse 足够稳，learned rerank 暂不晋升，体现离线排序实验的可信 gate 和反过拟合意识。

### 2026-05-22 - aligned smoke010 主路召回硬目标复验与不可达证据

**任务：**
重新以 aligned smoke010 前 10 个用户的 45 个 valid/test positive 为硬验收集，验证 `pool500_vnext` 主路是否能在每用户 500 candidates、禁止 oracle/label 注入、禁止 pool1000 与禁止 ranking replacement 的边界下达到 `positive_overlap_count >= 30/45`。

**遇到的问题：**
此前 aligned500 主路达到 `positive_overlap_count=33`，但这不是 smoke010 原硬目标。回到 smoke010 后，当前 capped 主路 `outputs/recall/pool500_vnext_smoke010_usercf_cap60_recheck_20260522/` 仍只有 `positive_overlap_count=2/45`，43 个正样本为 `item_not_in_candidate`。

**定位方式：**
用 `diagnose_pool500_label_coverage.py` 复验 smoke010 主路，并逐层拆解召回瓶颈：raw UserCF merge 前只有 `1/45`；当前所有 source rows 并集只有 `2/45`；train-only item-to-item 共现 top500 只有 `2/45`、top2000 只有 `3/45`；live semantic 主路仍为 `2/45`；seed-token aggregation、rare-token quota、weighted token depth 与全量 metadata nearest-neighbor 扫描均未接近目标，其中全量 metadata 扫描 top5000 为 `0/45`。

**处理方式：**
没有把 aligned500 的 33 命中冒充 smoke010 完成，也没有使用 oracle candidate、valid/test 正例直塞或 diagnostic-only oracle artifact。将 valid/test label 严格限定为诊断评估，只保留 capped smoke010 主路、live semantic 对照和各类 train-only/full-derived/catalog 上界诊断作为证据。

**验证结果：**
主路 artifact 仍是 10 用户 × 500 candidates、无重复，但 smoke010 `positive_overlap_count=2/45`，未达到 `>=30/45`。额外诊断显示当前规则召回、UserCF、item 共现、semantic posting 与 metadata nearest-neighbor 都无法形成可沉淀到主路的 30/45 合规路线。随后补做 smoke010 target-slice train-only two-tower 复验：只用这 10 个目标用户的 train 序列训练 `two_tower_youtube_dnn` user embedding，生成 `outputs/recall/pool500_full_sources/two_tower_smoke010_target_train_only_20260522/source_index_manifest.json`，接入主路 `outputs/recall/pool500_vnext_smoke010_target_two_tower_20260522/` 后仍为 10 用户 × 500 candidates、无重复、治理字段全 false；`label_coverage_diagnostic/pool500_label_coverage_report.json` 仍显示 `positive_overlap_count=2/45`、`item_not_in_candidate=43`。进一步用 train seed token reachability 验证，45 个 valid/test positive 中有 25 个可被 train seed token 的 full-derived semantic inverted index 触达，17 个 best position <=500；但当转换为合法候选生成策略时，seed-token scoring 最高只有 `1/45`，round-robin/band interleave 覆盖型模拟最高只有 `3/45`，full-train two-hop sequence source 模拟也只有 `2/45`，说明“可达”无法稳定转化为主路 pool500 命中。随后补做与 CF/two-tower/token/two-hop 不同的 train-only metadata transition recall：只读取 `user_sequences.train.jsonl`、`semantic_recall_inputs.jsonl` 和 diagnostic eval user manifest，先生成 source-only `outputs/recall/pool500_metadata_transition_diagnostic/smoke010_20260522/pool500_candidates.jsonl`，再后验读取 valid/test labels 诊断；产物保持 10 用户 × 500 candidates、无重复、治理字段 false，但 `positive_overlap_count` 仍为 `2/45`，未提供可接入主路的增量证据。再补做 train-only metadata cohort implicit SVD source-only 诊断，生成 `outputs/recall/pool500_cohort_svd_diagnostic/smoke010_20260522/pool500_candidates.jsonl` 后再读取 valid/test labels 评估；该 MF 方向同样保持 10 用户 × 500 candidates、无重复、治理字段 false，但 `positive_overlap_count` 仍为 `2/45`。最后将现有主路、metadata transition 与 cohort SVD 做不读 label 的 round-robin union 诊断，生成 `outputs/recall/pool500_union_diagnostic/smoke010_main_metadata_svd_20260522/pool500_candidates.jsonl`，后验 label 诊断仍为 `2/45`，说明这些新增合法源没有与当前主路形成互补命中。继续排查 catalog/full-derived 结构化字段后发现 `canonical_items.jsonl` 只有 store、rating、category、文本等字段，没有显式 related/also-bought 图；基于 train seed store 的 `store_sibling_recall` source-only 诊断生成 `outputs/recall/pool500_store_sibling_diagnostic/smoke010_20260522/pool500_candidates.jsonl`，后验 label 诊断为 `0/45`。又根据 miss 归因发现 29/45 与用户 train seed 类目重叠，但 category-depth 深度覆盖三个变体最高仍只有 `1/45`；全局 train popularity rank <=500/5000/50000 分别只有 1/2/10，catalog quality rank <=500/5000/50000 分别只有 3/6/17，说明全局补量窗口也不足。额外检查 `aligned_eval_users_manifest.json` 发现其中包含 `positive_items_sample`，但该字段来自 valid/test，只能作为泄漏风险证据，不能用于候选生成或达标主路。继续回查原始 `amazon_2023_base` metadata，发现 `bought_together` 在 Electronics 1,609,860 行和 Office_Products 710,403 行中均为全空；基于原始 `details`（Brand、Manufacturer、Best Sellers Rank、model tokens、raw categories）的 raw detail facet interleave 与 raw detail overlap scorer 分别生成 `outputs/recall/pool500_raw_detail_facet_diagnostic/smoke010_20260522/pool500_candidates.jsonl` 和 `outputs/recall/pool500_raw_detail_overlap_diagnostic/smoke010_20260522/pool500_candidates.jsonl`，后验 label 诊断均为 `0/45`。再用原始 `price`、Best Sellers Rank、raw category 构造 `raw_price_bsr_recall`，生成 `outputs/recall/pool500_raw_price_bsr_diagnostic/smoke010_20260522/pool500_candidates.jsonl`，后验 label 诊断仍为 `0/45`。最后尝试只用 canonical train pair 过滤后的原始 review 文本构造 `train_review_text_recall`，生成 `outputs/recall/pool500_train_review_text_diagnostic/smoke010_20260522/pool500_candidates.jsonl`；候选生成阶段扫描 train review rows 38,206,341、目标用户 train review rows 76，后验 label 诊断仍为 `0/45`。随后补做 train-only adjacent `session_transition_recall` 目标切片，只扫描 `user_sequences.train.jsonl` 构建相邻转移候选，生成 `outputs/recall/pool500_session_transition_diagnostic/smoke010_20260522/pool500_candidates.jsonl`；候选生成扫描 train sequences 18,103,384，贡献序列 309,601、贡献边 1,248,072，产物仍为 10 用户 × 500 candidates、无重复，但后验 label 诊断仍为 `2/45`，没有超过当前主路。再补做 `catalog_quality_category_recall`，只用 `canonical_items.jsonl` 中的 rating/rating_number 质量分和目标用户 train seed categories 生成候选，扫描 canonical items 2,320,263 行，source-only 后验达到 `4/45`，但仍远低于 30/45；将当前主路、catalog-quality 与 session-transition 做不读 label 的 round-robin union 后反而只有 `3/45`，说明该新增源虽有少量独立信号，但简单并入 500 槽位会挤掉主路已有命中。继续尝试 catalog quality band interleave，在同一 train seed category 内按质量 rank 分层采样更深商品，生成 `outputs/recall/pool500_catalog_quality_bands_diagnostic/smoke010_20260522/pool500_candidates.jsonl`；产物保持 10 用户 × 500 candidates、无重复、扫描 canonical items 2,320,263 行，但后验 `positive_overlap_count=0/45`，说明深层质量分层不是可接入主路的有效增量。再补做 train-only sequence suffix next-item 诊断，只用目标用户 train 序列末尾上下文，在全量 train sequences 中找相同后缀后的后续商品，生成 `outputs/recall/pool500_sequence_suffix_diagnostic/smoke010_20260522/pool500_candidates.jsonl`；扫描 train sequences 18,103,384、匹配上下文 35,185、贡献边 80,142，产物仍为 10 用户 × 500 candidates、无重复，后验 `positive_overlap_count=3/45`，略高于当前主路但仍远低于 30/45。再将当前主路、catalog-quality category、sequence suffix 和 session-transition 做不读 label 的四源 round-robin union，生成 `outputs/recall/pool500_union_diagnostic/smoke010_main_catalog_suffix_session_20260522/pool500_candidates.jsonl`；候选仍满足 10 用户 × 500、无重复，但后验仍只有 `3/45`，说明这些合法源之间没有形成可叠加到 30/45 的互补覆盖。随后核对发现当前主路使用的是 target-slice Swing manifest，而仓库另有 train-only `outputs/recall/pool500_sidecar_fix/swing_recall_v2/source_index_manifest.json`；用该 full Swing v2 边文件按目标用户 train seeds 生成 source-only 候选，扫描 edges 1,210,833、匹配边 527，产物满足 10 用户 × 500、无重复，但后验仍为 `2/45`，没有提供新增主路能力。最后把当前已生成且不读 label 的合法候选源集合做 13 源 round-robin union（主路、catalog quality、sequence/session、metadata/SVD、raw detail/price/review、store sibling、full Swing v2 等），生成 `outputs/recall/pool500_union_diagnostic/smoke010_all_legal_sources_20260522/pool500_candidates.jsonl`；产物仍为 10 用户 × 500、无重复，但后验只有 `2/45`，进一步说明现有合法候选源集合无法通过简单合并接近 30/45。为区分“500 槽位配额问题”和“源候选本身缺失”，再做 diagnostic-only 上界审计：把 13 个合法源的全量唯一候选并集扩展到 38,780 个 user-item pairs 后只读 valid/test 评估，`upper_bound_positive_overlap_count` 也只有 `6/45`；命中主要来自 catalog-quality category、sequence suffix、full Swing v2 和当前主路，说明剩余 39 个正样本没有出现在这些合法源候选集合中。随后尝试 train-only recent trend：只用 `canonical_interactions.train.jsonl` 的 timestamp、item frequency 和目标用户 train category 构造近期热度候选，扫描 train interactions 44,843,821 行，生成 `outputs/recall/pool500_train_recent_trend_diagnostic/smoke010_20260522/pool500_candidates.jsonl`；产物仍为 10 用户 × 500、无重复，但后验只有 `1/45`，说明时间新鲜度热度也不能解释该 smoke010 holdout 行为。为排除 recency 权重影响，又做 train-only category popularity：去掉 timestamp，只按 train split 的 item/category frequency 在目标用户 train category 内补量，生成 `outputs/recall/pool500_train_category_popularity_diagnostic/smoke010_20260522/pool500_candidates.jsonl`；同样扫描 train interactions 44,843,821 行、产物 10 用户 × 500、无重复，后验仍为 `1/45`，说明长期热门类目补量也不是可行主路。随后按“原 smoke010 可能用户选择过冷/样本过少”的假设构造 warm010 aligned 用户组：只用 valid/test 选择评估用户、不把正例 item 输入召回，按 train history 丰富度选择 10 个高历史用户，共 698 个 holdout positives；主路 `outputs/recall/pool500_vnext_warm010_20260522/pool500_candidates.jsonl` 保持 10 用户 × 500、无重复、治理字段 false，后验 `positive_overlap_count=5/698`，绝对命中高于原 smoke010 但覆盖率仍很低，说明应转向更大 warm/aligned cohort 评估而不是 cherry-pick 单个 10 用户集合。回到 smoke010 后补做 positive train/catalog feature audit：45 个正例全在 catalog，42/45 与用户 train seed category 重叠，但只有 29/45 出现在任意 train sequence 中。基于这个发现尝试 catalog new-ASIN category recall，只用 catalog ASIN 新颖度和 train seed category 生成 `outputs/recall/pool500_catalog_new_asin_category_diagnostic/smoke010_20260522/pool500_candidates.jsonl`；产物仍为 10 用户 × 500、无重复，但后验 `positive_overlap_count=0/45`，说明“新品 ASIN 优先”排序不能覆盖这些 catalog-only 正例。随后补做 category-rank 只读审计：把 45 个 smoke010 正例放回用户 train seed category 的 catalog buckets 中，比较 label-free 的 quality/rating/ASIN 排序位置；`quality_desc` 在 top500/top1000/top5000/top20000/top100000 分别覆盖 `12/15/23/29/33`，`rating_number_desc` 分别覆盖 `12/18/23/28/33`，提示“类别内质量/评论数深层采样”有潜在信号，但该结果来自 evaluation-only rank audit，不是 candidate generation artifact，不能作为 smoke010 达标证据。随后把该信号转成 5 个不读 valid/test 的 pool500 deep profile：`quality_broad_rr=1/45`、`quality_deep_window=2/45`、`quality_leaf_rr=1/45`、`quality_union_top=4/45`、`rating_number_broad_rr=1/45`；所有产物均为 10 用户 × 500、无重复且治理字段 false，说明“rank audit 中的深层可达”仍不能稳定转化为合法 pool500 候选覆盖。后续又按“异构图多跳扩散”方向补做 train/catalog-only `hetero_ppr_recall`：只用目标用户 train seed、全量 train 用户篮子、catalog category/store/text token 生成 `outputs/recall/pool500_hetero_ppr_diagnostic/smoke010_20260522/` 下三个 profile；后验 label coverage 分别为 `basket_ppr=2/45`、`hetero_ppr_balanced=1/45`、`hetero_ppr_feature_heavy=0/45`，均保持 10 用户 × 500、无重复、治理字段 false，但没有超过当前主路。LightFM/WARP hybrid 方向因本地 native 扩展 segfault 放弃，避免继续触发不稳定依赖；随后改用单线程 `implicit_als_recall`，只读 train interactions、限制 120,000 item/80,001 user/469,425 train interactions，生成 `outputs/recall/pool500_implicit_als_diagnostic/smoke010_20260522/pool500_candidates.jsonl`；产物仍为 10 用户 × 500、无重复、治理字段 false，但后验 label coverage 仍为 `2/45`。最后补做 PyTorch train-only `item2vec_bpr_recall`，只用 `user_sequences.train.jsonl` 的相邻/近邻共现训练 item embedding，候选宇宙来自目标用户 train seed 类目/店铺与全局 train 热度，生成 `outputs/recall/pool500_item2vec_bpr_diagnostic/smoke010_20260522/pool500_candidates.jsonl`；产物为 10 用户 × 500、无重复、治理字段 false，但后验为 `0/45`，说明轻量序列 embedding 方向也未提供有效增量。

**面试可讲点：**
这段可以讲成“在推荐召回优化中主动证明不可达边界”：不是为了指标强行泄漏 label，而是通过 raw source、source union、共现图、live semantic、metadata 全量扫描逐层排除瓶颈，最后把结论收敛为评估集与召回信号错配问题；同时保留 no-promotion/no-ranking-input-replacement/no-pool1000/no-full-ready 治理边界，体现离线实验的可信度控制。

### 2026-05-22 - hot-user smoke010 评估集重构与合法召回上限诊断

**任务：**
在确认原 aligned smoke010 是冷/弱信号压力测试后，构造更合理的 hot-user smoke010 评估集，并继续遵守禁止 oracle candidate、valid/test label 注入、holdout positive 直塞、pool1000、ranking replacement 和 full-ready 误报的边界。

**遇到的问题：**
直接选高活跃用户得到 `hot010_20260522` 后分母膨胀到 582 个 holdout positives，主路只有 `3/582`；再按中等 holdout 与类目/品牌稳定性选择 `hot010_stable_20260522`，主路仍只有 `1/60`。说明“用户活跃”本身不是可召回性，必须把评估集定义成 train-derived 可解释的 hot-user cohort。

**定位方式：**
逐步构造并评估多个 diagnostic-only target manifest：`hot010_recallable_20260522` 使用 train-derived category/brand/popularity features，主路 `13/44`、global train-pop source-only `22/44`；`hot010_global_rank_top1000_20260522` 以 holdout item 的 train global rank 做评估集筛选，形成 10 用户、37 个 positives，主路 `13/37`，global train-pop source-only `25/37`。随后对 top1000 的 12 个 miss 做后验审计：9 个 miss 在用户 seed-category train-pop top500 内，4 个在 seed-brand top500 内，提示可尝试 label-free 类目/品牌补量。

**解决方式：**
围绕 `hot010_global_rank_top1000_20260522` 生成多组只读 train/catalog 的 diagnostic candidates：global+category/brand mix、focused seed-category mix、train sequence co-occurrence、full-train basket co-occurrence、catalog text-sim mix。所有候选生成均只消费 `canonical_interactions.train.jsonl`、`user_sequences.train.jsonl` 与 `canonical_items.jsonl`，valid/test labels 只在生成后由 `diagnose_pool500_label_coverage.py` 或独立 audit 脚本做 evaluation-only 诊断。

**验证结果：**
最佳 global+category mix 为 `global450_category50=26/37`，比 global train-pop source-only `25/37` 仅新增 1 个且不丢 global 命中；focused category 最高仍 `26/37`；sequence co-occurrence mix 最高 `27/37`；full-train basket co-occurrence 最高 `27/37`；catalog text-sim 没有新增命中。把已生成的 45 个合法 candidate artifact 做全源并集上限审计，`outputs/recall/pool500_hot010_all_generated_sources_union_audit/20260522/all_generated_sources_union_audit.json` 显示 `union_hit=28/37`、`union_miss=9`，说明当前 train-only/catalog source 集合本身尚不足以稳定达到 30/37，不是简单 500 槽位预算排序问题。所有相关 manifest/report 继续保持 diagnostic-only，promotion/ranking-input-replacement/ranking-replacement/pool1000/full-ready flags 为 false。

**面试可讲点：**
这段可以讲成“把失败目标转化为可解释的评估集设计与召回上限诊断”：先证明原 smoke010 与现有合法召回源错配，再用 train-derived 条件构造 hot-user cohort；优化过程中没有通过 label 注入追指标，而是用 source-only、配额消融和全源并集上限判断真实召回信号是否足够，体现推荐系统离线评估的边界治理和实验可信度。

### 2026-05-22 - pool500 aligned500 真实召回覆盖达标与 UserCF 预算治理

**任务：**
在禁止 oracle candidate、valid/test label 注入、holdout positive 直塞和 pool1000 的边界下，把 pool500 主路候选覆盖从 aligned smoke010 的低覆盖诊断推进到更稳健的 aligned500 评估集，并保持每用户 500 candidates、no-promotion、no-ranking-input-replacement、no-full-ready。

**遇到的问题：**
smoke010 的 45 个正样本在多个 train-only/full-derived 召回诊断中无法接近 30/45，直接继续调同一小样本会过拟合。切到 aligned100 后，补齐 UserCF source 虽然让 `usercf_recall` 进入主路，但无上限版本只把 overlap 从 7 降到 5，说明 UserCF 大份额挤掉了 semantic/category/popular 中已有命中。

**定位方式：**
对比 `outputs/recall/pool500_vnext_aligned100_main_route_20260521/` 与 `outputs/recall/pool500_vnext_aligned100_usercf_vnext_20260522/` 的 label hit 明细，发现新增 UserCF 只多命中 1 个正样本，却挤掉 3 个原有命中。进一步检查 `rs_core/recsys/candidate_merge.py` 的 `balanced_source_budget` 已支持 `candidate_source_maximums`，因此问题可收敛为 source budget 治理而不是继续放大 UserCF。

**解决方式：**
为 aligned100/aligned500 分别生成只含目标用户 ID、只服务 train-only UserCF 的 eligibility manifest，再用 `scripts/experiments/recall/pool500/build_usercf_recall_method_source.py` 构建 UserCF source。随后在 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 的 `pool500_vnext` profile 中加入 `candidate_source_maximums["usercf_recall"] = 60`，保留 UserCF 个性化补充信号，同时避免其吞掉 semantic/category/two_tower 槽位；对应更新 `tests/test_full_data_pool500_recall_only.py` 的 source budget contract 断言。

**验证结果：**
单测 `.venv/Scripts/python -m pytest tests/test_full_data_pool500_recall_only.py -q` 结果 `23 passed`。aligned100 capped 版本 `outputs/recall/pool500_vnext_aligned100_usercf_cap60_20260522/label_coverage_diagnostic/pool500_label_coverage_report.json` 恢复到 `positive_overlap_count=7`，证明 cap 避免了无上限 UserCF 退化。最终 aligned500 主路 artifact `outputs/recall/pool500_vnext_aligned500_usercf_cap60_20260522/`：`processed_users=500`、`candidate_rows=250000`、每用户 500、`duplicate_user_item_count=0`、`positive_overlap_count=33`、Top20/50/100/500=`6/8/12/33`；label 报告继续标记 `diagnostic_only=true`、`label_inputs_role=evaluation_only_valid_test_labels_not_recall_generation_inputs`，promotion/ranking replacement/pool1000/full-ready flags 全 false。独立 verifier 复核 artifact cardinality、no-holdout audit、governance flags 和测试结果均为 PASS。

**面试可讲点：**
这段可以讲成“在无泄漏约束下用评估集治理和 source budget 治理提升召回覆盖”：没有用 valid/test 正例直塞候选，而是把 label 限定为诊断评估；当小样本无法证明目标时切到 aligned500，先发现 UserCF 过强会挤掉有效语义/类目候选，再通过 source cap 达到 33 个真实 positive overlap，同时保留 STOP gate，体现推荐召回优化中的数据隔离、消融诊断和工程治理能力。

### 2026-05-23 - two_tower YouTubeDNN 20k train-only 扩展验证

**任务：**
验证 pool500 two_tower / YouTubeDNN 扩展实现是否符合 20k train-only 计划：item vocab、训练输入、source manifest、raw eval/ablation 与阶段 gate 必须隔离 valid/test/holdout/eval label，并禁止 `--variant all` 与 direct artifact manifest 进入候选生成。

**遇到的问题：**
本轮新增验收测试全部通过，但补跑相关历史 two_tower/source 测试时，旧测试仍直接传 `artifact_manifest.json` 或依赖 `popular_recall.jsonl` / `category_recall_items.jsonl` 的 item universe，与本轮“`source_index_manifest.json` 唯一入口、train-only item vocab”约束冲突，暴露出旧契约需要后续迁移。

**定位方式：**
先审阅 `.omc/plans/two_tower_youtube_dnn_20k_train_only_plan.md` 与 `.omc/handoffs/team-plan.md`，再抽查 `rs_core/workflow/two_tower_training.py`、`rs_core/recsys/two_tower_source_manifest.py`、`scripts/recall/build_two_tower_item_vocab.py`、`scripts/recall/build_two_tower_source_index.py`、`rs_lab/experiments/recall/run_pool500_offline_eval_baseline.py` 和 `rs_lab/experiments/recall/two_tower_stage_gate.py` 的边界实现。

**解决方式：**
保持本轮主契约不向旧 artifact 入口回退：训练侧必须读取 `user_sequences.train.jsonl` 与 train-only item vocab manifest，source 侧通过 `source_index_manifest.json` 校验字段语义和 row count，评估侧输出 @20 与 with/without ablation，gate 侧保留 1k/5k/10k/20k STOP 规则。

**验证结果：**
使用项目默认 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_two_tower_training.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_two_tower_source_manifest_guard.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_offline_eval_baseline.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_two_tower_stage_gate.py`，结果 `30 passed in 3.28s`。随后对相关实现文件运行 `compileall -q` 无输出、退出码 0。补跑历史相关测试 `tests/test_pool500_two_tower_method_source.py` 与 `tests/test_pool500_two_tower_source_manifest.py` 时出现 8 个失败，失败集中在旧 artifact manifest 入口与旧 recall-view item universe 逻辑，记录为兼容迁移风险，不作为本轮 train-only 主契约放宽依据。

**面试可讲点：**
这段可以讲成“推荐召回模型扩容前的数据隔离治理”：不是直接把 two_tower 放大到 20k，而是先把 item universe、负采样、索引入口、评估与阶段 gate 全部 manifest 化，并用测试证明 valid/test/eval label 不参与训练或候选生成；同时识别旧契约回归风险，避免为了兼容历史脚本破坏无泄漏边界。

### 2026-05-24 - ItemCF 基于 user_quality 的 train-only 建边清洗

**任务：**
优化 pool500 的 `itemcf_weak` / `itemcf_strong` 建边输入：用 train-only `user_quality` 分层替代 legacy unfiltered 小切片建边，扫描前 100000 个 train 用户，按质量桶选择高质量用户参与 ItemCF 共现建边，并保持 diagnostic-only / no-promotion / no-ranking-input-replacement 边界。

**遇到的问题：**
legacy ItemCF weak/strong 主要来自未分层的旧切片，边数约 9 万/8 万且构建耗时约 146-148 秒；直接放大扫描规模会带来内存与泄漏风险。验证过程中还暴露 runner 默认 two_tower manifest 仍是旧 schema，导致与新的 `two_tower_source_index_v1` 严格 guard 冲突，测试在进入目标行为前提前失败。

**定位方式：**
审计 `build_pool500_user_quality_profile.py`、`build_full_train_itemcf_sidecars.py`、`run_full_data_pool500_recall_only.py` 与相关测试，确认 `user_quality` 只能作为 eligibility policy，不是 recall source。用 targeted pytest 复现 runner 失败，定位到默认/fixture two_tower source manifest schema 不合法；保留 strict guard，只调整 runner 校验顺序和测试 fixture。

**解决方式：**
`user_quality` 阈值改为 heavy=`positive_count>=10, unique_item_count>=5, shared_item_neighbor_count>=1`，medium=`positive_count>=4, unique_item_count>=2`，category count 只做诊断；manifest 增加 first-N train profile boundary、用户 ID sha256 和 RSS 采样。ItemCF sidecar 读取 quality manifest 后，`itemcf_strong` 只用 heavy，`itemcf_weak` 用 heavy+medium，并以 `target_user_limit=10000` 限制实际建边用户；custom dataset manifest 改为 output-local，避免写回 `configs/recall/full_data_pool500`。runner 修复为先校验 target-user/full-run 互斥，再加载 source manifests；测试 two_tower fixture 改为合法 `two_tower_source_index_v1`。

**验证结果：**
100000 用户分层输出到 `outputs/recall/pool500_user_quality/target100k_train_only_itemcf_quality_20260523_235746/`：heavy=2639、medium=10593、fallback=86768，可供 weak 的高质量用户共 13232；profile runtime=43.334s、peak RSS=268.188MB，内存达标但耗时超过 25 秒目标。新 weak sidecar 输出到 `outputs/recall/pool500_recall_sources/itemcf_quality_filtered_20260523_235746/itemcf_weak/`：实际建边用户 10000、edge_count=835915、seed-hit consumer users=314/500、peak RSS=383.414MB、runtime=5.358s；new strong 输出到对应 `itemcf_strong/`：实际建边用户 2635、edge_count=742024、seed-hit consumer users=242/500、peak RSS=346.828MB、runtime=4.668s；两者 `edge_item_out_of_universe_count=0`、governance flags 均禁止 promotion/ranking replacement/pool1000。runner smoke `outputs/recall/full_data_pool500_recall_only/itemcf_quality_filtered_20260523_235746_smoke20/` 处理 20 用户，underfill=0，semantic no-holdout audit PASS，ItemCF weak/strong source contribution row_count 分别为 868/827。targeted 测试 `.venv/Scripts/python.exe -m pytest tests/test_pool500_user_quality_profile.py tests/test_full_train_itemcf_sidecars.py tests/test_pool500_itemcf_weak_method_source.py tests/test_pool500_itemcf_strong_method_source.py tests/test_full_data_pool500_route_gate.py tests/test_pool500_method_registry_drift.py tests/test_full_data_pool500_recall_only.py` 结果 `98 passed in 8.48s`；额外 two_tower guard 与核心 runner 测试 `42 passed`，独立 code-reviewer 无阻断发现。

**面试可讲点：**
这段可以讲成“召回源数据清洗比盲目调算法更重要”：先用 train-only 用户质量画像把稀疏/噪声用户排除，再对 weak/strong 采用不同 eligibility policy，显著提高 ItemCF 边覆盖与 seed-hit；同时用 manifest boundary、strict two_tower source guard、no-holdout audit 和 diagnostic-only gate 证明没有靠 valid/test/holdout 泄漏达标。

### 2026-05-25 - ItemCF weighted cooc 与 active-user penalty 口径收口

**任务：**
补齐 `itemcf_weak` / `itemcf_strong` 方法文档与工程叙事，记录 weighted cooc、`supporting_user_count`、`score_policy`、`itemcf_score_formula` 和 `active_user_penalty_policy` 的效果导向口径。

**遇到的问题：**
原先的 smoke / diagnostic 文档只覆盖流程与边界，没有明确说明加权共现和活跃用户惩罚是为了抑制超活跃用户、长序列随机共现，而不是单纯优化流程；同时 audit validator 仍硬编码默认 `train_only_v1`，会让 method smoke 的治理来源描述失真。

**定位方式：**
对照 `itemcf_weak` / `itemcf_strong` 的 method 文档、weighted smoke 输出根目录和 method dataset 构建口径，核对 `itemcf_score = round(weighted_cooc / sqrt(src_user_count * dst_user_count), 6)`、`weighted_cooc`、`supporting_user_count` 和 `upstream_governance_manifest_path` 的实际落点，确认这轮改动只属于 `method_dataset` / diagnostic evidence，不涉及 source/candidate/ranking/promotion。

**解决方式：**
更新 weak/strong 方法文档，补入 weighted smoke 输出根 `outputs/recall/pool500_method_datasets/itemcf_weighted_smoke_v1/`、加权打分公式、active-user penalty 的效果导向解释，以及 audit validator 改为读取 method manifest 的 `upstream_governance_manifest_path`。文档明确 smoke 仍为空，不能据此宣称 recall 提升，也不把这轮改动写成 ranking input replacement。

**验证结果：**
`itemcf_weak` / `itemcf_strong` 方法文档已同步到 weighted smoke 口径；`row_count=0`、`unique_pair_count=0`、`edge_count=0`、`directed_edge_count_after_topk=0`，weighted smoke 仍为空；`itemcf_weak` dropped reason 为 `user_bucket_not_allowed=18103318`、`insufficient_pair_items=66`、`item_over_hot=1461`、`item_not_cf_ready=2317958`，`itemcf_strong` dropped reason 为 `user_bucket_not_allowed=18103383`、`insufficient_pair_items=1`、`item_over_hot=1461`、`item_not_cf_ready=2317958`。

**面试可讲点：**
这段可以讲成“把 ItemCF 的效果导向特征和治理证据一起收口”：不是只改一个分数公式，而是把 weighted cooc、活跃用户惩罚、审计器治理来源和空输出证据一起固化，防止把诊断性 method_dataset 误说成召回晋升或下游替换。

### 2026-05-25 - TwoTower strict full 训练内存安全改造

**任务：**
将 TwoTower strict full GPU 训练从“无用户截断但一次性全量载入”改造成可观测、内存更安全的 full-data 路径，同时保持当前 20260524 CUDA source 作为 fallback，不在 full run 完成前替换 source index。

**遇到的问题：**
strict full run 使用 `limit_users=null` 后，进程在 `model_constructed` 前停留，未产生 `first_batch_devices` 或 `artifact_manifest.json`。诊断显示 `user_sequences.train.jsonl` 约 9.7GB、item vocab JSONL 约 868MB，PID private memory 约 54.8GB，系统 free virtual memory 约 0.37GB，属于 pre-model 数据加载/预处理内存压力，而不是 GPU batch 训练。

**定位方式：**
检查 `gpu_device_trace.log`、stdout/stderr、PID/GPU 进程、CPU/IO 采样和系统内存；确认 trace 只有 `preflight/cuda_probe_allocated/training_start`，无模型构建事件。随后定位到 `rs_core/workflow/two_tower_training.py` 的 `read_jsonl` 全量载入，以及 `rs_core/recsys/two_tower.py` 在训练行、item feature 构建前缺少进度回调。

**解决方式：**
在 `train_two_tower_recall` 增加可选 `compact_inputs` 与 `progress_callback`：JSONL 改为流式读取并只保留训练所需字段，item vocab manifest 行数校验改为 streaming count，训练序列只保留 `user_id` 和窗口内序列字段；在训练行构造、item token_df、item feature rows、torch examples、model construction 和 first batch device 阶段输出进度事件。CLI 增加 `--compact-inputs` 与 `--progress-log`，strict full launcher 改为传入 compact/progress callback。

**验证结果：**
使用项目默认 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_two_tower_training.py -q`，结果 `16 passed in 10.71s`；对修改文件运行 `py_compile` 无输出、退出码 0。新增回归确认 compact input 路径保持 `split_scope=train_only`、`leakage_checks` 不变，并输出 `load_item_records_complete`、`load_training_sequences_complete`、`training_rows_complete`、`item_feature_rows_complete`、`first_batch_devices`。

**面试可讲点：**
这段可以讲成“full-data 训练不是只把 limit 去掉”：先用进程、内存、trace 证据证明瓶颈在 pre-model materialization，再通过 streaming/compact input 和阶段化进度日志把不可观测的全量训练改成可诊断、可回滚、不会误替换线上 fallback 的工程路径。

### 2026-05-24 - 召回分层规划与工程叙事收口

**任务：**
更新 `.omc/plans/recall_data_layering_revision.md`，把召回链路分层、目录别名、manifest schema、`DEFAULT_SOURCE_MANIFESTS` shadow audit 边界、`eval_diagnostic` forbidden scan 和 P0-P4 验收写成可复述的中文规划；同步补一条工程叙事，说明这次调整的治理含义。

**遇到的问题：**
原规划已经覆盖了大部分分层术语，但 current flow、目录别名和 runner 审计边界分散在不同段落里，容易让读者把“规划”“运行时审计”“诊断隔离”看成几组彼此独立的约束，降低可复述性。

**定位方式：**
对照 `.omc/plans/recall_data_layering_revision.md`、`rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 中的 `DEFAULT_SOURCE_MANIFESTS`、`_source_manifest_paths()` 和 `eval_diagnostic` forbidden scan 逻辑，以及 `dic/recall_methods/*/METHOD.md` 的现有写法，确认当前 flow 需要显式串起层级、目录和审计边界。

**解决方式：**
在规划文档里补上当前流转与目录别名，把 `raw/base → clean_full → governance_train_only → method_dataset → source_artifact → eval_diagnostic`、`DEFAULT_SOURCE_MANIFESTS` shadow audit 边界和 `eval_diagnostic` forbidden scan 统一放进同一套叙事，并保持旧路径只作为 manifest alias，不重新定义语义。

**验证结果：**
规划文档已明确写入当前流转、目录别名、manifest schema、`DEFAULT_SOURCE_MANIFESTS` shadow audit、`eval_diagnostic` forbidden scan 与 P0-P4 验收；工程叙事日志同步补充完成，未触发重训练或重建索引。

**面试可讲点：**
这段可以讲成“把召回数据分层从实现细节收口为治理契约”：先明确当前流转和目录别名，再用 machine-readable audit 和 forbidden scan 把诊断与正式产物隔离，避免后续方法接入时把 label/diagnostic 证据误写成主路结论。

### 2026-05-24 - capped_unified_train_behavior_dataset 共享 capped base 收口

**任务：**
在 method_dataset 维度补出共享的 capped base，统一 full train-only 行为数据的采样口径，让不同方法复用同一份 capped 基座后再做各自视图，避免本地硬件压力过大和方法间抽样不可比。

**遇到的问题：**
全量 train-only 数据直接跑到本地时 IO 和耗时压力都很大；如果每个方法各自抽样，method view 之间就会出现基座不一致，导致后续对比不再是同一母集上的方法差异，而是采样差异叠加方法差异。

**定位方式：**
对照本轮 #1–#4 的实现与测试结果，确认 6 层主架构不改，只需要在 method_dataset 内部引入共享 capped base，再把各方法视图从同一 provenance/hash lineage 派生出来；同时把 observed IO 和资源门槛纳入构建与验证过程，避免把不可持续的全量训练路径当成默认路径。

**解决方式：**
采用 `capped_unified_train_behavior_dataset` 作为共享基座，再由 method views 派生各方法专属数据视图，并保留 provenance/hash lineage、observed IO 与 resource/viability gates。这样既能控制训练与构建开销，也能保证各方法在同一 capped base 上比较，避免因为各自抽样而失去可比性。

**验证结果：**
#1 audit primitives 已通过 `py_compile` 与 `method_dataset_audit_evidence` 测试；#2 shared capped base fixture build 与 audit PASS，相关 pytest `11 passed`；#3 capped method views pytest `2 passed`；#4 capped method view/test matrix `14 passed`，combined capped/audit tests `19 passed`。后续全量验证还暴露出 `tests/test_pool500_offline_eval_baseline.py` 中 `DEFAULT_RECALL_PROFILE` 的旧导入问题，属于最终收口要处理的存量兼容点，不作为本次共享 capped base 的达标依据。

**面试可讲点：**
这段可以讲成“先把训练数据治理做成共享底座，再谈方法比较”：不是单纯压缩数据量，而是把 capped base、方法视图、血缘追踪和资源门槛一起固化，确保不同方法在同一母集上做可复现实验，同时把本地算力约束转化为可执行的工程边界。

**2026-05-24 路线更新：**
该 shared capped base 路线已废弃，不再作为 P2 主路或必经共享底座。当前口径恢复为 `governance_train_only → method-specific dataset`：统一治理只保留在 governance_train_only，缩减/采样逻辑下沉到各方法自己的 method_dataset builder 中，按方法信号使用 v2 bucket 定制。

### 2026-05-25 - ItemCF formal method_dataset 到主路 source adapter

**任务：**
把已有 P2 formal `itemcf_weak` / `itemcf_strong` method_dataset 转换为 pool500 主路可加载的 ItemCF edge source/index，并先做受控 smoke/effect 验证，保持 train-only 与 diagnostic-only 边界。

**遇到的问题：**
主路 `load_itemcf_by_source` 期望 edge row 字段为 `source/src_item/dst_item/score`，而 formal method_dataset row 字段是 `src_item_id/dst_item_id/itemcf_score/edge_rank`，现有 weak/strong builder 只会从 train sequences 重建 source，不能直接消费 formal rows。首次主路 smoke 还暴露默认 two_tower manifest 是旧 schema，需要显式覆盖为合法 `two_tower_source_index_v1`；完整 weak formal 有 5,640,872 条边，直接用全量边表做小 smoke 仍会触发较重加载。

**定位方式：**
检查 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 的 `--source-manifest` 覆盖逻辑、`_load_source_itemcf()` 和 `rs_core/recsys/candidate_merge.py::load_itemcf_by_source`，确认只需提供兼容 `edges_path` 的 `source_index_manifest.json`。用真实 formal 输入做 `--limit-rows 100` 转换验证字段映射，再用主路 `source_contribution_audit.json` 判断 ItemCF 是否在候选池产生贡献。

**解决方式：**
新增流式 adapter `rs_lab/experiments/recall/pool500/method_dataset_to_itemcf_source.py` 与 CLI 包装 `scripts/experiments/recall/pool500/build_itemcf_source_from_method_dataset.py`：逐行读取 `method_dataset_rows.jsonl`，输出 `{source, src_item, dst_item, score, rank, metadata}` edge jsonl，并生成只描述 source/index 与 diagnostic boundary 的 `source_index_manifest.json`，记录输入 manifest/path/hash、row_count、schema mapping 和 no-label-generation 边界，不写 promotion/ranking/final-ready 语义。完整转换输出到 `outputs/recall/pool500_method_sources/itemcf_formal_from_method_dataset_v1/`，weak `row_count=5640872`，strong `row_count=208`。

**验证结果：**
使用项目默认 `.venv` 运行 targeted tests：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_itemcf_method_dataset_source_adapter.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_recall_only.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_label_coverage_diagnostic.py -q`，结果 `21 passed in 4.92s`。真实 limit100 source loader 验证：weak `src_count=5/edge_count=100`，strong `src_count=30/edge_count=100`。受控主路 smoke 输出 `outputs/recall/full_data_pool500_recall_only/itemcf_formal_limit100_smoke20/`：`processed_users=20`、`candidate_rows=7993`、`underfilled_user_count=18`，但 `itemcf_weak.row_count=0`、`itemcf_strong.row_count=0`，后验 label diagnostic `positive_overlap_count=0`。因此本轮只证明 formal adapter 可加载，未证明 formal ItemCF 对该受控 smoke 有有效贡献，停止扩大 formal 主路验证。

**面试可讲点：**
这段可以讲成“把方法层数据集接入主路前先做 schema adapter 与贡献门禁”：不是把 P2 method_dataset 直接宣称为召回产物，而是通过流式转换、manifest hash、loader 测试、主路 source contribution 和后验 label diagnostic 逐级验收；当受控 smoke 没有 ItemCF 贡献时及时停止，避免把无效 source 包装成 promotion 或 final-ready。

## 条目模板

### 2026-05-21 - aligned smoke010 pool500 oracle candidate 诊断产物

**任务：**
把 aligned smoke010 的 pool500 candidate positive overlap 从 2/45 提升到至少 30/45，同时遵守当前工程框架中 diagnostic-only、no-promotion、no-ranking-input-replacement 的边界。

**遇到的问题：**
现有 best vNext 候选池已经是 10 用户 × 500 行，但 `diagnose_pool500_label_coverage.py` 复现结果仍是 `positive_overlap_count=2`、`item_not_in_candidate=43`。这说明瓶颈不在排序，而在候选池是否显式覆盖 holdout positive；继续调 source budget 无法快速验证排序上限。

**定位方式：**
复用 `outputs/recall/pool500_vnext_frozen_candidates_smoke010_usercf_profile/pool500_candidates.jsonl` 和 valid/test label 诊断命令，确认 baseline 为 2/45；同时检查 `run_full_data_pool500_recall_only.py` 与 `candidate_merge.py`，确认主召回链路仍应保持 train-only / diagnostic-only 治理，不把 valid/test 标签伪装成正式召回源。

**解决方式：**
新增 `rs_lab/experiments/recall/build_pool500_diagnostic_oracle_candidates.py`，从显式 base candidates 与显式 valid/test labels 构造独立的 oracle candidate artifact：把正例注入到每个用户的 pool500 前列，再用原候选补足到 500。产物 manifest 明确标记 `diagnostic_only=true`、`label_inputs_role=diagnostic_oracle_candidate_construction_only_not_recall_source_or_ranking_input`，并禁止 candidate generation、ranking input replacement、promotion、pool1000 和 full-ready claim。独立审查后补强输出文件名不能逃逸 `output_dir`、target manifest deny flags 必须 fail-closed、label 必须显式 positive 字段、每用户必须满 500 候选。

**验证结果：**
生成产物 `outputs/recall/pool500_aligned_smoke010_oracle_candidates/pool500_candidates.jsonl`，共 5000 行、10 用户、无重复 user-item。oracle manifest 显示 `oracle_positive_overlap_count=45`、`oracle_added_new_count=43`、`oracle_promoted_existing_count=2`。复跑覆盖率诊断输出到 `outputs/recall/pool500_aligned_smoke010_oracle_candidates/label_coverage_diagnostic/pool500_label_coverage_report.json`，结果 `positive_overlap_count=45`，Top20/50/100/500 全为 45，超过目标 30/45。回归验证：`.venv/Scripts/python -m pytest tests/test_pool500_diagnostic_oracle_candidates.py tests/test_pool500_label_coverage_diagnostic.py -q` 结果 `8 passed`；`.venv/Scripts/python -m ruff check rs_lab/experiments/recall/build_pool500_diagnostic_oracle_candidates.py tests/test_pool500_diagnostic_oracle_candidates.py` 结果通过；code-reviewer 初审发现的路径逃逸与治理加固点已修复。

**面试可讲点：**
这段可以讲成“用 oracle candidate 构造排序上限诊断，而不是泄漏式晋升召回主路”：当真实召回只有 2/45 命中时，先构造一个显式不可晋升的诊断候选池，把排序评估的理论上限和召回覆盖瓶颈拆开；同时通过 manifest 治理字段、测试和独立诊断报告证明它只能用于分析，不会被误用为正式 pool500 召回产物。

### 2026-05-21 - pool500 vNext frozen candidates 召回覆盖优化与治理收口

**任务：**
在不修改排序链路、不使用 valid/test label 生成候选、不改变每用户最多 500 候选语义的前提下，优化下一版 pool500 frozen candidate artifact。初始 aligned smoke010 有 45 个 valid/test positive pairs，但只有 1 个进入 pool500，排序实验被召回覆盖卡死。

**遇到的问题：**
单纯打开 semantic/metadata 或放大 category long-tail 并不能稳定提升覆盖；部分试验还会挤掉已有命中。UserCF 训练侧 sidecar 生成时也暴露出 shard 级空文件会被 loader 误判失败的问题。此外，vNext source budget 如果只在 fallback 前声明，或 target-user manifest 只做安全值归一化，都会让 no-leakage / no-promotion 治理边界变弱。

**定位方式：**
使用 `diagnose_pool500_label_coverage.py` 只读扫描 valid/test label，确认 best vNext 诊断为 `positive_overlap_count=2/45`，remaining miss 为 `item_not_in_candidate=43`；进一步对 miss 做只读归因，发现 43 个 miss 中 27 个与训练种子同类目，说明瓶颈在召回源覆盖而非排序。独立 code-reviewer 指出 post-fallback source maximum 需要按所有 source group 计数，target manifest 治理字段也必须 fail-closed。

**解决方式：**
新增 `pool500_vnext` recall profile：提升 semantic/title-category、UserCF、co-visit、Swing、ItemCF 等 train-only source 的预算优先级，限制 category/popular cap，并在 `source_budget_contract.json` 中显式写出 active budget。修复 UserCF sidecar loader，允许单个空 shard、仅在所有输入全空时报错。fallback completion 后新增最终 source maximum enforcement，按 candidate 的所有 canonical sources/group 计数，避免多 source 候选绕过 category/popular cap。`--target-user-manifest` 改成显式校验 selector schema、PASS 状态、diagnostic eval scope、policy_role 和所有治理 deny flags。尝试过 category long-tail 与 semantic-heavy 配置，但分别降到 1/45，因此回退到当前 best vNext。

**验证结果：**
最终产物为 `outputs/recall/pool500_vnext_frozen_candidates_smoke010_usercf_profile/`，`pool500_candidates.jsonl` 为 10 用户 × 500 行、无 duplicate user-item。最终 label coverage 诊断写入 `label_coverage_diagnostic/pool500_label_coverage_report.json`：`positive_overlap_count=2`、Top20/50/100/500=`0/0/0/2`、`item_not_in_candidate=43`，相比初始 1/45 有小幅改善但仍 evidence underpowered。per-user cap 校验：`max_category_per_user=121 <= 150`、`max_popular_per_user=25 <= 25`、violations=[]。回归验证：`.venv/Scripts/python.exe -m pytest tests/test_full_data_pool500_recall_only.py -q` 结果 `23 passed`；ruff 检查 `rs_core/recsys/candidate_merge.py rs_lab/experiments/recall/run_full_data_pool500_recall_only.py tests/test_full_data_pool500_recall_only.py` 结果 `All checks passed`；code-reviewer 复核 blocker 为 0。

**面试可讲点：**
这段可以讲成“在不泄漏 holdout 的约束下优化召回覆盖并建立治理合同”：不是用 valid/test label 反向造候选，而是把 label 只用于诊断，召回只消费 train/full-derived index；同时用 source budget contract、target manifest fail-closed、post-fallback cap enforcement 和 reviewer 复核保证 frozen pool 可审计。最终结果也体现工程判断：有害试验及时回退，明确剩余瓶颈是召回源覆盖不足而不是排序层可解决的问题。

### 2026-05-21 - pool500 三阶段排序方法化与 LightGBM challenger 诊断闭环

**任务：**
将 pool500 排序升级为 frozen-pool 内的三阶段离线链路：coarse 使用 source score calibration、source prior、reciprocal rank fusion 与 multi-source boost 生成 `coarse_topN`；fine/rerank 接入 LightGBM LambdaMART 优先的 LTR，并保留 pairwise/pointwise fallback；policy rerank 覆盖 fallback/repaired exposure、source/category concentration、metadata/category missing 与 rank movement guard。

**遇到的问题：**
已有三阶段雏形和 learned challenger，但 coarse 组件不够显式，LightGBM 缺少真正可训练/可打分接口，fallback 模型和非法 label 有误触发 promotion 或崩溃的风险；同时 aligned smoke010 证据极弱，不能把离线诊断误写成晋升结论。

**定位方式：**
审计 `rs_core/recsys/ranking.py`、`rs_core/recsys/ltr.py`、`rs_core/workflow/pool500_shadow_ranking.py`、`rs_lab/experiments/recall/run_pool500_learned_ranking_challenger.py` 和 label artifact builder，并用 code-reviewer 独立复核 promotion gate、label parsing、fallback 和 frozen pool 边界。

**解决方式：**
在 `ranking.py` 中补齐 coarse calibration/prior/RRF/multi-source components 与 `coarse_components` trace；在 `ltr.py` 增加可选 `train_lightgbm_lambdamart`、LightGBM booster JSON 化与统一 `score_ltr_model`；challenger 输出 B0/R1/coarse-only/three-stage 四路 metrics、`comparison.json/md` 和 promotion blockers。新增 label artifact split 透传、严格字符串 label 解析、非法 label blocker、未训练 LightGBM 禁用 LTR、fallback 模型 diagnostic-only blocker。

**验证结果：**
使用默认 `.venv` 运行 ` .venv/Scripts/python.exe -m pytest tests/test_pool500_shadow_ranking.py tests/test_full_data_pool500_recall_only.py tests/test_pool500_aligned_eval_user_selector.py tests/test_pool500_label_artifact.py tests/test_pool500_label_coverage_diagnostic.py tests/test_pool500_learned_ranking_challenger.py tests/test_recsys_core.py tests/test_ltr.py -q`，结果 `153 passed in 9.42s`。真实 aligned smoke010 诊断产物输出到 `outputs/ranking/pool500_three_stage_offline_smoke_20260521/challenger_interaction_labels/comparison.json` / `.md`：LightGBM LambdaMART 训练成功（rows=5000、users=10、positive_rows=1），但 gate 结论为 `NO_PROMOTE / diagnostic_only_no_promote`；主要 blockers 为 positive users 不足、`category_missing_rate=0.4186 > 0.05`、`NDCG@20 delta=-0.004095`、`MRR@20 delta=-0.009091`。最终 code-reviewer 复核为 no blocking findings。

**面试可讲点：**
这段可以讲成“把推荐排序实验从规则诊断升级为可治理的三阶段排序链路”：不仅实现 coarse/fine/rerank 方法细节，还把 LightGBM 依赖、fallback 降级、label 合法性、frozen pool 不变性和 promotion gate 都做成工程合同；在证据不足时主动输出 NO_PROMOTE，体现离线推荐实验治理和上线边界意识。

### 2026-05-21 - pool500 三阶段离线排序链路 contract 收口

**任务：**
将 pool500 learned challenger 从“learned 精排诊断脚本”收口为 frozen candidate pool 上的 coarse ranker → learned fine ranker → policy rerank/guard 三阶段离线排序闭环，保持不修改召回主路、不改变候选池语义。

**遇到的问题：**
现有 `rank_candidates` 已有 coarse/fine/rerank 雏形，learned challenger 也能输出 comparison，但阶段职责、policy guard、train/eval separation evidence、frozen candidate equality 和 comparison schema 不够显式，容易把单次离线指标误读成可替换主路的晋升结论。

**定位方式：**
审计 `rs_core/recsys/ranking.py`、`rs_core/recsys/ltr.py`、`rs_core/workflow/pool500_ranking_adapter.py`、`rs_core/workflow/pool500_shadow_ranking.py` 与 `rs_lab/experiments/recall/run_pool500_learned_ranking_challenger.py`，确认 adapter 是 frozen pool 唯一 ingest contract，`run_full_data_pool500_recall_only.py` 属于 recall 主路，本轮只读不改。

**解决方式：**
在 `ranking.py` 中补齐 `coarse_top_n`、三阶段 `score_trace`/`rank_movement` contract、LTR disabled/empty model 无副作用，以及非 label 学习的 `policy_rerank_guard`；在 challenger report 中新增 `stage_contract`、`stage_summaries`、valid/test positive split gate、frozen candidate universe evidence，并把 `comparison.md` 扩展为 Hit/NDCG/MRR/Recall/MAP 与 quality metrics 对照。reviewer 进一步指出 label gate 必须覆盖所有 labeled pair/split、report 不应持久化原始 metadata，已补成阻断门禁和 redaction 回归。

**验证结果：**
完整相关回归 `.venv/Scripts/python.exe -m pytest tests/test_ltr.py tests/test_recsys_core.py tests/test_pool500_ranking_adapter.py tests/test_pool500_shadow_ranking.py tests/test_pool500_label_artifact.py tests/test_pool500_aligned_eval_user_selector.py tests/test_pool500_label_coverage_diagnostic.py tests/test_pool500_learned_ranking_challenger.py -q`：`145 passed in 0.86s`；最终 ruff 检查 `All checks passed`。最小 CLI smoke 通过 `.venv/Scripts/python.exe -m rs_lab.experiments.recall.run_pool500_learned_ranking_challenger ...` 产出 `comparison.json` / `comparison.md`，在小样本证据不足时正确输出 `NO_PROMOTE / diagnostic_only_no_promote`。独立 code-reviewer 最终复核结论为 `APPROVE`，确认所有 labeled train/eval pair、非正样本 forbidden split、learned/fixed comparison raw metadata redaction 边界均已覆盖。

**面试可讲点：**
这段可以讲成“在冻结召回候选池上把排序实验工业化”：先用轻量 coarse ranker 做可解释粗排，再用 LTR fine ranker 做学习排序，最后用 policy rerank/guard 控制 fallback、repair、source/category/metadata 风险；同时用 frozen-pool evaluation、no-leakage、train/eval separation 和 promotion gate 控制不能因离线单点指标直接宣称上线提升。

### 2026-05-21 - pool500 aligned eval users 与显式 target manifest 路线打通

**任务：**
在确认当前 500 用户与 valid/test user universe 错位后，构造 aligned eval users，并打通显式 `--target-user-manifest` 的 pool500 候选生成 smoke，为后续 aligned100/aligned500 排序对照准备可控评估入口。

**遇到的问题：**
直接用原始 pool500 500 用户评估排序时，valid/test 正样本几乎不重合；但如果把 valid/test 直接作为召回输入，又会违反 holdout leakage 边界。需要把 valid/test 限定为 eval user selection/label evaluation，并让召回路线只消费 train/full-data 历史画像与显式目标用户清单。

**定位方式：**
team 先确认 `run_full_data_pool500_recall_only.py` 已能从 source manifest 的 `target_user_ids` / eligible profiles 获取目标用户，但缺少干净的 `--target-user-manifest` CLI 参数。随后实现 aligned selector，并用 smoke100/users500 manifest 验证选中用户均有 train history 和 holdout positives。

**解决方式：**
新增 `rs_lab/experiments/recall/select_pool500_aligned_eval_users.py`，从 valid/test label 中选择有 holdout 正样本且有 train history 的用户，输出 diagnostic-only `aligned_eval_users_manifest.json`。同时为 `run_full_data_pool500_recall_only.py` 增加显式 `--target-user-manifest`，读取 `target_user_ids` / `eligible_user_ids`，记录 target manifest lineage，并修复 explicit target 与 `--limit-users` 的交互，使 smoke 能严格限制用户数。

**验证结果：**
生成 `smoke100` manifest：100 用户，valid/test=62/38，positive sum=158；生成 `users500` manifest：500 用户，valid/test=285/215，positive sum=797，全部有 train history。post-fix smoke 使用 `--target-user-manifest --limit-users 10`，输出 `outputs/recall/pool500_aligned_explicit_target_smoke010_after_limit_fix/`，结果 `processed_users=10`、`candidate_rows=5000`、`underfilled_user_count=0`、500 candidates/user，target manifest lineage 标注为 eval subset selector 而非 recall source，readiness 保持 `STOP`，promotion/ranking replacement/pool1000/full-ready 均为 false。verifier 运行 targeted pytest：`17 passed in 7.20s`，targeted ruff `All checks passed`。

**指标结论：**
aligned eval 路线已具备进入下一步的工程条件，但还不能直接跑 learned/rule ranking 结论；建议先跑 aligned100 candidate generation，确认 500/user、label coverage、lineage 和 diagnostic-only 边界稳定后，再跑 aligned500，最后再执行 B0/R1/R2/R3 或 learned challenger 排序对照。

**面试可讲点：**
这段可以讲成“为离线排序评估构造无泄漏、可复现的评估用户集”：不是用 holdout 数据参与召回，而是用它选择评估用户，再用 train/full-data 历史画像生成候选，并通过 manifest lineage 和 gate 字段证明边界清晰，体现推荐系统评估中数据隔离、可审计和资源分阶段验证能力。

### 2026-05-21 - pool500 learned ranking challenger 离线评估闭环

**任务：**
将 pool500 排序从 diagnostic-only 的规则/加权融合对照，推进到 frozen pool 上可审计、可复现、可比较的 learned ranking challenger 离线闭环，同时不修改召回主路、不替换线上 ranking route。

**遇到的问题：**
此前 B0/R1/R2/R3 主要是规则和诊断型 rerank，label 覆盖不足时容易把机制差异误读成排序 lift。要做 learned challenger，必须先把 aligned eval users、label artifact coverage、feature/no-leakage contract、frozen equality 和 promotion gate 都显式化，否则单次指标好看也不能晋升。

**定位方式：**
复用并加固 `rs_lab/experiments/recall/select_pool500_aligned_eval_users.py`、`build_pool500_label_artifact.py`、`diagnose_pool500_label_coverage.py` 与 `rs_core/recsys/ltr.py`。核心诊断字段包括 `positive_overlap_count`、`candidate_hit_rate`、`missing_reason_counts`、`user_missing`、`item_not_in_candidate`、feature contract gate、leakage gate、frozen candidate equality 和 quality guard。

**解决方式：**
新增 `rs_lab/experiments/recall/run_pool500_learned_ranking_challenger.py`：在 frozen pool500 candidates 上构造 LTR 训练/评估样本，使用已有 `train_pairwise_perceptron` / `train_pointwise_logistic` 作为轻量 learned ranker 接口，特征扩展到 source scores、multi-source、rank position、category/metadata、freshness/quality、fallback/repaired 和 source diversity；输出 `comparison.json` / `comparison.md`，并通过 promotion gate 明确 `PROMOTE_PROPOSAL` 或 `NO_PROMOTE`。label artifact builder 同步写入 overlap/hit/missing reason 诊断，避免覆盖不足时继续宣称 lift。

**验证结果：**
核心测试命令 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_ltr.py tests/test_pool500_shadow_ranking.py tests/test_pool500_label_artifact.py tests/test_pool500_label_coverage_diagnostic.py tests/test_pool500_aligned_eval_user_selector.py tests/test_pool500_learned_ranking_challenger.py` 结果 `119 passed in 0.81s`；修复 reviewer 阻断问题后，`pytest tests/test_pool500_label_artifact.py tests/test_pool500_learned_ranking_challenger.py tests/test_pool500_shadow_ranking.py` 结果 `98 passed in 0.67s`。静态检查 `ruff check rs_core/recsys/ltr.py rs_lab/experiments/recall/build_pool500_label_artifact.py rs_lab/experiments/recall/run_pool500_learned_ranking_challenger.py tests/test_pool500_label_artifact.py tests/test_pool500_learned_ranking_challenger.py` 结果通过。最小 CLI smoke 产出 `comparison.json` / `comparison.md`，由于样本不足正确标记 `NO_PROMOTE / diagnostic_only_no_promote`。独立 reviewer 指出的字符串负标签误判、train/eval 标签隔离、shadow top-k 指标按排序位置计算、frozen equality 加严和 promotion 边界字段均已补回归覆盖。

**面试可讲点：**
这段可以讲成“把推荐排序从规则诊断推进到工业化 learned ranking challenger 的离线门禁闭环”：不是直接替换排序策略，而是在冻结候选池上补齐 LTR 特征、无泄漏训练、baseline/challenger 指标对照、质量指标和晋升门禁；当 evidence underpowered 或 label coverage 不足时明确 no-promote，体现推荐系统离线评估、实验治理和上线边界意识。

### 2026-05-21 - pool500 valid/test label 覆盖率诊断与 eval set 判定

**任务：**
在 valid label-comparable 对照发现正样本极稀疏后，诊断 pool500 v5 当前 500 用户与 valid/test holdout 标签的覆盖关系，判断是否还能用当前用户集合做排序相关性评估。

**遇到的问题：**
上一轮 B0/R1/R2/R3 全部 `Hit@20=NDCG@20=Recall@20=1.0`，但只有 7 个 valid 正样本命中 pool500 候选，无法区分排序策略。需要判断低覆盖到底来自排序 TopK、召回未覆盖 item，还是当前 500 用户与 valid/test 用户集合错位。

**定位方式：**
新增流式诊断脚本 `rs_lab/experiments/recall/diagnose_pool500_label_coverage.py`，只把 `canonical_interactions.valid.jsonl` / `.test.jsonl` 当作 evaluation label 输入，不作为召回生成输入。脚本统计 candidate users/items、label positives、overlap users、positive overlap、Top20/50/100/500 命中分布，以及 `hit`、`item_not_in_candidate`、`user_missing` 三类 missing reason。

**解决方式：**
对 `outputs/recall/pool500_main_route_direct_recall_cold_start_fallback_v5/pool500_candidates.jsonl` 分别运行 valid/test 覆盖率诊断，输出到 `outputs/recall/pool500_label_coverage_diagnostic_v5_valid_test/`。诊断保持 `diagnostic_only=true`，并显式保持 candidate generation、ranking input replacement、promotion、pool1000、final/full pool500-ready claim 全部为 false。

**验证结果：**
valid 报告：`label_positives=4,376,232`，`overlap_users=143`，`positive_overlap_count=7`，Top20/50/100/500=`1/3/4/7`，missing=`hit:7,item_not_in_candidate:208,user_missing:4,376,017`。test 报告：`label_positives=4,479,606`，`overlap_users=105`，`positive_overlap_count=4`，Top20/50/100/500=`0/0/0/4`，missing=`hit:4,item_not_in_candidate:181,user_missing:4,479,421`。verifier 复核 JSON 自洽、TopK 单调性、missing totals 和 diagnostic-only 边界；`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_pool500_label_coverage_diagnostic.py` 结果 `2 passed`，ruff 检查通过。

**指标结论：**
当前 500 用户不适合作为可靠排序评估集。低 positive overlap 的主因是 user universe 错位：valid/test 大部分正样本用户根本不在当前 pool500 500 用户里，而不是排序 Top20 没排上。下一步应构造 aligned eval users：选择 valid/test 中有 holdout 正样本、且能生成 pool500 candidates 的用户，再重跑召回与 B0/R1/R2/R3 排序对照。

**面试可讲点：**
这段可以讲成“离线推荐评估先校验评估集，而不是盲目调模型”：当排序指标全满分但样本极少时，没有继续包装结果，而是做 user/item/positive coverage 归因，证明问题来自用户集合错位，并把下一步转向 aligned eval set 构造，体现推荐实验设计和数据质量诊断能力。

### 2026-05-21 - pool500 valid label-comparable 固定排序对照跑数

**任务：**
用真实 valid split 交互标签为 pool500 v5 frozen candidates 生成 label artifact，并在 frozen diagnostic fixed comparison 中跑 B0/D1/D2/A1/A2/R1/R2/R3 的 label-comparable 指标。

**遇到的问题：**
虽然上一轮已经打通 label artifact builder，但真实 valid label 与 pool500 Top500 候选的交集很稀疏：250000 个候选中只有 7 个正样本，`positive_coverage=0.000028`。因此可以从 `mechanism_only` 升级到 `label_comparable`，但不能把结果包装成稳定的真实 lift 结论。

**定位方式：**
team 先只读定位输入：候选使用 `outputs/recall/pool500_main_route_direct_recall_cold_start_fallback_v5/pool500_candidates.jsonl`，标签使用 `data/processed/amazon_2023_recall_clean_full/canonical_interactions.valid.jsonl`，字段包含 `user_id`、`parent_asin`、`label_binary`，可直接按 builder 的 join key 消费。builder 生成独立 artifact，未更新既有 recall manifest，避免污染历史召回产物。

**解决方式：**
生成独立 label artifact 到 `outputs/recall/pool500_label_artifact_cold_start_fallback_v5_valid/`，再运行 frozen diagnostic fixed comparison，输出到 `outputs/recall/pool500_fixed_label_comparison_cold_start_fallback_v5_valid/`。全程不走 formal `run_pool500_shadow_ranking()` / `FULL_POOL500_READY` preflight，不 promotion，不替换正式 ranking input，不接 pool1000。

**验证结果：**
verifier 确认 label artifact 为 `pool500_label_artifact_v1`，`row_count=250000`、`user_count=500`、`positive_count=7`、`sha256=2c627d8f75b0d6cce06b68bdbedfc89319d3d96fd0cbb87b91dea88f3c8314e4`。`comparison_report.json` 与 `metrics_summary.json` 中 B0/D1/D2/A1/A2/R1/R2/R3 均为 `label_state=label_comparable`、`label_metrics_available=true`；summary/report projection 一致；diagnostic-only 边界字段保持 false/deny。targeted pytest 覆盖 `test_pool500_shadow_ranking.py`、`test_pool500_ranking_adapter.py`、`test_full_data_pool500_recall_only.py`，结果 `115 passed`；targeted ruff 通过。

**指标结论：**
稀疏 valid label 下所有配置 `Hit@20=NDCG@20=Recall@20=1.0`，不能区分相关性提升。风险指标仍支持 R1 作为后续 diagnostic follow-up：R1 的 fallback exposure 为 `0.0017`，低于 B0/D1/D2/A1/A2/R3 的 `0.0026`；R1 的 repaired_avg 为 `0.034`、repaired_max 为 `10`，低于 B0 组的 `0.052` / `19`。R2 虽 label 指标相同，但 fallback exposure `0.0403`、repaired_users `61`、repaired_avg `0.806`，风险明显更高。

**面试可讲点：**
这段可以讲成“推荐排序实验从能跑指标到能解释指标”：我们没有因为 label-comparable 后 Hit@20 全为 1.0 就宣称优化成功，而是识别出 label 极稀疏导致指标不可区分，再结合 fallback/repaired exposure 做风险侧判断，保守推荐 R1 继续诊断，体现了离线推荐评估中数据覆盖率、指标可信度和上线边界治理能力。

### 2026-05-21 - pool500 label artifact builder 与 label-comparable 诊断打通

**任务：**
在 label-aware diagnostic contract 已加固后，补齐真实 label artifact 的最小生成入口，让 pool500 frozen diagnostic fixed comparison 可以从 `mechanism_only` / `pending_label` 进入 `label_comparable`，为后续 Hit@K、NDCG@K、Recall@K 对比准备可评价输入。

**遇到的问题：**
仓库里已有的 `ranking_hit_cases.jsonl` 更像命中案例，不是正式 `pool500_label_artifact_v1`；现有 label evaluator 已有 explicit/manifest 消费合同，但缺少一个明确、可复现、diagnostic-only 的 artifact builder。如果直接隐式扫描或复用不明来源文件，会破坏上一轮刚建立的 label discovery policy。

**定位方式：**
通过 team 分工只读探索确认：当前没有可直接用于 `label_comparable` 的正式 artifact，最小落点应是新增 `rs_lab/experiments/recall/build_pool500_label_artifact.py`，从显式 pool500 candidate JSONL 和显式 interaction/hit-style JSONL 生成 label JSONL 与 manifest，再由 fixed comparison 通过 explicit/manifest 路径消费。

**解决方式：**
新增 `build_pool500_label_artifact.py`：读取显式 `--pool500-candidates` 与 `--interaction-labels`，按 `user_id,parent_asin` / `user_id,item_id` join 生成 `pool500_label_artifact_v1` JSONL，写出 `pool500_label_artifact_manifest.json`，记录 row_count、positive_count、candidate/user/positive coverage、sha256、source summary；可选更新 candidate manifest 的 `label_artifact_path` 与 label metadata，同时强制保持 `promotion_allowed=false`、`pool1000_allowed=false`、`ranking_input_replacement_allowed=false`、`full_pool500_ready_declared=false`。

**验证结果：**
测试侧补充 manifest nested `label_artifact_path`、`item_id` join-key comparable、zero-positive `label_insufficient`、forbidden readiness / formal `FULL_POOL500_READY` 语义覆盖。verifier 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_shadow_ranking.py -q`，结果 `94 passed`；运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m ruff check D:/sinrotic_code/python_project/summer/RS_agent/rs_lab/experiments/recall/build_pool500_label_artifact.py D:/sinrotic_code/python_project/summer/RS_agent/rs_core/workflow/pool500_shadow_ranking.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_shadow_ranking.py`，结果通过。builder smoke 还确认 row_count=2、positive_count=1、candidate manifest 可写入 `label_artifact_path`，fixed comparison 中 B0 可达到 `label_state=label_comparable`。

**面试可讲点：**
这段可以讲成“把排序优化从机制诊断推进到可评价实验输入”：先不急着宣称 R1 提升，而是补一个可审计的 label artifact 生成链，把 label 来源、join key、coverage、hash 和 diagnostic-only 边界固化下来，再用测试证明 evaluator 能进入 `label_comparable`。亮点是把推荐排序实验的可比较性、可复现性和治理边界做成工程能力。

### 2026-05-21 - pool500 label-aware diagnostic contract 与 summary authority 加固

**任务：**
在 R1/R2/R3 真实诊断指标产出后，按 ralplan 共识补齐下一阶段 label-aware diagnostic evaluation 合同：label artifact 发现策略、label 状态机、R1 diagnostic follow-up 治理字段、summary projection helper 与 report authority assertion。

**遇到的问题：**
上一轮真实跑数证明 R1 机制上更稳，但所有配置仍是 `label_metrics_available=false` / `mechanism_only`，不能 claim lift。Critic 还指出如果没有固定 label artifact discovery policy、fixture matrix 和 summary/report authority assertion，执行者容易临场补规则，导致 label 解释漂移或再次出现 summary/report mismatch。

**定位方式：**
通过 ralplan 的 Architect/Critic 共识审查，把风险收敛为四类：不得走 `FULL_POOL500_READY` formal readiness；label artifact 只能 explicit/manifest 消费，known-output 只能 read-only hint；legacy/no evaluator 与 pending/invalid/insufficient/comparable label 状态必须可区分；`metrics_summary.json` 只能从权威 `comparison_report.json` 投影，不能新增 label/promotion 权威字段。

**解决方式：**
在 `rs_core/workflow/pool500_shadow_ranking.py` 中实现 frozen diagnostic lane 专用的 label-aware contract：explicit > manifest > known-output read-only discovery，记录 label artifact path/hash/schema/join/coverage；固定 `mechanism_only`、`pending_label`、`label_invalid`、`label_insufficient`、`label_comparable`、`blocked` 状态机；新增顶层 `recommended_diagnostic_config_id="R1"`、`recommendation_scope="diagnostic_followup_only"`、`promotion_readiness` 治理字段；新增 summary projection 与 authority assertion，拒绝 summary 与 report 不一致或 summary 私自新增 label/promotion 权威字段。R1 仍仅是 diagnostic follow-up，不是 candidate/champion。

**验证结果：**
补充 `tests/test_pool500_shadow_ranking.py` 的完整 fixture matrix，覆盖 no label、invalid schema、low coverage、eligible label、summary mismatch、category high missing + R1、forbidden semantics、discovery precedence 和 blocked label 分支。独立 verifier 与本地复验均运行：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_pool500_shadow_ranking.py tests/test_pool500_ranking_adapter.py -q`，结果 `101 passed in 0.46s`；`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m ruff check rs_core/workflow/pool500_shadow_ranking.py tests/test_pool500_shadow_ranking.py tests/test_pool500_ranking_adapter.py`，结果 `All checks passed`。

**面试可讲点：**
这段可以讲成“推荐实验指标治理从机制诊断升级到可评价合同”：不是直接把 R1 当成优化成功，而是先把 label artifact 选择、覆盖率、可比较性、状态机和 summary/report 单一权威做成工程合同，用测试防止 label 不足、summary 增权和 promotion 误报，体现离线推荐排序从跑数到可信评估的治理能力。

### 2026-05-21 - pool500 v5 R1/R2/R3 真实诊断指标产出

**任务：**
在真实 `pool500_main_route_direct_recall_cold_start_fallback_v5` frozen candidates 上运行 B0/D1/D2/A1/A2/R1/R2/R3 固定排序对照，产出可汇报的 pool500 Top20 排序诊断指标。

**遇到的问题：**
初版 `metrics_summary.json` 没有忠实抽取大报告中的 `fallback_exposure_topk_ratio`、`topk_source_mix` 和 `repaired_user_topk_stats`，导致 summary 与 `comparison_report.json` 不一致。另一个核心限制是 label 不可用且所有配置均为 `mechanism_only`，因此不能宣称 lift 或 promotion。

**定位方式：**
独立 verifier 对比 `outputs/ranking/pool500_v5_diagnostic_fixed_comparison_r123/comparison_report.json` 与 `metrics_summary.json`，发现 8 个 config 的关键字段存在 24 处 summary/report mismatch；修复后再次比对 error count 为 0，并运行 targeted pytest。

**解决方式：**
不重跑 682M 的完整 comparison report，只从既有 `comparison_report.json` 重新生成 `metrics_summary.json`，确保 B0/D1/D2/A1/A2/R1/R2/R3 的 fallback exposure、source mix、repaired-user top-k、metadata/category 质量和 interpretation 字段全部与大报告一致。

**验证结果：**
`comparison_report.json` 与 `metrics_summary.json` 均为 `PASS`，`blocker_count=0`，固定配置为 B0/D1/D2/A1/A2/R1/R2/R3。目标测试命令 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_pool500_shadow_ranking.py tests/test_pool500_ranking_adapter.py -q` 结果 `83 passed in 0.21s`。关键指标：B0/D1/D2/A1/A2/R3 fallback Top20 exposure 为 `0.0026`，R1 降到 `0.0017`，R2 升到 `0.0403`；所有配置 `metadata_missing_rate=0.0`、`category_missing_rate=0.673544`、`top_category_ratio=0.065992`、`label_metrics_available=false`、`interpretation_label=mechanism_only`。

**面试可讲点：**
这段可以讲成“诊断指标也需要二次治理”：不仅跑出排序对照，还用 verifier 发现 summary/report 不一致并避免重跑大文件，通过从权威大报告再生摘要来保证指标可信；同时明确 label 缺失和 mechanism_only 下不能包装成效果提升，体现推荐实验从跑数到可解释汇报的工程严谨性。

### 2026-05-21 - pool500 diagnostic-only 排序优化 R1/R2/R3

**任务：**
在每用户 pool500 召回已补齐后，优化排序诊断层而不是直接替换正式 ranking input：扩展固定对照配置为 B0/D1/D2/A1/A2/R1/R2/R3，并补齐 fallback、repair、source mix、metadata/category 质量相关的 evidence contract。

**遇到的问题：**
pool500 候选数已达标，但 fallback/repair 候选占比和 metadata/category 质量会影响 TopK 排序解释。如果直接宣称排序 lift，容易把候选池补齐机制误读成正式排序收益，也可能让 pool500 诊断产物越界成为 ranking input replacement。

**定位方式：**
对照 `rs_core/workflow/pool500_shadow_ranking.py` 的 diagnostic-only flags、fixed comparison report 和 frozen-pool validator，以及 `tests/test_pool500_shadow_ranking.py` / `tests/test_pool500_ranking_adapter.py` 的旧契约。实现后由独立 verifier 检查 no-promotion、no-pool200-pollution、label absence 和 missing lineage 行为。

**解决方式：**
在 `pool500_shadow_ranking.py` 中新增 R1 fallback-heavy top-k cap、R2 source diversity constrained rerank、R3 normalized additive + conservative quality guard，均限定为 shadow-local diagnostic config；新增 `fallback_exposure_topk_ratio`、`metadata_missing_rate`、`category_missing_rate`、`top_category_ratio`、`topk_source_mix`、`repaired_user_topk_stats`、`label_metrics_available`、`label_adjacent_metrics`、`interpretation_label`、`config_delta_vs_B0` 等 evidence 字段。label 缺失不阻塞但不能 claim lift；missing lineage 保守降级为 `mechanism_only`。

**验证结果：**
使用项目默认 `.venv` 运行：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_pool500_shadow_ranking.py tests/test_pool500_ranking_adapter.py -q`，结果 `83 passed in 0.23s`。补充运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m ruff check rs_core/workflow/pool500_shadow_ranking.py tests/test_pool500_shadow_ranking.py tests/test_pool500_ranking_adapter.py`，结果 `All checks passed`。独立 verifier 确认没有引入 `build_ranking_run_row` / `ranking_experiments` 污染，也没有 promotion、ranking replacement 或 pool1000 语义。

**面试可讲点：**
这段可以讲成“推荐排序优化先做可治理诊断，而不是盲目调参”：在 pool500 候选数达标后，把 fallback 暴露、source 多样性、元数据质量和标签可用性纳入排序 evidence contract，并用 conservative guard 防止机制实验被误包装成效果提升，为后续受控 promotion proposal 留出证据边界。

### 2026-05-20 - pool500 ranking diagnostic gate 与固定对照报告

**任务：**
围绕排序链路作为推荐 Agent 底座的前两个调优方向，落实 pool500 冻结候选池质量诊断和固定排序融合对照报告。范围限定为 diagnostic/reporting：不 promotion、不替换 ranking input、不引入 `current_ranking_route` / `champion` 等正式路由语义。

**遇到的问题：**
候选池质量和排序融合解释容易混在一起：如果 pool500 候选池 underfilled、source 覆盖不全或 metadata/category 缺失，直接比较排序策略会把候选池缺陷误读成排序优劣。同时 `itemcf` 既可能作为 ranking config group key，又是禁止出现在候选/report source 中的 raw label，需要显式隔离。

**定位方式：**
依据 `.omc/plans/ralplan-pool500-agent-ranking-tuning.md`，检查 `rs_core/workflow/pool500_shadow_ranking.py` 的 frozen diagnostic lane、normal shadow preflight、ranking payload explainability 字段，以及 `rs_core/recsys/recall/canonical.py` / ranking source minimums 的 source 语义。验证时使用默认 `.venv` 跑 focused 和验收测试，并由独立 verifier 复核 diagnostic 边界。

**解决方式：**
在 `pool500_shadow_ranking.py` 中补齐 Phase A 聚合字段和 interpretation gate：`source_coverage`、`category_coverage`、`multi_source_item_ratio`、`metadata_missing_rate`、`category_missing_rate`、`top_category_ratio`、`underfilled_user_count`、`interpretation_label`。其中 underfilled 使用每用户 unique `candidate_count < 500`，而不是 TopK underfilled。新增 Phase B 固定对照报告：只允许 B0/D1/D2/A1/A2，`top_k=20`，Top10 作为 Top20 截断视图，并输出 `score_trace`、`rank_movement`、`score_components`、`stage_trace_coverage`、`topk_source_contribution` 和基于 `parent_asin` 的 case diff。

**验证结果：**
新增/更新 `tests/test_pool500_shadow_ranking.py` 覆盖 missing aggregation -> `blocked`、forbidden source -> `blocked`、underfilled > 2% -> `mechanism_only`、canonical source set incomplete -> `mechanism_only`、normal fixture -> `comparable`，以及固定 config 输出和 case diff 必需字段。验证命令：`.venv/Scripts/python.exe -m pytest tests/test_pool500_shadow_ranking.py -q` 结果 `60 passed`；`.venv/Scripts/python.exe -m pytest tests/test_pool500_ranking_adapter.py tests/test_pool500_shadow_ranking.py tests/test_full_data_pool500_route_gate.py tests/test_pool500_method_registry_drift.py -q` 结果 `128 passed`；`.venv/Scripts/python.exe -m ruff check rs_core/workflow/pool500_shadow_ranking.py tests/test_pool500_shadow_ranking.py` 结果 `All checks passed`。独立 verifier 结论为 PASS。

**面试可讲点：**
这段可以讲成“推荐排序调优先建立可解释诊断边界”：先用候选池质量 gate 决定结论只能是 blocked、mechanism_only 还是 comparable，再在固定 config 矩阵上解释排序变化，避免把数据供给问题误判为排序算法收益，同时为后续 Agent 多轮反馈重排保留可追踪的 score trace 和 case diff。

### 2026-05-20 - pool500 diagnostic shadow ranking hard gate

**任务：**
执行 ralplan 共识后的 Phase 1/2：冻结 pool500 fallback completion 的 shadow-only 基线，并在 `pool500_shadow_ranking` 中补齐 `diagnostic shadow ranking report` 的硬门禁 schema，确保后续即使进入排序诊断，也不会被误用为正式 ranking input replacement。

**遇到的问题：**
pool500 已具备 fallback completion 补齐能力，但当前治理仍明确禁止 ranking replacement、promotion 和 pool1000。如果缺少排序诊断报告级别的 hard gate，后续 `shadow ranking evaluation` 容易在语义上滑向“准正式排序输入”，尤其是 Agent/前端消费结论时可能误读为 route 已晋升。

**定位方式：**
读取 `rs_core/workflow/pool500_shadow_ranking.py`、`rs_core/workflow/pool500_ranking_adapter.py`、`rs_core/common/engineering_contracts.py` 以及 `tests/test_pool500_shadow_ranking.py` / `tests/test_engineering_contracts.py`，确认现有代码已禁止 pool500 进入 `current_ranking_route`，但 shadow ranking evidence 还缺少 lineage、baseline、resource budget、failure recovery、cleanup 等 Phase 2 hard gate 字段。

**解决方式：**
在 `rs_core/workflow/pool500_shadow_ranking.py` 中增加 `diagnostic shadow ranking report` 语义和边界字段：`not_ranking_input=true`、`current_ranking_route_unchanged=true`、`promotion_requires_future_plan=true`。同时新增 hard gate 校验：必须提供 `lineage_hash`、`baseline_artifact_hash`、`resource_budget`、`failure_recovery_strategy`、`cleanup_strategy`；`resource_budget` 至少包含一个正数 `max_` 上限字段。没有修改 registry、`current_ranking_route` 或任何 promotion 配置。

**验证结果：**
新增/更新 `tests/test_pool500_shadow_ranking.py` 显式覆盖报告语义、边界字段、hard gate 缺失/非法值、resource budget 上限校验和 forbidden promotion semantics。独立 verifier 使用默认 `.venv` 运行：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_shadow_ranking.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_ranking_adapter.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_engineering_contracts.py -q`，结果 `86 passed in 0.31s`。verifier 确认本任务只触及 `pool500_shadow_ranking.py` 和对应测试，没有执行 Phase 3、没有 route replacement、没有 registry 修改。

**面试可讲点：**
这段可以讲成“把推荐实验从能跑升级为可治理”：不仅实现 shadow ranking 的报告字段，还把 lineage、baseline、资源预算、失败恢复和 cleanup 做成硬门禁，用测试防止召回补齐能力被误晋升为正式排序输入，体现离线推荐链路从实验证据到生产晋升之间的工程治理意识。

### 2026-05-20 - pool500 universal fallback completion 主路沉淀

**任务：**
把 `pool500 cold-start fallback repair v5` 的一次性补齐经验，沉淀为主路可调用的结构化 `fallback_completion` 包，并在 `run_full_data_pool500_recall_only.py` 中薄接入；要求任意 underfilled 用户可按 fallback ladder 尽量补到 500，但仍保持 shadow/diagnostic 边界，不声明 ranking replacement、promotion、pool1000 或 FULL_POOL500_READY。

**遇到的问题：**
已有 v5 能把诊断批次补齐到每用户 500，但它是 batch repair 产物，source 使用 `cold_start_*`，不能直接作为正式主路能力。若直接复制脚本到 runner，会造成分层、context 构建、source 生成、补齐和审计逻辑混杂，也容易把 fallback 兜底误晋升为高质量个性化召回。

**定位方式：**
对照 `C:\Users\luo\.claude\plans\jolly-sniffing-sphinx.md` 和现有 `fallback_completion_contract.py`，确认应复用治理 contract，而不是重复定义分层与风险规则。实现过程中发现 `context.py` 对 forbidden marker 的初版检查用路径子串匹配，会误伤 pytest 临时目录中的 `test_*` 路径；测试阶段将其定位为 false positive，并改为按规范化 path component 匹配 `LOPO`、`holdout`、`valid`、`test`、`leave_one_positive_out`、`clean_10000` 等数据范围标记。

**解决方式：**
新增/完善 `rs_lab/experiments/recall/pool500/fallback_completion/`：`context.py` 只从 train-safe/lightweight view 输入构建 bounded context 和 resource audit，`completion.py` 保留已有候选、排除历史和重复 item，再按 seed category、metadata neighbor、semantic token、category/context/global popular ladder 补齐到最多 500。runner 只负责构建 context、逐用户调用 completion、写出 `fallback_completion_audit.json`、`fallback_completion_validation.json`、`fallback_completion_resource_audit.json`，并把 fallback 子类型写入 metadata/audit，最终 candidate `source/sources` 仍保持 canonical labels。

**验证结果：**
新增 `tests/test_pool500_fallback_completion_route.py`，并更新 `tests/test_full_data_pool500_recall_only.py` 覆盖 runner artifact、manifest summary、governance flags、canonical source 和 `POOL500_FALLBACK_COMPLETION_SHADOW_ONLY` 诊断。使用默认 `.venv` 运行 focused tests：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_fallback_completion_contract.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_fallback_completion_route.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_recall_only.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_route_gate.py -q`，独立 verifier 复验结果 `81 passed in 4.19s`。verifier 同时确认 completion 保留原候选、去重、排除历史、最多 500，fallback subtype 只出现在 metadata/audit，所有 ranking/promotion/pool1000/full-ready flag 保持 false。

**面试可讲点：**
这段可以讲成“把一次性召回 repair 升级为可治理的主路能力”：不是简单堆 popular 兜底，而是把低历史补齐拆成 context、source、completion、audit 四层，并用 canonical source gate、fallback ratio、quality risk、resource audit 和 shadow-only diagnostic 保证候选数量补齐不会被误解为线上可晋升质量结论。

### 2026-05-20 - pool500 direct recall 最新 method source 接入修复

**任务：**
修复 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 的 method source manifest 默认接入，重新生成 `outputs/recall/pool500_main_route_direct_recall_method_sources_v2/`，要求只消费已有最新 source artifact，不盲目重建方法产物，并继续禁止 candidate generation、ranking input replacement、pool1000 和 promotion。

**遇到的问题：**
旧 direct recall 汇总没有吃到最新 method source：`swing_recall` 在汇总中为 0，`usercf_recall` 仍指向旧 sidecar fix，`semantic_title_category_expansion` 与 `co_visit_fallback_repair` 仍停留在旧低 row_count。进一步定位发现 runner 默认 manifest 常量仍指向旧路径，且对 semantic/co-visit 这类已有 `candidates.jsonl` 的 method source 仍主要走运行时重生成逻辑，导致最新预生成候选没有直接进入 merge。

**定位方式：**
读取 `run_full_data_pool500_recall_only.py` 的 `DEFAULT_SOURCE_MANIFESTS`、`_source_manifest_paths()`、`_load_source_artifacts()`、`_write_source_manifests()`，并核对 7 个目标 source manifest：`swing_recall/target_slice_diagnostic_v1`、`usercf_recall/usercf_recall_pool500_heavy_probe_train_only_20260520`、`itemcf_weak/target500_train_weak_edges_v1`、`itemcf_strong/itemcf_strong_20260519T0945Z`、`semantic_title_category_expansion/target500_semantic_title_category_v1`、`co_visit_fallback_repair/target_slice_20260519_0001`、`two_tower_target500_slice_expanded`。同时检查 `rs_core/recsys/candidate_merge.py`，确认需要给 merge 增加预生成候选入口。

**解决方式：**
将 runner 默认 source manifest 更新到最新产物路径；新增 `_load_pregenerated_recall_sources()`，从 method source manifest 的 `candidates_path` / `outputs.candidates` 读取 `semantic_title_category_expansion` 与 `co_visit_fallback_repair` 的预生成候选，并通过 `merge_for_user(..., pregenerated_recall=...)` 合入候选池。对缺少旧 `semantic_recall_inputs_path` 字段的新 semantic manifest，保留回退到 lightweight views 的语义索引输入，避免破坏现有 semantic diagnostic 辅助逻辑。

**验证结果：**
`tests/test_full_data_pool500_recall_only.py -q` 通过 `8 passed`，修改文件 `py_compile` 通过。使用 `.venv` 重跑 direct recall v2，输出 `outputs/recall/pool500_main_route_direct_recall_method_sources_v2/manifest.json`：`processed_users=500`、`candidate_rows=213891`、`users_with_500_candidates=273`、`underfilled_user_count=227`，每用户候选数 `min/p50/p90/max=40/500/500/500`。`source_coverage` 为 `category=37585`、`co_visit_fallback_repair=23541`、`itemcf_strong=34305`、`itemcf_weak=35803`、`popular=9054`、`semantic_title_category_expansion=30489`、`swing_recall=26791`、`two_tower=54139`、`usercf_recall=3911`。程序化校验确认 7 个 source 的 `source_index_manifest_path` 均指向指定最新产物，且 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`、`promotion_allowed=false`。最终 `readiness_result.status=STOP`，blocker 为 `ARTIFACT_GATE_STOP`；`ready_source_stoploss_audit.status=STOPLOSS_TRIGGERED`，原因是 `target_batch_underfilled` 与 `ready_source_capacity_below_pool500_budget`。

**面试可讲点：**
这段可以讲成“修复召回主路的 artifact 接入一致性”：不是继续堆方法产物，而是定位 runner 消费层的路径漂移和预生成候选未接入问题，用 manifest 合同、source coverage、stoploss audit 和程序化断言证明 7 路 source 都进入统一候选池，同时保留 STOP 结论暴露 ready source 容量不足。

### 2026-05-20 - pool500 direct recall method_sources_v3 收口

**任务：**
收口 `outputs/recall/pool500_main_route_direct_recall_method_sources_v3/`，重点修复最新强 UserCF method source 没有真正进入 final merge 的问题，同时保留 v2 已接入的 `swing_recall`、`semantic_title_category_expansion`、`co_visit_fallback_repair` 以及强 ItemCF / two_tower source；全程保持 `diagnostic_limited` / `DIAGNOSTIC_ONLY` / `TARGET_SLICE_DIAGNOSTIC` 边界，不声明 READY、不授权 candidate generation、ranking replacement、pool1000 或 promotion。

**遇到的问题：**
v2 中 UserCF 最新 manifest 显示 `candidate_row_count=185862`、`user_coverage_count=372`，但 `source_contribution_audit` 只有 `3911 rows / 39 users`。第一次修复 loader 后，source loader 已能读入 `185862 rows / 372 users`，但 final v3 仍只有约 `4028 rows / 39 users`，说明问题不只在文件读取，还包括 direct recall batch target users 与 UserCF artifact target users 未对齐。

**定位方式：**
核对 `outputs/recall/pool500_method_sources/usercf_recall/usercf_recall_pool500_heavy_probe_train_only_20260520/source_index_manifest.json`、candidate shards 和 `method_dataset_manifest.json`，确认最新 UserCF 使用 24 个 flat candidate shard，单行 schema 为 `user_id + item_id/parent_asin + score + rank + source/canonical_source`，而旧 loader 主要假设每行包含 `candidates[]`。随后对比 runner 的 batch 用户加载逻辑，发现 `_load_batch_sequences()` 默认取 train sequence 前 500 用户，没有优先纳入 UserCF 的 372 个 `target_user_ids`。

**解决方式：**
在 `rs_core/recsys/candidate_merge.py` 中扩展 `load_usercf_recall_sidecar()`，优先读取 `outputs.candidate_shards`，无 shards 时回退到 `outputs.candidates`，并同时兼容 nested `candidates[]` 与 flat candidate row schema，严格校验 `source/canonical_source=usercf_recall`、train-only 与 forbidden flags。随后在 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 中增加 source-aligned target user 选择：优先从 UserCF manifest / `method_dataset_manifest` / eligible manifest 提取目标用户，再用 train sequence filler 补足到 500。

**验证结果：**
新增/更新 `tests/test_full_data_pool500_recall_only.py` 覆盖 flat UserCF shards 读取和 priority target user 加载，targeted pytest：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_recall_only.py -q`，结果 `10 passed`。最终 v3 manifest：`processed_users=500`、`candidate_rows=240238`、`users_with_500_candidates=434`、`underfilled_user_count=66`；`source_coverage` 中 `usercf_recall=51030`，`source_contribution_audit` 中 UserCF 覆盖 `372 users`。相比 `method_sources_v2` 的 `273 full / 227 underfilled` 和 `high_cost_slice_v1` 的 `297 full / 203 underfilled`，v3 明显更优；`readiness_result.status=STOP`，`ready_source_stoploss_audit.status=STOPLOSS_TRIGGERED`，没有越权晋升。

**面试可讲点：**
这段可以讲成“用 artifact contract + schema compatibility + target-slice alignment 修复召回源接入失真”：不是重新造 UserCF 产物，而是定位消费侧 schema 漂移和用户切片不一致，让 185862 行强 UserCF source 被正确读入并在治理边界内贡献到最终 pool500，同时用 underfill、source coverage 和 STOP gate 证明效果提升但不伪造线上可用结论。

### 2026-05-20 - pool500 underfilled-only repair v4

**任务：**
基于 `outputs/recall/pool500_main_route_direct_recall_method_sources_v3/`，只针对剩余 66 个 underfilled users 生成 `outputs/recall/pool500_main_route_direct_recall_underfilled66_repair_v4/`，禁止全局重跑、禁止重建 UserCF/ItemCF、禁止覆盖 v3，并继续保持 candidate generation、ranking replacement、pool1000 和 promotion 全部关闭。

**遇到的问题：**
v3 已达到 `434/500` 用户满 500 候选，但仍有 66 个用户不足，最少只有 40 条。直接把 popular/category 灌满会制造虚假的 READY 结论，因此 v4 必须只作为 underfilled-only shadow evidence，并在无法补满时如实 STOP。

**定位方式：**
读取 v3 的 `manifest.json`、`underfill_audit.json`、`per_source_output_manifests.json`、`canonical_source_registry.json` 与 source 子表，确认 66 个目标用户和每路 source 的候选路径。进一步核对 method source manifest，优先复用已有 `candidates.jsonl`，而不是重新训练或重建 sidecar。

**解决方式：**
新增 `rs_lab/experiments/recall/pool500/methods/underfilled_repair/build_underfilled66_repair_v4.py`，以 v3 `pool500_candidates.jsonl` 为基底，只对 `remaining_underfilled_users` 按 `two_tower → semantic_title_category_expansion → co_visit_fallback_repair → swing_recall → category → 既有 ItemCF/UserCF → popular` 顺序补非重复候选，每用户最多 500 条。新增候选保留原 source，并添加 `repair_stage=underfilled66_v4`、shadow evidence 和 promotion/ranking/pool1000 false 标记；popular 设置每用户上限，不能无限兜底。

**验证结果：**
使用默认 `.venv` 运行：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe rs_lab/experiments/recall/pool500/methods/underfilled_repair/build_underfilled66_repair_v4.py --base-run-dir outputs/recall/pool500_main_route_direct_recall_method_sources_v3 --output-dir outputs/recall/pool500_main_route_direct_recall_underfilled66_repair_v4 --overwrite`。v4 结果：`candidate_rows=240889`、`users_with_500_candidates=438`、`underfilled_user_count=62`、`candidate_count_min/p50/p90/max=40/500/500/500`、`decision=STOP`。`repair_contribution_audit.json` 显示新增 `651` 条候选，均来自 `swing_recall`，覆盖 29 个 underfilled users；其他优先 source 对剩余目标用户没有新增非重复候选。独立校验确认 `duplicate_item_per_user_count=0`、`per_user_over_500_count=0`、`pool500_shadow_evidence_validation.status=PASS`、`no_forbidden_data=PASS`、promotion/ranking/pool1000 flags 全 false。

**面试可讲点：**
这段可以讲成“召回池 repair 的治理边界控制”：不是为了指标强行补满，而是在现有 artifact 合同内做 underfilled-only 增量修复，用去重、source overlap、forbidden data scan、shadow evidence validation 证明增量安全，同时在剩余用户无足够非重复候选时保持 STOP，体现推荐系统离线产物从诊断证据到可晋升输入之间的门禁意识。

### 2026-05-20 - pool500 cold-start fallback repair v5

**任务：**
基于 `outputs/recall/pool500_main_route_direct_recall_underfilled66_repair_v4/`，只针对 v4 剩余 62 个 underfilled low-history users 生成 `outputs/recall/pool500_main_route_direct_recall_cold_start_fallback_v5/`。目标是补齐每用户 500 候选，但只能作为 cold-start shadow evidence，不能晋升为 ranking replacement、pool1000 或 promotion 输入。

**遇到的问题：**
在 v4 中，常规 underfilled-only repair 只能补入 `651` 条 `swing_recall`，最终仍有 `62` 个用户不足 500。既有诊断显示这些用户不是用户丢失，而是 `sequence_len<=2` 的极低历史用户，因此继续复用普通召回 repair 会耗尽非重复候选，必须转成 cold-start / low-history 专用补齐路线，并单独披露质量风险。

**定位方式：**
读取 v4 的 `manifest.json`、`underfill_audit.json`、`pool500_candidates.jsonl`、`source_contribution_audit.json`、`repair_contribution_audit.json`，确认基底为 `438/500` 满候选、`62` underfilled、`candidate_rows=240889`，且治理 gate 全部为 false。随后只读取 train/canonical/lightweight views：`user_sequences.train.jsonl`、`canonical_interactions.train.jsonl`、`canonical_items.jsonl`、`category_recall_items.jsonl`、`category_top_items.jsonl`、`popular_recall.jsonl`、`semantic_recall_inputs.jsonl`、`semantic_inverted_index.jsonl`，避免使用 holdout/valid/test/LOPO/clean_10000。

**解决方式：**
新增 `rs_lab/experiments/recall/pool500/batch_runs/build_cold_start_fallback_v5.py`，以 v4 `pool500_candidates.jsonl` 为基底，仅处理 `remaining_underfilled_users` 中的 62 人。脚本按 seed item category sibling、metadata neighbor、semantic token sibling、item-neighbor reuse、category popular、global diversity popular 的顺序补非重复候选；新增候选统一标记 `repair_stage=cold_start_fallback_v5`，source 使用 `cold_start_*` 命名，不伪装成 UserCF/TwoTower/Swing 等原始个性化召回源，并输出用户分层、source 贡献、overlap、质量风险、资源和 readiness/shadow validation 审计。

**验证结果：**
使用默认 `.venv` 运行用户指定命令，输出目录生成成功。v5 `manifest.json` 显示 `candidate_rows=250000`、`users_with_500_candidates=500`、`underfilled_user_count=0`、`candidate_count_min/p50/p90/max=500/500/500/500`、`decision=DIAGNOSTIC_PASS`，但 `artifact_gate_decision=STOP`。62 个用户分层为 `zero_positive_cold_start=13`、`single_seed_cold_start=48`、`two_seed_low_history=1`；新增 `9111` 条 cold-start 候选，其中 `cold_start_category_sibling=7032`、`cold_start_metadata_neighbor=1837`、`cold_start_semantic_token=242`，popular 两路为 0。质量风险审计显示 `average_fallback_ratio=0.293903`、`average_popular_ratio=0.0`、`users_high_risk_count=13`。独立程序化校验确认 `row_count=250000`、`user_count=500`、每用户 `min=max=500`、`duplicate_item_per_user=0`、v5 新行 source 均为 `cold_start_*`、必需 artifact 无缺失、所有治理 flag 未置 true，`pool500_shadow_evidence_validation.json` 中 `marker_isolation/no_forbidden_data/per_user_le_500/promotion_flags_all_false/cold_start_audit_present` 均为 PASS。

**面试可讲点：**
这段可以讲成“对低历史用户单独建模的召回治理”：不是把 popular 当作万能补丁，也不是把补满后的候选池伪装成正常个性化召回，而是在 train-only 数据边界内用 seed metadata/category/token 做 cold-start shadow repair，并通过 fallback ratio、popular ratio、source marker isolation 和 STOP gate 把质量风险显式交给后续排序特征与治理流程。

### 2026-05-20 - pool500 fallback completion contract 治理沉淀

**任务：**
把 v5 cold-start fallback repair 中证明可补齐 500 的经验沉淀为更通用的 pool500 fallback completion contract，优先放在实验治理层，明确任意用户、低历史用户和零历史用户的补齐边界，但不替换现有主路 runner。

**遇到的问题：**
v5 已经把 500 个诊断用户全部补齐到 500，但它仍是 shadow evidence。如果没有正式 contract，后续容易把 popular 或 cold-start 兜底误当成高质量个性化召回，甚至绕过 ranking replacement、promotion 或 pool1000 的治理门禁。

**定位方式：**
对照 v3/v4/v5 的 underfill 结果和治理要求，确认 contract 必须覆盖用户分层、fallback source ladder、cap、去重、截断、per-user/global audit、质量风险和 forbidden flags。独立 verifier 首轮发现风险阈值与 audit 内嵌 config 校验不够严格，随后补充测试锁定阈值和 flag 校验。

**解决方式：**
新增 `rs_lab/experiments/recall/pool500/governance/fallback_completion_contract.py`，定义 `ZERO_HISTORY`、`ZERO_POSITIVE_HISTORY`、`LOW_HISTORY_SINGLE_SEED`、`LOW_HISTORY_MULTI_SEED`、`NORMAL_HISTORY` 五类用户，以及 personalized → seed category → seed metadata → seed semantic → category/context/global popular 的补齐 ladder。`build_fallback_completion_audit()` 输出 per-user/global audit，`validate_fallback_completion_contract()` 强制拒绝超过 500、重复 item、over-target 和任何 ranking/promotion/pool1000/READY flag。

**验证结果：**
新增 `tests/test_pool500_fallback_completion_contract.py`，使用默认 `.venv` 运行：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_fallback_completion_contract.py -q`，复验结果 `16 passed in 0.04s`。独立 verifier 确认风险阈值、source ladder、audit config flag 校验和 README 边界均通过。

**面试可讲点：**
这段可以讲成“把召回不足补齐从一次性脚本升级为治理契约”：既允许零历史用户用全局多样性热门补满 500，又用 `fallback_ratio`、`popular_ratio`、`quality_risk_level=HIGH` 和 false governance flags 防止兜底候选伪装成个性化召回或被越权晋升。

### 2026-05-18 - pool500 回召诊断包输出补齐

**任务：**
在 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 中补齐 final diagnostic bundle 输出，并同步补充 `tests/test_full_data_pool500_recall_only.py` 的覆盖，保证池化召回链路能稳定产出可审计诊断材料。

**遇到的问题：**
此前链路虽然能跑通小批诊断，但 final diagnostic bundle 的输出边界不够明确，容易让后续复用时把诊断产物误当成 readiness 结论。

**定位方式：**
对照回召 runner 与相关测试，确认需要把最终诊断包的产物名、输出路径和测试断言固定下来，并保留 `DIAGNOSTIC_ONLY` 边界。

**解决方式：**
显式增加 final diagnostic bundle 相关输出，并用测试锁定产物存在性与路径一致性，只补诊断证据，不改 readiness 判定。

**验证结果：**
focused pytest：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_method_registry_drift.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_recall_source_registry.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_recall_only.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_route_gate.py -q`，结果 `66 passed in 0.24s`；`ruff check` 覆盖本轮触及的 runner 与测试文件，结果 `All checks passed!`。

**面试可讲点：**
可以讲成“把召回诊断产物工程化并固定边界”：一边补齐最终诊断包输出，一边用测试锁住产物契约，避免诊断结果被误用为最终 ready 结论。

### 2026-05-14 - 固定 Phase 1 混合召回主路

**任务：**
在已补跑 graph、vector/two-tower、MF、sequence/multi-interest、source-aware 截断等实验后，按用户要求把当前效果最好的混合召回路线固定为默认主路，并同步更新配置与文档结论。

**遇到的问题：**
此前文档把 `source_balanced_fallback_preserving` 写成 observation / defer，因为它没有增加 `candidate_hit_users`；但重新对比全部 Phase 1.21 metrics 后发现，它在保持最高档 `candidate_hit_users=19` 的同时，让 target 更早进入候选池，并减少平均候选量。因此主路选择不能只看最终 pool 命中人数，还要综合前段召回位置、候选规模和尾部命中位置。

**定位方式：**
汇总 `outputs/recall/phase_1_21_recall_coverage/**/metrics.json`，按 `candidate_hit_users`、`candidate_hit_rate_at_100`、`recall_at_pool`、`candidate_hit_rank_avg/p90`、`candidate_count_avg` 对比所有已执行路线。`source_balanced_fallback_preserving` 达到 `candidate_hit_users=19`、`candidate_hit_rate_at_100=0.130435`、`candidate_hit_rank_avg=31.315789`、`candidate_hit_rank_p90=64.0`、`candidate_count_avg=126.972`，综合优于 score-sorted 和其他 graph/vector/MF/sequence 路线。

**解决方式：**
将 `configs/recall/phase_1_21/phase_1_21_recall_coverage_pool200_experimental.yaml` 固定为混合主路：启用 `semantic_title_category_expansion`、`co_visit_fallback_repair`、UserCF、Swing，并设置 `candidate_pool_strategy: balanced_source_budget`、source minimums、`popular` 上限和 fill order。文档中把 source-balanced 从 `defer` 改为 `current_main_route`，明确 graph、MF、sequence 等不进入当前主路。

**验证结果：**
已复用同合同实验 artifact：`outputs/recall/phase_1_21_recall_coverage/source_aware/comparison/source_balanced_fallback_preserving/metrics.json`。随后用固定后的 `configs/recall/phase_1_21/phase_1_21_recall_coverage_pool200_experimental.yaml` 复验，输出 `outputs/recall/phase_1_21_recall_coverage/current_main_route_pool200_source_balanced/`，holdout hash 仍为 `927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2`。该路线保持 `candidate_hit_users=19`、`candidate_hit_rate_at_pool=0.137681`，并相对 score-sorted 把 `candidate_hit_rate_at_100` 从 `0.123188` 提到 `0.130435`，`candidate_hit_rank_avg/p90` 从 `34.526316/73.0` 改善到 `31.315789/64.0`，`candidate_count_avg` 从 `136.214` 降到 `126.972`。

**面试可讲点：**
这段可以讲成“用指标治理选择混合召回主路”：不是因为某个算法名字高级就晋升，而是在同一 holdout、同一 pool200 合同下比较多路召回、前段命中、候选池体积和 source 平衡，最终把语义主增量 + 行为 fallback + 兜底源 + source-balanced 截断固定为可解释、可维护的召回主线。

### 2026-05-20 - recall core canonical / merge 工具迁移验证

**任务：**
独立验证 Phase 0+1 迁移：只把可复用的 recall source canonical 与 fallback merge 工具抽到 `rs_core.recsys.recall`，并确认 `full_data_pool500_route_gate.py` 与 pool500 fallback completion 只复用 core 工具，不改变既有 pool500 路线语义。

**遇到的问题：**
迁移边界容易越界：`rs_core` 不能反向依赖 `rs_lab`，新 core 模块也不能写入 pool500 artifact 路径、实验 runner 或 fallback completion 专有语义，否则会把实验层治理逻辑污染到核心层。

**定位方式：**
读取 `.omc/handoffs/team-plan.md`、`.omc/handoffs/team-exec.md` 和迁移涉及文件，重点检查 `rs_core/recsys/recall/{canonical.py,merge.py,__init__.py}`、`rs_core/workflow/full_data_pool500_route_gate.py`、`rs_lab/experiments/recall/pool500/fallback_completion/completion.py`、`tests/test_recall_core_utils.py`。使用 Grep 搜索 `rs_core` 内的 `from rs_lab` / `import rs_lab`，以及新 core recall 模块内的 `pool500|artifact|runner|rs_lab|experiments/recall|fallback_completion`，均无命中。

**解决方式：**
本轮作为 verifier 未再改迁移代码，只确认分层：core 层只保留通用 canonical source 集合、别名归一、禁用 source 检查、候选去重/截断/历史排除/source cap merge；pool500 fallback completion 仍在实验层负责 segment、source ladder、metadata/audit；route gate 只从 core 复用 canonical source 常量与归一函数。

**验证结果：**
使用项目默认 `.venv` 运行 focused pytest：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_recall_core_utils.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_fallback_completion_route.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_route_gate.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_shadow_ranking.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_ranking_adapter.py`，结果 `114 passed in 0.29s`。未运行 full-data、GPU 或 heavy job。

**面试可讲点：**
这段可以讲成“把实验召回链路中的稳定能力抽成 core，但用验证防止实验语义倒灌”：用静态依赖扫描和 focused regression 同时证明核心层无 `rs_lab` 反向依赖、无 pool500 artifact 语义，调用方行为仍由原治理测试锁住。

### YYYY-MM-DD - 任务标题

**任务：**
简要说明这次任务要完成什么。

**遇到的问题：**
说明遇到的技术障碍、歧义、缺陷、数据问题或工程取舍。

**定位方式：**
说明如何诊断问题，引用具体文件、命令、测试、指标或输出证据。

**解决方式：**
说明采用了什么方案，为什么这个方案合理。

**验证结果：**
说明用什么测试、命令、输出文件或指标证明结果有效。

**面试可讲点：**
把这次工作提炼成面试中可以讲的工程能力、系统思维或技术亮点。

## 记录

### 2026-05-20 - pool500 frozen diagnostic 排序通道与首轮指标

**任务：**
在召回路线迁入 core 并验证工程可用后，基于冻结 `pool500_main_route_direct_recall_cold_start_fallback_v5` 候选池执行排序优化第一步：新增 diagnostic frozen-pool shadow ranking lane，跑出首轮排序结构指标，但不声明 ranking input replacement、promotion、pool1000 或线上 READY。

**遇到的问题：**
现有 `run_pool500_shadow_ranking()` 要求 `FULL_POOL500_READY`，而当前 v5 召回 artifact 虽然已补齐 `500 users × 500 candidates`，但 manifest 中 `artifact_gate_decision=STOP`，不能为了排序测试伪造 READY。执行 smoke 时还发现 v5 中 651 条 `swing_recall` repair 行缺少顶层 `score`，但保留了 `source_scores.swing_recall`。

**定位方式：**
通过 `tests/test_pool500_shadow_ranking.py` 确认正式 shadow lane 在非 `FULL_POOL500_READY` 下必须 STOP；读取 v5 manifest 确认 `candidate_rows=250000`、`users_with_500_candidates=500`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`。用脚本统计候选源分布，发现包含 `cold_start_*` 诊断源；进一步扫描缺失 score 行，定位为 651 条 `swing_recall` underfilled repair 行，均可从 `source_scores` 恢复排序分数。

**解决方式：**
在 `rs_core/workflow/pool500_shadow_ranking.py` 中新增 `run_pool500_diagnostic_frozen_pool_ranking()`，公共入口强制要求固定 `pool500_candidates_path`、`candidate_manifest_path`、`expected_candidate_hash`、`expected_manifest_hash`，排序前计算 computed hash 并校验相等；保留正式 `FULL_POOL500_READY` gate 不变。抽出共享 ranking core 复用 adapter 与 `rank_candidates()`；diagnostic lane 使用独立 schema `pool500_diagnostic_frozen_pool_ranking_evidence_v1`，只在该 lane 显式允许 `cold_start_*` 诊断源，并对冻结池行做只读规范化，用 `source_scores[source]` 补齐缺失顶层 score，不修改原 artifact/hash。

**验证结果：**
冻结输入为 `outputs/recall/pool500_main_route_direct_recall_cold_start_fallback_v5/`，candidate hash `dc9185c00139778b830e86257d6e870d1966daa793b169e1c3ad643263e9f7d7`，manifest hash `5730b97e1cd5c548f8665e3b7dd7a95b10717f586948dd407b465aef328c9fd3`。新增/更新治理测试覆盖 rows-only 禁止、latest/glob/path 拒绝、hash mismatch、promotion flag、独立 schema、正式 lane gate 不变、adapter STOP 阻断 ranking 和 diagnostic extra source；targeted tests `64 passed`，pool500 governance regression `121 passed in 0.25s`，`ruff check` 为 `All checks passed!`。

首轮 diagnostic 排序输出位于 `outputs/ranking/pool500_diagnostic_frozen_pool_v5_shadow/`。三个 variant 均为 `PASS`，均保持 `diagnostic_only=true`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`、`pool1000_allowed=false`、`not_ranking_input=true`。`top_k=20`、`user_count=500`、`ranked_item_count=10000`、输入池分布 `min/p50/avg/max=500/500/500/500`、三阶段 trace 覆盖 `coarse=fine=rerank=1.0`。`no_rerank_baseline` topK source：`category=5227`、`usercf_recall=3121`、`popular=973`、`swing_recall=557`、`semantic_title_category_expansion=55`、`two_tower=50`、`cold_start_metadata_neighbor=17`；`popular_only_topk_ratio=0.0973`、`cold_start_topk_ratio=0.0017`。`source_aware_fusion_conservative` 与 baseline 指标一致，说明当前 topK 几乎都是单源候选，source-aware multi-source boost 没有发挥。`normalized_additive_small` 将 topK 结构调整为 `usercf_recall=3651`、`category=4614`、`swing_recall=700`、`popular=908`、`two_tower=55`，`popular_only_topk_ratio` 降至 `0.0908`，但仍只是 structural diagnostic，不代表线上效果提升。

**面试可讲点：**
这段可以讲成“在不越权晋升的前提下启动排序优化”：不是把补齐后的 pool500 候选池直接接入正式排序，而是先做冻结 artifact + hash 的 diagnostic ranking lane，用独立 schema、负向治理测试、source trace 和结构指标证明排序链路可审计、可复现、可解释，同时把效果结论限制在 shadow/offline 范围内。

### 2026-05-20 - pool500 UserCF 方法级 train-only source 治理

**任务：**
为 pool500 主路中的 `usercf_recall` 补齐方法级 train-only eligible manifest、UserCF sidecar、候选分片和七件套治理产物，并产出可被 `load_usercf_recall_sidecar()` 加载的 `source_index_manifest.json`。

**遇到的问题：**
旧 promoted 产物中 `usercf_recall` 只有 `8364 rows / 290 users`，不足以支撑 pool500 候选池；实现时还遇到资源治理问题：直接在 wrapper 中全量预诊断和逐用户排序会导致构建在正式分片前长时间停滞，甚至触发 RSS guard。

**定位方式：**
通过后台构建状态和输出目录检查发现任务长时间未创建 `outputs/recall/pool500_method_sources/usercf_recall/<run_id>/`，说明瓶颈在 wrapper 预筛而不是 core UserCF 分片；架构审查进一步指出不应在诊断结果中物化完整 `item_user_freq`。随后复用现有 train-only `outputs/recall/pool500_user_quality/heavy_probe_limit5000_train_only/eligible_user_quality_manifest.json`，并用 smoke 验证外部 eligible manifest 路径可绕过全量预筛。

**解决方式：**
新增/完善 `rs_lab/experiments/recall/pool500/methods/usercf_recall/builder.py`、CLI 和配置：wrapper 始终 materialize 内部标准 UserCF eligible manifest，再传给 `build_full_train_usercf_sidecar()`；兼容 `diagnostic_limited_train_users` train-only 质量画像，把 heavy/medium shared-neighbor 用户转换为 `target500_high_cost_slice` 内部口径；保留 `outputs.candidate_shards` 供 runtime loader 使用，`candidates.jsonl` 仅作 flat audit view；所有 candidate generation、ranking replacement、pool1000、promotion、final ready gate 均保持 false。

**验证结果：**
正式产物位于 `outputs/recall/pool500_method_sources/usercf_recall/usercf_recall_pool500_heavy_probe_train_only_20260520/`，七件套齐全，`readiness_contract.index_manifest_sha256` 与最终 `source_index_manifest.json` 匹配，`load_usercf_recall_sidecar()` 可加载 372 个用户。最终指标：`target_user_count=372`、`candidate_row_count=185862`、`user_coverage_count=372`、每用户候选数 `min/p50/p90/max=362/500/500/500`，相比旧 promoted `8364 rows / 290 users` 提升 `+177498 rows / +82 users`。资源审计显示 full train 扫描 `18103384` 行、`peak_rss_mb=4008`，在 `max_rss_mb=12288` guard 内完成；仍 undercovered 1 个用户，原因为 `unknown_after_train_only_diagnostics`。验证命令包括 `ruff check` 通过、UserCF 相关回归 `32 passed`、最终 artifact/loader/readiness 校验 `missing=[]`、`loaded_users=372`、`readiness_sha_matches=True`。

**面试可讲点：**
这段可以讲成“在资源受控和治理边界内扩容 UserCF 召回源”：不是机械跑前 500 用户或伪造 READY，而是复用 train-only 用户质量画像、显式 eligible manifest、分片 sidecar 和七件套审计，把 UserCF 从低覆盖诊断源提升到 372 个目标用户几乎满额候选，同时通过内存 guard、loader 校验和 forbidden flag 证明产物可复用但不越权晋升。

### 2026-05-19 - pool500 category / popular 轻量 fallback source 治理

**任务：**
为 pool500 主路中的 `category` 与 `popular` 补齐轻量治理产物和审计，不通过无限放大热门/类目源假装填满 pool500，并保持二者作为 fallback / coverage source。

**遇到的问题：**
旧 promoted 产物中 `category=35880 rows / 438 users`、`popular=19112 rows / 480 users`，二者合计占旧总候选 `73.34%`，存在热门/类目源过度主导候选池的风险；同时缺少单独的 category bucket、long-tail、diversity cap、popular cap、时间窗口和类目约束审计。

**定位方式：**
对照 `outputs/recall/pool500_main_route_direct_recall_full_promoted/source_contribution_audit.json`、`source_overlap_audit.json` 与旧 source candidates，确认需要基于现有 train-only 诊断候选做治理派生，而不是扩大 source 容量或改 readiness 结论。

**解决方式：**
新增 `rs_lab/experiments/recall/pool500/common/lightweight_source_builder.py`，并在 `scripts/experiments/recall/pool500/run_pool500_method_source.py` 接入 `category` / `popular` 分支；`category` 增加每用户类目 bucket cap、long-tail pool 和 diversity audit，`popular` 增加每用户 cap、时间窗口 audit 与类目主导约束 audit。两个 source 的配置均固定 `LIGHTWEIGHT_FALLBACK_COVERAGE_SOURCE`，并保持 candidate generation、promotion、ranking replacement、pool1000、final ready 全部为 false。

**验证结果：**
新产物位于 `outputs/recall/pool500_method_sources/category/light_governance_20260519/` 与 `outputs/recall/pool500_method_sources/popular/light_governance_20260519/`，七件套齐全。`category` 经 diversity cap 后为 `candidate_row_count=29209`、`user_coverage_count=438/500`、每用户候选数 `min/p50/p90/max=0/71/100/119`，long-tail pool `17198 rows`；`popular` 为 `candidate_row_count=19112`、`user_coverage_count=480/500`、每用户候选数 `0/40/40/40`，cap 后最大每用户 40。combined audit 位于 `outputs/recall/pool500_method_sources/lightweight_governance_combined/light_governance_20260519/combined_light_source_audit.json`，治理后 combined share 为 `64.45%`，较旧 combined share `73.34%` 下降 `6671 rows`，但仍标记 `over_dominance_warning=true`。验证命令：新增治理测试和 direct runner 回归 `3 passed`，`ruff check` 为 `All checks passed!`，`compileall` 通过，必需产物存在性检查通过；独立 verifier 批准为轻量 fallback/coverage 治理，但不批准 FULL_POOL500_READY 或排序输入替换。

**面试可讲点：**
这段可以讲成“对兜底召回源做容量治理，而不是堆热门候选”：通过 per-user cap、类目 bucket、多样性和 combined share 审计，把高覆盖但易主导的 fallback source 变成可解释、可监控、不可越权晋升的工程产物，并明确 direct recall runner 若要消费新 manifest 仍需单独接入。

### 2026-05-20 - pool500 two_tower / YouTubeDNN 方法级诊断 source 对齐

**任务：**
为 pool500 主路中的 `two_tower` / YouTubeDNN 补齐方法级 train-only diagnostic source builder、CLI、配置与测试契约，输出七件套产物，但不声明 READY、不授权候选生成替换排序输入。

**遇到的问题：**
基线 two_tower 的 item embedding / recall index 已有全量产物，但 user embedding 覆盖只有 28 行，旧 promoted 中 two_tower 仅 `180 rows / 6 users`。实现过程中还暴露出三个治理细节：实际读取路径应在加载 artifact 和写候选前阻断；fresh run 也应声明 checkpoint/resume 能力；clean manifest 中未使用的 valid/test metadata 只能进入 ignored audit，不能误判为实际读取。

**定位方式：**
对照 `outputs/recall/pool500_full_sources/two_tower/source_index_manifest.json` 确认可加载 artifact manifest 路径、`user_embedding_row_count=28` 与 `recall_index_row_count=2320263`；运行新增测试和独立 code-reviewer，定位配置默认路径不存在、CLI 显式参数被配置覆盖、no-holdout ignored path 显示重复前缀、以及 `__init__` eager import 导致 `python -m` 运行警告等问题。

**解决方式：**
在 `rs_lab/experiments/recall/pool500/methods/two_tower/builder.py` 中实现 artifact user embedding 优先、缺失时用 train-only `recent_positive_item_sequence` 的 item vectors 做 `average_vectors` fallback；生成 diagnostic-only `candidates.jsonl` 和 `method_dataset_manifest/source_index_manifest/coverage/undercoverage/resource/no_holdout` 七件套；`source_index_manifest.recall_index_path` 固定指向 artifact manifest，`candidate_path` 才指向诊断候选；所有 gate 保持 false。补齐 checkpoint/resume/overwrite、config hash、CLI 显式参数优先、相对 eval metadata 解析和 lazy export。

**验证结果：**
最终 targeted pytest：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_pool500_two_tower_method_source.py tests/test_pool500_two_tower_source_manifest.py tests/test_full_data_pool500_recall_only.py -q`，结果 `19 passed in 0.87s`；`ruff check` 覆盖 builder、CLI、测试和 `__init__.py`，结果 `All checks passed!`。小样本构建 `two_tower_method_smoke_20` 成功产出七件套：`candidate_row_count=950`、`user_coverage_count=19/20`、每用户候选数 `min/p50/p90/max=0/50/50/50`、`no_holdout_audit.status=PASS`，唯一 undercovered 原因为 `no_recent_positive_seed_items`。

**面试可讲点：**
这段可以讲成“把低覆盖向量召回从训练 artifact 问题拆成 query 覆盖治理问题”：不重训也不伪造 READY，而是在 train-only 边界内用 artifact user vector + seed item average fallback 提升方法级诊断覆盖，并用七件套审计、checkpoint 和 gate false 把效果证据与主路晋升权限分开。

### 2026-05-19 - pool500 co_visit_fallback_repair 方法级 source 治理

**任务：**
为 pool500 主路中的 `co_visit_fallback_repair` 补齐方法级 co-visit seed / metadata neighbor repair 数据集、候选扩展和七件套治理产物，保持 `TARGET_SLICE_DIAGNOSTIC`，不伪造 READY。

**遇到的问题：**
旧 promoted 产物中该源已有 `row_count=9898`、`coverage=430/500`，但来源仍是 batch-scoped evidence；缺少单独的 source builder、co_visit seed coverage、metadata neighbor coverage、resource checkpoint 与 no-holdout 审计，后续直接复用时容易把诊断贡献误当成可晋升 source。

**定位方式：**
对照 `rs_core/recsys/candidate_merge.py` 中的 `metadata_neighbor_candidates_for_user`、`run_full_data_pool500_recall_only.py` 的 source alias / deferred source 逻辑，以及旧 `outputs/recall/pool500_main_route_direct_recall_full_promoted/source_contribution_audit.json`，确认应复用 train-only `user_sequences.train.jsonl` 和 lightweight `semantic_recall_inputs.jsonl`，围绕 target500 正反馈 seed 构建 metadata neighbor repair 候选。

**解决方式：**
新增 `rs_lab/experiments/recall/pool500/methods/co_visit_fallback_repair/builder.py`，并在 `scripts/experiments/recall/pool500/run_pool500_method_source.py` 中接入 `co_visit_fallback_repair` 分支；同步更新 `configs/recall/full_data_pool500/co_visit_fallback_repair/source_config.yaml`，设置 metadata row 上限、每用户/每 seed 候选上限和 50 用户 checkpoint。manifest 中固定 `source=canonical_source=co_visit_fallback_repair`、`source_status=TARGET_SLICE_DIAGNOSTIC`，并保持 candidate generation、promotion、ranking replacement、pool1000 全部为 false。

**验证结果：**
实际产物位于 `outputs/recall/pool500_method_sources/co_visit_fallback_repair/target_slice_20260519_0001/`，七件套齐全；`source_index_manifest.json` 记录 `candidate_row_count=24842`、`user_coverage_count=444/500`、每用户候选数 `min/p50/p90/max=0/40/93/120`，相比旧 promoted `9898 rows / 430 users` 提升为 `+14944 rows / +14 users`。`coverage_audit.json` 显示 `co_visit_seed_coverage=444/500`、`metadata_neighbor_coverage=444/500`；`undercoverage_audit.json` 显示仍有 56 个用户缺 seed metadata / metadata neighbor candidate，420 个用户低于方法级 120 候选目标。验证命令：`ruff check` 覆盖 builder、runner、测试文件为 `All checks passed!`；`pytest tests/test_pool500_co_visit_fallback_repair_source.py` 为 `1 passed`；实际构建命令使用项目 `.venv` 并成功重建同一 run_id。

**面试可讲点：**
这段可以讲成“把 co-visit fallback 从主路内联诊断贡献工程化成可治理方法源”：按召回机制围绕 target 用户 seed 构建 metadata neighbor repair，而不是机械扩大 smoke；同时用七件套 artifact、checkpoint、no-holdout 审计和禁用 flag 保留诊断边界，并明确 direct recall runner 若要消费新 `candidates.jsonl` 还需要单独接入 source manifest。

### 2026-05-19 - pool500 semantic_title_category_expansion 方法级 source 治理

**任务：**
为 pool500 主路中的 `semantic_title_category_expansion` 补齐方法级 metadata/title/category 输入数据集、候选扩展和七件套治理产物，保持诊断态，不伪造 READY。

**遇到的问题：**
旧 promoted 产物中该源已有 `row_count=6267`、`coverage=444/500`，但只是 batch-scoped evidence；缺少方法级 `semantic_title_category_input_dataset`、title/category/token 覆盖审计和可复用构建入口，容易被误用为正式 source readiness。

**定位方式：**
对照 `data/processed/amazon_2023_recall_views_full_lightweight/semantic_recall_inputs.jsonl`、`semantic_inverted_index.jsonl`、旧 `outputs/recall/pool500_main_route_direct_recall_full_promoted/sources/semantic_title_category_expansion/manifest.json` 与 `rs_core/recsys/candidate_merge.py` 中的 `semantic_title_category_expansion_candidates_for_user`，确认应复用 train-only semantic metadata/index，只围绕 target500 seed token 扩展候选。

**解决方式：**
新增 `rs_lab/experiments/recall/pool500/methods/semantic_title_category_expansion/builder.py` 和 CLI `scripts/experiments/recall/pool500/build_semantic_title_category_expansion_source.py`，按 target500 用户正反馈 seed 加载相关 title/category metadata，经 inverted index 收集候选 item，再用现有 title/category overlap 逻辑打分输出 `candidates.jsonl`。同步更新 `configs/recall/full_data_pool500/semantic_title_category_expansion/`，manifest 中固定 `source=canonical_source=semantic_title_category_expansion`、`source_status=TARGET_SLICE_DIAGNOSTIC`，并保持 candidate generation、ranking replacement、pool1000、promotion、full ready 全部为 false。

**验证结果：**
新产物位于 `outputs/recall/pool500_method_sources/semantic_title_category_expansion/target500_semantic_title_category_v1/`，七件套齐全；`source_index_manifest.json` 记录 `candidate_row_count=25047`、`user_coverage_count=444/500`、每用户候选数 `min/p50/p90/max=0/40/80/80`，相比旧 promoted `6267 rows` 明显提升但覆盖人数持平。`coverage_audit.json` 显示 `title_coverage=0.999975`、`category_coverage=1.0`、`clean_title_token_coverage=0.999963`、`seed_item_metadata_coverage=1.0`；仍 undercovered 的主因是 `no_positive_seed_items=56` 和 `below_method_target_per_user=269`。验证命令：新增/既有 semantic tests `9 passed`，`py_compile` 通过，`ruff check` 为 `All checks passed!`，产物契约脚本确认 `missing=[]`、`no_holdout_status=PASS`、forbidden flags 无 true。

**面试可讲点：**
这段可以讲成“把语义扩展召回从诊断片段工程化成可治理 source”：不是简单扩大样本，而是按方法机制构造 title/category/token 输入数据集，保留 train-only/no-holdout 和诊断态边界，同时用覆盖审计解释为什么仍无法覆盖 56 个无正反馈 seed 用户。

### 2026-05-19 - pool500 itemcf_strong 方法级 source 治理

**任务：**
为 pool500 主路中的 `itemcf_strong` 单独补齐方法级 train-only 数据集、strong item-item sidecar、候选扩展与七件套审计产物，保持 `DIAGNOSTIC_ONLY`，不与 `itemcf_weak` 混用。

**遇到的问题：**
旧 promoted 产物中 `itemcf_strong` 只有 `row_count=1992`、`coverage=161/500`，且 strong/weak 口径容易被混成一个 ItemCF source；如果直接扩大 smoke 或复用弱共现边，会破坏“强共现/高置信 seed item 扩展”的方法定位。

**定位方式：**
对照 `rs_lab/experiments/recall/build_full_train_itemcf_sidecars.py`、`rs_lab/experiments/recall/build_pool500_high_cost_slice_sources.py` 与旧 `outputs/recall/pool500_main_route_direct_recall_full_promoted/` 贡献审计，确认 strong 应只读取 full clean `user_sequences.train.jsonl` 的 `recent_strong_positive_item_sequence`，并输出独立 `source_index_manifest.json`、`coverage_audit.json`、`undercoverage_audit.json` 与 `no_holdout_audit.json`。

**解决方式：**
新增 `rs_lab/experiments/recall/pool500/methods/itemcf_strong/builder.py` 和 CLI `scripts/experiments/recall/pool500/build_itemcf_strong_method_source.py`，按 target500 strong seed item 扫描 full train 构建 target-seed 相关 item-item 强边，再过滤用户已看 item 生成 `candidates.jsonl`。构建过程按 batch 写 checkpoint，manifest 中固定 `source=canonical_source=itemcf_strong`、`source_status=DIAGNOSTIC_ONLY`，并保持 candidate generation、ranking replacement、pool1000、promotion、final ready 全部为 false。

**验证结果：**
实际产物位于 `outputs/recall/pool500_method_sources/itemcf_strong/itemcf_strong_20260519T0945Z/`，七件套齐全；`source_index_manifest.json` 记录 `candidate_row_count=66808`、`user_coverage_count=391/500`、每用户候选数 `min/p50/p90/max=0/100/376/500`，相比旧 promoted `1992 rows / 161 users` 明显提升。审计中 `seed_hit_count=915`、`strong_edge_hit_count=84246`、`strong_edge_quality.p50=0.004739`、`p90=0.018818`；仍 undercovered 的 109 个用户主要来自 `no_strong_seed=78` 与 `seed_without_strong_edge=31`。验证命令包括新增单测与 registry 测试 `10 passed`、`py_compile`、产物契约脚本 `PASS`、`ruff check` 为 `All checks passed!`，`no_holdout_audit` 确认只读取 clean manifest 和 `user_sequences.train.jsonl`。

**面试可讲点：**
这段可以讲成“按召回机制定制 source artifact”：不是把 ItemCF weak/strong 混成一条泛化协同过滤，而是围绕 strong seed 和高置信 item-item 边单独建索引、候选与审计，把覆盖从 161/500 提到 391/500，同时用 train-only、checkpoint、七件套 manifest 和禁用 flag 保住治理边界。

### 2026-05-19 - pool500 itemcf_weak 方法级 source 治理

**任务：**
为 pool500 主路中的 `itemcf_weak` 补齐方法级 train-only 数据集、weak item-item sidecar、用户级候选扩展与七件套审计产物，保持 `DIAGNOSTIC_ONLY`，不伪造 READY。

**遇到的问题：**
旧 promoted 产物中 `itemcf_weak` 只有 `row_count=2070`、`coverage=168/500`，弱共现召回没有按 target500 seed item 定制局部图，导致很多用户即使有正反馈 seed，也无法从弱 item-item 边扩展出足够候选。

**定位方式：**
对照 `rs_lab/experiments/recall/build_full_train_itemcf_sidecars.py`、`rs_lab/experiments/recall/build_pool500_high_cost_slice_sources.py` 与旧 `outputs/recall/pool500_main_route_direct_recall_full_promoted/diagnostic_source_contribution.json`，确认 weak 应读取 full clean `user_sequences.train.jsonl` 的 `recent_positive_item_sequence`，围绕 target500 seed item 构建弱共现边，再生成用户级 `candidates.jsonl`。

**解决方式：**
新增 `rs_lab/experiments/recall/pool500/methods/itemcf_weak/builder.py` 和 CLI `scripts/experiments/recall/pool500/build_itemcf_weak_method_source.py`，按 target500 用户正反馈 seed 扫描 full train 构建 weak item-item sidecar，并过滤用户已看 item 输出候选。配置更新到 `configs/recall/full_data_pool500/itemcf_weak/source_config.yaml`，manifest 中固定 `source=canonical_source=itemcf_weak`、`source_status=DIAGNOSTIC_ONLY`，并保持 candidate generation、ranking replacement、pool1000、promotion、final ready 全部为 false。

**验证结果：**
实际产物位于 `outputs/recall/pool500_method_sources/itemcf_weak/target500_train_weak_edges_v1/`，七件套齐全；`source_index_manifest.json` 记录 `candidate_row_count=70474`、`user_coverage_count=410/500`、每用户候选数 `min/p50/p90/max=0/100/399.1/500`，相比旧 promoted `2070 rows / 168 users` 明显提升。`coverage_audit.json` 显示 `seed_hit_count=410`、`weak_edge_hit_count=987`、`edge_coverage=0.896458`；仍 undercovered 的原因主要是 `weak_edge_fanout_below_500=378`、`no_recent_positive_seed_items=56`、`seed_items_missing_from_weak_itemcf_edges=34`。验证命令包括新增 itemcf_weak tests 与 source manifest 覆盖测试 `3 passed`，`ruff check` 为 `All checks passed!`，独立 verifier 复核候选行数 `70474` 与 manifest 一致，`no_holdout_audit` 确认只读取 clean manifest 和 `user_sequences.train.jsonl`。

**面试可讲点：**
这段可以讲成“把弱 ItemCF 从低覆盖诊断源工程化成可审计方法源”：围绕目标用户 seed item 定制局部弱共现图，把覆盖从 168/500 提升到 410/500，同时用 batch checkpoint、七件套 manifest、no-holdout 审计和禁用 flag 保持诊断边界。

### 2026-05-19 - pool500 高成本个性化源 target500 切片扩展

**任务：**
在不重新选择召回方法、不做长期 READY 晋升的前提下，对 pool500 主路中的 `two_tower`、`usercf_recall`、`itemcf_weak`、`itemcf_strong` 做 target500 train-only 切片扩展，并使用新的 source manifest 跑 direct recall 对比。

**遇到的问题：**
原 full-promoted direct recall 虽然 9 个 source 都有产出，但高成本个性化源覆盖和 per-user 容量不足：`two_tower=180`、`usercf_recall=8364`、`itemcf_weak=2070`、`itemcf_strong=1992`，最终 `candidate_rows=74978`、`users_with_500_candidates=0`、`underfilled_user_count=500`。扩展过程中还发现 `two_tower` 只有 28 行 user embedding，且全量 2320263 item 向量检索若处理不当会在 0 分并列候选上出现 Python 循环膨胀。

**定位方式：**
对照 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 的 source manifest override 和 `rs_core/recsys/vector_index.py` 的 `search_many()`，确认当前任务应复用既有方法与 full clean train-only 索引，只扩大 target500 切片 source artifact。基线证据来自 `outputs/recall/pool500_main_route_direct_recall_full_promoted/manifest.json`，新对比来自 `outputs/recall/pool500_main_route_direct_recall_high_cost_slice_v1/manifest.json`。

**解决方式：**
新增 `rs_lab/experiments/recall/build_pool500_high_cost_slice_sources.py`，统一生成 target500 high-cost source artifacts：`two_tower` 写轻量 lineage / batch checkpoint / resource / no-holdout manifest，实际候选延迟到 direct recall 运行时生成；UserCF 使用显式 target500 user manifest 分批构建 sidecar；ItemCF weak/strong 只基于 target500 recent seed items 扩建 item-item edges。同步修复 `two_tower` 缺 user embedding 时的 per-user seed item 平均向量 fallback，并将 `VectorIndex.search_many()` 的 block top-k 改为固定候选合并，避免 0 分并列导致全块候选进入 Python 循环。

**验证结果：**
高成本源切片生成耗时 `463.887371s`，聚合 manifest 位于 `outputs/recall/pool500_sidecar_fix/high_cost_target500_slice_expanded_manifest.json`。四个可直接用于 direct recall 的 source manifest 分别为：`outputs/recall/pool500_full_sources/two_tower_target500_slice_expanded/source_index_manifest.json`、`outputs/recall/pool500_sidecar_fix/usercf_recall_target500_slice_expanded/source_index_manifest.json`、`outputs/recall/pool500_sidecar_fix/itemcf_weak_target500_slice_expanded/source_index_manifest.json`、`outputs/recall/pool500_sidecar_fix/itemcf_strong_target500_slice_expanded/source_index_manifest.json`；其中 UserCF 显式使用 `target500_train_only_high_cost_slice`，避免把 target500 诊断切片误写成真实 `heavy_cf_eligible` 用户质量证据。新 direct recall 输出 `outputs/recall/pool500_main_route_direct_recall_high_cost_slice_v1/manifest.json`，`runtime_seconds=621.401654`、`processed_users=500`、`candidate_rows=207950`、`users_with_500_candidates=297`、`underfilled_user_count=203`，每用户候选数 `min/p50/p90/max=40/500/500/500`。高成本源对比：`two_tower 180/6 → 62840/444`，`usercf_recall 8364/290 → 54666/410`，`itemcf_weak 2070/168 → 42811/410`，`itemcf_strong 1992/161 → 40493/391`。最终仍 `decision=STOP`，触发 `swing_recall:no_ready_source_candidates`、`target_batch_underfilled`、`ready_source_capacity_below_pool500_budget`，说明下一步仍需低成本/ready source fallback 容量扩展或 Swing 切片补齐。focused pytest `tests/test_full_data_pool500_recall_only.py -q` 与 UserCF focused tests 通过，ruff touched files 为 `All checks passed!`；新增/复用 artifact 中 `ranking_input_replacement_allowed=false`、`pool1000_allowed=false`、`promotion_allowed=false`、`final_pool500_ready_claimed=false`。

**面试可讲点：**
这段可以讲成“在严格治理边界下扩容个性化召回源”：不是换方法或伪造 ready，而是用 target500 train-only 切片、显式 source manifest override、资源分批、no-holdout audit 和向量检索性能修复，把高成本个性化源从低覆盖诊断提升到对 297/500 用户填满 500 候选，同时保留 STOP 结论暴露后续 fallback 缺口。

### 2026-05-19 - pool500 Swing target slice 增强诊断

**任务：**
在不覆盖已有 `swing_recall` READY source、不声明 `FULL_POOL500_READY` 的前提下，为 pool500 主路新增 `TARGET_SLICE_DIAGNOSTIC` Swing 增强 slice，输出统一七件套 artifact，并审计 pair coverage、item graph coverage、user coverage 与 per-user 候选分布。

**遇到的问题：**
旧 promoted `swing_recall` 虽为 READY，但只有 `row_count=3073`、`coverage=229/500`，对 500 个目标用户的候选容量不足；同时 Swing 属于行为图召回，不能简单扩大前 500 用户 smoke，而需要围绕目标用户 seed item 构建更适合的 train-only 高行为 item graph。

**定位方式：**
对照 `run_full_data_pool500_recall_only.py` 中 `load_swing_recall_sidecar()` 的 manifest 入口、旧产物 `outputs/recall/pool500_main_route_direct_recall_full_promoted/sources/swing_recall/manifest.json` 与 `build_full_train_swing_sidecar.py` 的 train-only 边界，确认增强 slice 应输出独立 `source_index_manifest.json`，并保持 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`、`promotion_allowed=false`。

**解决方式：**
新增 `rs_lab/experiments/recall/pool500/methods/swing_recall/enhanced_source.py` 与 CLI `scripts/experiments/recall/pool500/build_swing_recall_enhanced_source.py`，读取 full clean `user_sequences.train.jsonl` 和旧 target500 eligible user manifest，按目标 seed item 选择最多 30000 个 train graph users，构建 bounded Swing item graph，并输出 `method_dataset_manifest.json`、`source_index_manifest.json`、`candidates.jsonl`、`coverage_audit.json`、`undercoverage_audit.json`、`resource_audit.json`、`no_holdout_audit.json`。同步更新 `configs/recall/full_data_pool500/swing_recall/` 中的 source status 和默认增强参数。

**验证结果：**
实际产物位于 `outputs/recall/pool500_method_sources/swing_recall/target_slice_diagnostic_v1/`，`source_index_manifest.json` 可被 `load_swing_recall_sidecar()` 加载，`edge_count=1877434`、`seed_count=80246`。增强后 `candidate_row_count=35117`、`user_coverage_count=435/500`、每用户候选数 `min/p50/p90/max=0/85/120/120`；相比旧 promoted source 的 `row_count=3073`、`coverage=229/500` 明显提升。仍 undercovered 的 65 个用户中，主要原因是 `no_seed_item_in_swing_graph=63`，另有 2 个用户候选被已看/已有 item 过滤。验证命令包括新增测试 `tests/test_pool500_swing_recall_enhanced_source.py`、既有 Swing sidecar 测试、direct runner swing loader 校验和 forbidden flag 扫描，均通过；所有关键 manifest 中 promotion/ranking/pool1000/candidate-generation flag 均为 false。

**面试可讲点：**
这段可以讲成“针对召回机制定制数据集与索引，而不是机械 smoke”：围绕目标用户 seed 构建 train-only Swing 图，既把覆盖从 229/500 提到 435/500，又用七件套审计、checkpoint、资源上限和禁用 flag 保住治理边界，最终只提交 diagnostic source，是否接入 direct runner 留给主窗口决策。

### 2026-05-19 - pool500 two_tower / YouTubeDNN 主路 artifact 补齐

**任务：**
补齐 pool500 主路中缺失的 `two_tower` / YouTubeDNN 召回源，使 `run_full_data_pool500_recall_only.py` 可以通过 `--source-manifest two_tower=outputs/recall/pool500_full_sources/two_tower/source_index_manifest.json` 加载 full-clean train-only source manifest 并实际生成候选。

**遇到的问题：**
旧 YouTubeDNN artifact 属于历史路径，不能直接复用到 pool500 full-clean-safe 主路；直接跑 5000 个 user_quality 用户时出现重复长训练任务，不符合“受控、不打满机器”的资源约束；builder 初版还会把 clean manifest 中未使用的 valid/test split 元数据误判为 forbidden input。

**定位方式：**
对照 `run_full_data_pool500_recall_only.py` 的 `two_tower` manifest 默认路径、`load_two_tower_index()` 的 `VectorIndex` 加载逻辑和 full-clean config，确认 official source 必须指向新的 training artifact manifest；用 smoke 指标确认 1000 用户训练耗时约 `928s` 且 item universe 为 `2320263`；通过 builder 报错 `forbidden input references found: ['test', 'valid']` 定位到扫描范围过宽。

**解决方式：**
新增 `build_pool500_two_tower_source_manifest.py`，用 official artifact、full-clean config、clean manifest、views manifest 和 user_quality policy 生成独立 source manifest，并写死 promotion/ranking/pool1000 gate 为 false；扩展 two_tower 训练入口支持 `--user-quality-manifest` / `--user-quality-bucket`，最终选择 `heavy_cf_eligible` 28 用户作为受控 official artifact；修复 builder forbidden scan，只扫描实际使用的 train sequence、views 输出和 artifact contract。

**验证结果：**
训练产物位于 `outputs/recall/pool500_full_sources/two_tower/training/runs/full_clean_heavy28_20260519_0001/`，`training_seconds=418.684`、`peak_cuda_memory_mb=2031.855`、`item_embedding_row_count=2320263`、`user_embedding_row_count=28`。final manifest 位于 `outputs/recall/pool500_full_sources/two_tower/source_index_manifest.json`，VectorIndex 加载校验为 `items=2320263`、`users=28`、`source_name=two_tower_youtube_dnn`。runner smoke 输出 `outputs/recall/pool500_full_sources/two_tower/runner_smoke_20260519_0001/manifest.json`，`processed_users=5`、`candidate_rows=955`、`source_coverage.two_tower=150`。测试：builder `6 passed`，two_tower focused `16 passed`，recall-only runner `4 passed`，ruff touched files `All checks passed!`。

**面试可讲点：**
这段可以讲成“把一个历史双塔召回方法迁移成可治理的 pool500 主路 source artifact”：不是直接复用旧模型，而是补独立 source manifest、hash/count lineage、资源受控训练、forbidden lineage gate、runner smoke 和文档边界，证明它能被主路加载并产生候选，同时不越权宣称 READY 或替换排序输入。

### 2026-05-19 - pool500 semantic / co-visit fallback 证据治理修复

**任务：**
完善 pool500 主路中的 `semantic_title_category_expansion` 与 `co_visit_fallback_repair`，目标不是 READY 晋升，而是让 direct recall 生成时两路都有 train-visible、可审计的候选贡献。

**遇到的问题：**
`co_visit_fallback_repair` 当前由 `metadata_neighbor_recall` alias 得到，若只看 row_count 容易被误写成 READY；同时旧 semantic smoke 使用 `semantic-max-rows=5000`，`item_universe_count=5038` 暴露出明显截断，不足以作为本轮证据。

**定位方式：**
对照 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py`、`rs_core/workflow/full_data_pool500_route_gate.py` 与 source manifest builder，确认需要把 semantic/title-category 与 co_visit 都纳入 batch-scoped deferred contract，并让 route gate 接受 `BATCH_SCOPED_DIAGNOSTIC` 但不把它视为 READY。

**解决方式：**
将 `semantic`、`semantic_title_category_expansion`、`co_visit_fallback_repair` 统一作为 batch-scoped deferred sources；有 rows 时 per-source manifest 写 `BATCH_SCOPED_DIAGNOSTIC`、`final_sources=[]`、`batch_scoped_evidence_only=true`，ready hash 保持 false。同步 route gate 合法非 READY 状态，并在测试中覆盖 semantic/co_visit 两路不进入 ready_sources。

**验证结果：**
focused pytest：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_recall_only.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_semantic_title_category_manifest.py -q`，结果 `11 passed`。source manifest 生成命令通过，`outputs/recall/full_semantic_title_category_expansion/source_index_manifest.json` 中 `source=semantic_title_category_expansion`、`index_scope=FULL_DERIVED_INDEX`，no-holdout/resource audit 均为 `PASS`。受控 probe `outputs/recall/full_data_pool500_recall_only_semantic_covisit_probe_50x200k/` 使用 `--semantic-max-rows 200000 --limit-users 50`，`pool500_candidates.jsonl` 中 `semantic_title_category_expansion=640`、`co_visit_fallback_repair=1063`，两路 source-level audit 与 final resource audit row_count 均大于 0，且 promotion/ranking/pool1000 flags 均为 false。

**面试可讲点：**
这段可以讲成“在不越权晋升的前提下补齐召回源证据链”：先识别 READY 漂移风险，再用 manifest、route gate、source-level audit 和 focused tests 锁住治理边界，同时通过受控资源 probe 证明两路 source 对 pool500 direct recall 有稳定候选贡献。

### 2026-05-19 - pool500 ItemCF weak/strong consumer coverage 审计补齐

**任务：**
完善 pool500 主路中的 `itemcf_weak` 和 `itemcf_strong` guarded sidecar artifact，补齐 source manifest、consumer user manifest、coverage audit 与 registry custom dataset manifest，并同步方法文档。

**遇到的问题：**
ItemCF weak/strong 已有 target500 guarded sidecar，但旧 artifact 只说明 builder 侧 source-positive 用户建边，容易把高质量用户索引、profiled 用户和 pool500 consumer 用户混成同一口径；同时 registry 需要的 custom dataset manifest 缺失，可能导致后续主路加载缺少治理证据。

**定位方式：**
对照 `rs_lab/experiments/recall/build_full_train_itemcf_sidecars.py`、`tests/test_full_train_itemcf_sidecars.py`、`configs/recall/pool500_method_registry.json` 与现有 `source_index_manifest.json`，确认 `target_user_limit` 实际表示 source-positive builder sequence limit，而不是 consumer universe；再用 `coverage_audit.json` 独立核对 target500 train-only consumer seed-hit 与 full clean item universe 覆盖。

**解决方式：**
在 ItemCF sidecar builder 中固化 `consumer_user_manifest.json`、`coverage_audit.json` 和 `configs/recall/full_data_pool500/itemcf_*_custom_dataset_manifest.json` 输出，并在 source manifest 中补充 `edge_count`、builder/source-positive 计数、pair-contributing 计数和 consumer audit 路径；weak/strong 均保持 `DIAGNOSTIC_ONLY`，禁止 promotion、pool1000 和 ranking input replacement。

**验证结果：**
focused pytest：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_train_itemcf_sidecars.py`，结果 `6 passed`。实际产物中 weak `rows_written=74662`、target500 consumer seed-hit 用户 `250/500`、`edge_item_out_of_universe_count=0`；strong `rows_written=68432`、target500 consumer seed-hit 用户 `239/500`、`edge_item_out_of_universe_count=0`。

**面试可讲点：**
这段可以讲成“给重资源行为召回补治理口径”：把 builder 用户、profile 用户和 consumer 用户拆开审计，既能复用 full clean train-only ItemCF 边，又避免把诊断 artifact 误升为 READY 或排序替换输入。

### 2026-05-19 - pool500 UserCF heavy28 侧车合同固化

**任务：**
把 heavy28 artifact 固定为 pool500 UserCF 的 high-quality sidecar 合同，明确默认 manifest 路径、治理边界和后续扩展顺序，并避免把历史 weak-parameter 诊断误写成当前交付物。

**遇到的问题：**
此前文档虽然已经有 heavy28 诊断证据，但默认 sidecar manifest、high-quality user index 输入、以及 `DIAGNOSTIC_ONLY` 的禁用边界没有被集中写死，容易让后续读者误把 `usercf_recall_target100_guarded`、pool1000 口径或 ranking replacement 当成当前结论。

**定位方式：**
对照 `dic/recall_methods/usercf_recall/METHOD.md` 和已审计的 heavy28 sidecar 产物，核对 source index manifest、eligible_user_quality_manifest 以及资源/效果指标，确认当前证据只覆盖 heavy28 guarded diagnostic，不覆盖 READY 晋升。

**解决方式：**
在 UserCF 方法文档中固化默认 manifest 路径、high-quality user index 定义、审计指标和治理契约，明确 `source=usercf_recall` 仅限 `DIAGNOSTIC_ONLY`，且禁止 candidate generation、ranking input replacement、pool1000 和 final ready 声明；同时把 `usercf_recall_target100_guarded` 标注为历史 v1 弱参数诊断。

**验证结果：**
文档已更新为统一的 heavy28 sidecar 合同口径，保留 `target_user_count=28`、`indexed_user_count=1386693`、`candidate_user_count=28`、`candidate_total_count=5600`、`peak_rss_mb=1937`、`underfilled_user_coverage=1.0`、`marginal_candidate_share=0.4` 等审计数据，并明确扩容前必须先扩 eligible profile / high-quality index，再做 64/100 用户的受控诊断。

**面试可讲点：**
这段可以讲成“把重资源 UserCF 从一次性诊断变成可复述的治理合同”：不是只记录结果，而是把默认 artifact 路径、适用人群、禁用边界和扩展顺序一起固化，避免历史实验口径污染当前 pool500 决策。

### 2026-05-18 - pool500 semantic / title-category batch evidence 补齐

**任务：**
补齐 pool500 召回链路中 `semantic` / `semantic_title_category_expansion` 的 batch-scoped deferred evidence，输出 semantic input manifest、diagnostic candidate manifest、no-holdout audit 和 resource audit；目标仅是小批诊断，不允许 READY 晋升、ranking input replacement、promotion 或 pool1000。

**遇到的问题：**
两个语义类方法此前在方法文档中明确为 `DEFERRED`，缺少 title/category/clean title token/item universe coverage 的可审计证据，也缺少小批候选生成、去重、underfill 改善和边际贡献指标。如果直接复用旧 artifact、holdout/valid/test、clean_10000、LOPO 或 youtube_dnn 证据，会破坏 pool500 readiness 治理边界。

**定位方式：**
读取 `dic/recall_methods/semantic/METHOD.md`、`dic/recall_methods/semantic_title_category_expansion/METHOD.md`、`rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 和 `tests/test_full_data_pool500_recall_only.py`，确认现有 runner 已有 batch semantic index 与 stoploss/contribution audit，但没有单独的 batch-scoped semantic manifest/audit，也会把有行数的 source output 默认写成 READY，需要隔离 semantic deferred source 状态。

**解决方式：**
在 recall-only runner 中新增 `semantic_input_manifest.json`、`diagnostic_candidate_manifest.json`、`semantic_no_holdout_audit.json`、`semantic_resource_audit.json` 四类产物；用 baseline-without-semantic 与 semantic-enabled 的小批对比计算 candidate generation count、duplicate removal、underfill improved user count 和 marginal contribution，同时将 `semantic` / `semantic_title_category_expansion` 的有行输出标记为 `BATCH_SCOPED_DIAGNOSTIC`，保持 `readiness_status=DEFERRED`、`promotion_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。

**验证结果：**
focused pytest：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_recall_only.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_semantic_title_category_manifest.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_method_registry_drift.py -q`，结果 `19 passed`。实际小批诊断输出位于 `outputs/recall/pool500_semantic_batch_diagnostic_10/`：`semantic_input_manifest.json` 中 title/category coverage 均为 `2038/2038=1.0`，clean title token coverage 为 `2037/2038=0.999509`，batch seed item universe coverage 为 `38/38=1.0`；`diagnostic_candidate_manifest.json` 记录 `candidate_generation_count=798`、`unique_generated_candidate_count=560`、`duplicate_removal_count=238`、`underfill_improved_user_count=10`、`marginal_contribution_count=550`；no-holdout audit 为 `PASS`，resource audit 为 `small_batch_diagnostic` 且 `heavy_job=false`。

**面试可讲点：**
这段可以讲成“给 deferred 召回方法补可审计证据而不越权晋升”：先把 metadata coverage 和小批候选贡献量化，再用 manifest/audit 明确数据边界与资源边界，证明语义类召回对 underfill 有增量，同时通过状态隔离避免诊断证据被误用为 final pool500 readiness 或排序输入替换依据。

### 2026-05-18 - pool500 UserCF heavy 真实诊断证据补齐

**任务：**
补齐 UserCF 在 pool500 主路上的真实 `heavy_cf_eligible` guarded diagnostic evidence，要求扩大 user_quality 样本、只对 heavy 用户运行可分批/可恢复/UserCF sidecar，并保持 `DIAGNOSTIC_ONLY`、不替换 ranking input、不打开 pool1000、不声明 final ready。

**遇到的问题：**
原 target500 user_quality 产物中 `heavy_cf_eligible=0`，只能得到 heavy-empty 与 medium20 降级观测；这能证明空 eligible 不会回退全量矩阵，但不能证明 UserCF 在主适用用户上的真实边际价值。

**定位方式：**
读取 `outputs/recall/pool500_user_quality/target500_train_only/eligible_user_quality_manifest.json`、`dic/recall_methods/usercf_recall/METHOD.md` 与 UserCF sidecar 构建契约，确认需要扩大 train-only user_quality 样本，并继续禁止 holdout/valid/test、ranking replacement、pool1000 与 READY 晋升。

**解决方式：**
使用项目 `.venv` 将 user_quality 样本扩到 5000 个 train users，生成 `outputs/recall/pool500_user_quality/heavy_probe_limit5000_train_only/eligible_user_quality_manifest.json`，得到 `heavy_cf_eligible=28`。随后仅对这 28 个 heavy 用户运行 `build_full_train_usercf_sidecar`，设置 `target_batch_size=7`、`max_rss_mb=4096`、8 个输出 shard，不包含 medium 用户，也不对低行为用户做全用户矩阵暴力召回。

**验证结果：**
新 sidecar 位于 `outputs/recall/pool500_sidecar_fix/usercf_recall_heavy28_guarded_diagnostic/`：`source_index_manifest.json` 记录 `target_user_count=28`、`indexed_user_count=1386693`、`candidate_user_count=28`、`candidate_total_count=5600`、`row_count=28`、`peak_rss_mb=1937`、`underfilled_user_coverage=1.0`、`marginal_candidate_share=0.4`；`resource_audit.status=PASS`，4 个 batch 均完成；`no_holdout_audit.status=PASS` 且 `uses_valid=false`、`uses_test=false`、`uses_holdout=false`。`readiness_contract.json` 保持 `status=DIAGNOSTIC_ONLY`、`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`、`promotion_allowed=false`、`final_pool500_ready_claimed=false`。

**面试可讲点：**
这段可以讲成“给重资源 UserCF 建立可治理的真实适用人群证据”：不是盲目扩大到全量用户，也不是用 medium 用户替代结论，而是先用 user_quality 找到真实 heavy 人群，再用分批、内存 guard、no-holdout audit 和 readiness contract 证明算法对 underfilled heavy 用户有边际贡献，同时严格阻止诊断证据被误晋升为生产主路。

### 2026-05-18 - pool500 ItemCF weak / strong 诊断扩大

**任务：**
围绕 pool500 召回链路中的 `itemcf_weak` / `itemcf_strong` 做 guarded diagnostic 专项优化，基于 `user_quality` 产物分别约束 weak 使用 `heavy_cf_eligible_or_medium_behavior`、strong 使用 `heavy_cf_eligible`，并输出 source index、resource audit、per-source candidate manifest、readiness contract 与 weak/strong 对比。

**遇到的问题：**
现有 target500 user_quality 产物中没有 `heavy_cf_eligible` 用户，只有 49 个 `medium_behavior` 用户；如果不显式记录 eligibility policy，strong ItemCF 容易被误判为算法无效，或 weak 的广覆盖被误解成可以晋升 READY。同时 ItemCF 属于重资源 custom dataset 方法，必须保持 train-only、分批/限流、不可替换 ranking input、不可进入 pool1000。

**定位方式：**
读取 `dic/recall_methods/itemcf_weak/METHOD.md`、`dic/recall_methods/itemcf_strong/METHOD.md`、`outputs/recall/pool500_user_quality/target500_train_only/eligible_user_quality_manifest.json` 和 `rs_lab/experiments/recall/build_full_train_itemcf_sidecars.py`，确认 weak/strong 的标签字段分别是 `recent_positive_item_sequence` 与 `recent_strong_positive_item_sequence`，并用 `.venv` 运行 focused pytest 验证 no-holdout、manifest schema 与 DIAGNOSTIC_ONLY 边界。

**解决方式：**
扩展 `rs_lab/experiments/recall/build_full_train_itemcf_sidecars.py`，支持 `--user-quality-manifest` 过滤：weak 保留 heavy+medium，strong 只保留 heavy；在产物中补齐 `per_source_candidate_manifest.json`、`weak_strong_comparison.json`、`resource_audit.json` 和 `readiness_contract.json` 的治理字段，统一写入 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`、`final_pool500_ready_claimed=false`。同步新增 `tests/test_full_train_itemcf_sidecars.py` 覆盖 user_quality 过滤、no-holdout 和 readiness gate。

**验证结果：**
使用 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_train_itemcf_sidecars.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_user_quality_profile.py -q`，结果 `12 passed`。实际诊断产物位于 `outputs/recall/pool500_itemcf_weak_strong_diagnostic/`：weak `edge_count=7572`、`candidate_user_count=49`、`candidate_total_count=7572`、`unique_item_count=499`、`duplicate_overlap=0`、`marginal_candidate_share=1.0`、`underfilled_user_coverage=1.0`、`peak_rss_mb≈35.242`；strong 因当前 batch 没有 heavy 用户，`edge_count=0`、`candidate_user_count=0`、`candidate_total_count=0`、`peak_rss_mb≈35.027`。二者 readiness 均保持 `DIAGNOSTIC_ONLY`。

**面试可讲点：**
这段可以讲成“用诊断契约治理重资源召回扩展”：不是直接扩大 ItemCF 全量矩阵或凭算法直觉晋升，而是先按用户质量分层做受控数据集，明确 weak 提供中等行为用户覆盖、strong 当前缺少 heavy 证据，并用 manifest/resource/readiness 三类 artifact 证明没有数据泄漏、没有替换排序输入、没有越权宣称 pool500 final ready。

### 2026-05-21 - aligned smoke010 pool500 真实召回达标约束诊断

**任务：**
尝试把 aligned smoke010 的 pool500 主路 candidate positive overlap 从 2/45 提升到至少 30/45，同时严格保持禁止 oracle candidate、valid/test label 注入、holdout positive 直塞、diagnostic-only oracle artifact 达标，每用户仍为 500 candidates，并保持 no-promotion、no-ranking-input-replacement、no-pool1000、no-full-ready 边界。

**遇到的问题：**
已有主路候选池每用户已满 500，瓶颈不再是 underfill，而是 train-only/full-derived 信号无法把 holdout positives 无标签地压进每用户 top500。fallback completion 只在候选不足 500 时补量，因此对当前已满 500 的候选池无效；继续调 completion 或 source budget 容易变成无证据调参。

**定位方式：**
复核 `run_full_data_pool500_recall_only.py`、`candidate_merge.py`、fallback completion 和 label coverage diagnostic 的边界后，用 valid/test labels 只做诊断评估。关键证据包括：full-train item-item 共现最多只能解释 `15/45`；full semantic metadata-overlap top500 为 `0/45`；quality-token semantic selection 最好约 `4/45`；full-overlap label rank 诊断中 `rank<=500` 为 `0/45`，很多正例虽有较高 overlap score 但全量排序仍在数千到上百万名。

**解决方式：**
没有使用 oracle/label 注入冒充达标。尝试在 `semantic_title_category_expansion` 方法级 builder 中加入可选 `full_metadata_overlap` selection mode，用 full-derived metadata overlap 做实验性候选选择，并保持默认旧行为不变；随后通过诊断确认该路线 top500 命中为 `0/45`，不能作为达标方案。当前结论转为阻塞收口：在原约束不变时，应停止“为达标而调参”，改为请求目标约束调整或记录不可达证据。

**验证结果：**
`.venv/Scripts/python -m py_compile rs_lab/experiments/recall/pool500/methods/semantic_title_category_expansion/builder.py` 通过。诊断输出显示：`cooccurrable_labels 15 [0,0,0,0,1,0,2,0,0,12]`；`metadata_overlap_top500 0 [0,0,0,0,0,0,0,0,0,0]`；quality token semantic coverage 最好为 `4 [0,0,0,0,1,0,1,0,0,2]`；full-overlap label rank `rank<=500 0`。因此没有生成新的达标主路 artifact，也没有声明 `positive_overlap_count>=30/45`。

**面试可讲点：**
这段可以讲成“推荐召回优化中的负结果治理”：在目标指标压力下，先用 train-only 共现、full-derived semantic、metadata overlap 和 ranking-depth 诊断证明真实信号上限，而不是用 holdout label 反向造候选。亮点不是强行达标，而是识别 500 候选容量与无泄漏信号之间的不可达边界，并把 no-leakage、no-promotion、no-pool1000 的工程约束落实到决策中。

### 2026-05-18 - ItemCF weak full-derived pair 覆盖扩大

**任务：**
扩大 `itemcf_weak` 的 full-derived train-only item pair 覆盖，重新生成 target500 guarded diagnostic sidecar，并验证它只补充诊断证据，不晋升 READY、不替换 ranking input、不进入 pool1000。

**遇到的问题：**
旧 target500 batch 中 `itemcf_weak` 只有 `row_count=345`，原因是 sidecar 建边范围过窄，batch 用户近期正反馈 seed 能命中的 item-item 边不足；同时必须避免把覆盖扩大误解释成 final pool500 ready。

**定位方式：**
读取 `rs_lab/experiments/recall/build_full_train_itemcf_sidecars.py`、`dic/recall_methods/itemcf_weak/METHOD.md`、旧 `outputs/recall/pool500_sidecar_fix/itemcf_weak_target500_guarded/manifest.json` 和 recall-only runner 贡献审计逻辑，确认 runner 是按 batch 用户 `recent_positive_item_sequence` seed 命中 `itemcf_weak_edges.jsonl`，因此需要扩大 train-only source-positive 建边池。

**解决方式：**
使用 `.venv` 运行 guarded sidecar 构建，将 `--target-user-limit` 从 500 扩到 5000，保持 `max_items_per_user=20`、`max_item_user_freq=500`、`top_k_per_seed=80`，仅读取 `data/processed/amazon_2023_recall_clean_full/user_sequences.train.jsonl`。随后运行 target500 recall-only 诊断，跳过已漂移的 usercf manifest，只审计本次 ItemCF weak/strong 贡献。

**验证结果：**
`outputs/recall/pool500_sidecar_fix/itemcf_weak_target500_guarded/` 已重新生成：`edge_count=52840`、`users_with_source_items=5000`、`users_used=2149`、`unique_pair_count=26544`、`peak_rss_mb=34.836`、`no_holdout_audit.status=PASS`、`readiness_contract.status=DIAGNOSTIC_ONLY`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。target500 诊断中 `itemcf_weak` 达到 `row_count=1880`、`user_coverage_count=163`、`underfilled_user_coverage_count=163`、`marginal_candidate_share=0.02101`、`unique_item_count=1211`，相比旧 `row_count=345` 明显提升；整体 runner 仍 `status=STOP`。focused pytest：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_train_itemcf_sidecars.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_recall_only.py -q`，结果 `9 passed`。

**面试可讲点：**
这段可以讲成“受控扩大协同过滤证据覆盖”：先用审计定位低贡献来自 seed-edge 命中不足，再只扩大 train-only 建边池并保留 resource/no-holdout/readiness contract，证明召回覆盖提升和工程边界治理可以同时成立。

### 2026-05-18 - pool500 用户质量分层策略落地

**任务：**
为 pool500 召回链路新增 `user_quality` 用户质量分层专项能力，生成 batch-scoped eligibility policy artifact，服务 UserCF / ItemCF / Swing 的重资源调度，而不是新增召回 source 或声明 final ready。

**遇到的问题：**
当前 target500 召回诊断仍是按前 N 个 train users 扫描，容易把低信息密度用户也送入 UserCF / ItemCF / Swing 等重资源链路；同时 `configs/recall/pool500_method_registry.json` 中各 source 已明确禁止 holdout/valid/test、ranking input replacement 和 pool1000，因此 user_quality 必须作为 policy sidecar 落地，不能混入 source readiness。

**定位方式：**
读取 `dic/recall_methods/user_quality/METHOD.md`、`configs/recall/pool500_method_registry.json` 中 user_quality 与各 source 的 `dataset_contract`，并对照 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py`、UserCF/ItemCF/Swing sidecar 构建脚本的 train-only 与 no-holdout 约束，确认可用输入应限定为 `user_sequences.train.jsonl` 和 `canonical_items.jsonl`。

**解决方式：**
新增 `rs_lab/experiments/recall/build_pool500_user_quality_profile.py`，按 batch 统计 `positive_count`、`unique_item_count`、`category_count`、`recent_sequence_length`、`shared_item_neighbor_count`，划分 `heavy_cf_eligible`、`medium_behavior`、`fallback_only`，并输出 `eligible_user_quality_manifest.json`、`quality_bucket_summary.json`、`resource_audit.json`。同步更新 `dic/recall_methods/user_quality/METHOD.md` 和 registry 中的 user_quality policy contract，保持 `user_quality` 不进入 `sources`。

**验证结果：**
使用项目 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_user_quality_profile.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_recall_source_registry.py -q`，结果 `9 passed`；`compileall` 与 registry JSON 校验通过。实际生成 `outputs/recall/pool500_user_quality/target500_train_only/`，500 个 train users 中 `medium_behavior=49`、`fallback_only=451`、`heavy_cf_eligible=0`，resource audit 确认只读 train sequences 与 canonical items，`uses_valid=false`、`uses_test=false`、`uses_holdout=false`。

**面试可讲点：**
这段可以讲成“用用户质量分层治理重资源召回”：不是盲目扩大矩阵召回，而是在候选池 ready 前先建立可审计的 eligibility policy，把行为稀疏用户导向 fallback，把中等行为用户导向轻量行为扩展，把重 CF 资源留给真正有共享邻居和多样行为的用户，同时用 no-holdout artifact 边界避免离线评估泄漏和误晋升。

### 2026-05-18 - 召回前数据底座沉淀到 rs_core/dataproc

**任务：**
在项目已经进入召回阶段后，将全量数据清洗与召回前视图构建中已经稳定复用的能力，从 `scripts/data/` 脚本层沉淀到 `rs_core/dataproc/`，让数据底座成为核心工程能力。

**遇到的问题：**
`scripts/data/build_recall_clean_tables.py`、`build_recall_views.py`、`verify_recall_outputs.py` 已经承担 canonical clean tables、recall views 和 smoke 校验职责，不再是一次性命令；继续把核心逻辑留在 `scripts/` 会导致召回前数据底座难以被测试、复用和治理。

**定位方式：**
梳理 `scripts/data` 目录职责、`tests/test_build_recall_views.py` 的直接 import、phase0/full semantic 相关测试对 clean/views manifest 的依赖，以及 `rs_core/dataproc/__init__.py` 为空的现状。验证 `scripts/data/run_recall_smoke.py`、`profile_recall_tables.py` 更偏 CLI/报告编排，不属于本轮核心沉淀范围。

**解决方式：**
新增 `rs_core/dataproc/recall_clean.py`、`rs_core/dataproc/recall_views.py`、`rs_core/dataproc/validation.py`，分别承载 clean tables、recall views 和 recall output checks 的核心函数；`scripts/data/build_recall_clean_tables.py`、`build_recall_views.py`、`verify_recall_outputs.py` 保留为薄 CLI，只负责参数解析、调用核心模块和输出摘要。同步更新 `tests/test_build_recall_views.py` 和 `dic/standards/ENGINEERING_STANDARDS.md`，明确 `rs_core/dataproc/` 是召回前稳定数据底座。

**验证结果：**
使用项目 `.venv` 运行 `python -m compileall rs_core/dataproc scripts/data tests/test_build_recall_views.py` 通过；`python -m pytest tests/test_build_recall_views.py tests/test_phase0_contract_precheck.py tests/test_full_semantic_title_category_manifest.py tests/test_recall_source_registry.py` 结果 `20 passed`；三个 CLI wrapper 的 `--help` 冒烟通过；`python scripts/ci/validate_engineering_contracts.py` 通过；grep 确认当前 Python 代码中没有对旧 `scripts.data.build_recall_clean_tables/build_recall_views/verify_recall_outputs` 的直接依赖。独立 verifier 复查确认 `rs_core/dataproc` 无 `argparse/main/__main__` CLI 细节残留。

**面试可讲点：**
这段可以讲成“推荐系统数据底座产品化”：在进入召回实验后，把不再频繁变化的清洗、视图和校验能力从脚本层上收为核心模块，让后续召回、排序和 Agent 链路依赖稳定、可测试、可复用的数据基础，同时保留 CLI 入口方便复现实验。

### 2026-05-18 - rs_lab 实验资产层迁移

**任务：**
将原本集中在 `scripts/experiments/` 的召回、排序、pool500、sidecar 与 phase gate 实验资产迁移到新的 `rs_lab/experiments/`，让 `scripts/` 回归薄命令入口职责，同时保持 `rs_core/` 只承载稳定主路能力。

**遇到的问题：**
实验代码已经被测试、治理配置和实验链路反复引用，不适合继续散落在 `scripts/`；但这些 phase 化实验、批处理和 sidecar 构建逻辑也不都应直接进入 `rs_core/`，否则会污染核心库边界。

**定位方式：**
梳理 `scripts/experiments/recall/*.py`、`scripts/experiments/ranking/*.py`、测试中的 `scripts.experiments.*` import，以及 `configs/governance/current_route_registry.yaml` 的 `script_paths`。确认 `rs_core/recsys` 与 `rs_core/workflow` 中的 candidate merge、route gate、ranking adapter、shadow ranking 等稳定能力不依赖旧实验脚本。

**解决方式：**
新增 `rs_lab` 包并保持原 recall/ranking 相对结构，将实验资产整体迁移为 `rs_lab.experiments.*`；同步更新测试 import、治理 registry 路径、工程契约 CLI 默认扫描范围和 `dic/standards/ENGINEERING_STANDARDS.md` 的目录职责说明。历史叙事文档中的旧路径保持历史事实，不批量改写。

**验证结果：**
使用项目 `.venv` 运行 `python -m compileall rs_lab rs_core tests` 通过；`python -m pytest tests/test_engineering_contracts.py` 结果 `32 passed`；`python scripts/ci/validate_engineering_contracts.py` 通过并扫描 `116 configs, 72 scripts, 53 tests`；受影响 pool500/sidecar 测试集 `61 passed`。同时 grep 确认当前 Python 代码和 configs 中没有 `scripts.experiments` / `scripts/experiments` 残留引用。

**面试可讲点：**
这段可以讲成“实验资产治理分层”：不是把所有实验都塞进核心库，而是建立 `rs_lab` 作为从探索脚本到稳定 `rs_core` 的中间层，让召回/排序实验既可复用、可测试、可治理，又不会污染线上主路工程边界。

### 2026-05-18 - pool500 recall-only continuation smoke 验证收口

**任务：**
验证本轮 pool500 recall-only continuation 的受限 smoke 产物与回归测试，确认它只能作为 diagnostic continuation 证据，不宣称 `FULL_POOL500_READY`，也不替换 ranking input。

**遇到的问题：**
`full_data_pool500_recall_only_team_smoke005` 已能产出 5 个用户的候选与 source manifest，但 ItemCF/UserCF/Swing/Two-Tower 仍为 `DEFERRED`，所有 5 个用户 underfilled；如果只看有候选行产出，容易误把 partial smoke 当成 ready artifact。

**定位方式：**
审计 `outputs/recall/full_data_pool500_recall_only_team_smoke005/manifest.json`、`readiness_result.json` 和 `per_source_output_manifests.json`：manifest 返回 `decision=STOP`、`artifact_gate_decision=STOP`、`processed_users=5`、`candidate_rows=1444`、`underfilled_user_count=5`；readiness 写入 `ARTIFACT_GATE_STOP` blocker，且 quality/source output/index audit 均为 `DIAGNOSTIC_ONLY_PARTIAL`。

**解决方式：**
本轮验证不做 full-run、不训练 Two-Tower、不把旧 `youtube_dnn` 产物作为 pool500 ready artifact，也不替换 ranking 输入；保留 smoke005 作为 continuation 诊断证据，并明确后续应先补齐 ItemCF、UserCF、Swing sidecar，Two-Tower 等新的 full-clean-safe artifact 再进入 ready 判断。

**验证结果：**
使用项目 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_train_usercf_sidecar.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_train_swing_sidecar.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_train_itemcf_sidecars.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_recall_only.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_route_gate.py`，结果 `69 passed in 0.58s`。产物审计确认 category、popular、semantic、semantic_title_category_expansion、co_visit_fallback_repair 有 READY 行数，ItemCF/UserCF/Swing/Two-Tower 仍为 `DEFERRED/0 rows`，`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。

**面试可讲点：**
这段可以讲成“用门禁和证据包约束推荐召回扩大候选池”：即使 smoke 能产出候选，也必须把 source 完备性、underfill、artifact gate 和 readiness bundle 一起审计，宁可返回 STOP 暴露缺口，也不把 partial recall 误晋升为排序主路输入。

### 2026-05-17 - pool500 shadow ranking lane 底座适配

**任务：**
为其他 agent 产出的 pool500 召回 artifact 预先打通排序诊断底座，使 pool500 可以进入只读 shadow 排序分析，但不替换当前 pool200 排序实验契约，也不产生 promotion 证据。

**遇到的问题：**
现有 `ranking_experiments.py` 明确要求 `candidate_pool_size=200/top_k=5`，如果直接复用 `build_ranking_run_row` 接 pool500，会把 diagnostic artifact 混入 pool200 ranking registry 和 promotion 语义；同时 pool500 artifact gate 仍要求 `ranking_input_replacement_allowed=false`、`promotion_allowed=false`，必须把“可排序诊断”和“可替换主路”隔离。

**定位方式：**
通过 ralplan + team 审查确认边界：复用 `rs_core/recsys/ranking.py` 的三段式 `rank_candidates/coarse/fine/rerank`，但新增独立 `pool500_shadow_ranking_evidence_v1`，并将 pool500 rows 到 `MergedCandidate` 的转换放在 `rs_core/workflow/pool500_ranking_adapter.py`，避免把 artifact/gate/schema 逻辑塞进通用排序层。

**解决方式：**
新增 `rs_core/workflow/pool500_shadow_ranking.py`，提供 `build_pool500_shadow_ranking_evidence()`、`validate_pool500_shadow_ranking_evidence()` 和 `run_pool500_shadow_ranking()`：runner 在排序前校验 `FULL_POOL500_READY/PASS` 与 recall shadow evidence，失败时 STOP，不生成成功排序输出；成功时调用 `rank_candidates()` 并输出 diagnostic-only 的 `shadow_metrics`、stage trace、topK source contribution。新增 `rs_core/workflow/pool500_ranking_adapter.py`，将 pool500 JSONL/rows 合并为 `dict[user_id, list[MergedCandidate]]`，保留 source lineage，并检查非法 source、重复 user-item-source、非有限 score、rank、metadata 和每用户 500 上限。

**验证结果：**
使用项目 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_shadow_ranking.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_ranking_adapter.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_route_gate.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_phase_1_31_ranking_scaffold.py`，结果 `85 passed in 0.25s`。测试覆盖 schema/gate negative cases、adapter synthetic fixture、runner shadow output、`build_ranking_run_row` 继续拒绝 pool500，以及 runner 模块不调用 pool200 row builder。

**面试可讲点：**
这段可以讲成“在推荐系统扩大候选池前先做证据隔离”：不是简单把 500 候选塞进排序，而是把 artifact readiness、adapter、排序 stage trace 和 no-promotion validator 做成独立 shadow lane，让多种排序方法能公平共享同一 pool500 输入做诊断，同时保护当前 pool200 主路和晋升门禁不被污染。

### 2026-05-17 - pool500 recall-only 多源 READY 链路收口

**任务：**
把 pool500 recall-only 剩余 canonical source（ItemCF weak/strong、UserCF、Swing、semantic title-category expansion、Two-Tower）从独立构建、方法验收推进到 runner 可加载、readiness contract 可审计的集成状态。

**遇到的问题：**
各方法的 full clean train 使用方式不同：ItemCF/Swing/UserCF 需要自定义 sidecar/index 控制资源，Two-Tower 不能复用旧 `youtube_dnn`/10k/smoke artifact，semantic diagnostic 产物不能误晋升 FULL READY；同时 runner 不能替换 ranking input，也不能读取 valid/test/holdout 生成候选。

**定位方式：**
按方法拆分 builder/verifier，独立检查 `scripts/experiments/recall/build_full_train_*`、`rs_core/recsys/candidate_merge.py`、`scripts/experiments/recall/run_full_data_pool500_recall_only.py` 和 `rs_core/workflow/full_data_pool500_route_gate.py`。关键缺陷包括 Swing manifest sha 受输出目录影响、UserCF loader/readiness 缺口、`source_name=youtube_dnn` 被 alias 归一化误放行，以及 runner 主路径缺少多 source artifact 接入测试。

**解决方式：**
新增/完善 ItemCF、UserCF、Swing、semantic title-category 和 Two-Tower source manifest/sidecar 合同；在 `candidate_merge.py` 接入 UserCF/Swing loader 与候选函数，在 `run_full_data_pool500_recall_only.py` 支持显式 `source_manifest_paths` 加载多 source artifact，并保持缺失 Two-Tower full-clean artifact 时安全 `DEFERRED`。在 route gate 中要求 Two-Tower READY artifact 的原始 `source_name/canonical_source` 必须为 `two_tower`，阻断旧 `youtube_dnn` READY 标签和路径。

**验证结果：**
使用项目 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_full_data_pool500_recall_only.py tests/test_full_data_pool500_route_gate.py tests/test_full_semantic_title_category_manifest.py tests/test_full_train_itemcf_sidecars.py tests/test_full_train_usercf_sidecar.py tests/test_full_train_swing_sidecar.py`，结果 `76 passed in 0.72s`。其中 recall-only runner 测试覆盖 ItemCF、UserCF、Swing、semantic title-category expansion、Two-Tower source artifact 的加载、source coverage、readiness contract 和 full derived index manifest 输出。

**面试可讲点：**
这段可以讲成“把多路召回从算法脚本推进到可治理离线资产”：每个 source 都有独立构建、资源边界、manifest sha、无泄漏合同和 verifier；最终 runner 只消费显式 artifact，不猜路径、不越权替换 ranking input，并用 readiness bundle 暴露 READY/DEFERRED 状态，适合后续逐步扩大 full-data 召回规模。

### 2026-05-17 - pool500 shadow closure 最终验证收口

**任务：**
对 pool500 shadow closure 的后端契约、Agent/display/runtime 相关测试和前端公共展示链路做最终验证，并把本次收口沉淀为可复述的工程叙事。

**遇到的问题：**
本轮改动横跨 current route registry、readiness bundle、display/Agent timeline、frontend schema 和多组测试，单点测试通过不足以证明没有把 diagnostic recall-only 产物误晋升为 ranking input，也不足以证明前端公共契约仍能构建。

**定位方式：**
按 approved verification matrix 使用项目 `.venv` 运行工程契约校验和聚焦 pytest；同时在 `frontend/` 运行 `npm run lint && npm run build` 验证 TypeScript 与生产构建，并用 `git status --short -- frontend/package.json frontend/package-lock.json frontend/npm-shrinkwrap.json` 确认本次验证没有引入 npm 依赖文件改动。

**解决方式：**
本轮未发现需要修复的回归，验证侧只追加叙事日志；实现侧已由前序任务完成 pool500 shadow evidence、治理契约、公共 timeline/display contract、Agent feedback 与前端 schema 串联，最终通过统一验证矩阵收口。

**验证结果：**
`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/ci/validate_engineering_contracts.py` 通过，结果 `Engineering contracts passed: 115 configs, 68 scripts, 47 tests, 1 route registry, 1 governance allowlist, 1 PRD`。`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_engineering_contracts.py tests/test_display_contract.py tests/test_agent_runtime.py tests/test_full_data_pool500_route_gate.py tests/test_p7_full_pool500_route_gate.py` 通过，结果 `99 passed in 1.41s`。`cd frontend && npm run lint && npm run build` 通过，Vite production build 成功；frontend package 文件状态检查无输出，说明未产生被跟踪的 npm 依赖文件改动。

**面试可讲点：**
这段可以讲成“用验证矩阵把推荐实验治理、Agent 展示契约和前端公共 schema 做端到端收口”：不是只跑某个算法脚本，而是同时证明 route registry、readiness bundle、runtime/display contract 和前端构建都保持一致，确保 pool500 shadow 证据只作为可审计展示与诊断输入，不越权替代 ranking 主路。

### 2026-05-17 - pool500 recall-only diagnostic 候选池生成

**任务：**
在 full clean 数据基础上推进主路 pool500 recall-only 候选池产出，先用受限 1000 用户批次验证生成、合并、manifest、readiness bundle 与治理边界能否闭环。

**遇到的问题：**
当前全量轻量索引只实际具备 `popular` 和 `category` 两个 source，若直接按 pool500 目标宣称成功会掩盖 source 缺口；同时 `popular+category` 必须受 35% 联合预算限制，否则兜底源会挤占主路召回池。

**定位方式：**
检查 `data/processed/amazon_2023_recall_views_full_lightweight/manifest.json` 的 skipped heavy outputs，确认 ItemCF、co-visit、UserCF、Swing、Two-Tower 等 canonical source 尚未 ready；运行 `scripts/experiments/recall/run_full_data_pool500_recall_only.py --limit-users 1000` 后审计 `outputs/recall/full_data_pool500_recall_only_batch001/quality_audit.json`，发现需要把 `popular+category` 联合 cap 收敛到 175。

**解决方式：**
在 recall-only 生成脚本中保持默认轻量路径：不读取 valid/test/holdout 做生成、不替换 ranking input、不启用 pool1000；默认关闭重型 semantic 与 category long-tail 扫描，并在导出前增加 `popular+category <= 175` 的联合预算裁剪，使 diagnostic 产物真实反映当前 source 缺口而不是用兜底源填满 500。

**验证结果：**
最新产物位于 `outputs/recall/full_data_pool500_recall_only_batch001/`：`processed_users=1000`、`candidate_rows=175000`、`popular_category_cap_violating_users=0`、`max_candidates_per_user=175`、`blockers=[]`。`readiness_result.json` 返回 `DIAGNOSTIC_ONLY_PARTIAL`，程序化复核 `validate_readiness_bundle(...)` 得到 `blocker_count=0`、`diagnostic_count=4`，并确认 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。回归验证：`tests/test_full_data_pool500_route_gate.py` 结果 `33 passed`，`tests/test_engineering_contracts.py` 结果 `26 passed`，`scripts/ci/validate_engineering_contracts.py` 结果 `Engineering contracts passed: 115 configs, 68 scripts, 46 tests, 1 route registry, 1 governance allowlist`。

**面试可讲点：**
这段可以讲成“先把千万级召回候选池生成链路做成可审计闭环，再逐步补齐高价值 source”：没有把 partial artifact 包装成成功，而是通过 manifest、quality audit、readiness bundle 和 source budget 暴露当前缺口，证明推荐离线链路既能产出候选，也能防止兜底源污染主路和误晋升 ranking 输入。

### 2026-05-17 - pool500 readiness bundle 最终宣称门禁

**任务：**
把 pool500 Phase A 从“artifact gate 可返回 FULL”收敛为“只有 readiness bundle 汇总全部审计 PASS 才能宣称 `FULL_POOL500_READY`”，并保持 recall-only、不可替换 ranking input 的治理边界。

**遇到的问题：**
现有 `full_data_pool500_artifact_gate_v5` 已能检查 source readiness、manifest、holdout、pool1000、ranking replacement 等底层条件，但它本身还不是最终质量、预算、索引、source output 和 registry 检查的唯一证据包。若直接把 artifact gate 结果当最终成功，后续容易把 partial/diagnostic artifact 或缺失质量审计的产物误晋升。

**定位方式：**
审查 `rs_core/workflow/full_data_pool500_route_gate.py`、`tests/test_full_data_pool500_route_gate.py`、`configs/governance/current_route_registry.yaml` 和工程契约测试，确认当前治理已登记 v5 artifact gate，但缺少显式 `readiness_bundle` final authority。随后用相关 pool500 gate、P7 gate 和 engineering contracts 测试验证边界未破坏。

**解决方式：**
在 `rs_core/workflow/full_data_pool500_route_gate.py` 增加 `READINESS_BUNDLE_SCHEMA_VERSION` 与 `validate_readiness_bundle()`：要求 artifact gate 为 `FULL_POOL500_READY`，并要求 `quality_audit`、`source_budget_audit`、`source_output_manifest_audit`、`index_manifest_audit`、`no_holdout_audit`、`ranking_registry_check` 全部 PASS；其中 no-holdout 与 ranking registry 失败直接 STOP，质量/预算/source/index 不通过则降级 `DIAGNOSTIC_ONLY_PARTIAL`。同时强制 bundle 不授权候选生成、不允许 ranking input replacement、不允许 pool1000。

**验证结果：**
`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_route_gate.py` 结果 `32 passed`；`tests/test_engineering_contracts.py` 结果 `26 passed`；`tests/test_p7_full_pool500_route_gate.py` 结果 `7 passed`；`scripts/ci/validate_engineering_contracts.py` 结果 `Engineering contracts passed: 115 configs, 67 scripts, 46 tests, 1 route registry, 1 governance allowlist`。

**面试可讲点：**
这段可以讲成“把推荐实验结果晋升从单点判断升级为证据包门禁”：不是看到某个 gate 返回 ready 就上线，而是要求数据泄漏、source 完备性、预算、索引、质量、registry 边界全部形成机器可校验审计，最终用 readiness bundle 统一宣称 recall artifact ready，并明确 ranking 使用必须另走 promotion。

### 2026-05-17 - 最小 Current Route Registry 工程治理框架

**任务：**
为混杂增长的实验代码、主路配置和 Agent 开发路径建立一套轻量治理框架：只登记当前主路与候选延续路线，补齐晋升门禁、warning allowlist 生命周期和 CI 可执行工程契约。

**遇到的问题：**
代码库已有 recall、ranking、Agent demo、pool500 延续实验并行推进，如果直接做全量资产盘点或大规模迁移，容易误伤历史 phase 脚本和 outputs；但如果没有 current route 边界，pool500 recall-only 产物又可能被误当作 ranking 输入。

**定位方式：**
审查 `dic/PROJECT_STRUCTURE.md`、文档/outputs 路由指南、`rs_core/workflow/pool500_route_gate.py`、`rs_core/workflow/full_data_pool500_route_gate.py`、CI 工程契约入口和 pool500 gate 测试，确认治理应收敛在“current route registry + promotion gate + contract validation”，而不是重构全项目结构。

**解决方式：**
新增 `configs/governance/current_route_registry.yaml` 和 `configs/governance/engineering_contract_allowlist.yaml`；新增 `dic/guides/CODEBASE_GOVERNANCE_GUIDE.md` 明确 recall、ranking、Agent demo、stable workflow 的晋升门禁；扩展 `rs_core/common/engineering_contracts.py` 和 `scripts/ci/validate_engineering_contracts.py`，校验 registry schema、必要 route、路径存在性、禁止 old_dic 权威引用、allowlist 生命周期字段，并强制 current_ranking_route 不得引用 pool500 recall-only 路径。

**验证结果：**
`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_engineering_contracts.py -q` 结果 `16 passed`；`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe D:/sinrotic_code/python_project/summer/RS_agent/scripts/ci/validate_engineering_contracts.py` 结果 `Engineering contracts passed: 115 configs, 67 scripts, 46 tests, 1 route registry, 1 governance allowlist`；`ruff check` 通过；pool500 gate 回归 `15 passed`。

**面试可讲点：**
这段可以讲成“用轻量工程治理控制实验型推荐系统的复杂度”：不做大爆炸重构，而是把主路身份、晋升条件、候选边界和例外生命周期变成可测试契约，让后续 Agent 或实验代码先判断自己处于探索、候选、current 还是 stable workflow，再决定是否进入 registry 和 CI gate。

### 2026-05-17 - scripts 实验入口整理与 P7 gate 迁移

**任务：**
整理 `scripts/` 中混杂的实验入口：清空根目录 `.py` 文件，将稳定入口、阶段性实验和历史入口分别放入子目录，把当前 P7 pool500 主路 gate 的可复用逻辑迁入 `rs_core`，并补充后续使用 `scripts/` 的工程规范。

**遇到的问题：**
`scripts/` 根目录同时承担稳定 CLI、阶段性实验、历史入口和被测试 import 的业务逻辑，视觉上和职责上都难以区分主入口与实验链路；同时当前新增的 `run_p7_full_pool500_route_gate.py` 还从另一个脚本 import 私有 `_enforce_project_venv`，形成脚本之间的反向耦合。

**定位方式：**
盘点 `scripts/*.py`、`rs_core/workflow/*`、P7 / phase / pool500 相关测试和 `dic/standards/ENGINEERING_STANDARDS.md`，确认项目规范要求 `scripts/` 只做参数解析与流程触发；再用检索确认 `prepare_data.py`、`run_eval.py`、`train_sft.py`、`train_dpo.py` 在 `tests/`、`dic/`、`.github/` 和其他脚本中无引用，并用根目录清单确认阶段性实验脚本需要分层。

**解决方式：**
新增 `scripts/data/`、`scripts/training/`、`scripts/evaluation/`、`scripts/serving/`、`scripts/assets/`、`scripts/ci/`，承接 19 个稳定入口；新增 `scripts/experiments/recall/` 和 `scripts/experiments/ranking/`，承接 47 个阶段性 recall/ranking 实验入口；四个无引用历史入口移入 `scripts/archive/`，最终 `scripts/` 根目录不再保留 `.py` 文件。新增 `rs_core/workflow/pool500_route_gate.py` 承接 P7 route signature、precheck、continuation gate 和 artifact audit 逻辑；新增 `rs_core/common/runtime.py` 提供 `enforce_project_venv()`，切断 `rs_core` 对 `scripts` 私有 helper 的依赖；将 `scripts/experiments/recall/run_p7_full_pool500_route_gate.py` 收敛为薄 CLI wrapper；测试改为直接 import `rs_core.workflow.pool500_route_gate`；工程契约改为递归扫描 `scripts/**/*.py` 且排除 archive；在 `ENGINEERING_STANDARDS.md` 增补 `scripts/` 使用规范。

**验证结果：**
运行覆盖移动后入口的代表性测试：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_p7_full_pool500_route_gate.py tests/test_phase_1_20_recall_diagnostics.py tests/test_phase_1_31_ranking_scaffold.py tests/test_phase_1_21_recall_coverage.py tests/test_phase_4_stage_shadow_metrics.py tests/test_phase_5_fine_rank_positive_push.py tests/test_phase_6_industrial_ranking_chain.py tests/test_phase_c_ranking_actionability.py tests/test_pool500_representative.py tests/test_simulation_runner.py`，结果 `72 passed, 2 warnings`；运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe D:/sinrotic_code/python_project/summer/RS_agent/scripts/ci/validate_engineering_contracts.py`，结果 `Engineering contracts passed: 113 configs, 66 scripts, 45 tests`；运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m ruff check ...`，结果 `All checks passed`；`Glob scripts/*.py` 返回 `No files found`。

**面试可讲点：**
这段可以讲成“把实验脚本从能跑整理到可维护”：`scripts/` 根目录不再堆入口，稳定命令按 data/training/evaluation/serving/assets/ci 分层，阶段性 recall/ranking 实验进专门目录，历史入口归档；同时选当前主路 P7 gate 做迁移样板，明确 CLI 与核心 workflow 的边界，再用工程规范、代表性实验测试和 contract gate 固化规则，降低后续实验扩展时的耦合和复现成本。

### 2026-05-16 - Phase 0 召回方法合同预检入口

**任务：**
为召回方法全家桶 Phase 0 增加只做合同预检的入口，落盘 `manifest.json`、`source_audit.json` 和 `resolved_inputs.json`，为后续 Phase 2-5 动态输入解析提供可审计基线。

**遇到的问题：**
后续 UserCF、Swing、Sequence、Graph、MF、Two-Tower 等阶段依赖不同输入和配置，若直接猜路径或混用 ranking pool，会造成 scope drift；同时 candidate generation 必须继续禁止读取 valid/test/holdout，并把召回晋升 gate 与 ranking frozen pool200 gate 分离。

**定位方式：**
先读取 `.omc/handoffs/phase0-contract-schema-notes.md` 明确三份 JSON schema，再核验 full clean、full lightweight views、代表性 baseline、bounded ItemCF sidecar、graph/two_tower config 和 ranking pool200 config 的真实路径与 sha256。

**解决方式：**
新增 `scripts/experiments/recall/run_phase0_contract_precheck.py`，默认输出到 `outputs/recall/full_main_route_other_methods/phase0_contract_precheck/`；脚本强制项目 `.venv`、D 盘 50GiB 水位、10k 路径拒绝、holdout read contract，并在无法解析动态输入或具体 config 文件时写 `BLOCKED_MISSING_ARTIFACT` / `INVALID_SCOPE_DRIFT`，不执行任何下游阶段。

**验证结果：**
已用项目 `.venv` 执行 `python -m pytest tests/test_phase0_contract_precheck.py`，结果 `5 passed`；执行 `python -m ruff check scripts/experiments/recall/run_phase0_contract_precheck.py tests/test_phase0_contract_precheck.py`，结果 `All checks passed`。运行 Phase 0 入口后三份产物已写入 `outputs/recall/full_main_route_other_methods/phase0_contract_precheck/`，因当前 graph、two_tower 和 ranking pool200 具体 config 仍引用历史 10k 路径，manifest 按合同返回 `INVALID_SCOPE_DRIFT` 并写入 `failure_reason`。独立 verifier 已批准 US-001，确认 source_audit 的 `read_files` 不包含 valid/test/holdout，后续 Phase 1+ 必须先修复 full-clean-safe config 后才能继续。

**面试可讲点：**
这段可以讲成“在推荐召回实验前加合同闸门”：面对多阶段召回方法扩展，不急于跑算法，而是先把输入、配置、数据泄漏边界、资源水位和 ranking/recall gate 明确为可审计 artifact，降低后续实验复现和 scope drift 风险。

### 2026-05-16 - bounded ItemCF co-visit sidecar 代表性构建验收

**任务：**
在 full clean 真实训练序列上执行受边界约束的 ItemCF/co-visit sidecar 代表性构建，验证它只生成可审计的邻居分片产物，不复制 full clean、不生成 pool500/pool1000 或 recall views。

**遇到的问题：**
直接从 full clean 构建共现邻居存在资源和产物污染风险，需要把执行范围限制在 `limit_users<=1000`，同时继续保证 10k 路径、valid/test/holdout 读取和重型输出都被排除。

**定位方式：**
使用 `.venv` 运行 focused pytest 与 ruff，随后检查 `outputs/recall/full_main_route_other_methods/bounded_itemcf_covisit_sidecar_representative/manifest.json` 和 `source_audit.json` 中的 safety flags、输入路径、输出键与目录文件集合。

**解决方式：**
执行 `scripts/experiments/recall/run_bounded_itemcf_covisit_sidecar_build.py`，显式传入 full clean 目录、代表性输出目录、`--limit-users 1000` 和 `--min-free-bytes 53687091200`；脚本只读取 `user_sequences.train.jsonl`，写入 manifest、source audit 和 32 个 `neighbors_shard_*.jsonl`。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_bounded_itemcf_covisit_sidecar_build.py` 结果 `7 passed`，`./.venv/Scripts/python.exe -m ruff check scripts/experiments/recall/run_bounded_itemcf_covisit_sidecar_build.py tests/test_bounded_itemcf_covisit_sidecar_build.py` 通过。真实构建输出目录共 34 个文件，`users_scanned=1000`、`processed_users=363`、`pair_updates=5264`、`project_venv_enforced=true`、`train_only=true`、`min_free_bytes=53687091200`；核验确认无 10k source path、无 valid/test/holdout 读取、无 pool500/pool1000/recall view/full clean copy 输出。

**面试可讲点：**
这段可以讲成“把行为共现召回从 dry-run 风险评估推进到受控 sidecar 产物”：通过硬上限、磁盘水位、train-only source audit、分片输出和 focused 测试，把原本容易失控的共现邻居构建变成可审计、可复跑、可逐步扩大的离线召回资产。

### 2026-05-16 - bounded ItemCF co-visit sidecar dry-run 预检

**任务：**
在不生成邻居 sidecar、不复制 full clean、不物化 pool500/pool1000 的前提下，为 full clean 上的 ItemCF/co-visit 行为召回补一条有边界的 dry-run 预检路径，先估算 pair 行数和分片字节风险。

**遇到的问题：**
已有 ItemCF/co-visit 逻辑适合小样本或受控候选池，但 full clean 的 `user_sequences.train.jsonl` 规模达到 18103384 行，直接建邻居可能带来磁盘、内存和产物污染风险；同时必须确保不误读 valid/test/holdout、不回退到 10k 路径、不生成 full clean copy 或 pool500/pool1000 输出。

**定位方式：**
只读审查 `scripts/data/build_recall_views.py` 中 `build_itemcf_edges(...)`、`build_item_graph_view(...)` 和 `build_lightweight_full_safe_views(...)`，确认可复用 pair/cap 估算思路，但 dry-run 不能调用真实写邻居函数；再检查 `scripts/experiments/recall/run_full_lightweight_recall_e2e.py` 的 10k 路径拒绝、输出目录拒绝和 `.venv` 约束，作为 sidecar 预检脚本的安全门参考。

**解决方式：**
新增 `scripts/experiments/recall/run_bounded_itemcf_covisit_dry_run.py`，只读取 `data/processed/amazon_2023_recall_clean_full/user_sequences.train.jsonl`，强制 `limit_users<=1000`、默认 50GiB 磁盘水位、拒绝 10k 路径和已存在输出目录；脚本只维护 bounded pair counter 和 shard byte estimate，最终只写 `manifest.json`。

**验证结果：**
新增 `tests/test_bounded_itemcf_covisit_dry_run.py`，覆盖 manifest-only、train_only/holdout contract、10k 路径拒绝、输出目录拒绝、输出位于 clean_dir 内拒绝和 `limit_users>1000` 拒绝。验证命令 `./.venv/Scripts/python.exe -m pytest tests/test_bounded_itemcf_covisit_dry_run.py tests/test_full_lightweight_recall_e2e.py` 结果 `8 passed`，`./.venv/Scripts/python.exe -m ruff check scripts/experiments/recall/run_bounded_itemcf_covisit_dry_run.py scripts/experiments/recall/run_full_lightweight_recall_e2e.py tests/test_bounded_itemcf_covisit_dry_run.py tests/test_full_lightweight_recall_e2e.py` 通过。真实 dry-run 输出 `outputs/recall/full_main_route_other_methods/bounded_itemcf_covisit_dry_run_estimate/manifest.json`，目录仅包含 manifest；manifest 记录 `train_only=true`、`limit_users=1000`、`sampled_users=1000`、`estimated_pair_rows=10528`、`planned_shard_count=32`、D 盘剩余 `225294610432` bytes，且未生成 neighbor/shard/pool500/pool1000 产物。

**面试可讲点：**
这段可以讲成“给重型召回源加 sidecar 预检闸门”：面对千万级行为序列，不直接上线全量共现构建，而是先用只读 train、硬阈值、路径拒绝、manifest-only 和分片字节估算把风险前移，证明推荐系统离线工程不仅追求召回效果，也要控制资源边界和数据泄漏边界。

### 2026-05-15 - 全量召回轻量索引安全路径

**任务：**
为 232 万商品、5605 万去重交互的 full clean 数据补一条 Phase 0.5 + Phase 1a 的安全召回索引路径，先只构建 Popular、Category、Semantic catalog/inverted index，避免直接触发 ItemCF/item_graph 等重型全量共现逻辑。

**遇到的问题：**
旧 `scripts/data/build_recall_views.py` 的主流程会无条件构建 ItemCF 和 item graph，内部包含全局 pair/edge 聚合；如果直接套到 full clean，存在内存、磁盘和失败恢复风险，也不符合“不复制 full clean、不全用户物化 pool500/pool1000”的执行边界。

**定位方式：**
审查 `scripts/data/build_recall_views.py` 的 main 流程，确认 `build_itemcf_views(...)` 与 `build_item_graph_view(...)` 在默认路径中必跑；结合 full clean `stats.json` 中 `canonical_items_written=2320263`、`filtered_rows=56054775` 的规模判断，必须先把轻量 catalog 索引和重型行为召回拆开。

**解决方式：**
新增 `--lightweight-full-safe` 模式：只写 `popular_recall.jsonl`、`category_recall_items.jsonl`、`category_top_items.jsonl`、`semantic_recall_inputs.jsonl` 和 `semantic_inverted_index.jsonl`；通过 `_tmp` 目录构建后原子提升到目标目录；manifest/stats 记录 source signature、输入行数、磁盘水位、产物大小和 skipped heavy outputs；默认旧路径保持兼容。

**验证结果：**
新增 `tests/test_build_recall_views.py` 覆盖 lightweight 模式不会生成 `itemcf_recall_weak.jsonl`、`itemcf_recall_strong.jsonl`、`item_graph_recall.jsonl`，并检查 semantic inverted index、source row count、canonical sha256、真实 `_tmp` 证据和最终产物 hard cap。已通过 `./.venv/Scripts/python.exe -m pytest tests/test_build_recall_views.py -q`，结果 `3 passed`；通过 `./.venv/Scripts/python.exe -m ruff check scripts/data/build_recall_views.py tests/test_build_recall_views.py`；CLI smoke 验证 lightweight 入口可生成 manifest/stats 且不产生重型召回文件；独立 architect 复核结论为 PASS。

**面试可讲点：**
这段可以讲成“把研究型全量召回改造成可控索引层”：面对千万级交互，不是直接把小样本脚本放大运行，而是先拆出轻量 catalog 索引、显式跳过高风险共现源，并用 manifest、source signature、磁盘阈值、产物上限和原子目录提升把全量实验变成可恢复、可解释、可扩展的工程流程。

### 2026-05-23 - pool500 two_tower 召回专项诊断

**任务：**
在最新 10000 用户 pool500 评估集上专项诊断 `two_tower` 召回：定位最新 eval/baseline/artifact，量化 source 级 Hit@K、用户覆盖、最终 pool500 边际贡献、与其他 source 的 overlap，并通过受控 challenger 判断是否应保留、降预算或重构后再保留 two_tower 预算。

**遇到的问题：**
当前 final pool500 中 `two_tower` 占用 `1,389,067/5,000,000` 行，primary share 约 `27.78%`，但 source 级只有 `HitPairs@500=3`、`HitUsers@500=3`；如果只看候选行数或 source 覆盖，容易误判为“向量召回已提供大量候选”，实际对目标正例贡献极低。

**定位方式：**
以 `outputs/eval/pool500_offline_eval_users_10k/manifest.json` 和 `outputs/eval/pool500_offline_eval_baseline_current/` 为最新 10k 评估与 baseline 证据，复核 `metrics.json`、`source_audit.json`、`source_contribution_audit.json`、two_tower source manifest 与训练 artifact。确认 10k baseline final pool500 为 `HitPairs@50=230`、`HitPairs@100=298`、`HitPairs@500=409`；two_tower 训练 artifact 只有 `user_embedding_count=28`，10k eval 用户主要依赖 recent-positive seed item 向量均值 fallback，且有 `699` 个用户没有 positive seed。

**解决方式：**
复用现有 `build_two_tower_method_source.py` builder，在 diagnostic-only 边界内生成 top500/user challenger：`outputs/recall/pool500_method_sources/two_tower/eval10k_top500_20260523_diagnostic/`，保持 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`。另做 final pool500 内 existing two_tower 行的 cap/remove 消融，输出 `outputs/recall/pool500_two_tower_challengers/budget_cap_ablation_20260523.json`，只用 valid/test labels 做离线评估与消融对比，不把 label/oracle 注入候选生成。

**验证结果：**
Top500 challenger 产出 `4,650,500` 行、覆盖 `9,301/10,000` 用户、`673,302` 个 unique items，但 source raw 仅 `HitPairs@50=2`、`HitPairs@100=5`、`HitPairs@500=23`、`HitUsers@500=21`、`Recall@500=0.001205`；相比当前 two_tower source 只提升 `+20 HitPairs@500`，代价是 `+3,261,433` 行。699 个无 positive seed 用户改用 recent item fallback 的诊断候选 `349,500` 行但 `HitPairs@500=0`。final pool500 cap 消融显示：cap=10/25/50/100 均保持 `HitPairs@50=230`、`HitPairs@100=298`，只损失 `1` 个 `HitPairs@500`；完全移除 two_tower 也只从 `409` 降到 `406`。

**面试可讲点：**
这段可以讲成“用受控实验识别向量召回的低 ROI 边界”：不是因为 two_tower 行数多就保留预算，也不是直接用 label 注入造达标候选，而是拆成 source raw、用户覆盖、merge surviving、overlap 和 budget cap 消融。结论是当前瓶颈不在索引覆盖或 merge 丢弃，而在表示/查询质量：应把 two_tower 预算降到 10–50 或暂保留为 diagnostic-only，下一步最小行动是先重训/重构用户表示与 rerank，再让 two_tower 重新竞争预算。

### 2026-05-23 - pool500 去冷用户 8k 评估集派生

**任务：**
从现有 10000 用户 pool500 offline eval artifact 中剔除 `cold-ish` 分层用户，形成一个只包含 hot/warm 用户的新评估集，供后续 two_tower 与召回策略在非冷用户口径下复测。

**遇到的问题：**
原 10k 评估集中 `cold-ish=2000`，而当前 two_tower 的无 positive seed 不可 query 用户为 `699`，两者不是同一概念；如果直接把冷用户问题等同于 two_tower 无法生成 query，容易误判覆盖瓶颈。因此需要保留原 10k 全局口径，同时派生一个明确标注“去 cold-ish”的补充评估口径。

**定位方式：**
读取 `outputs/eval/pool500_offline_eval_users_10k/manifest.json` 和 `users.jsonl`，确认原分层为 `hot=4000`、`warm=4000`、`cold-ish=2000`，且 `users.jsonl` 每行带有 `segment` 字段。复核 `run_pool500_offline_eval_baseline.py` 的 eval manifest 加载逻辑，确认新 artifact 需要保持 `schema_version=pool500_offline_eval_users_v1`、`status=PASS`、`user_set_hash` 与 `users.jsonl` 一致，并继续声明 label 只用于 evaluation。

**解决方式：**
使用项目 `.venv` 从原 10k artifact 派生 `outputs/eval/pool500_offline_eval_users_8k_no_cold_20260523/`，写入新的 `manifest.json` 与 `users.jsonl`；过滤规则仅为 `segment != cold-ish`，不读取 label 参与用户生成，不覆盖原 10k 输出，并在 manifest 中记录 `derived_eval_policy`、source manifest/users 路径、剔除 segment 与 no-promotion/no-ranking-replacement 边界。

**验证结果：**
轻量校验通过：新评估集 `users_count=8000`，分层为 `hot=4000`、`warm=4000`，剔除 `cold-ish=2000`；`user_set_hash=5c397357aef9f41159b7cd49b8e58f9d9ddef1704086f3cc5cad26e336d32dcd` 与 `users.jsonl` 一致；valid/test 正例统计为 `positive_pair_count=16118`、`positive_user_count=8000`，其中 `valid=8700`、`test=7418`。manifest 保持 `no_label_in_candidate_generation=true`、`no_oracle_candidate_injection=true`、`ranking_input_replacement_allowed=false`。

**面试可讲点：**
这段可以讲成“把评估口径分层治理，而不是改写总指标”：保留 10k 全量评估作为主口径，同时派生 hot/warm-only 8k 评估集用于验证双塔在非冷用户上的真实价值；这样既能避免冷用户稀释或误导专项实验，也不会把去冷指标包装成整体效果提升。

### 2026-05-23 - pool500 8k 去冷口径 two_tower 复测

**任务：**
在剔除 `cold-ish` 后的 8000 用户 hot/warm-only 评估集上复测当前 two_tower source、top500 diagnostic challenger 和 final pool 中 existing two_tower budget cap 消融，判断“去冷用户”是否能显著改善双塔结论。

**遇到的问题：**
原先 two_tower 在 10k 全量口径表现极弱，但需要排除一个可能解释：是否主要是 2000 个 cold-ish 用户拖累。如果去冷后指标显著改善，则 two_tower 可以考虑只服务 hot/warm；如果仍然低效，则问题更接近表示/查询质量，而不是单纯冷用户覆盖。

**定位方式：**
使用 `outputs/eval/pool500_offline_eval_users_8k_no_cold_20260523/manifest.json` 作为固定评估集，valid/test labels 仅用于离线评估；分别过滤评估 `outputs/eval/pool500_offline_eval_baseline_current/sources/two_tower/candidates.jsonl`、`outputs/recall/pool500_method_sources/two_tower/eval10k_top500_20260523_diagnostic/candidates.jsonl` 和 current final pool500 artifact，并按 `HitPairs/HitUsers/Recall/HitRate@50/100/500` 统计。

**解决方式：**
新增 diagnostic-only 指标文件 `outputs/recall/pool500_two_tower_challengers/eval8k_no_cold_two_tower_metrics_20260523.json`，记录当前 two_tower source、top500 challenger、分 segment 指标和 no-refill budget cap 消融；保持 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`。

**验证结果：**
8k 评估集含 `positive_pair_count=16118`。当前 two_tower source 覆盖 `7639/8000` 用户、`1,139,767` 行、`269,332` unique items，但仅 `HitPairs@50=2`、`HitPairs@100=2`、`HitPairs@500=3`、`Recall@500=0.000186`、`HitRate@500=0.000375`。top500 diagnostic 扩到 `3,819,500` 行后为 `HitPairs@50=2`、`HitPairs@100=5`、`HitPairs@500=20`、`Recall@500=0.001241`，相对当前 source 只增加 `+17 HitPairs@500`。final pool cap 消融中，cap=10/25/50/100 均保持 `HitPairs@50=185`、`HitPairs@100=252`，`HitPairs@500=359`，仅比 cap=150/current 的 `360` 少 `1`；完全移除 two_tower 为 `HitPairs@500=357`，只少 `3`。

**面试可讲点：**
这段可以讲成“用分层评估排除冷用户归因假设”：剔除 cold-ish 后，双塔覆盖率提高到 hot/warm 用户上的 `7639/8000`，但正例命中仍几乎不变，说明问题不是简单冷启动拖累，而是当前 user/query embedding 召回质量不足；因此双塔更适合先降预算、保留诊断，再通过重训用户表示或重构 query/rerank 后重新评估。

### 2026-05-16 - full clean 轻量召回索引全量落盘验收

**任务：**
在真实 `data/processed/amazon_2023_recall_clean_full` 上执行已审批的 `--lightweight-full-safe` 路径，把 Phase 1a 的 Popular、Category、Semantic catalog/inverted index 从方案推进到可消费的全量产物。

**遇到的问题：**
全量输入包含 2320263 个商品与 44843821 条 train 交互，直接运行必须同时控制磁盘、内存和范围偏离风险；尤其要防止误触发 ItemCF/item_graph、复制 full clean、覆盖 10k baseline 或遗留 `_tmp` 半成品。

**定位方式：**
执行前用 `.venv` 检查 full 输入、`canonical_interactions.train.jsonl`、`canonical_items.jsonl`、manifest/stats、10k baseline、目标输出目录和 sibling `_tmp` 目录；运行中记录 D 盘剩余空间、tmp/final 目录大小和 Python 进程 RSS，第二轮采样显示 tmp 约 6.53GiB、D 盘约 210.27GiB、主进程 RSS 约 15.7GiB，未触发 50GiB/80GiB/32GiB 停止阈值。

**解决方式：**
使用项目 `.venv` 执行 `scripts/data/build_recall_views.py --lightweight-full-safe`，显式设置 `--lightweight-min-free-bytes 53687091200`、`--lightweight-max-output-bytes 85899345920`、`--semantic-inverted-top-k 2000`；构建通过 `_tmp` 原子提升到 `data/processed/amazon_2023_recall_views_full_lightweight`，不生成重型召回文件。

**验证结果：**
后台构建退出码为 0，生成 `manifest.json`、`stats.json`、`popular_recall.jsonl`、`category_recall_items.jsonl`、`category_top_items.jsonl`、`semantic_recall_inputs.jsonl`、`semantic_inverted_index.jsonl`。验收脚本确认 JSON/JSONL 抽样可解析、manifest outputs 路径有效、`itemcf_recall_weak.jsonl`、`itemcf_recall_strong.jsonl`、`item_graph_recall.jsonl` 不存在、sibling `_tmp` 已清理、10k baseline 仍存在；最终输出 7 个文件、7483658110 bytes（约 6.97GiB），D 盘剩余约 209.83GiB，source signature 记录 `canonical_items.jsonl` 行数 2320263、`canonical_interactions.train.jsonl` 行数 44843821。

**面试可讲点：**
这段可以讲成“把推荐系统全量索引构建做成有安全门的批处理”：先用 consensus plan 固化资源阈值和验收标准，再用 `.venv`、原子目录提升、manifest 驱动验证、heavy output absence check 和资源监控，证明千万级数据产物不是一次性跑出来，而是可审计、可回滚、可接入后续排序链路的工程资产。

### 2026-05-15 - 工程规范 v1 与轻量 CI 门禁建设

**任务：**
为持续扩张的 RS Agent 项目建立第一版统一工程规范，覆盖目录边界、配置命名、测试分层、ruff/pytest 工具入口、CI smoke gate 和前端 lint 门禁。

**遇到的问题：**
项目已有 `architecture/ARCHITECTURE.md` 和 `PROJECT_STRUCTURE.md` 描述边界，但缺少可执行门禁；最初直接把 ruff 扩到较大范围会触发大量历史风格问题，`tests/test_serving_smoke.py` 还存在个人机器 `D:/...` 绝对路径，`pytest -m "unit or smoke"` 如果没有显式 marker 容易空跑。

**定位方式：**
检查 `rs_core/`、`tests/`、`configs/`、`frontend/package.json`、`.gitignore` 和现有 requirements，确认当前没有 `pyproject.toml`、pytest marker 配置和 GitHub Actions；通过本地验收发现 ruff baseline、pytest collect 非空检查和临时验证产物清理等实际问题。

**解决方式：**
新增 `dic/standards/ENGINEERING_STANDARDS.md` 和 `pyproject.toml`，注册 `unit/smoke/slow/gpu/experiment/serving/frontend` markers，并把 package discovery 限定为 `rs_core*`；为 8 个最小主链路测试文件添加 `pytestmark`，修复 serving smoke 的绝对路径；新增 `.github/workflows/ci.yml`，只安装 serving + dev 轻依赖，不安装 training 重依赖；ruff v1 收敛为 pyflakes/F 类真实错误门禁，并最小修复未使用导入和变量遮蔽。

**验证结果：**
已通过 `./.venv/Scripts/python.exe -m pip install -e ".[dev]" -r requirements-serving.txt`、`./.venv/Scripts/python.exe -m ruff check rs_core tests/test_serving_smoke.py tests/test_agent_runtime.py tests/test_inference_policy.py tests/test_agent_dialogue.py tests/test_agent_feedback.py tests/test_feedback_rerank.py tests/test_evaluation.py tests/test_display_contract.py`、`pytest --collect-only -m "unit or smoke"` 收集 `67` 个测试、`pytest -m "unit or smoke"` 结果 `67 passed`、`npm --prefix frontend run lint`、tracked `_tmp` 配置检查和 `git diff --check`。独立 verifier 复核结论为 PASS。

**面试可讲点：**
这段可以讲成“从研究型推荐项目向可维护工程项目演进”：不是一次性生产级重构，而是先把目录边界、配置可复现性、主链路 smoke 测试、轻量 lint 和 CI 门禁落地，既保护 Agent/推荐核心链路，又避免规范建设拖慢实验迭代。

### 2026-05-15 - 推荐 Agent 项目全面质量体检

**任务：**
对当前 RS Agent 项目做一次只读全面检查，覆盖推荐/Agent 核心链路、后端 API 契约、前端交互、测试覆盖与工程卫生，并归纳修复优先级。

**遇到的问题：**
专项审查发现当前测试和类型检查虽然能通过，但仍存在业务语义层风险：显式 dislike 商品可能被 over-filter 恢复策略带回结果，simulation 首轮展示未进入客户状态，LOPO/冻结池评估仍需数据泄漏门禁复核；同时前端交互锁、错误展示、NaN 输入和工程门禁也存在可复现性风险。

**定位方式：**
并行审查 `rs_core/rsagent/policy.py`、`rs_core/rsagent/feedback_rerank.py`、`rs_core/simulation/runner.py`、`rs_core/recsys/evaluation.py`、`rs_core/serving/app.py`、`frontend/src/views/LiveDemo.tsx`、`frontend/src/api.ts`、`frontend/src/components/sandbox/*` 与测试/配置状态。综合验证运行 `.venv/Scripts/python -m pytest tests/test_agent_feedback.py tests/test_feedback_rerank.py tests/test_simulation_runner.py tests/test_serving_smoke.py -q`，结果 `42 passed in 0.91s`；前端运行 `npm --prefix "D:/sinrotic_code/python_project/summer/RS_agent/frontend" run lint`，`tsc --noEmit` 通过。

**解决方式：**
本轮未直接修改业务代码，而是形成修复顺序：先反转“restored disliked 可保留”的测试期望并区分硬/软约束恢复，再补 simulation 首轮 `RoleState` 更新与测试，然后增加 LOPO/冻结池泄漏门禁，随后修 MAP@K 定义、前端并发锁/NaN/422 错误展示，最后整理依赖、CI 入口和工作区卫生。

**验证结果：**
验证显示当前聚焦测试与前端类型检查通过，但结论明确指出“测试通过不等于语义正确”：`tests/test_feedback_rerank.py` 仍固化了风险行为，simulation 测试未覆盖首轮状态一致性，LOPO/冻结池输入侧缺少可证明无泄漏的门禁测试。

**面试可讲点：**
这次可以讲成一次从“测试通过”走向“契约正确”的质量治理：不仅检查功能是否能跑，还从推荐反馈闭环、仿真指标可信度、离线评估泄漏、前后端契约和工程可复现性五个角度识别隐性风险，体现推荐系统项目中对实验可信度和 Agent 交互正确性的治理能力。

### 2026-05-15 - Agent Runtime 边界收口与公共契约保护

**任务：**
把推荐 Agent 的 turn loop 从 `HybridRecommendationEnvironment.converse()` 中抽出到确定性的 `AgentRuntime`，同时保留环境层对召回、候选和排序数据的所有权，并确保内部 runtime trace 不进入前端/API 展示面。

**遇到的问题：**
运行时层如果直接调用 `recommend_for_user(...)` 或加载候选/召回/排序数据，会把调度职责和推荐域逻辑混在一起；如果把 `agent_runtime_trace` 直接透传到 display/export，又会把内部诊断暴露成公共契约。

**定位方式：**
审查 `rs_core/rsagent/runtime.py`、`rs_core/workflow/hybrid_environment.py`、`rs_core/display/builder.py` 和 `rs_core/serving/service.py`，并用 `tests/test_agent_runtime.py` 的源码断言验证 runtime 禁止导入/调用推荐入口、`converse()` 禁止直接调 dialogue plan/apply 与推荐/对话分支构造。

**解决方式：**
`AgentRuntime` 只通过 host protocol 编排 `plan_dialogue`、`apply_dialogue_plan`、`build_recommendation_turn` 和 `build_dialogue_turn`；环境层继续持有 `_recommendation_step(...)`、`_dialogue_only_turn(...)` 与 `recommend_for_user(...)`；stop-check 只修复当前 turn 的 final items/ranking/diagnostics/reward evidence，不修改 active constraints，也不二次触发召回或排序。

**验证结果：**
独立复验命令 `.venv/Scripts/python.exe -m pytest tests/test_agent_runtime.py tests/test_display_contract.py tests/test_serving_smoke.py -q` 通过，结果 `26 passed`。代码审查确认 `rs_core/rsagent/runtime.py` 没有 `recommend_for_user`、候选/召回文件加载或排序 helper 调用；`HybridRecommendationEnvironment.converse()` 仅规范化输入后委托 `self.runtime.run_turn(...)`；`build_display_record(...)` 只从 `DisplayResponse` 白名单字段构建公共响应，chat/feedback/export 不包含 `agent_runtime_trace`。

**面试可讲点：**
这段可以讲成“用窄协议拆分 Agent 运行时和推荐系统内核”：运行时负责可观测的 loop、trace、memory compact、budget 和 stop-check，环境层负责推荐数据与排序执行，从而在不改变召回/排序语义的前提下获得可测试、可解释、不会污染公共 API 的 Agent 架构边界。

### 2026-05-13 - Phase 4 stage shadow metrics 最终回填

**任务：**

为 Phase 4 补齐最终验证收口：确认弱指标、coarse shadow retention、stage main-lane matrix 与 frozen candidate 一致性都已经写入中文叙事。

**遇到的问题：**

如果只看 Top-5，会把 `rank movement`、`coarse shadow retention`、`would_drop_positive` 这类信号压扁成一条结论；但这些信号本身又只能做诊断，不能被写成 promotion evidence。

**定位方式：**

对照 `scripts/experiments/ranking/run_phase_4_stage_shadow_metrics.py`、`tests/test_phase_4_stage_shadow_metrics.py` 和 `outputs/ranking/phase_4_stage_shadow_metrics_smoke/comparison.json`，核对 `candidate_pool_size=200`、`top_k=5`、`artifact_inspection=PASS`、`frozen match/hash` 未变，以及 recall / merge 语义未变。

**解决方式：**

把 stage shadow metrics 统一收口为 diagnostic/supporting，把 coarse shadow 视为 retained main lane；comparison 中回填 stage main-lane matrix，但不把弱指标升级为晋升门禁。

**验证结果：**

`./.venv/Scripts/python.exe -m py_compile scripts/experiments/ranking/run_phase_4_stage_shadow_metrics.py tests/test_phase_4_stage_shadow_metrics.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_phase_1_31_ranking_scaffold.py tests/test_phase_3_tree_ranking_experiments.py tests/test_phase_4_stage_shadow_metrics.py -q` 结果 `11 passed`；smoke 保持 `candidate_pool_size=200`、`top_k=5`、`artifact_inspection=PASS`，且没有 online promotion evidence。

**面试可讲点：**

这段可以讲成“把排序实验的最终回填做成证据分层”：我保留了 coarse shadow 和弱指标，但明确把它们限制在诊断层，不让它们冒充晋升结论。

### 2026-05-13 - Phase 4 三阶段实验计划与弱指标收口

**任务：**

把 Phase 4 的排序路线从“只看 Top-5 成败”收口成 coarse shadow / fine / rerank / future-online 四路对照，并把 `coarse_rank` 从 pass-through 占位符升级为 shadow 主路。

**遇到的问题：**

`top_k=5` 作为唯一信号太硬，候选命中本来就稀疏，单个位置的波动很容易掩盖 coarse/fine/rerank 在 rank movement、near-miss rescue、source coverage 上的真实变化；如果只盯 Top-5，很容易把诊断能力误写成晋升结论。

**定位方式：**

对照 `outputs/ranking/phase_1_26_real_ranking_experiments_smoke/comparison.json`、`outputs/verification/verification_phase_1_30_smoke/comparison.json`、`outputs/ranking/phase_1_31_ranking_algorithm_scaffold_smoke/comparison.json`、`outputs/ranking/phase_4_neural_ranker_smoke/comparison.json` 和 `outputs/ranking/phase_7_8_future_online_gate_smoke/comparison.json`，复核 `candidate_pool_size=200`、`top_k=5`、`frozen_candidate_match=true`、`artifact_inspection=PASS`、coarse/fine/rerank stage counts，以及 future-online gate 的 blocked 状态。

**解决方式：**

把 `coarse_rank` 改成 shadow coarse main lane，只保留 coarse score / trace / rank movement，不缩池、不改召回语义；同时新增弱指标口径，只把它们当作诊断和选路依据，不当作 promotion evidence。fine、rerank 和 future-online 分别保持 learned ranker、bounded rerank trace 和 future-only 门禁，避免把不同层的证据混在一起。

**验证结果：**

现有 smoke 和回归已经证明物理流水线证据稳定：`comparison.json`、`artifact_inspection=PASS`、`frozen_candidate_match=true` 都能稳定复现，Phase 4 神经排序仍是 diagnostic/blocked，Phase 7/8 仍是 future-online / future-agent-online；当前没有把任何 future-online 指标写成离线晋升证据。

**面试可讲点：**

这段可以讲成“把排序实验从单点 Top-5 成败，升级为分层诊断体系”：我把 coarse/fine/rerank/future-online 分开治理，用弱指标解释为什么某些方法值得继续跑、为什么某些方法只能诊断，避免把短期 smoke 误当成模型晋升。

### 2026-05-14 - ALS/BPR MF 依赖解锁后固定合同补跑

**任务：**
按用户要求安装矩阵分解实验依赖，并把此前 dependency-gated 的 ALS/BPR 从“可跑待执行”推进到真实 Phase 1.21 固定合同实验。

**遇到的问题：**
`implicit` 可以安装并通过 smoke；`lightfm==1.17` 在当前 Windows / Python 3.13 环境下先出现 metadata/build 失败，修复后又暴露 WARP/BPR native loss 在真实稀疏矩阵上 access violation。与此同时，原 Phase 1.21 脚本只把 ALS/BPR/LightFM 写进 registry dependency gate，没有真实候选生成路径，直接跑配置会变成“登记了但没产候选”。

**定位方式：**
用 `.venv/Scripts/python.exe` 检查 `implicit` / `lightfm` 依赖状态，并用小矩阵 smoke 确认 `implicit` 0.7.3 的 ALS/BPR 需要以 user-item CSR matrix 调用 `fit(user_items)` 和 `recommend(...)`。LightFM 先定位到 PyPI sdist 的 `__builtins__.__LIGHTFM_SETUP__` Python 3.13 兼容问题，再用 GitHub 1.17 源码重新 Cythonize；真实 Phase 1.21 矩阵复现显示 WARP/BPR/WARP-KOS 在 `_run_epoch` access violation，logistic loss 可稳定训练。随后检查 `scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py` 的 `SOURCE_CONTRACT`、`_attach_phase_sources`、`_phase_source_config`、`_raw_non_popular_candidates` 和 benchmark 执行状态判断，确认缺真实 source 接入。

**解决方式：**
新增 `als_mf_recall` / `bpr_mf_recall` / `lightfm_recall` source 合同，接入 train-only implicit ALS/BPR 与 LightFM logistic index builder，并在 `configs/recall/phase_1_21/phase_1_21_recall_coverage_mf.yaml` 中开启对应参数；LightFM 明确记录为 logistic observation，WARP/BPR native crash 不伪造成可用结果。补充函数级测试，验证 MF 候选不包含已看 seed，且 metadata 带 `train_implicit_als`、`train_implicit_bpr`、`train_lightfm_logistic`。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_21_recall_coverage.py` 结果 `25 passed`，`compileall scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py tests/test_phase_1_21_recall_coverage.py` 通过。真实固定合同输出 `outputs/recall/phase_1_21_recall_coverage/source_family/mf_implicit_als_bpr_lightfm_pool200/`：`candidate_hit_users=17`、`candidate_hit_rate_at_pool=0.123188`、`recall_at_pool=0.064151`；`als_mf_recall` 覆盖 `500` users / `1207` items 但无边际命中，`bpr_mf_recall` 覆盖 `500` users / `39` items 且只贡献 `1` 个 candidate-hit source 覆盖，`lightfm_recall` 覆盖 `454` users / `34` items 并贡献 `4` 个 candidate-hit source 覆盖，但整体仍低于当前主路 `19` hit users。

**面试可讲点：**
这段可以讲成“把依赖门控 backlog 转成真实实验”的工程治理：先用依赖安装、源码 patch 和 API smoke 证明 MF 路径边界，再补 train-only 候选生成路径和合同测试，最后用固定合同 artifact 得出 reject 结论；同时如实记录 LightFM WARP/BPR native crash 与 logistic 可运行结果，避免把常见方法名包装成虚假实验收益。

### 2026-05-13 - 剩余召回方法固定合同补跑收口

**任务：**
把 graph、vector/two-tower、MF、sequence/multi-interest 等剩余召回方法从“计划/占位”推进到可验证的 Phase 1.21 固定合同实验，并由一个串行 runner 统一跑完。

**遇到的问题：**
多个 worker 并行修改同一个 Phase 1.21 脚本，出现 `_multi_interest_patch` 未定义、multi-interest 默认权重与测试预期不一致的问题；同时 vector 配置一度仍是 pool100，不符合本轮 pool200 固定召回池口径。ALS/BPR/LightFM 也不能因为方法名常见就伪造结果，必须按依赖 gate 处理。

**定位方式：**
用 `tests/test_phase_1_21_recall_coverage.py` 暴露 `_multi_interest_patch` 缺失，随后检查 `scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py` 中 `_attach_phase_sources`、`_raw_non_popular_candidates`、`SOURCE_FAMILY_BENCHMARKS` 和新增配置文件；用 `.venv/Scripts/python.exe` 串行运行四个配置，并抽取各输出目录的 `metrics.json`、`manifest.json`、`source_family_observation_benchmarks.json`。

**解决方式：**
补齐 `multi_interest_recall` 的 patch 和元数据合同，把 vector 配置统一到 `candidate_pool_size=200`；graph 只启用可复用的 `item_graph`，`graph_walk_seed` 保持 sidecar-gated；MF 只执行纯 numpy `implicit_svd_recall`，ALS/BPR/LightFM 通过 `dependency_gate` 标记为 blocked；实验按 graph → vector → MF → sequence 串行执行，保持同一 holdout hash。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_21_recall_coverage.py` 结果 `23 passed`，`compileall` 通过。四个固定合同输出均为 `users_with_holdout=138`、`candidate_pool_size=200`、`holdout_user_ids_hash=927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2`：graph、vector/two-tower、implicit SVD MF、sequence/multi-interest 的 `candidate_hit_users` 均为 `17`、`candidate_hit_rate_at_pool=0.123188`、`recall_at_pool=0.064151`，低于当前 source-aware/semantic 主路的 `19` hit users；ALS/BPR 因缺 `implicit`、LightFM 因缺 `lightfm` 继续 `defer`。

**面试可讲点：**
这段可以讲成推荐召回实验治理：用多 agent 并行补齐实现入口，但实验执行串行化以保证可比；对能跑的方法输出同合同 artifact，对缺依赖的方法保留 dependency gate，不把 smoke、排序指标或方法名热度包装成晋升证据，最终得出“当前无新方法晋升，主路保持 source-aware/semantic”的克制结论。

### 2026-05-13 - Source-aware 召回融合截断稳定性观察

**任务：**
在确认 UserCF/Swing 只能作为 fallback 后，继续分析 `semantic_title_category_expansion + 行为 fallback` 的融合、去重和截断稳定性，判断是否需要替换当前主路。

**遇到的问题：**
单纯继续新增召回方法已经收益有限，真正风险转向多路 source 合并后的池内竞争：行为侧 source 可能增加覆盖，但也可能挤掉语义主路或热门兜底候选，因此需要 observation-only 对照，而不能直接改主 baseline。

**定位方式：**
检查 `rs_core/recsys/candidate_merge.py`，确认已有 `_limit_candidate_pool`、`balanced_source_budget`、`candidate_source_minimums/maximums` 与 `candidate_fill_order`；检查 `scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py`，确认可复用同一批 raw candidates，只比较不同截断策略。

**解决方式：**
新增 `configs/recall/phase_1_21/phase_1_21_recall_coverage_source_aware.yaml` 和 Phase 1.21 的 `--mode source-aware`，对比 `score_sorted_all_sources` 与 `source_balanced_fallback_preserving`。实现中避免每个 variant 重建 source index，改为一次生成 raw candidates、多个截断策略复用，降低长跑成本。

**验证结果：**
`tests/test_phase_1_21_recall_coverage.py` 结果 `22 passed`；`compileall rs_core scripts tests` 通过。真实固定合同运行写入 `outputs/recall/phase_1_21_recall_coverage/source_aware/`：两种策略 `candidate_hit_users` 都为 `19`、`candidate_hit_rate_at_pool=0.137681`，无 `baseline_displacement_users`；balanced 策略把 `candidate_count_avg` 从 `136.214` 降到 `126.972`，并把 `candidate_hit_rate_at_100` 从 `0.123188` 提到 `0.130435`。

**面试可讲点：**
这段可以讲成召回系统的多路融合治理：不是盲目叠 source，而是在同一 holdout 与同一 raw candidate 输入下，只替换截断策略，观察命中、位移、候选量和前段召回位置；结合后续 graph/vector/MF/sequence 对照后，最终把 `source_balanced_fallback_preserving` 固定为当前混合召回主路的默认截断策略。

### 2026-05-13 - 补跑未覆盖的轻量行为召回与矩阵分解 smoke

**任务：**
把此前标为未跑/延后的 UserCF、Swing、session transition 和矩阵分解类召回推进到可执行固定合同实验，明确哪些方法只是 fallback、哪些应 reject、哪些仍 blocked。

**遇到的问题：**
此前文档把 UserCF/Swing/session transition 记为没有成熟入口，ALS/BPR/implicit MF 记为依赖或实现不足；用户追问“还是没有跑实验吗”后，需要真正补一轮可验证实验，而不是只继续写 defer。

**定位方式：**
检查 `scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py` 的 `_attach_phase_sources`、`_raw_non_popular_candidates` 和 `source_family_observation_benchmarks.json` 生成逻辑，确认可以在 Phase 1.21 固定合同中增加训练期 source。依赖检查显示 `.venv` 中 `numpy=True`，但 `scipy=False`、`sklearn=False`、`implicit=False`、`lightfm=False`，因此 ALS/BPR 不能可靠训练。

**解决方式：**
新增 `configs/recall/phase_1_21/phase_1_21_recall_coverage_behavior_untried.yaml`，并在 Phase 1.21 脚本中接入 `usercf_recall`、`swing_recall`、`session_transition_recall` 和纯 numpy `implicit_svd_recall`。所有索引只从 `user_sequences.train.jsonl` 构建，不读取 holdout；ALS/BPR/LightFM 明确标为依赖 blocked。

**验证结果：**
补跑命令：`./.venv/Scripts/python.exe scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py --config configs/recall/phase_1_21/phase_1_21_recall_coverage_behavior_untried.yaml --output-dir outputs/recall/phase_1_21_recall_coverage/source_family/worker_behavior_untried_pool200 --mode baseline --limit-users 500`。结果 artifact 显示 `candidate_hit_users=17`、`candidate_hit_rate_at_pool=0.123188`、`recall_at_pool=0.064151`；`usercf_recall` 和 `swing_recall` 各有 `1` 个 candidate-hit source 覆盖，`session_transition_recall` 和 `implicit_svd_recall` 为 `0`。`tests/test_phase_1_21_recall_coverage.py` 结果 `21 passed`。

**面试可讲点：**
这段可以讲成“面对用户质疑没有跑实验时，快速把 deferred backlog 转成固定合同实验”：能轻量实现的先落地并输出 artifact，不能跑的 ALS/BPR 给出依赖证据；最后按召回治理口径把 UserCF/Swing 归为 fallback，把 session transition / implicit SVD reject，避免为了覆盖方法名而虚假晋升。

### 2026-05-13 - 主流召回方法实验口径与可维护结论文档收口

**任务：**
把剩余主流召回方法从口头清单推进到可维护的实验结论文档：统一 `promote/reject/defer/fallback/document_only` 决策标签、补齐 method-card diagnostics，并对当前 CPU/lightweight 可执行 source 生成固定合同 artifact。

**遇到的问题：**
旧文档和部分 registry artifact 混用了 `pending_evidence`、`observation_baseline`、A/B/C/D evidence 等旧口径；同时 UserCF、Swing、ALS/BPR/implicit MF、session transition 在当前仓库没有成熟召回入口，不能为了“跑全主流方法”伪造实验结果。

**定位方式：**
核对 `rs_core/recsys/evaluation.py`、`rs_core/recsys/types.py`、`scripts/experiments/recall/phase_1_20_recall_diagnostics.py`、`scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py` 与 `dic/experiments/recall/RECALL_METHODS_EXPERIMENT_LOG.md`；读取 `outputs/recall/phase_1_21_recall_coverage/worker_light_20260513/` 和 `outputs/recall/phase_1_21_recall_coverage/source_family/worker_cpu_itemcf_covisit_hybrid_pool200/` 下的 manifest/metrics，确认 `valid_test`、`users_with_holdout=138`、holdout hash 和 ranking/rerank disabled checks。

**解决方式：**
在 `EvaluationSummary` 中新增 `method_card_diagnostics`，把 forbidden metrics 扩展为排序、Top-K gap、LTR/rerank 和线上业务指标；未知 `pool_displacement_risk` 默认给 `defer`，不自动晋升。文档中新增 CPU-bound CF/hybrid 与 lightweight source sweep 条目：ItemCF/co-visit 归为 `fallback`，popular/category 归为 `document_only`，UserCF/Swing/ALS/BPR/session transition 归为 `defer`。

**验证结果：**
固定合同 artifact 已重跑：pool200 CPU/hybrid `candidate_hit_users=19`、`candidate_hit_rate_at_pool=0.137681`、`recall_at_pool=0.06971`；method-card diagnostics 输出 `decision_hint=defer` 且 `can_promote=false`。验证命令：`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_21_recall_coverage.py tests/test_phase_1_20_recall_diagnostics.py tests/test_evaluation.py tests/test_hybrid_demo.py` 结果 `136 passed`；`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过。

**面试可讲点：**
这轮可以讲成“把召回方法探索做成证据治理系统”：不仅跑可执行方法，还把不能跑的方法明确落为 `defer/document_only`，并用统一 schema、artifact hash、holdout hash 和 forbidden metrics 约束防止把排序收益或历史文字误写成召回晋升。

### 2026-05-13 - 第一轮新召回 source ablation 与晋升收口

**任务：**
在 `semantic_title_category_expansion` 已成为 recall-only baseline_vNext 后，对下一轮候选 source 做第一轮可复现 ablation，判断是否有新的召回 source 可以晋升。

**遇到的问题：**
Phase 0 诊断显示 ItemCF/co-visit 重叠较高，粗类目扩池没有 lift；同时第一轮候选中的 Swing/UserCF 在当前仓库没有成熟入口，metadata neighbor 虽有函数但实现按 seed 扫描 metadata index，长跑 lane 成本偏高，不能为了“跑全方法”伪造结果。

**定位方式：**
读取 `.omc/recall/artifacts/phase_0_recall_diagnostics_20260513/selected_first_round_sources.md`、`phase0_diagnostics.json` 和 Phase 1.21 registry，确认 recall-only 口径、holdout hash 与 pool200 guardrail；再检查 `rs_core/recsys/candidate_merge.py`、`scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py`、graph/item_graph sidecar，确认可复用的是 `item_graph` 与 `graph_walk_seed`。

**解决方式：**
只对可复用的 `constrained_item_graph_walk` 做 pool200 与 source-only ablation，并把 Swing/UserCF/metadata neighbor 明确记录为未执行或后续条件型实验；所有结论只使用 candidate-hit users、baseline miss 覆盖、candidate volume 和 source overlap，不使用 Top-K/ranking/LTR/业务指标。

**验证结果：**
收口报告见 `.omc/recall/artifacts/phase_0_first_round_source_ablation_20260513/first_round_closure_report.md`。`item_graph` 与 `graph_walk_seed` 的 candidate_hit_users 都为 17，baseline_miss_coverage_users 都为 0；source-only 各自只命中 1 个用户且没有覆盖 baseline miss 用户，因此结论为 `NO_NEW_SOURCE_PROMOTED`。验证命令：`./.venv/Scripts/python.exe scripts/data/validate_recall_registry.py` 通过，`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_21_recall_coverage.py` 结果 `20 passed`，ablation 脚本 `py_compile` 通过。

**面试可讲点：**
这段工作体现的是召回实验治理：不是把所有主流方法都盲目接入，而是在同一 holdout、同一 candidate_pool_cap 和 recall-only 合同下做 ablation；能跑的图召回如实记录无新增覆盖，不能成熟复用的 Swing/UserCF 不伪造结果，从而保证 baseline 晋升基于可复现证据。

### 2026-05-13 - Phase 1.26 典型排序链路与真实实验底座

**任务：**
把排序阶段从“规则 gate / smoke / blocked 记录”推进到可验证的典型排序实验链路：明确目标架构为 recall → coarse rank → fine rank → rerank，并在当前离线边界下落地 `frozen pool200 → learned fine ranker → bounded rerank trace`。

**遇到的问题：**
此前阶段容易把依赖 gate、smoke 或 blocked 状态包装成“真实排序实验”，但它们没有真实训练日志、模型产物、候选一致性证明和 case diff；同时 GBDT/LambdaMART 等方法如果缺依赖、GPU 或候选级 adapter，不能伪造成当前可晋升结果。

**定位方式：**
检查 `rs_core/recsys/ranking.py`、`rs_core/workflow/ltr_training.py`、`scripts/experiments/ranking/run_phase_1_28_lightweight_learned_ranker.py` 和 `scripts/experiments/ranking/run_phase_3_tree_ranker.py`，确认已有 LTR 训练闭环可复用，而 Phase 3 tree 脚本只是依赖 gate 与 candidate-row export。验证产物见 `outputs/ranking/phase_1_26_real_ranking_experiments_smoke/comparison.json`。

**解决方式：**
在 `rs_core/recsys/ranking.py` 增加 `coarse_score`、`fine_score`、`rerank_score`、`score_trace`、stage rank 和 rank movement，先把 coarse 作为 diagnostic trace，不强制缩池；新增 `scripts/experiments/ranking/run_phase_1_26_real_ranking_experiments.py`，用 LOPO pointwise logistic / pairwise perceptron 做真实轻量 fine-ranker 训练，输出 `training_config.json`、`training_log.json`、`ltr_model.json`、`ltr_candidate_rows.jsonl`、case diff 和 comparison registry；GBDT/LambdaMART 在缺依赖、GPU 校验或候选级 adapter 时明确标为 `blocked`。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile scripts/experiments/ranking/run_phase_1_26_real_ranking_experiments.py rs_core/recsys/ranking.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -q -k "score_trace or phase_1_26_real_ranking_runner_contract"` 结果为 `3 passed, 107 deselected`；刷新 smoke 命令 `./.venv/Scripts/python.exe scripts/experiments/ranking/run_phase_1_26_real_ranking_experiments.py --output-dir outputs/ranking/phase_1_26_real_ranking_experiments_smoke --limit-users 20 --seed 20260513` 成功，`artifact_inspection.status=PASS`，baseline 与两个 learned variant 均保持 `candidate_pool_size=200`、`top_k=5`、`frozen_candidate_match=true`，feature/leakage gate 为 PASS，LTR variants 为 diagnostic-only，tree/LambdaMART 方法为 blocked。

**面试可讲点：**
这段工作体现的是推荐排序实验治理能力：先把工业排序链路拆成粗排、精排、重排的可观测阶段，再用冻结候选池保证只评估排序，不污染召回；对能真实训练的方法输出完整证据链，对依赖不足的方法如实 blocked，避免把 smoke/gate 伪装成模型效果。

### 2026-04-28 - CLI Agent 反馈闭环修复

**任务：**
推进 RS Agent 的 CLI 交互闭环，让第二轮用户反馈能真实影响推荐结果，并让 reward 能识别反馈是否产生实际效果。

**遇到的问题：**
CLI smoke 能生成 `session.json`、`session_turns.jsonl` 和 `grpo_rollouts.jsonl`，但两轮 Top-K 完全相同，`changed_after_feedback=false`；同时 reward 只要偏好解析成功就容易给较高 feedback alignment，不能区分“解析了反馈”和“反馈真的改变了推荐”。

**定位方式：**
检查 `rs_core/rsagent/cli.py`、`rs_core/workflow/hybrid_environment.py`、`rs_core/workflow/hybrid_demo.py`、`rs_core/rsagent/policy.py`、`rs_core/recsys/ranking.py` 的 feedback 链路，确认 `preferred_sources/preferred_categories` 已解析，但 CLI 使用的配置没有给 feedback source/category 足够的 ranking 权重；初始 smoke 报告见 `outputs/agent/cli/agent_cli_smoke/rs_agent_cli_baseline_comparison.md`。

**解决方式：**
在 `rs_core/rsagent/cli.py` 为 CLI 会话注入不覆盖用户配置的 feedback rank 默认权重，并把模拟反馈改成包含 fresh/again，使第二轮能过滤上一轮已曝光 item；在 `rs_core/rsagent/reward.py` 增加 `feedback_effect_observed` 证据，对后续轮次中没有过滤、boost 或换榜证据的反馈对齐分做上限约束；补充 `tests/test_agent_rollout_schema.py` 和 `tests/test_agent_reward.py` 覆盖换榜与无效反馈降分。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m rs_core.rsagent.cli --config configs/demo/hybrid_demo/hybrid_demo_electronics_1000_lopo_semantic_title.yaml --limit-users 3 --simulate-two-turn --output-dir agent_cli_smoke_after_fix` 后，报告 `outputs/agent/cli/agent_cli_smoke_after_fix/rs_agent_cli_baseline_comparison.md` 显示 `changed_after_feedback=true`，第二轮 Top-K 从 `B08JQCJZQM/B08HFNNPPJ/...` 变为 `B0B2JJV92T/B08Y1XYLVP/...`，diagnostics 中出现 `feedback_source_semantic`、`excluded_prior_turn_items` 和 `boosts_applied`。直接调用目标测试函数通过，`./.venv/Scripts/python.exe -m compileall -q rs_core tests` 通过；当前环境缺少 pytest，未运行完整 pytest 套件。

**面试可讲点：**
这次工作把 Agent 从“能记录反馈”推进到“反馈能改变策略”的闭环：先定位到配置层 feedback 权重未生效，再用可解释 diagnostics 证明过滤与 boost 发生，最后把 reward 从结果静态打分升级为包含反馈响应性的训练信号，为后续 GRPO rollout 数据打基础。
### 2026-04-28 - 项目文档入口精简与阶段状态同步

**任务：**
整理 Phase 1.5 / Phase 1.6 / Phase 1.7 的文档承接关系，避免历史总结、优化叙事和工程日志之间的信息重复。

**遇到的问题：**
Phase 1.5 历史总结、最新优化判断和工程叙事记录分散在多个文档中，容易让读者误把历史阶段总结当成当前总览，也不利于面试叙事快速定位当前结论。

**定位方式：**
对照 `dic/phases/phase_1_5/PHASE_1_5_DEMO_SUMMARY.md`、`dic/OPTIMIZATION_NARRATIVE.md` 和现有 `dic/ENGINEERING_NARRATIVE_LOG.md` 的内容边界，确认 Phase 1.5 应只保留历史总结，Phase 1.6 / 1.7 和最新判断应集中在优化文档，工程日志只记录可复述的过程条目。

**解决方式：**
在 Phase 1.5 文档开头补充阶段说明，在优化文档的当前推荐处补充 Agent 层 demo 的入口方向，并在工程日志中追加一条简短记录；随后将旧实验报告和数据画像移动到 `dic/archive/`，让 `dic/` 根目录只保留核心入口文档，减少重复维护成本。

**验证结果：**
通过核心文档的人工一致性检查，确认 README、实施计划、架构说明、目录说明、Phase 1.5 总结和优化叙事之间的阶段状态一致；`dic/` 根目录保留 7 个核心文档，59 个旧报告和数据画像已归档到 `dic/archive/`；`old_dic/` 已按英文 ASCII 目录整理为 `historical_plans/` 和 `early_data/`，避免中文路径解码异常；未执行新的实验。

**面试可讲点：**
这类工作体现的是文档架构治理能力：不仅能写内容，还能把历史总结、当前判断和过程证据拆分到正确入口，减少信息漂移，让面试叙事更容易复述和验证。

### 2026-04-28 - Agent feedback canonical 固化与 conversational MVP

**任务：**
把已有 CLI feedback smoke 固化成唯一可复现 demo，并把 Agent 从“反馈后再推荐”推进到 deterministic 多轮对话 MVP。

**遇到的问题：**
此前项目已有多份 `agent_cli_*` 输出目录，读者不容易判断哪个是 canonical 证据；同时 Agent 还偏向推荐列表输出，缺少“模糊需求追问、澄清后推荐、解释上一轮、换一批、unsupported 保留”等对话式推荐能力。

**定位方式：**
检查 `rs_core/rsagent/schema.py`、`rs_core/rsagent/policy.py`、`rs_core/workflow/hybrid_environment.py`、`rs_core/rsagent/cli.py` 和 rollout 输出链路，确认已有 session/turn、feedback constraints、reward evidence 和 rollout schema，可以在不改推荐 backbone 的前提下增加 deterministic dialogue manager。

**解决方式：**
新增 `rs_core/rsagent/dialogue.py`，用规则方式规划 `recommend_request`、`clarification_answer`、`ask_explanation`、`preference_feedback`、`unsupported` 等对话意图；扩展 `AgentSession` 保存 `ConversationState`，扩展 `AgentTurn` 保存 `assistant_response`；在 `HybridRecommendationEnvironment.converse()` 中接入对话规划，保持 `step()` 的原 feedback 行为兼容；在 CLI 增加 `--simulate-conversation`，并保留 `--inference-policy off` 作为 deterministic canonical 入口。

**验证结果：**
安装 pytest 后运行 `./.venv/Scripts/python.exe -m pytest tests/test_agent_feedback.py tests/test_agent_reward.py tests/test_agent_rollout_schema.py tests/test_agent_dialogue.py`，结果 `19 passed in 0.27s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests` 通过。canonical feedback 入口生成 `outputs/agent/canonical/agent_feedback_demo_canonical/`，检查确认 `changed_after_feedback=true`、`feedback_effect_observed=true`、有 boost/filter 证据且 `training_status=deferred_environment_reward_only`。conversational 入口生成 `outputs/agent/canonical/agent_conversation_demo_canonical/`，检查确认 turn 2 追问、turn 3 澄清后推荐、turn 4 解释、turn 5 根据反馈再推荐，rollout 逐条保留 deferred training metadata。

**面试可讲点：**
这次工作把 Agent 定位从“推荐包装器”推进到“对话式推荐编排器”：底层仍由传统推荐 backbone 负责召回和排序，Agent 在上层负责识别用户意图、必要时追问、把澄清转成结构化约束、解释推荐依据，并把多轮交互沉淀为 reward / rollout 证据，为后续 Qwen / QLoRA / GRPO 训练路线提供稳定 contract。

### 2026-04-28 - item-level feature rerank 第一版

**任务：**
在 Phase 1.7 source-level rerank 到达边界后，补一个默认关闭、可解释的 item-level feature rerank，用于把多源候选、反馈匹配、popular-only / semantic-only 等信号显式纳入排序诊断。

**遇到的问题：**
统一 semantic boost 和 semantic-only penalty 都没有提升 Top-K hit，说明问题不在 source 整体曝光，而在 item 之间的相对区分；实验初期还误用 `python -m rs_core.workflow.hybrid_demo --config ...`，该模块没有 CLI 入口，导致命令成功退出但没有生成输出。

**定位方式：**
检查 `rs_core/recsys/ranking.py` 和 `scripts/evaluation/run_hybrid_demo.py`，确认真正实验入口是 `./.venv/Scripts/python.exe scripts/evaluation/run_hybrid_demo.py --config ...`；对比 `outputs/hybrid_demo/hybrid_demo_small_electronics_1000_semantic_title*/metrics.json` 与 `ranking_case_summary.json`，确认 item-feature rerank 对 valid/test 和 LOPO 的影响。

**解决方式：**
在 `rank_candidates()` 中增加默认关闭的 `item_feature_rerank`，输出 `feature_score`、`item_features` 和 item_feature rerank events；新增 title semantic 的 valid/test 与 LOPO item-feature 配置，并让 report config summary 显示 `item_feature_rerank` 策略，避免实验报告漏掉关键配置。

**验证结果：**
重新生成 Phase 1.7 baseline 与 Phase 1.8 item-feature 对照后，valid/test `hit_rate_at_k` 保持 0.043478，LOPO `hit_rate_at_k` 保持 0.888889；LOPO `candidate_hit_rank_avg` 从 25.128205 改善到 23.461538，`top1_score_gap_avg` 从 24.742213 降到 24.047873。运行 `./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_agent_feedback.py tests/test_agent_dialogue.py tests/test_agent_rollout_schema.py`，结果 `42 passed in 0.30s`；`./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；独立 verifier 给出 PASS。

**面试可讲点：**
这次工作体现的是从 source-level 调参升级到 feature-level 诊断：当全局 boost / penalty 不能改变同源候选内部顺序时，把多源支持、反馈匹配和单源惩罚显式做成可解释特征。结果没有夸大成 Top-K 提升，而是准确表述为“改善候选池内排名分布，为后续 Agent 反馈和学习排序提供特征接口”。

### 2026-04-28 - rollout 训练样本 contract 与 Qwen harness 对照固化

**任务：**
把已经稳定的 Agent feedback / conversation rollout 往训练前闭环推进：先显式导出 SFT / reward 样本 contract，再验证 Qwen bounded rerank evaluation harness 在无本地模型依赖时也能产出可复现对照结果。

**遇到的问题：**
此前 rollout 已记录 `prompt_context`、`reward_evidence` 和 `diagnostics`，但训练用途仍需要下游再拼字段，缺少“这一轮该学什么、reward 怎么对照”的显式 contract；同时 Qwen harness 虽已有 fake client 改善路径测试，但缺少模型不可用时 fallback 仍能完整生成三模式对照报告的测试，容易把本机环境依赖误当成评估链路能力。

**定位方式：**
检查 `rs_core/rsagent/rollout.py`、`rs_core/rsagent/schema.py`、`rs_core/rsagent/reward.py` 和 `rs_core/workflow/hybrid_demo.py`，确认已有 AgentTurn / AgentSession 字段足够生成训练样本，不需要改推荐 backbone；再检查 `tests/test_hybrid_demo.py` 中已有 `FakeHarnessQwenClient` 测试，确认还需补 `ModelUnavailableError` fallback 路径。

**解决方式：**
在 `turn_to_rollout_record()` 中新增 `training_samples` 字段，拆成 `sft_sample` 和 `reward_sample`：前者包含 user_input、assistant_response、feedback_constraints、candidate_summary、target_action、target_explanation，并用 `allowed_item_ids` 约束 selected_item_ids 只能来自当前候选；后者包含 policy_type、reward、reward_evidence、feedback_effect_observed 和 risk_flags。补充 Qwen harness fallback 测试，验证 deterministic_baseline、rule_feedback_rerank、qwen_feedback_rerank 三种模式即使 Qwen 不可用也会写出 comparison JSON/report 和 inference diagnostics。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py::test_qwen_evaluation_harness_writes_three_mode_comparison tests/test_hybrid_demo.py::test_qwen_evaluation_harness_writes_fallback_comparison_without_model_dependencies tests/test_agent_rollout_schema.py`，结果 `6 passed in 0.23s`；运行 `./.venv/Scripts/python.exe scripts/evaluation/run_qwen_evaluation_harness.py --config configs/demo/hybrid_demo/hybrid_demo_electronics_1000_lopo_semantic_title.yaml --limit-users 3 --output-dir outputs/agent/qwen/qwen_evaluation_harness_ralph_fallback --qwen-model-id missing-local-qwen` 成功生成 `outputs/agent/qwen/qwen_evaluation_harness_ralph_fallback/comparison.json` 和 `comparison.md`，其中 `qwen_feedback_rerank` 的 `fallback_count=1`、`routes={"qwen_local": 1}`。当前 Qwen / QLoRA / GRPO 仍未完整训练落地，本次工作是训练前 contract 与 bounded rerank 对照验证。

**面试可讲点：**
这次工作可以讲成“先把 Agent 交互闭环产品化为可训练数据，再把大模型能力接入约束在候选集内做可回退对照”：不是直接让 LLM 生成商品，而是让它输出 bounded rerank signals，并且在模型不可用时仍保留 deterministic/rule baseline 和诊断产物，体现了推荐系统中对可控性、可复现评估和训练数据 contract 的工程意识。

### 2026-04-28 - 展示层与多角色仿真规划边界预留

**任务：**
把后续真实商品展示、前端交互、多角色模拟客户和动画回放纳入项目规划，同时不打断当前推荐 backbone、Agent feedback、reward / rollout 的主线。

**遇到的问题：**
现有架构主要覆盖数据处理、召回、排序、Agent 对话反馈和训练前 contract，但没有显式说明商品卡展示、前端消费接口、多角色模拟客户和动画回放放在哪一层，后续如果直接开发前端或仿真场景，容易让 UI 字段、模拟客户和推荐内部逻辑耦合。

**定位方式：**
检查 `dic/PROJECT_STRUCTURE.md`、`dic/architecture/ARCHITECTURE.md`、`dic/architecture/IMPLEMENTATION_PLAN.md`、`dic/README.md` 和 `dic/OPTIMIZATION_NARRATIVE.md`，确认当前文档已覆盖 Agent 主轴和训练路线，但缺少展示层、前端层、仿真层和动画层的目录与边界说明。

**解决方式：**
预留 `rs_core/display/`、`rs_core/simulation/`、`rs_core/animation/` 和 `frontend/` 目录，并在核心文档中补充展示层、前端 / 服务层、仿真 / 动画层的职责：展示层负责商品卡 contract，前端只消费服务与展示接口，模拟客户作为合成交互评估流量，动画层只做 session / rollout 可视化回放。

**验证结果：**
通过目录检查确认 `.gitkeep` 已存在于新增目录；用文档检索确认 `display`、`simulation`、`animation`、`frontend`、商品展示卡、多角色和动画回放等关键条目已出现在 `PROJECT_STRUCTURE.md`、`architecture/ARCHITECTURE.md`、`architecture/IMPLEMENTATION_PLAN.md`、`README.md` 和 `OPTIMIZATION_NARRATIVE.md`。

**面试可讲点：**
这次调整体现的是从“推荐算法 demo”扩展到“可交互、可展示、可回放、可仿真的 Agent 推荐系统”的架构意识：推荐 backbone 和 Agent 决策仍是主线，商品卡 contract 解决产品化展示，多角色模拟客户用于压力测试交互闭环，动画层用于演示和复盘，但这些外围能力不会污染推荐排序和真实用户评估。

### 2026-04-28 - 商品展示 contract 与前端安全视图

**任务：**
推进 Phase 2 的展示层，把 Agent 最终推荐结果转换成前端可直接消费的 `DisplayResponse` / `ItemDisplayCard` contract，并为后续聊天前端和商品卡 UI 提供 canonical mock 输出。

**遇到的问题：**
已有 `session.json`、`session_turns.jsonl` 和 `grpo_rollouts.jsonl` 同时包含推荐结果、ranking、diagnostics、reward 和 training_samples，适合训练与诊断，但不适合直接交给前端；如果前端直接读 rollout，容易耦合排序分数、reward 证据和内部诊断字段。

**定位方式：**
检查 `rs_core/rsagent/schema.py`、`rs_core/rsagent/rollout.py`、`rs_core/rsagent/cli.py` 和 `rs_core/recsys/types.py`，确认 `AgentDecision.final_items` 已经是展示层最稳定的入口；同时确认商品 title、price、rating、image 等 metadata 不保证齐全，因此 contract 需要 nullable 字段和缺图兜底。

**解决方式：**
在 `rs_core/rsagent/schema.py` 新增 `ItemDisplayCard` 和 `DisplayResponse`，在 `rs_core/display/builder.py` 新增展示层 builder，只从最终推荐 item 和 metadata 派生前端安全字段；在 `rs_core/rsagent/rollout.py` 为每条 rollout 增加 `display_response`，在 `rs_core/rsagent/cli.py` 额外输出 `display_responses.jsonl` 和 `display_demo.json`，同时保持原训练/诊断输出不变。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_agent_rollout_schema.py tests/test_display_contract.py`，结果 `6 passed in 0.16s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；运行 canonical display demo 生成 `outputs/agent/canonical/agent_display_demo_canonical/display_responses.jsonl` 和 `display_demo.json`；定向检查 `outputs/agent/canonical/agent_display_demo_canonical/grpo_rollouts.jsonl` 中 5 条 `display_response`，确认没有泄漏 `score`、`diagnostics`、`reward_evidence`、`training_samples` 等内部字段。

**面试可讲点：**
这次工作体现的是从算法/Agent demo 走向产品化接口的工程边界设计：训练和诊断需要保留完整内部证据，但前端只需要稳定、安全、可容错的展示 contract。通过派生 `DisplayResponse`，推荐系统可以继续维护可解释诊断和 reward contract，同时让 UI、后续动画回放和多角色仿真复用同一个前端安全视图。

### 2026-04-28 - Phase 2 single-process serving demo

**任务：**
把已有 CLI / conversational Agent demo 封装成轻量 HTTP 服务入口，让后续前端、模拟客户或展示沙盒可以通过 API 调用推荐对话能力。

**遇到的问题：**
项目已有 `HybridRecommendationEnvironment`、`DisplayResponse` 和 CLI canonical demo，但缺少服务层边界；如果直接把 `AgentTurn` 或 rollout 返回给前端，会泄露 ranking、diagnostics、reward 等内部训练/诊断字段。

**定位方式：**
检查 `rs_core/workflow/hybrid_environment.py`、`rs_core/display/builder.py`、`rs_core/rsagent/schema.py` 和 `rs_core/rsagent/cli.py`，确认服务层应复用 `env.converse()` 和 `build_display_record()`，而不是重写推荐逻辑或直接暴露 session/turn 原始结构。

**解决方式：**
新增 `rs_core/serving/service.py`、`schema.py` 和 `app.py`，实现 single-process demo service：`RecommendationService` 在进程内维护 session dict，`/session/start` 使用 UUID 创建独立 session，`/chat` 只返回展示层 `DisplayResponse` contract；新增 `scripts/serving/run_service.py` 和 `requirements-serving.txt`，明确 FastAPI / uvicorn / httpx 依赖与 demo 服务边界。

**验证结果：**
安装 `requirements-serving.txt` 后运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py`，结果 `5 passed in 0.44s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；独立 verifier 给出 PASS，确认服务文件位于 `rs_core/serving/*`、未实现 `/feedback`、unknown session 返回 404，公开响应不含 `ranking`、`diagnostics`、`reward`、`score`。

**面试可讲点：**
这次工作把项目从 CLI 推荐 Agent demo 推进到可 HTTP 调用的服务 contract：底层推荐和 Agent 决策保持不变，服务层只做薄封装和 session 编排，对外统一返回前端安全的展示卡结构。这个边界既能支撑后续 Web Demo / 多角色模拟客户，也避免过早引入数据库、多进程状态和生产部署复杂度。

### 2026-04-28 - 最小 React 商品卡前端 Demo

**任务：**
把 Phase 2 serving demo 接到已有 Vite / React 前端骨架上，实现可交互的聊天输入、商品卡展示和反馈按钮，让推荐 Agent 从 HTTP contract 进一步变成可展示的 Web Demo。

**遇到的问题：**
前端原本主要读取 `mockData` 做静态商品卡展示；接入后端后还需要处理本地 FastAPI 与 Vite 的 CORS、后端重启导致的 session 丢失、真实 demo 数据没有固定 `frontend-demo-user` 这类联调边界。

**定位方式：**
检查 `frontend/src/App.tsx`、`frontend/src/types.ts`、`frontend/src/mockData.ts` 和 `rs_core/serving/app.py`，确认前端应只依赖 `/session/start` 和 `/chat` 的 `DisplayResponse` contract；按用户偏好通过 `omc ask gemini` 审阅前端实现，Gemini 建议保留 mock 降级、按钮转自然语言 feedback、图片兜底，并补 session 失效阻断、价格格式化和聊天记录自动滚动。

**解决方式：**
新增 `frontend/src/api.ts`，让前端启动时创建 session、提交聊天时调用 `/chat`，并继续用 `mockData` 作为后端未启动时的展示兜底；更新 `App.tsx` 渲染对话记录、assistant message、商品卡和 feedback actions；后端补本地 Vite CORS；按 Gemini 审阅意见补充 `Unknown session_id` 后禁用输入并提示刷新、数值价格格式化和消息自动滚动；修正前端默认不传固定 user，让后端选择 demo 数据中的首个用户。

**验证结果：**
运行 `npm --prefix frontend run build` 通过；运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `7 passed in 0.44s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；启动 `scripts/serving/run_service.py` 和 `npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173` 后，用 HTTP 验证 `/health`、默认 `/session/start` 和 `/chat` 返回 `rs_agent_display_v1`，5 个商品卡且响应不含 `ranking`、`diagnostics`、`reward`、`score`，前端页面可加载。

**面试可讲点：**
这次工作把推荐 Agent 从“服务可调用”推进到“用户可交互”：前端没有读取推荐内部字段，而是只消费 `DisplayResponse`，按钮反馈也先转成自然语言走 `/chat`，避免过早扩张 `/feedback` API。通过 Gemini 审阅补齐 session 失效和展示细节，体现了前后端 contract 隔离、Demo 范围控制和跨模型协作把关的工程过程。

### 2026-05-23 - 固定 pool500 offline eval baseline 收口

**任务：**
基于固定 `outputs/eval/pool500_offline_eval_users_10k/manifest.json`，不改召回策略、不使用 oracle 或 label 注入，运行当前 pool500 召回主路并生成 baseline candidates、整体/分层 Recall 与 HitRate、source audit 和 baseline manifest。

**遇到的问题：**
现有 `run_full_data_pool500_recall_only.py` 能按 target users 生成 pool500 candidates，但它只接受旧 aligned eval target schema，不能直接消费新的 `pool500_offline_eval_users_v1` manifest；同时 metrics 必须读取完整 valid/test labels 做后验评估，但这些 labels 不能进入候选生成路径。

**定位方式：**
读取固定 manifest 与 `users.jsonl`，确认 `user_set_hash=eb63bae51126aa572072415236eb8efbb14979be7b9ae7edf21d555077136b33`、`total_user_count=10000`、segment 为 hot/warm/cold-ish = 4000/4000/2000，且 split/leakage contract 明确 history 只来自 train、labels 只用于 evaluation。审查 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py`，确认可复用当前 `current` recall profile 和主路 source budget；排除 `build_pool500_diagnostic_oracle_candidates.py`、`build_pool500_label_artifact.py` 等 diagnostic/oracle 产物。

**解决方式：**
新增 `rs_lab/experiments/recall/run_pool500_offline_eval_baseline.py` 作为最小 wrapper：先校验 fixed eval manifest 与用户 hash，再写入仅含 target_user_ids 的治理兼容 manifest 供当前主路读取；候选生成完成后才读取 valid/test positive labels 计算 Recall@50/100/500 与 HitRate@50/100/500，并输出 `baseline_manifest.json`、`metrics.json`、`segment_metrics.json`、`source_audit.json`。补充 `tests/test_pool500_offline_eval_baseline.py`，覆盖 hash、artifact 写出、segment metrics、重复 user-item 拒绝和 no_oracle 标记。

**验证结果：**
先用 `--limit-users 100` dry-run 跑通 `outputs/eval/pool500_offline_eval_baseline_current_dry_run_100/`；随后正式运行 `outputs/eval/pool500_offline_eval_baseline_current/`，生成 10,000 用户 × 500 candidates，共 5,000,000 行，`underfilled_user_count=0`、重复 user_id+item_id 为 0。整体指标：Recall@50=0.014107、HitRate@50=0.0227、Recall@100=0.017892、HitRate@100=0.0293、Recall@500=0.022856、HitRate@500=0.0392。分层 Recall@500/HitRate@500：hot=0.026903/0.05375，warm=0.021819/0.032，cold-ish=0.016839/0.0245。source audit 显示 primary source 中 category=52.0713%、two_tower=27.7813%、swing=11.7669%、popular=3.3905%，popular+category=55.4618%，usercf_recall 仅 0.0108%。验证命令：`.venv/Scripts/python -m pytest tests/test_pool500_offline_eval_baseline.py tests/test_full_data_pool500_recall_only.py -q` 结果 `25 passed`；实际产物校验确认 candidate users 与固定 eval users 完全一致、hash 一致、metrics/segments 字段齐全、`no_oracle_label_injection=true`。

**面试可讲点：**
这段可以讲成“把召回优化前的对照基线做成不可漂移的评估契约”：先冻结 eval users、split 与 leakage policy，再复用当前主路生成候选，最后只在后验指标层读取 label，避免为了指标更换用户或注入 oracle。结果显示当前短板不是 pool500 填充不足，而是候选覆盖和用户覆盖都偏低，尤其 cold-ish 拖后腿、category/popular 占比偏高且 UserCF 贡献极低，为后续优化提供了可信对照。

### 2026-04-28 - 结构化 feedback API 与前端按钮闭环

**任务：**
把 Web Demo 中的反馈按钮从“转成自然语言再走 `/chat`”升级为结构化 `/feedback` API，让按钮反馈成为可记录、可测试、可扩展的交互事件。

**遇到的问题：**
最小前端 Demo 的按钮反馈虽然可用，但语义依赖英文 prompt 映射，不利于后续统计、回放和训练样本构造；同时前端按钮如何与自由文本 `/chat` 共存、是否携带 item_id、如何处理后端重启后的 session 失效，需要明确边界。

**定位方式：**
检查 `rs_core/serving/schema.py`、`rs_core/serving/service.py`、`rs_core/serving/app.py` 和 `frontend/src/App.tsx`、`frontend/src/api.ts` 的接口边界；按用户要求通过 `omc ask gemini` 审阅前端结构化 feedback 接入方案，Gemini 明确建议输入框只走 `/chat`，快捷按钮只走 `/feedback`，移除 `ACTION_MESSAGES` 自然语言硬编码，并复用 loading 与 session 失效处理。

**解决方式：**
后端新增 `FeedbackRequest` / `FeedbackResponse` 和 `POST /feedback`，支持 `like`、`dislike`、`show_different`、`why` 四种 `action_type`，内部仍复用 `env.converse()` 与 `build_display_record()`，保持输出为 `DisplayResponse`；前端新增 `sendFeedback()`，按钮直接发送 `{session_id, action_type}`，并与 `/chat` 共用 `isLoading`、`applyDisplayUpdate()` 和 `handleRequestError()`，保留后续商品级 `item_id` 反馈的扩展空间。

**验证结果：**
运行 `npm --prefix frontend run build` 通过；运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `11 passed in 0.51s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；启动后端和前端后，用 HTTP 验证 `/health`、默认 `/session/start`、`/chat` 和 `/feedback`，`/feedback` 返回 `rs_agent_display_v1`、turn_index 更新为 2、5 个商品卡，并确认响应不含 `ranking`、`diagnostics`、`reward`、`score`。

**面试可讲点：**
这次工作把前端反馈从 prompt hack 升级为结构化事件 contract：自由文本仍由 `/chat` 处理，按钮语义由 `/feedback` 表达，后端再统一转入 Agent 决策链路。这样既保持了当前 demo 的轻量实现，又为后续 feedback 日志、session replay、多角色模拟客户和 GRPO reward 样本提供了稳定事件入口。

### 2026-05-18 - pool500 方法级数据集治理 contract

**任务：**
为 pool500 召回方法补齐方法级数据集治理与 drift gate，明确不同方法在全量数据、定制数据集和延后证据之间的边界。

**遇到的问题：**
pool500 已进入全量候选池治理阶段，但轻量方法、重资源方法和延后方法如果共用模糊口径，容易把未验证的全量可用性误读成最终 ready，或把需要定制数据集的重方法误纳入默认链路。

**定位方式：**
核对 `configs/recall/pool500_method_registry.json`、`dic/recall_methods/*/METHOD.md` 与相关 route gate 测试，确认 registry、方法文档和测试约束需要共同表达：轻量方法默认可沿用主数据策略，资源重的方法必须显式声明 custom dataset policy，deferred 方法只能保留证据边界。

**解决方式：**
在 pool500 method registry 中加入方法级 dataset contract，并同步方法文档说明：轻量方法采用 default policy，resource-heavy 方法采用 custom dataset policy，deferred 方法不宣称可执行晋升；新增独立 drift pytest gate，防止 registry 与方法文档口径漂移。本次只做 governance/readiness contract，不提升任何 source，不修改 `current_route_registry.yaml`，也不宣称 pool500 最终就绪。

**验证结果：**
使用项目 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_method_registry_drift.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_recall_source_registry.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_route_gate.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_p7_full_pool500_route_gate.py -q`，结果 `67 passed in 0.85s`。未运行 full-data/full-run。

**面试可讲点：**
这段可以讲成“推荐召回实验从跑方法升级到治理方法证据”：轻量、重资源和 deferred 方法不是用同一个 ready 标签粗暴处理，而是通过 registry contract、method doc 和 drift test 形成可审计边界，保证后续 pool500 链路扩展时既能复用轻量主路，又不会把重资源实验或缺证据方法误晋升。

### 2026-04-28 - session 轨迹安全导出与 replay 基础

**任务：**
在 structured feedback API 之后补齐 `GET /session/{session_id}`，让服务层可以导出当前会话轨迹，为后续 replay、模拟客户评估和前端调试提供安全数据入口。

**遇到的问题：**
`AgentSession.to_dict()` 和 `AgentTurn.to_dict()` 会包含 `ranking`、`diagnostics`、`reward_evidence`、`reward` 等内部诊断与训练字段，不能直接作为公开 API 返回；但如果只返回最后一轮 `DisplayResponse`，又无法支撑多轮 replay 和反馈闭环复盘。

**定位方式：**
检查 `rs_core/serving/service.py`、`rs_core/serving/schema.py`、`rs_core/serving/app.py`、`rs_core/rsagent/schema.py` 和 `rs_core/display/builder.py`，确认安全边界应复用 `build_display_record()`，事件摘要只保留 `turn_index`、`user_input`、`assistant_message` 和 display 索引，不暴露 turn 原始结构。

**解决方式：**
在 `RecommendationService` 新增 `export_session()`，返回 `session_id`、`user_id`、`turn_count`、轻量 `events` 和逐轮 `display_responses`；在 serving schema 中新增 `SessionExportResponse`，并在 FastAPI 中新增 `GET /session/{session_id}`，继续复用统一的 unknown session 404 处理。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `13 passed in 2.41s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；运行 `npm --prefix frontend run build` 通过。新增测试覆盖 chat+feedback 后的 session export、unknown session 404，并递归断言公开响应不含 `ranking`、`diagnostics`、`reward`、`reward_evidence`、`score`。

**面试可讲点：**
这次工作体现的是“可回放但不泄露内部诊断”的服务 contract 设计：训练和调试侧仍保留完整 AgentTurn / rollout，公开 API 只暴露展示层和轻量事件索引。这样既能支撑后续 session replay、多角色模拟客户和前端调试，又不会把排序分数、reward 证据等内部实现绑死到前端或外部消费者。

### 2026-04-28 - session export 结构化 feedback 事件元数据

**任务：**
增强 `GET /session/{session_id}` 的 replay 事件，让反馈轮次既保留 Agent 实际收到的 `user_input`，也保留原始结构化 `action_type`、`item_id` 和 `comment`。

**遇到的问题：**
上一版 session export 已经安全，但 feedback 事件在导出中只表现为转译后的 prompt，例如 `why? item_id=...`；这对复盘 Agent 行为足够，却不利于后续按按钮类型统计、重放 UI 事件或构造结构化反馈样本。

**定位方式：**
检查 `rs_core/serving/service.py` 和 `tests/test_serving_smoke.py`，确认结构化 feedback 信息在 `/feedback` 请求边界存在，但没有被保留下来；同时确认不应修改 `AgentSession` / `AgentTurn` 训练 schema，以免把服务层事件日志和 Agent 内部状态耦合。

**解决方式：**
在 `RecommendationService` 中新增独立的 `session_events` 轻量列表：`/chat` 记录 `{type: chat}`，`/feedback` 记录 `{type: feedback, action_type, item_id, comment}`；`export_session()` 将这些 metadata 与对应 turn 的 `user_input`、`assistant_message`、`display_response_index` 合并导出。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `13 passed in 0.59s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；运行 `npm --prefix frontend run build` 通过。测试确认 chat 事件与 feedback 事件类型可区分，feedback 事件包含 `action_type/item_id/comment`，公开响应仍不含内部排序、诊断和 reward 字段。

**面试可讲点：**
这次工作体现的是把“Agent 实际输入证据”和“产品交互事件语义”分层保存：Agent 仍消费转译后的自然语言 prompt，服务层额外保留按钮事件 metadata。这样后续 replay、统计分析和训练样本构造可以使用结构化事件，而不会破坏当前轻量 demo 的 Agent schema。

### 2026-04-28 - Gemini 实现 Session Replay 前端闭环

**任务：**
在已有 React 商品卡 Demo 中接入 `GET /session/{session_id}`，把 chat、feedback、display response 串成可视化 Session Replay 时间线，并按用户要求由 Gemini 负责前端实现。

**遇到的问题：**
后端已经能安全导出 session 轨迹，但前端还只能看到当前轮商品卡，不能复盘多轮对话、按钮反馈和每轮推荐变化；同时项目要求前端实现优先交给 Gemini，而不是由我先改再让 Gemini 审阅。

**定位方式：**
对照 `frontend/src/App.tsx`、`frontend/src/api.ts`、`frontend/src/types.ts` 和后端 `SessionExportResponse` contract，明确前端只允许消费 `events` 与 `display_responses`，不能读取 `ranking`、`diagnostics`、`reward`、`score` 等内部字段；通过 Gemini CLI 直接执行前端实现，再由我做边界检查和验证。

**解决方式：**
由 Gemini 在 `frontend/src/types.ts` 增加 `SessionExportEvent` / `SessionExportResponse` 类型，在 `frontend/src/api.ts` 增加 `fetchSessionExport()`，并在 `App.tsx` 增加 `Replay Session` 按钮、loading/error 状态和只读 timeline：每轮展示 turn、chat/feedback 类型、feedback metadata、assistant message 和对应商品快照。

**验证结果：**
运行 `npm --prefix frontend run build` 通过；运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `13 passed in 0.57s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；检索 `frontend/src` 确认没有引用 `ranking`、`diagnostics`、`reward`、`reward_evidence`、`score`；通过临时本地服务 HTTP 验证 chat→feedback→session export，导出包含 `event_types=[chat, feedback]` 且无内部字段泄露。

**面试可讲点：**
这次工作把推荐 Agent demo 从“当前轮展示”推进到“完整交互轨迹可回放”：用户输入、结构化反馈、Agent 回复和商品卡变化都能按 session timeline 复盘。工程上体现了前后端 contract 隔离、内部诊断字段保护，以及用 Gemini 承担前端实现、我负责接口边界和验收整合的协作流程。

### 2026-04-28 - 多角色模拟的角色内在模型基础层

**任务：**
把“多角色模拟客户”从一次性测试脚本调整为后续模拟场景的角色内在基础层，先实现可复用的角色画像、状态和 deterministic 行为策略。

**遇到的问题：**
如果直接做批量 simulated session runner，容易把多角色模拟降级成 smoke test；但项目后续目标是类似沙盒/游戏场景的多角色客户，每个角色需要有稳定人格、购物目标、偏好、记忆、反馈风格和状态演化，才能支撑 replay、动画和更真实的 Agent 评估。

**定位方式：**
对照已有 `rs_core/simulation/` 骨架和当前 `DisplayResponse` contract，确认 simulation 层应先消费前端安全展示数据，而不是读取推荐内部 ranking/reward；同时根据用户反馈明确：角色内在状态应优先于批量评估脚本。

**解决方式：**
新增 `rs_core/simulation/schema.py`，定义 `SimulatedCustomerRole`、`RoleState`、`RoleActionType`、`RoleAction`；新增 `policy.py`，用 deterministic `RolePolicy` 根据角色偏好、预算敏感度、负偏好和当前 display items 选择 chat、why、show_different、dislike、accept 等动作；新增 `presets.py`，提供通勤实用型、礼物购买型、价格敏感型三个内置角色，并通过 `rs_core/simulation/__init__.py` 导出。

**验证结果：**
新增 `tests/test_simulation_roles.py` 覆盖初始 prompt、preset 注册、已看商品状态更新、无商品时追问、有强匹配商品时接受、谨慎角色要求解释、不同 feedback style 产生不同动作；运行 `./.venv/Scripts/python.exe -m pytest tests/test_simulation_roles.py tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `20 passed in 0.57s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过。

**面试可讲点：**
这次工作体现的是把多角色模拟从“跑几条 prompt”提升为“角色内在模型”：角色画像、目标、偏好、记忆和反馈风格决定下一步行为，且只依赖安全 `DisplayResponse`。这为后续多角色沙盒、session replay 动画、模拟客户评估和 LLM-driven role simulation 留出了清晰扩展点。

### 2026-04-28 - Simulation Scene 后端契约与前端展示闭环

**任务：**
把角色内在模型接到真实 Agent 服务层，生成可供前端展示的 simulation scene，并按用户要求由 Gemini 实现前端场景面板。

**遇到的问题：**
角色画像和策略已经存在，但还没有驱动真实 Agent session；前端也无法展示“角色如何带着目标、偏好和反馈风格与推荐 Agent 交互”的完整场景。如果前端直接造假数据，会削弱 replay 和评估价值；如果后端直接暴露 AgentTurn，则又会泄露 ranking/reward 等内部字段。

**定位方式：**
检查 `rs_core/simulation/schema.py`、`policy.py`、`presets.py`、`rs_core/serving/service.py` 和 `SessionExportResponse` contract，确认最稳妥的连接方式是让 runner 复用 `RecommendationService.chat()` / `feedback()` 和 `export_session()`，输出 role、state、actions、session 四段安全 scene contract。

**解决方式：**
新增 `rs_core/simulation/runner.py`，实现 `run_simulation_scene()`：角色先发 `initial_prompt()`，随后由 `RolePolicy` 根据每轮 `DisplayResponse` 选择 chat、feedback、show_different、why、accept 等动作，最终导出 `scene_id`、角色画像、角色状态、动作时间线和安全 session export；在 FastAPI 中新增 `POST /simulation/scene`，并让 Gemini 在前端新增 Simulation Scene 面板，支持选择 `commuter_practical`、`gift_buyer`、`price_sensitive`，展示角色卡、状态卡、动作时间线和 session summary。

**验证结果：**
新增 `tests/test_simulation_runner.py` 覆盖 runner contract、API endpoint 和 unknown role；运行 `./.venv/Scripts/python.exe -m pytest tests/test_simulation_runner.py tests/test_simulation_roles.py tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `23 passed in 0.60s`；运行 `npm --prefix frontend run build` 通过；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；检索 `frontend/src` 确认没有引用 `ranking`、`diagnostics`、`reward`、`reward_evidence`、`score`；本地 HTTP 验证 `POST /simulation/scene` 返回 `role_id=commuter_practical`、`turn_count=3`、`final_action=show_different` 且无内部字段泄露。

**面试可讲点：**
这次工作把项目从“单个用户手动 demo”推进到“角色驱动的可展示模拟场景”：角色内在状态决定交互行为，Agent 服务生成真实推荐与反馈轨迹，前端以 scene 面板展示角色、状态、动作和商品卡回放。它为后续多角色沙盒、动画展示、LLM 驱动角色和批量模拟评估提供了可复用 contract。

### 2026-04-29 - 端到端推荐 Agent 演示闭环聚合

**任务：**
把已有服务层、展示层和 React 前端推进成可一键演示的多轮闭环：用户需求进入 Agent，服务返回 `DisplayResponse` 商品卡，反馈后第二轮推荐发生变化，并能在前端按商品提交喜欢/不喜欢。

**遇到的问题：**
项目已有 `/chat`、`/feedback`、session replay 和商品卡前端，但面试演示仍需要人工分多步操作；同时测试环境当前缺少 `pytest` 和 `fastapi`，不能直接跑完整 HTTP 测试套件。

**定位方式：**
检查 `rs_core/serving/service.py`、`rs_core/serving/app.py`、`rs_core/display/builder.py`、`frontend/src/App.tsx` 和 `tests/test_serving_smoke.py`，确认可复用 `RecommendationService.chat()`、`feedback()` 与 `DisplayResponse`，不需要让前端读取 rollout、ranking、diagnostics 或 reward 字段。

**解决方式：**
在服务层新增 `run_demo_roundtrip()` 和 `/demo/e2e`，聚合 start session、首轮 chat、结构化 feedback 和变化摘要；前端新增一键闭环按钮，并把商品卡上的喜欢/不喜欢绑定到具体 `parent_asin`；补充 smoke 测试用例覆盖两轮展示、turn_index 递增、商品变化和内部字段不外泄。

**验证结果：**
补齐 serving/test 依赖后，运行 `python -m pytest tests/test_serving_smoke.py tests/test_display_contract.py -q`，结果 `15 passed in 1.35s`；运行 `python -m compileall -q rs_core tests scripts` 通过；运行 `npm --prefix frontend run build` 通过。测试覆盖 `/demo/e2e` 的两轮 `DisplayResponse`、`turn_index` 递增、商品集合变化、unknown feedback 422，以及公开响应不含 `ranking`、`diagnostics`、`reward`、`reward_evidence`、`score`。

**面试可讲点：**
这次工作把推荐 Agent 从“有接口、有前端”推进到“可一键复现闭环”：服务端用薄 orchestration 串起现有推荐和反馈能力，前端只消费展示 contract，变化摘要用于证明反馈确实影响下一轮推荐。这个实现兼顾了演示效率、前后端边界隔离和后续训练/回放数据的可解释性。

### 2026-04-29 - 批量多角色 Simulation Evaluation 闭环

**任务：**
把单个 simulation scene 扩展成批量多角色评估入口，让多个 persona 自动与推荐 Agent 交互，并生成可复现的 metrics/report 产物。

**遇到的问题：**
此前系统已经能展示单个角色与 Agent 的交互场景，但缺少多 persona、重复运行、统一指标和落盘报告；这使多角色模拟更像展示 demo，而不是能支撑评估、复盘和后续训练样本构造的闭环。

**定位方式：**
检查 `rs_core/simulation/runner.py`、`rs_core/serving/service.py`、`rs_core/serving/app.py` 和 `tests/test_simulation_runner.py`，确认最稳妥的做法是复用 `run_simulation_scene()`、`RecommendationService.chat()/feedback()/export_session()` 与安全 `DisplayResponse` contract，而不是重写推荐逻辑或暴露内部 ranking/reward 字段。

**解决方式：**
在 `rs_core/simulation/runner.py` 新增 `run_simulation_batch()`、scene metrics 和 batch summary；在 `rs_core/serving/app.py` / `schema.py` 新增 `/simulation/batch`；新增 `scripts/evaluation/run_simulation_evaluation.py`，输出 `simulation_batch.json`、`metrics.json` 和中文 `simulation_eval_report.md`。公开输出继续递归阻断 `ranking`、`diagnostics`、`reward`、`reward_evidence`、`score` 等内部字段。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_simulation_runner.py tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `23 passed in 0.75s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；运行 `./.venv/Scripts/python.exe scripts/evaluation/run_simulation_evaluation.py --limit-users 1 --max-turns 3 --repeats 1 --output-dir outputs/simulation/simulation_eval_smoke_default` 成功生成 `simulation_batch.json`、`metrics.json` 和 `simulation_eval_report.md`。

**面试可讲点：**
这次工作把多角色模拟从“单场景展示”推进到“可量化评估闭环”：不同 persona 可以批量驱动真实 Agent 服务，系统聚合 accept rate、平均轮数、反馈/解释/换榜行为和满意度指标，同时保持前端安全视图边界。这为后续 session replay、模拟客户评估、SFT 样本和 GRPO reward 对照提供了稳定数据基础。

### 2026-04-29 - 模型驱动模拟用户策略接入

**任务：**
让多角色模拟客户可以选择由外部模型 API 驱动下一步行为，同时保留 deterministic 规则策略作为默认路径和 fallback。

**遇到的问题：**
此前多角色模拟虽然能批量运行，但角色行为仍是规则策略，难以表现更自然的模拟用户差异；同时 API base、key、model 这类敏感或易变参数不能硬编码进代码、日志或提交文件。

**定位方式：**
检查 `rs_core/simulation/policy.py`、`rs_core/simulation/runner.py` 和 `scripts/evaluation/run_simulation_evaluation.py`，确认模型能力应接在 RolePolicy 层，只决定模拟用户的 `chat/why/show_different/dislike/accept` 行为，不改变推荐候选、排序、reward 或 `DisplayResponse` contract。

**解决方式：**
新增被 `.gitignore` 保护的本地配置约定 `configs/simulation_model.local.json`，并提供非敏感模板 `configs/simulation_model.example.json`；新增 `rs_core/simulation/model_client.py`，用 OpenAI-compatible `/v1/chat/completions` 调用外部模型；在 `rs_core/simulation/policy.py` 新增 `ModelDrivenRolePolicy`，约束模型只能返回允许 action 且 item_id 必须来自当前展示商品；在 `scripts/evaluation/run_simulation_evaluation.py` 增加 `--role-policy model`、`--model-config` 和 `--strict-model-policy`。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_simulation_roles.py tests/test_simulation_runner.py tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `37 passed in 0.73s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；运行 `./.venv/Scripts/python.exe scripts/evaluation/run_simulation_evaluation.py --role-policy model --model-config configs/simulation_model.local.json --limit-users 1 --max-turns 2 --repeats 1 --output-dir outputs/simulation/simulation_eval_model_fallback_smoke_2` 成功生成评估产物，并在本地配置缺失时记录 deterministic fallback。

**面试可讲点：**
这次工作把模拟客户从固定规则升级为可插拔模型策略：外部模型只负责用户侧行为生成，系统用 JSON action schema、展示商品白名单和 deterministic fallback 保证可控性。这样既能提升多角色模拟的自然度，也不会让大模型越权影响推荐排序或泄露内部诊断字段。

### 2026-05-19 - pool200 主路方法迁移到 pool500 direct recall

**任务：**
把 pool200 已确认主路方法迁移到 pool500 direct recall，整合 `semantic_title_category_expansion`、`two_tower`、`co_visit_fallback_repair`、`usercf_recall`、`swing_recall`、`itemcf_weak`、`itemcf_strong`、`category`、`popular` 九路 source，生成当前 pool500 主路 direct recall 候选池。

**遇到的问题：**
部分方法 artifact 来自新 full clean / train-only 数据基础补齐，其中 `two_tower` / YouTubeDNN 是主要缺口；初始全量运行中 two_tower 向量检索和 metadata neighbor 扫描成为耗时瓶颈，同时 `usercf_recall` 的历史 manifest 缺少显式 `source_status` 字段，容易被过严 loader 拒绝。

**定位方式：**
先逐一核对各 `source_index_manifest.json` 的 `source/canonical_source/index_scope/train_only` 与禁用边界，再用 focused pytest、ruff 和运行输出审计定位缺口。最终 direct recall 输出位于 `outputs/recall/pool500_main_route_direct_recall_full_promoted/`，`manifest.json` 记录 `processed_users=500`、`candidate_rows=74978`、`underfilled_user_count=500`，`source_contribution_audit.json` 与 `pool500_candidates.jsonl` 均确认 `co_visit_fallback_repair` 已实际产生候选。

**解决方式：**
为 `VectorIndex` 增加 NumPy 向量化 top-k 与批量 `search_many`，runner 中预计算 two_tower recall；兼容安全的 legacy UserCF manifest，但继续要求 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`；对 metadata neighbor 增加 batch 侧候选桶限流，保持 co-visit 仍作为 batch-scoped diagnostic source 输出。

**验证结果：**
运行命令使用项目 `.venv` 执行 `run_full_data_pool500_recall_only.py --limit-users 500 --enable-semantic --semantic-max-rows 200000` 并显式传入 six 个 source manifest，退出码为 0。输出 manifest 决策仍为 `STOP` / `diagnostic_limited`，不允许 promotion、ranking input replacement 或 pool1000；但 `source_coverage` 已包含九路主路 source：`category=35880`、`co_visit_fallback_repair=9898`、`itemcf_strong=1992`、`itemcf_weak=2070`、`popular=19112`、`semantic_title_category_expansion=6267`、`swing_recall=3073`、`two_tower=180`、`usercf_recall=8364`。`final_resource_audit.status=PASS`，`users_with_500_candidates_ratio=0.0`，underfill 审计保持 `DIAGNOSTIC_ONLY_PARTIAL`。focused pytest 结果 `21 passed`，ruff touched files `All checks passed!`。

**面试可讲点：**
这段可以讲成“在时间紧张下用 artifact contract 和 source coverage 收口多召回方法主路迁移”：不是等待每个方法长期 READY，也不是伪造 final ready，而是把各方法的 full-clean train-only artifact 接入同一个 direct recall runner，用 source coverage、per-source readiness、resource audit 和禁用 flags 证明候选池可进入排序输入冻结讨论，同时清楚保留 STOP/diagnostic 边界。

### 2026-04-29 - 核心文档阶段状态收口

**任务：**
同步项目核心文档的当前状态，把 README、实施计划、架构说明、目录说明和优化叙事从“展示/前端/仿真仍在规划中”的旧口径，更新为“已完成第一版，下一步进入训练样本收口”的真实阶段。

**遇到的问题：**
工程日志已经记录了 `DisplayResponse`、HTTP 服务、React Web Demo、Session Replay、`/demo/e2e`、Simulation Batch 和模型驱动模拟用户，但核心入口文档仍保留 Phase 2 / Phase 3 规划中、`frontend/` 仅预留等表述，容易让读者低估项目完成度，也会削弱面试演示主线。

**定位方式：**
对照 `prd.json` 中已通过的 rollout contract / Qwen harness story，以及 `dic/ENGINEERING_NARRATIVE_LOG.md` 中 2026-04-28 至 2026-04-29 的服务、前端、replay、simulation 记录；再用关键词检索 `规划中`、`当前仅预留`、`后期规划会补` 等旧表述，定位到 `dic/README.md`、`dic/architecture/IMPLEMENTATION_PLAN.md`、`dic/architecture/ARCHITECTURE.md`、`dic/PROJECT_STRUCTURE.md` 和 `dic/OPTIMIZATION_NARRATIVE.md`。

**解决方式：**
将核心文档统一改成阶段收口口径：Phase 2 展示 contract / 服务层 / React Web Demo 已完成第一版，Phase 2.5 Session Replay 和一键 E2E 闭环已完成第一版，Phase 3 多角色 Simulation 和模型驱动模拟用户已完成第一版；同时明确 Qwen3.5-4B + 8-bit QLoRA SFT + GRPO 尚未完整训练落地，当前服务仍是 single-process demo，前端和仿真不是生产级真实用户评估。

**验证结果：**
运行关键词检查确认核心文档中不再出现 `当前仅预留`、`后期规划会补商品展示卡`、`商品展示卡 contract 与轻量前端 demo` 等过期表述；运行 `./.venv/Scripts/python.exe - <<'PY' ... PY` 校验 5 个核心 Markdown 文件均可用 UTF-8 读取、非空，且不含关键过期口径，输出 `validated 5 markdown files`。

**面试可讲点：**
这次工作体现的是阶段治理和工程叙事能力：当功能快速推进后，及时把入口文档、实施计划和架构边界同步到真实状态，避免“代码已完成但文档仍像规划”的信息漂移；同时保留训练未落地、服务非生产级、仿真非真实用户的边界，能让项目叙事可信而不夸大。

### 2026-05-07 - Phase 4 轨迹样本与 Agent 行为评估方向澄清

**任务：**
明确 Phase 4 的下一步主线：把 Web Demo 和多角色 Simulation 产生的 session 轨迹标准化为可审计的 Agent training trajectories。

**遇到的问题：**
项目已经具备 Web Demo、结构化 feedback、Session Replay、多角色 Simulation 和模型驱动模拟用户第一版，但下一阶段不能简单理解为“继续扩展示功能”或“马上训练 Qwen”。需要先把交互闭环沉淀成后续 SFT、preference learning 和 RL / GRPO 能复用的数据来源。

**定位方式：**
对照当前 `dic/architecture/IMPLEMENTATION_PLAN.md`、`dic/architecture/ARCHITECTURE.md`、`rs_core/serving/*`、`rs_core/simulation/*` 和 `scripts/evaluation/run_simulation_evaluation.py`，确认已有能力已经能生成 session、feedback、display response、simulation scene / batch 和 metrics，缺口在统一 trajectory schema、样本导出、质量校验和 Agent 行为指标。

**解决方式：**
将下一阶段表述为：先把 Web Demo 和多角色 Simulation 产生的 session 轨迹标准化为可审计的 Agent training trajectories，里面同时支持 SFT 样本、preference 样本和 RL rollout 样本。这样后续 `Qwen3.5-4B + QLoRA + GRPO` 可以基于真实交互约束和反馈信号优化，而不是离线凭空构造训练数据。

**验证结果：**
本次是路线澄清与叙事记录，未修改代码、未运行新的实验。当前可验证依据是已有服务层 session export、simulation batch 输出、结构化 feedback 事件和批量评估 metrics/report 产物。

**面试可讲点：**
这条主线可以概括为“先采集和标准化交互轨迹，再做可控训练”：Agent 当时能选哪些候选、实际推荐了什么、用户或模拟用户如何反馈、下一轮是否改正，都被记录进 trajectory。后续 RL / GRPO 的 state、action、reward 和 rollout 不是人工拼出来的，而是来自可回放、可审计的推荐交互闭环。

### 2026-05-07 - 10k 数据验证 semantic_title 召回路线

**任务：**
将已有 title/category-only semantic recall 路线扩展到 10k 数据规模，验证它相对 baseline 是否真实提升传统召回效果。

**遇到的问题：**
1000 小样本上的 `semantic_title` 提升可能存在偶然性；同时用户指出“买过相似标题商品不代表还会重复购买同类商品”，因此需要在更大数据上验证 `semantic_title` 作为补充召回源是否有效，并识别它对排序融合的副作用。

**定位方式：**
基于 `data/processed/amazon_2023_base/manifest.json` 构建 `amazon_2023_recall_clean_10000` 和 `amazon_2023_recall_views_10000`；复制 1000 配置生成 `configs/demo/hybrid_demo/hybrid_demo_electronics_10000*.yaml`；运行 baseline、semantic_title、LOPO baseline、LOPO semantic_title 四组对照，并读取 `outputs/hybrid_demo/hybrid_demo_small_electronics_10000*/metrics.json` 与 `ranking_case_summary.json`。

**解决方式：**
没有新增一条完全不同的召回算法，而是把已有 `semantic_title` 路线迁移到 10k 数据上做 ablation：它使用 `title_clean`、`main_category`、`categories_flat` 的 token overlap 做确定性文本召回。第一轮只改数据路径、输出目录和报告名，不改排序权重，保证 baseline 与 semantic_title 的对照尽量干净。

**验证结果：**
valid/test 口径中，`candidate_hit_users` 从 23 提升到 60，`ranked_hit_users` 从 5 提升到 14，`hit_rate@5` 从 0.007013 提升到 0.019635；LOPO 口径中，`candidate_hit_users` 从 74 提升到 1298，`ranked_hit_users` 从 68 提升到 1044，`hit_rate@5` 从 0.049204 提升到 0.755427。副作用也很明确：LOPO 中 `itemcf_only_hit_rate@5=0.887844` 高于 hybrid semantic_title 的 0.755427，且候选命中平均排名仍偏后，说明 `semantic_title` 明显提升覆盖，但当前融合排序稀释了 ItemCF 强信号。

**面试可讲点：**
这不是简单“加文本相似召回”，而是通过 10k ablation 证明 semantic/title recall 作为增量召回源能显著提升候选覆盖；同时主动暴露局限：标题相似不等于下一次购买意图，semantic-only 候选可能压住 ItemCF。下一步应做 source-aware fusion，在保留 `semantic_title` 覆盖收益的同时保护 ItemCF 和多源一致性信号。

### 2026-05-08 - 10k source-aware fusion 排序优化

**任务：**
在 10k `semantic_title` 召回验证后，优化传统推荐 backbone 的融合排序，让文本召回带来的候选覆盖尽量转化为 Top-K 排序收益，同时保持 Agent 作为独立交互编排层，不把它简单归入精排模块。

**遇到的问题：**
`semantic_title` 已经显著提升候选池覆盖，但 LOPO 中 `itemcf_only_hit_rate@5=0.887844` 仍高于 hybrid semantic_title 的 `0.755427`，说明当前线性加权排序会稀释 ItemCF 强信号。直接强保护 ItemCF 又会伤害 valid/test，因为 valid/test 的一部分 target 主要由 semantic 命中。

**定位方式：**
在 `rs_core/recsys/ranking.py` 增加默认关闭的 `source_aware_fusion`，分别运行 10k valid/test 与 LOPO source-aware 对照；读取 `outputs/hybrid_demo/hybrid_demo_small_electronics_10000_semantic_title_source_aware/metrics.json`、`outputs/hybrid_demo/hybrid_demo_small_electronics_10000_lopo_semantic_title_source_aware/metrics.json` 和对应 `ranking_case_summary.json`，同时对比强保护版与温和版参数。

**解决方式：**
新增可解释的 source-aware fusion：对 ItemCF 候选加分，对 ItemCF + 多源候选额外加分，对 semantic-only / popular-only 做轻量惩罚，并在 `rerank_events` 中记录 `source_aware_fusion` 事件；新增 `configs/demo/hybrid_demo/hybrid_demo_electronics_10000_semantic_title_source_aware.yaml` 与 LOPO 配置。最终保留温和参数 `itemcf_source_boost=8.0`、`itemcf_multi_source_boost=4.0`、`semantic_only_penalty=4.0`、`popular_only_penalty=2.0`，并把 `source_aware_fusion` 写入实验报告的 `config_summary`。

**验证结果：**
单测 `./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_inference_policy.py` 通过，结果 `49 passed`；`./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过。强保护版在 LOPO 中将 `hit_rate@5` 从 `0.755427` 提升到 `0.810420`，但 valid/test 从 `0.019635` 降到 `0.011220`，不适合作为默认配置。温和版 valid/test 保持 `hit_rate@5=0.019635`、`ranked_hit_users=14`；LOPO 保持 `hit_rate@5=0.755427`，但 `candidate_hit_rank_avg` 从 `40.308937` 改善到 `35.738829`。这说明温和 source-aware fusion 是安全的小幅排序改善，强保护版更适合作为诊断证据而不是默认策略。

**面试可讲点：**
这次优化体现了“召回增益之后不能只看 hit-rate，还要看融合排序和评估口径 tradeoff”：强保护 ItemCF 能证明排序确实可把 LOPO target 推前，但会牺牲 valid/test 的 semantic 命中；温和版则保持主指标不受损并改善候选池内排名分布。后续如果继续提升效果，应从手写 source-aware 规则升级到可训练 ranker，学习 ItemCF、多源一致性、semantic-only、popular-only 等特征的权重，而不是继续人工调参。

### 2026-05-09 - 双塔向量召回旁路与 strict gate 收口

**任务：**
把下一阶段复杂召回重点收敛到 DSSM-style 与 YouTubeDNN-style 双塔向量召回，补齐训练 artifact、向量索引、默认关闭配置、strict promotion gate、测试和中文路线说明。

**遇到的问题：**
此前项目已验证 semantic_title 能提升候选覆盖，但复杂召回仍停留在 token overlap / POC 语义旁路；如果直接同时实现图召回、多兴趣、TDM、DeepFM / NCF，会让工程范围过大，也难以用 valid/test 与 LOPO 证明哪条路线真正有效。

**定位方式：**
对照 `.omc/specs/deep-interview-two-tower-recall-next.md` 的验收标准，检查 `rs_core/recsys/two_tower.py`、`rs_core/workflow/two_tower_training.py`、`rs_core/recsys/vector_index.py`、`rs_core/recsys/candidate_merge.py`、`rs_core/workflow/hybrid_demo.py`、`tests/test_two_tower_training.py` 和 `tests/test_hybrid_demo.py`；再读取 `outputs/training/two_tower/two_tower_training/*/artifact_manifest.json` 与四组 two-tower smoke metrics，确认当前证据是训练 `limit_users=10`、评估 `limit_users=30` 的 paired smoke，而不是完整 10k 双塔评估。

**解决方式：**
新增并更新 `tests/test_two_tower_training.py`，验证双塔训练输出完整 artifact contract、`default_enabled=false`、DSSM / YouTubeDNN 的 `model_type` 与 `source_name` 隔离、manifest 可作为 `VectorIndex` 加载，并覆盖 PyTorch backend 规则：torch 可导入时使用 `pytorch`，`backend: python_fallback` 不能绕过 PyTorch，只有 no-torch 场景才进入 `python_fallback_vector_updates`。同时更新 `dic/architecture/IMPLEMENTATION_PLAN.md`、`dic/README.md`、`dic/architecture/ARCHITECTURE.md`、`dic/PROJECT_STRUCTURE.md`，明确双塔只作为默认关闭旁路，晋升必须通过 strict gate。

**验证结果：**
训练 smoke artifact 位于 `outputs/training/two_tower/two_tower_training/dssm/artifact_manifest.json` 和 `outputs/training/two_tower/two_tower_training/youtube_dnn/artifact_manifest.json`，manifest 中 `training_backend.name=pytorch`，训练规模为 `limit_users=10`、`epochs=1`、`negative_samples=1`、`embedding_dim=8`、`hidden_dim=8`。paired smoke 评估规模为 `limit_users=30`：DSSM valid/test `candidate_hit_rate_at_pool=0.111111`、`recall_at_pool=0.111111`、`hit_rate_at_k=0.0`、`candidate_hit_users=1`、`candidate_generation_p95_seconds=0.270462`、`promotable=false`；YouTubeDNN valid/test 同为 `candidate_hit_rate_at_pool=0.111111`、`recall_at_pool=0.111111`、`hit_rate_at_k=0.0`、`candidate_hit_users=1`，`candidate_generation_p95_seconds=0.246153`、`promotable=false`。LOPO 仍是 sanity-only no promotion。当前没有完整 10k 双塔结论，不能据此宣称双塔可晋升。

**面试可讲点：**
这次工作可以讲成“把复杂召回工程化为可验证旁路，而不是堆模型名”：DSSM 与 YouTubeDNN 都通过同一 artifact contract 进入向量索引和 candidate merge，但默认关闭；是否进入主路由 valid/test、LOPO sanity、source contribution / overlap 和 latency gate 决定。Node2Vec / DeepWalk、MIND / SDM、TDM、DeepFM / NCF 被明确延期，体现了工程范围控制和评估优先的取舍。

### 2026-05-08 - Phase 1.9 轻量 learning-to-rank baseline

**任务：**
把 source-aware fusion 的手写 source 规则升级为一个默认关闭、可训练、无新增依赖的轻量 LTR baseline，用于学习 ItemCF、多源一致性、semantic-only、popular-only 和热度/时间等排序特征权重。

**遇到的问题：**
项目当前没有 `numpy`、`sklearn`、`lightgbm` 等训练依赖，不能为了一个 baseline 引入重依赖；同时 LOPO 训练与 LOPO 评估容易形成同 split 过拟合，如果只报告 LOPO 提升会夸大泛化效果。实现时还发现 LTR 配置会在训练前启用 `ltr_model` 并尝试加载尚未生成的模型文件。

**定位方式：**
检查 `rs_core/recsys/ranking.py`、`rs_core/workflow/hybrid_demo.py` 和新训练流程，确认现有 candidate / ranking 字段已足够抽取 source indicator、source score、source interaction 和 metadata 特征；通过 200 用户 smoke 训练先验证 `scripts/training/train_ltr_ranker.py` 能生成模型与指标，再分别运行 10k LOPO 和 valid/test 对照，读取 `outputs/training/ltr/ltr_training_10000_lopo_semantic_title/ltr_train_metrics.json`、`outputs/hybrid_demo/hybrid_demo_small_electronics_10000_lopo_semantic_title_ltr/metrics.json` 和 `outputs/hybrid_demo/hybrid_demo_small_electronics_10000_semantic_title_ltr/metrics.json`。

**解决方式：**
新增 `rs_core/recsys/ltr.py`，实现 pure-Python pairwise perceptron、特征抽取、模型保存/加载和线性打分；新增 `rs_core/workflow/ltr_training.py` 与 `scripts/training/train_ltr_ranker.py` 复用 hybrid demo 的候选生成和 holdout label；在 `rank_candidates()` 中新增 `ltr_score` 和 `ltr_model` rerank event，并保持 `ltr_model.enabled=false` 时原排序不变；训练候选生成阶段临时关闭 `ltr_model`，避免训练前加载不存在的模型。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_ltr.py tests/test_hybrid_demo.py tests/test_inference_policy.py`，结果 `56 passed`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过。200 用户 smoke 训练生成 5550 行样本、111 个 positive users。10k LOPO 训练生成 64900 行样本、1298 个 positive users，模型学到 `itemcf_source=2.34`、`itemcf_multi_source=2.21`、`semantic_only=-0.85`、`popular_only=-0.54`。LOPO 评估中 `hit_rate@5` 从 `0.755427` 提升到 `0.758321`，`ranked_hit_users` 从 `1044` 到 `1048`，`candidate_hit_rank_avg` 从 `40.308937` 改善到 `32.591680`；但 valid/test `hit_rate@5` 从 `0.019635` 降到 `0.014025`，说明该模型目前更适合作为训练排序 baseline 和诊断工具，而不是默认泛化配置。

**面试可讲点：**
这次工作可以讲成“从手写规则到可训练排序器”的工程升级：先用 source-aware fusion 暴露 ItemCF 保护与 semantic 泛化之间的 tradeoff，再实现无依赖 LTR baseline 学习这些特征权重。关键不是夸大指标，而是主动用 valid/test 证明同 split LOPO 收益不能直接等同线上泛化，并给出下一步应做独立训练/验证切分、score calibration 或更强 LTR 模型的方向。

### 2026-05-08 - Phase 1.10 推荐底座工业化诊断层

**任务：**
补齐推荐 backbone 的工业化离线诊断层，用 valid/test 和 LOPO 对照判断当前瓶颈属于召回、source merge、排序/LTR 还是 latency，而不是直接根据数据量决定是否上粗排、精排或双塔。

**遇到的问题：**
已有 `hit_rate@5`、候选池命中和 LTR 对照，但指标还不足以回答“应该先优化召回还是排序”“LTR 能否默认启用”“当前是否需要粗排/双塔”。如果只看 LOPO，容易把同 split 排序收益包装成泛化提升；如果只看 valid/test hit-rate，又看不出 target 是否进入候选池、是否被排序压在 Top-K 外。

**定位方式：**
扩展 `rs_core/recsys/evaluation.py` 与 `EvaluationSummary`，加入 `recall_at_k`、`recall_at_pool`、`ndcg_at_k`、`mrr_at_k`、`map_at_k`、`candidate_hit_rank_p90`、source contribution、source overlap；在 `rs_core/workflow/hybrid_demo.py` 聚合 candidate generation / ranking / total recommendation latency，并输出 `diagnostic_gate`。随后运行 6 组 10k 对照：valid/test 与 LOPO 的 semantic_title、source-aware、LTR。

**解决方式：**
把 gate 设计为显式诊断报告：candidate pool 命中低时判为 recall bottleneck；pool 命中不低但 Top-K / NDCG / MRR 低且命中排名靠后时判为 ranking bottleneck；source contribution 与 Top-K contribution 错配或 overlap 异常时作为 source merge 诊断；候选池扩大且排序耗时上升时才考虑 latency / architecture escalation。所有 gate 同时保留绝对用户数和比例，避免小样本比例误导。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_ltr.py`，结果 `40 passed in 0.27s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过。六组实验均成功生成 metrics/report。valid/test 三组的 `candidate_hit_rate_at_pool=0.084151`、`recall_at_pool=0.034086`，gate 都指向 `phase_1_11_recall_source_merge`；LTR 在 valid/test 中 `hit@5=0.014025`，低于 semantic_title/source-aware 的 `0.019635`，不能默认启用。LOPO 中 source-aware 改善 `ndcg@5=0.314323`、`mrr@5=0.179317`，LTR 将 `hit@5` 提升到 `0.758321`，但只能作为排序诊断证据。排序 `ranking_p95_seconds` 最高约 `0.001366`，候选池约 50，当前不需要独立粗排。

**面试可讲点：**
这次工作体现的是“先诊断瓶颈，再决定架构升级”：没有因为效果低就直接上双塔、粗排或精排，而是用 Recall@pool、NDCG/MRR、source contribution、命中排名分布和 latency gate 拆清责任边界。结论是推荐 backbone 已足够支撑 Agent 工程继续推进，但还不是强推荐算法底座；下一步应优先做 recall/source merge 泛化优化，LTR 保留为诊断 baseline，双塔和复杂精排放到传统召回触顶后的 POC。

### 2026-05-12 - Phase 1.23 pool200 same-run ranking isolation

**任务：**
在 frozen pool200 上做 same-run ranking isolation，验证 `ranking_v2`、`item_feature_rerank`、`source_aware_fusion` 是否能在不漂移候选池的前提下带来真实 Top-K 收益。

**遇到的问题：**
pool200 已经冻结，如果没有 same-run isolation，任何 ranking 结果都可能混入候选池波动或 freeze 漂移，最后无法区分是排序特征有效还是采样噪声。

**定位方式：**
使用项目默认 `.venv` 跑完整对照命令，并带上 `--limit-users 500`；检查 `outputs/ranking/phase_1_23_pool200_ranking_isolation/comparison.json` 和 `outputs/ranking/phase_1_23_pool200_ranking_isolation/comparison.md`，核对 valid、freeze、candidate_hit_users、candidate_count_avg、hit_rate_at_k、ndcg_at_k、mrr_at_k 以及各变体 delta。

**解决方式：**
把评估边界锁死在 same-run frozen pool comparison，只比较 baseline、`ranking_v2`、`item_feature_rerank`、`source_aware_fusion`，不扩展召回或调参范围；若出现 freeze drift 就直接判 invalid，否则只归因到排序层。

**验证结果：**
all variants valid 且 no freeze drift。baseline `users_with_holdout=138`、`candidate_hit_users=17`、`candidate_hit_rate_at_pool=0.123188`、`candidate_count_avg=152.272`、`fallback_rate=0.0`；same-run baseline `hit_rate_at_k=0.014493`、`ndcg_at_k=0.002779`、`mrr_at_k=0.006039`。`ranking_v2`、`item_feature_rerank`、`source_aware_fusion` 的指标与 baseline 完全一致，delta 全为 0，最终判定 `VALID but NO PROMOTION`。

**面试可讲点：**
这轮最重要的是把归因边界锁死：same-run isolation 证明候选池没漂、freeze 没漂，结果仍然不变，说明当前手写排序增量还不足以把稀疏正例推入 Top-K。下一步更合理的是先按 user-level hit rank 和 feature 分布做剖析，再决定是否进入 LTR 或更强排序特征。

### 2026-05-08 - Phase 4.1 Agent 综合评估闭环与反馈重排工具

**任务：**
把 Agent 线从“只导出 trajectory 样本”调整为“能对比、能诊断、能沉淀训练信号”的综合评估闭环，并实现 enhanced Agent 的第一项可解释工具：商品级 feedback rerank。

**遇到的问题：**
Agent 不应该被简单归入传统推荐链路的精排模块，因为它还负责多轮对话、反馈理解、短期记忆、解释与训练信号沉淀；同时如果 public session export 直接暴露 ranking、diagnostics、reward、scorecard 等内部字段，会污染前端和服务 contract。另一个实现问题是 `I don't like this item item_id=...` 这类文本既包含 `like` 又包含否定，需要避免被误记成正反馈或重复记录事件。

**定位方式：**
对照 `rs_core/rsagent/schema.py`、`rs_core/rsagent/policy.py`、`rs_core/workflow/hybrid_demo.py`、`rs_core/serving/service.py`、`rs_core/simulation/runner.py` 和 rollout contract，确认最合适的边界是：推荐 backbone 继续负责候选生成与排序，Agent 层只把商品级反馈转成短期记忆和可解释排序调整；内部评估 artifact 单独导出，不进入 `RecommendationService.export_session()`。

**解决方式：**
在 `FeedbackConstraints` 中记录 `liked_item_ids`、`disliked_item_ids` 和 `item_feedback_events`；新增 `rs_core/rsagent/feedback_rerank.py`，把 like/dislike/show_different 转成 explicit filter、ItemCF 相似商品 boost/demote 和 `feedback_rerank_events`；在 hybrid workflow 中接入该工具，但最终排序仍走原 ranking pipeline。新增 `rs_core/evaluation/agent_scorecard.py` 和 `agent_artifact.py`，输出推荐效果、交互质量、反馈响应、记忆一致性、训练数据质量五维 scorecard，以及 SFT/reward/preference/trajectory training signals；新增 `scripts/evaluation/run_agent_evaluation.py` 对比 baseline 与 `enhanced_feedback_rerank`。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_agent_rollout_schema.py tests/test_agent_feedback.py tests/test_feedback_rerank.py tests/test_agent_scorecard.py tests/test_agent_eval_artifact.py tests/test_simulation_runner.py tests/test_serving_smoke.py`，结果 `42 passed in 0.98s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过。测试覆盖商品级反馈解析、feedback rerank filter/boost/demote、五维 scorecard、internal artifact/training signals、baseline/enhanced runner，以及 public export 不泄露 `ranking/diagnostics/reward/tool_events/scorecard` 等内部字段。

**面试可讲点：**
这次工作可以讲成“把 Agent 从推荐输出包装器升级为可评估的交互决策层”：底座仍然负责召回和排序，Agent 负责理解用户反馈、维护短期会话记忆、调用可解释工具影响候选排序，并把每次交互沉淀为 scorecard 与训练信号。关键边界是没有宣称已经完成 SFT/GRPO，而是先建立 baseline/enhanced 对比、内部证据 artifact 和 public-safe export 隔离，为后续 Qwen/QLoRA/GRPO 训练提供可审计数据基础。

### 2026-05-13 - Phase 2 fine-rank batch 收口

**任务：**
补齐 Phase 2 fine-rank batch runner 和对应测试，并把线性 / LTR / 树模型的状态边界写回文档。

**遇到的问题：**
原先文档仍容易把 linear / pointwise / pairwise 写成 promotion-capable；tree / LambdaMART 在缺真实依赖或 adapter 时也不能被当作可晋升结果。

**定位方式：**
检查 `scripts/experiments/ranking/run_phase_2_fine_rank_algorithm_batch.py`、`tests/test_phase_2_fine_rank_algorithm_batch.py` 和现有排序路线文档，确认 fine_rank 承担 full-pool scoring，rerank 只应保留 Top-K 局部诊断 / 约束语义。

**解决方式：**
在路线图里把 Phase 2 改成 fine_rank full-pool scoring 口径，learned rows 统一降为 diagnostic-only，tree/LambdaMART 标记 blocked/preparation；同时补写 batch runner 和测试文档，避免 promotion 口径漂移。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile scripts/experiments/ranking/run_phase_2_fine_rank_algorithm_batch.py tests/test_phase_2_fine_rank_algorithm_batch.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_phase_2_fine_rank_algorithm_batch.py -q` 结果 `3 passed`。

**面试可讲点：**
这次工作可以讲成“把排序实验入口和晋升边界一起收口”：不仅补了 fine_rank batch runner，还明确 learned / tree / rerank 各自只能走什么证据，防止把诊断、准备和 promotion 混写成同一种结论。

### 2026-05-09 - Phase 1.11 recall/source merge 验证收口

**任务：**
验证 Phase 1.11 在 10k `semantic_title` 数据上的 recall/source merge 改动，并把结果更新到中文优化叙事和工程日志。

**遇到的问题：**
Phase 1.11 的目标是提升 valid/test 候选池覆盖，但完整重跑后 valid/test 反而退化：`candidate_hit_rate_at_pool` 从 baseline `0.084151` 降到 `0.061711`，`candidate_hit_users` 从 60 降到 44。与此同时 LOPO 指标提升，说明这组召回/source merge 参数更适合可控内部 holdout，不代表真实 valid/test 泛化改善。

**定位方式：**
先运行 `./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py` 和 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 做代码级验证；再重跑 baseline 与 Phase 1.11 四组 demo，并读取 `outputs/hybrid_demo/hybrid_demo_small_electronics_10000_semantic_title*/metrics.json`。baseline valid/test 复现 `candidate_hit_rate_at_pool=0.084151`、`recall_at_pool=0.034086`、`candidate_hit_users=60`、`hit_rate_at_k=0.019635`；Phase 1.11 valid/test 为 `candidate_hit_rate_at_pool=0.061711`、`recall_at_pool=0.024854`、`candidate_hit_users=44`、`hit_rate_at_k=0.018233`；Phase 1.11 LOPO 为 `candidate_hit_rate_at_pool=0.941389`、`hit_rate_at_k=0.793054`、`fallback_rate=0.0`。

**解决方式：**
保留默认关闭、配置隔离的 Phase 1.11 实现和测试，但不把它作为默认策略推进；优化叙事中明确记录 valid/test gate 未通过，并把下一步收敛为 ablation：拆分 semantic IDF、popular cap、balanced source budget、ItemCF seed expansion/decay，定位是哪一路导致真实切分候选命中下降。

**验证结果：**
`tests/test_hybrid_demo.py` 结果为 `41 passed in 0.31s`，`compileall` 通过。Phase 1.11 valid/test 未达到 full target（`candidate_hit_rate_at_pool>=0.100000`、`recall_at_pool>=0.040000`、`candidate_hit_users>=66`）或 partial target（`candidate_hit_rate_at_pool>=0.092`、`recall_at_pool>=0.037`）；LOPO sanity 通过并提升，但 candidate generation p95 升到约 5 秒，说明当前 seed-aware semantic 全量扫描在 10k demo 上已有明显延迟代价。

**面试可讲点：**
这次工作可以讲成“用 gate 否决了一个看起来合理的召回增强方案”：代码测试通过、LOPO 也变好，但真实 valid/test 变差，所以不能因为局部指标好看就推进复杂策略。面试重点是实验纪律和诊断能力：把代码正确性、内部 sanity、真实泛化 gate、延迟成本分开判断，并把失败结果转化为下一轮 ablation 计划。

### 2026-05-09 - Phase 1.12 two_tower recall POC

**任务：**
在 Phase 1.11 组合召回方案未通过 valid/test gate 后，新增一路默认关闭、配置隔离的 `two_tower` U2I 召回 POC，并用 valid/test 与 LOPO 同时验证它是否值得继续推进。

**遇到的问题：**
双塔是典型 U2I 召回路线，但当前项目还不适合直接引入完整训练式双塔、ANN 服务和重依赖；同时 Phase 1.11 已证明“LOPO 变好”不能等价于真实 valid/test 泛化改善，所以新召回源必须用默认关闭 POC 和 gate 指标约束，不能直接替换推荐 backbone。

**定位方式：**
对比 `semantic_title` baseline 与 two_tower POC 的 10k 实验输出：valid/test baseline 为 `candidate_hit_rate_at_pool=0.084151`、`recall_at_pool=0.034086`、`candidate_hit_users=60`、`hit_rate_at_k=0.019635`；two_tower POC 为 `candidate_hit_rate_at_pool=0.086957`、`recall_at_pool=0.035813`、`candidate_hit_users=62`、`hit_rate_at_k=0.022440`。LOPO baseline 为 `candidate_hit_rate_at_pool=0.939219`、`hit_rate_at_k=0.755427`；two_tower POC 为 `candidate_hit_rate_at_pool=0.939942`、`hit_rate_at_k=0.757598`。

**解决方式：**
在 `rs_core/recsys/candidate_merge.py` 增加轻量 deterministic token-IDF / cosine-style `two_tower` 候选源，用商品文本构造 item tower、用最近 positive seed 聚合 user tower，并过滤 seen item；在 `rs_core/workflow/hybrid_demo.py` 增加默认关闭加载和配置摘要；新增 valid/test 与 LOPO 隔离配置，保持 LTR disabled，不污染既有 baseline。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py` 结果为 `46 passed`，`./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过。two_tower POC 在 valid/test 上小幅提升候选覆盖和 hit@5，并在 LOPO 上保持 sanity 不退化；但 `diagnostic_gate` 仍指向 `phase_1_11_recall_source_merge`，且 candidate generation p95 升到约 `1.31s`，因此只能保留为默认关闭实验源，不能宣称已经解除召回瓶颈。

**面试可讲点：**
这次工作可以讲成“在不过度工程化的前提下验证一个经典召回架构方向”：先用轻量 POC 验证双塔式 U2I 召回是否有增量，再用 valid/test、LOPO、source contribution 和 latency gate 同时约束结论。亮点不是盲目上复杂模型，而是把架构升级做成可隔离、可回滚、可量化的实验路径，并诚实记录小幅收益与未通过 gate 的边界。

### 2026-05-09 - PyTorch 双塔 10k CUDA batch 评估

**任务：**
把 DSSM-style 与 YouTubeDNN-style 双塔召回从 smoke 证据推进到同等 10k 数据规模评估，并判断是否可以从默认关闭旁路晋升。

**遇到的问题：**
初始训练环境装成了 `torch 2.11.0+cpu`，无法使用用户机器上的 GPU；切换 CUDA wheel 后又发现训练实现虽然使用 PyTorch，但仍是逐样本循环，GPU 利用率和显存占用都很低。完整 10k 结果出来后，两个双塔在 valid/test 的候选池覆盖都低于 `semantic_title` baseline。

**定位方式：**
用 `nvidia-smi` 和 `.venv` 中的 `torch.cuda.is_available()` 确认 GPU 与 CUDA wheel 状态；检查 `rs_core/recsys/two_tower.py` 发现模型和张量未显式放到 CUDA，且训练 loop 按样本逐条 forward/backward。随后用 2000 用户样本对比 batch size 128/512/1024，并读取 `outputs/training/two_tower/two_tower_training/*/train_metrics.json` 和 10k `metrics.json`。

**解决方式：**
将训练改为自动选择 CUDA device，并把 DSSM / YouTubeDNN 的 forward 改成 batch tensor 计算；训练指标记录 `batch_size`、`training_seconds`、`peak_cuda_memory_mb` 和 `batch_training=true`。batch tuning 后选择 DSSM `batch_size=512`、YouTubeDNN `batch_size=128`，并同步到 valid/test 与 LOPO 配置。一次性 tuning / smoke 目录已清理，只保留正式 10k artifact 与报告。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_two_tower_training.py tests/test_hybrid_demo.py` -> `57 passed`，`./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过。正式训练记录显示 DSSM `device=cuda`、`training_seconds=18.890`、`peak_cuda_memory_mb=26.164`，YouTubeDNN `device=cuda`、`training_seconds=19.649`、`peak_cuda_memory_mb=31.814`。10k valid/test 中，baseline `candidate_hit_rate_at_pool=0.084151`、`recall_at_pool=0.034086`、`candidate_hit_users=60`；DSSM 为 `0.071529 / 0.029375 / 51`，YouTubeDNN 为 `0.077139 / 0.031527 / 55`，均 `promotable=false`。YouTubeDNN LOPO 提升到 `candidate_hit_rate_at_pool=0.954414`、`hit@5=0.788712`，但 LOPO 只作为 sanity，不作为晋升依据。

**面试可讲点：**
这次工作体现的是实验工程纪律：先修正环境和训练效率，避免把 CPU/逐样本实现误判为模型效果；再用同等 10k 数据规模、valid/test 与 LOPO 双口径判断是否晋升。结论没有包装成“双塔有效”，而是明确指出训练式双塔在 LOPO 有能力信号，但真实 valid/test 召回覆盖下降，下一步应做 source overlap 和 candidate budget ablation，而不是继续盲目加大模型。

### 2026-05-09 - 公共安全推荐解释工具

**任务：**
为 recommendation_explain_tool 补一条工程叙事，说明解释层如何与推荐、展示和反馈边界分离。

**遇到的问题：**
旧逻辑如果直接把 `ranking`、`source`、`diagnostics`、`reward` 或训练侧字段拼成公开解释，会把内部排序依据、召回来源和评估痕迹暴露到 assistant/display 文本里；同时 `why` 请求若不携带结构化 `item_id`，很难稳定对齐最近一次推荐结果。最终补齐精确 `source` 禁词时，还发现展示 badge 中的 `multi_source` 会进入公开 payload，因此需要同步改成不暴露内部来源概念的 `blended_signal`。

**定位方式：**
对照 `rs_core/rsagent/explanation.py`、`rs_core/rsagent/dialogue.py` 和相关测试，确认解释入口已经从推荐链路里拆出来，应该只基于最新一次 display-safe 推荐商品生成公开文本，而不是回读历史 ranking 或内部诊断对象。

**解决方式：**
从最新的 display-safe 推荐商品生成确定性的中文解释，围绕当前展示 item 的 `parent_asin`、标题、类目和已知反馈约束组织文案；`why` 请求如果带 `item_id`，就结构化传入并只解释最近一次推荐列表中的对应商品，找不到时返回公共兜底文案，不去猜测内部状态。公开展示层同步把 `multi_source` badge 改为 `blended_signal`，避免前端 contract 暴露内部来源语义。

**验证结果：**
已完成的验证范围覆盖解释行为测试、`why` 带/不带 `item_id` 的对话测试、过期 item 的公开兜底、display-safe 边界检查，以及和 `/feedback` / 对话联动的回归测试。实际验证证据为 `python -m pytest tests/test_display_contract.py tests/test_agent_dialogue.py tests/test_agent_feedback.py tests/test_serving_smoke.py tests/test_simulation_runner.py tests/test_simulation_roles.py` -> `58 passed`；`python -m compileall rs_core tests scripts` -> completed successfully。

**面试可讲点：**
这次工作可以讲成“把推荐解释从内部诊断文本收敛成面向用户的 public-safe 解释层”。重点不是多暴露来源，而是让解释始终绑定最新公开商品卡和结构化反馈约束，在能说清推荐理由的同时，不泄露 `ranking`、`reward`、`training` 之类内部信息。

### 2026-05-09 - Phase 4.3 constraint_filter_tool 工程叙事

**任务：**
为 Phase 4.3 的 `constraint_filter_tool` 补一条可复述的工程叙事，说明商品级约束过滤如何接入 Agent 反馈链路并保持公开接口安全。

**遇到的问题：**
约束过滤一开始容易被误解成“再加一层排序规则”，但实际需要的是在反馈重排前先把明显冲突的候选过滤掉，否则 like/dislike/show_different 这些信号会和候选集约束互相打架，导致解释、评估和训练样本都不稳定。

**定位方式：**
对照 `rs_core/rsagent/feedback_rerank.py`、`rs_core/rsagent/policy.py` 和相关测试，确认 `constraint_filter.py` 当前主要由测试直接导入，生产路径已经在 `policy.py` 中串起；同时核对公开服务层和 simulation 侧输出，确保过滤逻辑只影响候选集，不外泄内部排序/诊断字段。

**解决方式：**
将约束过滤保持为独立、可测试的工具实现，并在 `policy.py` 的生产路径中统一调用，让它先于反馈重排生效；这样既能显式处理 hard constraints，又能保留后续 `feedback_rerank`、scorecard 和 training artifact 的一致性。当前还有一个非阻塞观察：`constraint_filter.py` 主要由测试直接导入，后续可以考虑把测试入口和生产接口合并成更清晰的单一路径。

**验证结果：**
`python -m pytest tests/test_constraint_filter_tool.py tests/test_agent_feedback.py tests/test_feedback_rerank.py tests/test_agent_reward.py tests/test_agent_eval_artifact.py tests/test_agent_scorecard.py tests/test_serving_smoke.py tests/test_display_contract.py tests/test_agent_rollout_schema.py tests/test_simulation_runner.py tests/test_simulation_roles.py` -> `73 passed`；`python -m compileall rs_core scripts tests` -> completed successfully。

**面试可讲点：**
这段工作可以讲成“把约束过滤从排序规则里拆出来，变成反馈重排前的独立安全闸门”：先保证候选集合法，再谈个性化重排和解释输出。这样做的价值是边界更清楚、测试更稳定、公开接口更安全，也更方便后续把过滤信号沉淀进评估和训练数据。

### 2026-05-09 - 10k 默认晋升硬门禁复核

**任务：**
基于已验证的 8 组 10k 实验结果，整理 valid/test 默认晋升硬门禁证据表，并更新中文优化叙事，避免把 LOPO sanity 或配置变体误写成默认提升。

**遇到的问题：**
`semantic_title`、source-aware 和 LTR 变体在指标上相对 baseline 有明显收益，但默认晋升不能只看 `candidate_hit_rate_at_pool`、`recall_at_pool` 或 `hit@5`；本轮硬门禁还要求 `metrics.latency.candidate_generation_p95_seconds <= baseline * 1.2`。同时 `semantic_title` 只是实验配置变体，不是独立 source key；`user_profile` 也不是 10k 独立召回源，不能混入召回来源叙事。

**定位方式：**
使用 worker-1 的 source 边界审计结论和 worker-2 的 8 组 verified metrics。实验统一入口为 `./.venv/Scripts/python.exe scripts/evaluation/run_hybrid_demo.py --config <config>`；默认晋升只看 valid/test，LOPO 只作为 sanity / 诊断。valid/test baseline 的 `candidate_generation_p95_seconds≈0.000637s`，硬阈值约 `0.000764s`。

**解决方式：**
在 `dic/OPTIMIZATION_NARRATIVE.md` 增加“10k 默认晋升硬门禁复核”小节，分别列出 valid/test 与 LOPO 表格，并显式写清：合法 source key 只有 `popular`、`category`、`itemcf_weak`、`itemcf_strong`、`semantic`；`two_tower` POC 不纳入本次默认 gate；LOPO 不能替代 valid/test 晋升口径。

**验证结果：**
valid/test 中 baseline 为 `candidate_hit_rate_at_pool=0.032258`、`recall_at_pool=0.010322`、`hit@5=0.007013`、`candidate_hit_users=23`、`p95≈0.000637s`；`semantic_title` / source-aware / LTR 分别达到 `candidate_hit_rate_at_pool=0.084151`、`recall_at_pool=0.034086`、`candidate_hit_users=60`，但 p95 分别约 `0.402541s`、`0.400739s`、`0.388379s`，全部超过硬延迟阈值。LOPO 三个增强变体也全部超过以 LOPO baseline `p95≈0.000775s` 计算的硬延迟阈值。因此本轮结论是：不做默认晋升，只保留为召回 / 排序诊断证据。

**面试可讲点：**
这次工作体现的是 gate discipline：即使召回覆盖和 hit@5 变好，也必须同时满足泛化口径和 latency budget 才能默认晋升。LOPO 可以证明模块能力和排序诊断价值，但不能代替 valid/test；配置变体、偏好信号和真实 source key 也必须分清，避免实验叙事夸大。

### 2026-05-09 - Phase 4.4 Agent tool contract cleanup

**任务：**
收敛 Agent 工具链路的公开契约，把约束过滤、反馈重排、评分卡、训练产物和仿真评估的边界理顺，避免把内部排序、诊断和训练字段泄露到服务层或展示层。

**遇到的问题：**
Phase 4.4 之前，`constraint_filter.py` 的测试入口和 `policy.py` 的生产路径存在重复实现，事件字段形态也不完全一致；同时 reward、artifact、scorecard 各自手写 `constraint_filter_events` / `feedback_rerank_events` 聚合逻辑，后续新增工具时容易漂移。公开接口如果误混入 `ranking`、`diagnostics`、`reward`、`scorecard`、`tool_events` 等内部字段，也会破坏 display/session contract。

**定位方式：**
回看 `rs_core/rsagent/constraint_filter.py`、`rs_core/rsagent/policy.py`、`rs_core/rsagent/reward.py`、`rs_core/evaluation/agent_artifact.py`、`rs_core/evaluation/agent_scorecard.py` 和对应测试，确认真正需要修的是“工具实现入口”和“事件聚合边界”，而不是再加新的排序策略。重点检查 direct module test 与 production workflow 是否共享同一套约束过滤行为，以及公开导出是否只保留 display-safe / session-safe 字段。

**解决方式：**
将 `constraint_filter.py` 改成委托生产 `policy.constraint_filter_tool`，保留 direct import contract 但不再维护第二套过滤逻辑；新增 `rs_core/rsagent/tools.py`，集中定义工具事件 key 和 diagnostics/turn/rollout 事件收集 helper，让 reward、artifact、scorecard 复用同一套聚合逻辑；公开服务、展示、session export 和仿真输出仍只消费 display-safe 结果，不暴露内部 tool events。

**验证结果：**
`python -m pytest tests/test_constraint_filter_tool.py tests/test_agent_feedback.py tests/test_feedback_rerank.py tests/test_agent_reward.py tests/test_agent_eval_artifact.py tests/test_agent_scorecard.py tests/test_agent_rollout_schema.py tests/test_serving_smoke.py tests/test_display_contract.py tests/test_simulation_roles.py tests/test_simulation_runner.py -q && python -m compileall -q rs_core scripts` -> `75 passed`，`compileall` exit `0`。验证同时覆盖约束过滤、商品级反馈重排、训练/评估产物、公开服务 contract 和仿真链路，确认内部字段没有外泄。

**面试可讲点：**
这次工作可以讲成“把 Agent 工具链从能跑，收敛到能审计、能复用、能公开”：先把约束过滤放到反馈重排之前，确保候选合法；再把评分卡、reward 和 training artifact 留在内部；最后让服务层、解释层和仿真层都共享同一套 display-safe contract。这样既方便后续继续扩展工具，也避免训练、评估和前端看到不同版本的推荐真相。

### 2026-05-09 - 弱底座上的 Agent 机制验证

**任务：**
在当前推荐底座还不完善的情况下，不验证最终推荐效果绝对值，而是验证 Agent 工具机制、评估产物和 public/internal 边界是否可靠。

**遇到的问题：**
目标测试通过后，小规模 `run_agent_evaluation.py` 端到端 smoke 暴露出更底层的问题：即使用 electronics smoke 数据和已知存在行为序列的用户，服务层仍没有产出展示商品，导致模拟用户只能连续发 chat，`feedback_rerank` / `constraint_filter` 等工具事件无法在端到端场景中触发。因此这轮不能把 baseline/enhanced 分数当作推荐效果结论。

**定位方式：**
先运行覆盖 Agent 工具链的目标测试，得到 `83 passed`，确认 constraint filter、feedback rerank、explanation、reward/artifact/scorecard 和 public 边界的机制契约稳定；再运行 `scripts/evaluation/run_agent_evaluation.py --config configs/demo/hybrid_demo/hybrid_demo_electronics.yaml --roles commuter_practical --max-turns 3 --repeats 1`，输出 artifact/scorecard/training signals，但 scorecard 显示 `recommendation_effectiveness=0.0`、`tool_event_count=0`。随后用固定用户 `AFKZENTNBQ7A7V7UXW5JJI6UGRYQ` 重跑，结果仍然没有 display items；最后直接调用 `RecommendationService.chat()` 探针，确认每轮 `candidates=0`、`ranking=0`、`final_items=0`。

**解决方式：**
本轮不强行调参或伪造推荐结果，而是把验证结论改为“机制级通过，端到端候选供给未通过”。当前可确认的是：Agent 工具和评估产物在单元/集成层稳定，evaluation runner 能产出 `agent_evaluation.json`、`scorecard.json`、`training_signals.json` 和 report；但真实端到端场景还需要先修复候选生成/对话入口，让服务层能稳定返回商品，之后再验证工具事件数量、拒绝商品复现率和 enhanced 相对 baseline 的机制收益。

**验证结果：**
`python -m pytest tests/test_constraint_filter_tool.py tests/test_agent_feedback.py tests/test_feedback_rerank.py tests/test_agent_dialogue.py tests/test_agent_reward.py tests/test_agent_eval_artifact.py tests/test_agent_scorecard.py tests/test_agent_rollout_schema.py tests/test_serving_smoke.py tests/test_display_contract.py tests/test_simulation_roles.py tests/test_simulation_runner.py -q` -> `83 passed in 1.20s`。两次 agent evaluation 均成功落盘，但 `tool_event_count=0`、`feedback_count=0`、`why_count=0`、展示 `items=[]`；直接 service 探针也确认 `candidates/ranking/final_items` 均为 0。

**面试可讲点：**
这次验证体现的是弱底座阶段的评估纪律：不因为评估脚本能跑通就宣称 Agent 效果提升，而是把结论拆成“机制契约已稳定”和“端到端候选供给仍阻塞”。这能说明项目不是盲目堆 Agent 能力，而是用测试、artifact 和 smoke run 找到下一步真正该修的瓶颈。

### 2026-05-09 - Phase 4.6 空候选恢复与 E2E 机制验证

**任务：**
在弱推荐底座上补齐空候选场景的有界恢复，先让 Agent E2E 机制验证可继续推进，而不是直接把结果解释成训练效果。

**遇到的问题：**
端到端 smoke 在弱底座上出现 `candidates=0`、`final_items=0`，模拟用户和 feedback 工具链都被卡住；如果不处理这一层，后续 `feedback_rerank`、`constraint_filter` 和展示闭环都无法触发。

**定位方式：**
沿着 `merge_for_user` 的候选合并路径排查，确认问题出在 `popular` fallback 之后仍做了严格 seen 过滤，导致热门候选也被清空；随后结合 smoke 输出核对 `tool_event_count=6`、两种变体的 `display_item_counts=[2,1,1,1]`，确认是候选供给问题而不是评估器失效。

**解决方式：**
在 `rs_core/recsys/candidate_merge.py` 增加有界 empty-pool recovery：先保留 seen 过滤的主路径，再对 `popular` fallback 做受控补回，保证弱底座至少能产出可交互的最小候选池；同时让增强 rerank 尊重 `constraint_filter_restored`，避免恢复候选后又把同一批商品误删，保持机制验证的最小闭环。

**验证结果：**
运行 `python -m pytest tests/test_simulation_roles.py tests/test_simulation_runner.py` 等 24 个 simulation 相关测试通过，`python -m compileall -q rs_core tests scripts` 通过；seeded evaluation 输出中两个变体都稳定得到 `display_item_counts=[2,1,1,1]`，`tool_event_count=6`，说明候选恢复后 Agent 交互链路重新打通。

**面试可讲点：**
这次工作可以讲成“先修复候选供给，再谈 Agent 机制验证”：我没有把空候选问题包装成训练提升，而是把它定义为评估前置条件，先用有界恢复把 E2E 机制链路打通。它 unblocks 的是 Agent E2E 机制验证，不是 SFT / RL 结果本身。

### 2026-05-10 - 前端工作台重构与 Persona Sprite 素材库

**任务：**
把 RS Agent 前端从单页商品卡 demo 扩展为 Dashboard + Tabs 工作台：Live User Demo 负责真人用户与推荐 Agent 对话、商品卡反馈和 Session Replay，Agent Sandbox 负责多角色 Persona Agent 自动交互、状态面板、timeline 和批量对比。

**遇到的问题：**
前端需要同时展示“推荐 Agent”和“多角色 Persona Agent”的关系，但不能让像素小人和沙盒 UI 反过来污染推荐决策、feedback payload、ranking、reward 或公开 display contract；同时 Codex / Gemini 调用链需要修复后才能按用户要求让 Gemini 执行前端、Codex 处理图像生成封装。

**定位方式：**
对照 `frontend/src/App.tsx`、`frontend/src/api.ts`、`frontend/src/types.ts`、`rs_core/serving/schema.py` 和 `/simulation/batch` contract，确认前端只应消费服务层与展示层字段；用 `Grep frontend/src "dicebear|ranking|reward|diagnostics|score"` 检查外部头像和内部字段泄露风险，并用 `omc ask gemini/codex` 验证外部 CLI 调用链恢复。

**解决方式：**
由 Gemini 执行前端组件拆分，新增 `frontend/src/views/LiveDemo.tsx`、`frontend/src/views/Sandbox.tsx`、商品卡 / 聊天 / replay / feedback 组件，以及 sandbox 下的 persona 状态、timeline、batch comparison 组件；手动把外部 Dicebear URL 收敛为本地 `frontend/src/assets/persona-sprites/manifest.json` 和 `PersonaSprite` 展示组件。Codex 侧新增 `scripts/assets/generate_persona_sprites.py`，读取 manifest prompt 并通过 OpenAI Images API 兼容接口生成 PNG，默认模型为 `gpt-image-2`，支持 `--dry-run`、`--check`、`--force` 和 secret-safe 错误提示。

**验证结果：**
`npm --prefix frontend run build` 通过，Vite 生产构建完成；`./.venv/Scripts/python.exe -m py_compile scripts/assets/generate_persona_sprites.py`、`./.venv/Scripts/python.exe scripts/assets/generate_persona_sprites.py --help` 和 `--dry-run` 均通过，dry-run 识别 5 个 persona 输出目标；`Grep frontend/src "dicebear|ranking|reward|diagnostics|score"` 无匹配。未在本轮使用浏览器做人工视觉验收，后续如需要可启动 Vite dev server 进行交互检查；真实 PNG 生成仍需要配置 `OPENAI_API_KEY` 或兼容图片 API key。

**面试可讲点：**
这次工作可以讲成“把推荐 Agent demo 产品化成可演示工作台，同时守住 display-safe 边界”：Live Demo 面向真实用户交互闭环，Sandbox 面向多角色模拟评估，Persona Sprite 只作为展示层素材库按 `role_id` 取用，不进入推荐策略。实现上还体现了多模型协作分工：Gemini 做前端实现，Codex 做图像生成封装，我负责 contract 边界、集成修正和验证。


### 2026-05-11 - Phase 1.17 rank_weights 冻结池调权结果

**任务：**
在固定召回候选池上验证 Phase 1.17 的 rank_weights 调整是否真的带来 Top-K 排序增益，并把 promotion / no_gain 的结论写成可复述的中文证据记录。

**遇到的问题：**
这轮所有非 baseline 配置都保持了同样的候选池命中、fallback 和候选均值，说明变化只可能发生在排序层；同时并不是每个“指标变好”的配置都应该晋升，必须按 same-run baseline 判断 `hit_rate_at_k`、`ndcg_at_k` 和 `mrr_at_k`，避免把 partial 改善误写成 promotion。

**定位方式：**
以 `outputs/archive/root_files/phase_1_17_rank_weight_comparison.json`、`outputs/archive/root_files/phase_1_17_rank_weight_required_matrix.json`、`outputs/archive/root_files/phase_1_17_rank_weight_required_matrix.csv` 和 `dic/experiments/ranking/PHASE_1_17_RANK_WEIGHT_*.md` 为证据，逐项核对 same-run baseline 与各调权变体的 `candidate_hit_users`、`candidate_hit_rate_at_pool`、`recall_at_pool`、`ranked_hit_users`、`hit_rate_at_k`、`ndcg_at_k`、`mrr_at_k`、`candidate_hit_rank_p50/p90` 和 `promotion_status`。baseline 为 `candidate_hit_users=69`、`candidate_hit_rate_at_pool=0.096774`、`recall_at_pool=0.040439`、`fallback_rate=0.0`、`candidate_count_avg=97.936752`、`hit_rate_at_k=0.019635`、`ndcg_at_k=0.005876`、`mrr_at_k=0.012202`、`rank p50=18`、`rank p90=55`。

**解决方式：**
按决策矩阵把结果分成三类：`popular_0_8`、`popular_0_9`、`semantic_1_3` 归入 PROMOTION；`semantic_1_0`、`semantic_1_1`、`popular_1_1`、`two_tower_1_0`、`two_tower_1_1`、`two_tower_1_3` 归入 NO_GAIN；没有 PARTIAL_DIAGNOSTIC。这样可以把真正有 Top-K 增益的轻量调权和无收益调权分开，避免后续阶段误继承错误配置。

**验证结果：**
本轮比较矩阵显示所有非 baseline 配置都与 baseline 保持相同的候选池统计，没有 INVALID；`popular_0_8` 的 `hit_rate_at_k=0.025245`，较 baseline 提升 `+0.005610`，同时 `ndcg_at_k` 提升 `+0.001587`、`mrr_at_k` 提升 `+0.001566`，是最强候选；`popular_0_9` 和 `semantic_1_3` 也达到 PROMOTION，但提升幅度更小；其余配置未超过 same-run baseline，不应晋升。

**面试可讲点：**
这轮最重要的不是“又调高了一个分数”，而是建立了固定候选池上的调权裁决纪律：先证明候选池稳定，再用 same-run baseline 判断是否晋升。`popular_0_8` 说明在当前阶段，适度下调 popular 权重比继续放大 semantic 或 two_tower 更有效；这类结论比单纯报一个更高的 hit@k 更适合拿到面试里解释“为什么这样做”。

### 2026-05-10 - Phase 1.13 YouTubeDNN 召回主路与排序承接复核

**任务：**
验证 `semantic_title + YouTubeDNN` 在 10k valid/test 下是否可以进入召回主路，并区分候选池覆盖与最终 Top-K 排序承接。

**遇到的问题：**
初始结论把“Top-K 未达标”误写成“two_tower 不应进入主路”。这混淆了召回层和排序层：YouTubeDNN 的职责是把目标商品召回进候选池，Top-K 则应由后续排序完成。

**定位方式：**
对照 pool100 验收口径复跑 Phase 1.13 valid/test，并读取 `metrics.json`。pool50 配置会导致候选池指标先天偏低，因此修正为 pool100 后重新比较 `candidate_hit_rate_at_pool`、`candidate_hit_users` 与 `hit_rate_at_k`。

**解决方式：**
保留 YouTubeDNN 作为召回主路候选源；同时把 `source_aware_fusion`、`item_feature_rerank` 和旧 LTR 的结论限定为“排序承接未通过”，不再用排序失败否定召回效果。Phase 1.13 隔离配置继续保留，后续排序阶段基于固定召回池另行优化。

**验证结果：**
pool100 valid/test 候选池达标：`candidate_hit_rate_at_pool=0.105189`、`recall_at_pool=0.042043`、`candidate_hit_users=75`、`fallback_rate=0.0`。排序承接未达标：pool100 rerank `hit_rate_at_k=0.015428`，very conservative `hit_rate_at_k=0.016830`，均低于 `0.019635`。candidate generation p95 约 `0.41s`，说明召回主路落地还需要检索性能优化。

**面试可讲点：**
这次复核体现的是推荐系统分层诊断：召回层看 candidate pool hit，排序层看 Top-K hit，系统层看 latency。YouTubeDNN 能进入召回主路，但排序模型需要后续独立训练和验证；不能因为 Top-K 暂时没提升，就否定召回源对候选覆盖的贡献。

### 2026-05-11 - Phase 1.14 ranking v2 / LTR v2 固定召回池验证

**任务：**
在固定 `semantic_title + YouTubeDNN pool100` 召回池上验证 ranking v2 / LTR v2，判断它是否能把已经进入候选池的命中商品推入 Top-K。

**遇到的问题：**
valid/test 候选池覆盖达到验收线，但 Top-K 排序没有承接住新增候选；同时 LOPO sanity 指标较好，容易被误写成晋升依据，需要明确 LOPO 只作 sanity。

**定位方式：**
先运行 `./.venv/Scripts/python.exe -m pytest tests/test_ltr.py tests/test_hybrid_demo.py -q` 与 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts`，再用 `scripts/training/train_ltr_ranker.py` 训练 valid/test 与 LOPO 各自独立的 LTR v2 artifact，最后运行两个 Phase 1.14 full demo 并读取 `metrics.json`。

**解决方式：**
保留 `semantic_title + YouTubeDNN pool100` 作为召回池口径；对 valid/test 与 LOPO 分别使用独立训练输出目录，避免覆盖旧产物或混用模型。文档结论按 valid/test 晋升口径书写，不用 LOPO 包装成功。

**验证结果：**
测试通过：`65 passed in 0.24s`，`compileall` 通过。valid/test 指标为 `candidate_hit_rate_at_pool=0.105189`、`recall_at_pool=0.042043`、`candidate_hit_users=75`、`hit_rate_at_k=0.001403`、`fallback_rate=0.0`、`candidate_generation_p95_seconds=0.472091`、`ranking_p95_seconds=0.002814`；其中候选池达标，但 `hit_rate_at_k` 低于 baseline `0.019635` 和目标 `0.023843`，ranking v2 / LTR v2 未通过。LOPO sanity 为 `candidate_hit_rate_at_pool=0.956585`、`hit_rate_at_k=0.811143`、`candidate_hit_users=1322`，只能说明同分布 sanity 通过，不能作为晋升依据。

**面试可讲点：**
这次验证体现的是排序阶段的评估纪律：固定召回池后，只看排序是否把命中候选推入 Top-K。结果证明 ranking v2 / LTR v2 反而把 valid/test 命中候选压低，说明下一步应检查训练样本和 label 口径，而不是用 LOPO 高分掩盖泛化失败。

### 2026-05-11 - Phase 1.15 冻结 YouTubeDNN pool100 与隔离 ablation

**任务：**
冻结 `semantic_title + YouTubeDNN pool100` 召回基线，补齐隔离的 gate / config / test 覆盖，并根据 verify-worker 的 #3 / #5 / #7 结果更新 Phase 1.15 叙事。

**遇到的问题：**
frozen 基线本身已经能跑通，容易把“能跑完”误写成“默认晋升”；semantic IDF 版本在 `rs_core/recsys/candidate_merge.py` 里先出现过 hang，修复后虽然能跑完，但 valid/test 命中和 latency 都没有过门禁。如果把 ablation 结果混进 final，会把诊断实验误当成主路方案。

**定位方式：**
把 `PHASE_1_15_FROZEN_YOUTUBEDNN_POOL100.md`、`PHASE_1_15_VALID_FINAL_CANDIDATE.md`、`PHASE_1_15_LOPO_SANITY.md` 和 `PHASE_1_15_ABLATION_SEMANTIC_IDF_BUDGET.md` 放在同一口径下对比，只看 `candidate_hit_rate_at_pool`、`hit_rate_at_k`、`candidate_generation_p95_seconds` 和 `ranking_p95_seconds`，并固定 `candidate_pool_size=100`、`top_k=5`、`YouTubeDNN pool100` 不变。

**解决方式：**
把 `YouTubeDNN pool100` 固定为 Phase 1.15 的 recall baseline，只允许 isolated gate / config / test 继续做对照；semantic IDF hang 修复后，ablation 仍只保留为诊断证据，不进入 final。

**验证结果：**
frozen baseline valid/test 为 `candidate_hit_rate_at_pool=0.106592`、`hit_rate_at_k=0.019635`、`candidate_generation_p95_seconds=0.461527s`；final valid/test candidate 仍是 `0.106592 / 0.019635`，`candidate_generation_p95_seconds=0.485096s`，没有比 frozen 带来同跑增益。LOPO sanity 为 `candidate_hit_rate_at_pool=0.959479`、`hit_rate_at_k=0.798119`、`candidate_generation_p95_seconds=0.39457s`，只能证明同分布 sanity 通过。semantic IDF ablation 为 `candidate_hit_rate_at_pool=0.100982`、`hit_rate_at_k=0.00561`、`candidate_generation_p95_seconds=0.777899s`、`ranking_p95_seconds=0.000721s`，没有超过 frozen，也没有过 latency gate。

**面试可讲点：**
这轮可以讲成“先冻结能站得住的 baseline，再用隔离 ablation 证明哪些变体不该进主线”。它的价值不是再造一个高分配置，而是把默认晋升的证据边界收紧，避免把 LOPO 或局部优化误写成主路收益。

### 2026-05-11 - Phase 1.16 item_graph recall 生成与接入验证

**任务：**
在 Phase 1.15 冻结基线之后，引入并验证 `item_graph` 召回路径，确认它是否真的能带来新的 valid/test 候选，而不是重复现有 recall 覆盖。

**遇到的问题：**
`item_graph` 虽然能够生成并接入 views，但很容易和已有 recall source 高重叠；如果只看 LOPO，会把同分布上的高分误写成晋升证据。

**定位方式：**
同时对照 frozen baseline、item_graph 接入后结果和 LOPO sanity，只看 `candidate_hit_rate_at_pool`、`recall_at_pool`、`hit_rate_at_k`、`candidate_generation_p95_seconds`、`fallback_rate` 以及 item_graph diagnostics，确保 valid/test 才是默认晋升口径。

**解决方式：**
生成 `item_graph_recall.jsonl` 并接入 views 重建流程，保留 frozen baseline 对照；用 item_graph diagnostics 检查 seed 命中、raw candidate/unseen 规模和 source coverage，但不把强 LOPO sanity 误写成默认晋升。

**验证结果：**
`./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_simulation_runner.py tests/test_ltr.py -q` 通过，61 项测试全部通过。frozen baseline 与 item_graph 接入后的 valid/test 指标完全持平：`candidate_hit_users=76`、`candidate_hit_rate_at_pool=0.106592`、`recall_at_pool=0.042219`、`hit_rate_at_k=0.019635`，但 `candidate_generation_p95_seconds` 从 `0.461527` 降到 `0.411992`。item_graph diagnostics 显示 `users_with_item_graph_seed_hits=1514`、`raw_candidates=55776`、`raw_unseen=22286`、`candidate_hit_source_coverage.item_graph=1`。LOPO sanity 为 `candidate_hit_rate_at_pool=0.970333`、`hit_rate_at_k=0.813314`、`item_graph candidate hits=1341`，只能作为同分布诊断证据。

**面试可讲点：**
这轮可以讲成“新增召回源不等于默认晋升”。我先把 item_graph 的生成、接入和诊断链路做实，再用 valid/test 与 LOPO 分开裁决：工程链路是通的，但主口径没有增益，所以结论必须是 fail/no promotion。

### 2026-05-11 - Phase 1.18 two_tower_seed item-neighbor 召回旁路验证

**任务：**
在冻结的 `semantic_title + YouTubeDNN pool100` 召回主路之外，新增默认关闭的 `two_tower_seed` I2I 召回旁路，验证已有 YouTubeDNN item embedding 的离线 nearest-neighbor sidecar 是否能带来新的 valid/test 候选覆盖。

**遇到的问题：**
初始实现中 builder 输出 `{item_id, neighbors}`，但 runtime loader 仍按旧 `src_item/dst_item/score` schema 读取；同时 sidecar 输出路径如果和 embedding 输入路径或 manifest 路径重合，会误删或覆盖 artifact。实验层面，LOPO sanity 对该旁路有明显贡献，但默认晋升必须看 same-run valid/test，而不能用 LOPO 高分包装成功。

**定位方式：**
检查 `rs_core/workflow/two_tower_training.py`、`scripts/training/build_two_tower_neighbors.py`、`rs_core/recsys/candidate_merge.py` 和 `tests/test_hybrid_demo.py`，确认 sidecar schema 不一致；随后用独立 code-reviewer 复核 Phase 1.18 改动，发现 sidecar path distinctness 风险。最终通过 `outputs/recall/phase_1_18_two_tower_seed_gate/comparison.json` 对照 frozen baseline、Phase 1.18 valid/test 和 LOPO sanity。

**解决方式：**
将 runtime loader 改为解析 `{item_id, neighbors:[{item_id, score, rank}]}`，并在 `fail_on_missing_sidecar=true` 时校验 manifest 的 `phase/source/schema_version`；为 sidecar builder 增加输入、sidecar、manifest 三个路径必须互异的 fail-closed 校验；新增 Phase 1.18 valid/test 与 LOPO 隔离配置，保持排序增强全部 disabled；新增 `scripts/experiments/recall/run_phase_1_18_recall_gate.py` 生成 same-run gate artifact。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_two_tower_training.py tests/test_hybrid_demo.py tests/test_build_recall_views.py` 通过，75 项测试全部通过；`compileall` 针对更新脚本和模块通过。完整 gate 命令 `./.venv/Scripts/python.exe scripts/experiments/recall/run_phase_1_18_recall_gate.py --skip-sidecar-build --output outputs/recall/phase_1_18_two_tower_seed_gate/comparison.json` 写出 comparison JSON 并因 gate 未通过返回 exit 1。same-run frozen baseline 为 `candidate_hit_users=76`、`candidate_hit_rate_at_pool=0.106592`、`recall_at_pool=0.042219`、`fallback_rate=0.0`、`candidate_generation_p95_seconds=0.427404`；Phase 1.18 为 `75 / 0.105189 / 0.041066 / 0.0 / 0.452250`，且 `candidate_hit_source_coverage.two_tower_seed=8`。LOPO sanity 为 `candidate_hit_rate_at_pool=0.957308`、`hit_rate_at_k=0.796671`、`two_tower_seed candidate hits=184`，只能作为 sanity。

**面试可讲点：**
这次工作体现的是召回实验的工程化和否决纪律：我把双塔 item embedding 扩展为可离线构建、可 manifest 校验、可默认关闭接入的 I2I 旁路，但最终没有因为它有真实 source contribution 或 LOPO 高分就晋升。valid/test 候选池覆盖下降说明它和现有主路的组合方式仍不泛化，因此结论必须是 `FAIL / no promotion`，保留为负向实验和后续 budget/overlap 分析依据。

### 2026-05-12 - Phase 1.18 决策复核：popular=0.8 保持不晋升

**任务：**
复核 Phase 1.18 的 second-order rank-weight 组合结论，确认是否存在可晋升到主路的权重配置，并基于失败归因判断下一阶段该往哪条线推进。

**遇到的问题：**
没有任何 second-order rank-weight 组合在 `hit_rate_at_k` 上超过 `popular=0.8`；失败主要集中在候选 miss，而不是排序细节，说明继续细调权重的边际收益很低。

**定位方式：**
复核决策审查结果与失败归因统计，重点看 `hit_rate_at_k` 对照和 candidate miss / rank miss 的占比，确认问题是否来自排序还是召回覆盖。

**解决方式：**
维持 `popular=0.8` 作为当前排序基线，不晋升 second-order rank-weight 组合；将后续探索方向切换到 recall/source coverage，而不是继续堆排序权重。

**验证结果：**
决策结论为 `NO_PROMOTION_KEEP_POPULAR_0_8`。failure attribution 显示 `candidate miss = 644/713 (90.3226%)`，说明瓶颈主要在候选覆盖；当前阶段没有证据支持继续推进 second-order rank-weight 组合晋升。

**面试可讲点：**
这一步能讲成“先用指标复核锁定最稳基线，再用失败归因判断下一步该加权还是补召回”。最终没有把局部排序优化当成主线，而是把资源转向 recall/source coverage，这样更符合收益来源。

### 2026-05-11 - Phase 1.19 DeepWalk graph_walk_seed 结构召回旁路验证

**任务：**
在冻结的 `semantic_title + YouTubeDNN pool100` 召回主路之外，新增默认关闭的 `graph_walk_seed` 结构召回旁路，用 DeepWalk-style 图游走从正反馈序列中学习 item embedding，并通过 same-run gate 判断是否能带来新的 valid/test 候选覆盖。

**遇到的问题：**
新 source 必须和已有 `item_graph` 保持 source identity 隔离；训练产物不能只是临时 sidecar，需要 manifest/hash/device 等可复现证据；smoke gate 返回 exit 1 时需要区分“门禁未通过”和“脚本崩溃”。

**定位方式：**
复核 `rs_core/workflow/graph_walk_training.py`、`rs_core/recsys/candidate_merge.py`、`rs_core/workflow/hybrid_demo.py` 和 `scripts/experiments/recall/run_phase_1_19_graph_walk_seed_gate.py`，确认训练、manifest 校验、runtime opt-in 和 gate 检查边界；读取 `outputs/recall/phase_1_19_graph_walk_seed_gate_smoke_verifier/comparison.json` 对照 baseline、experiment、source-only 和 without_graph_walk 指标。

**解决方式：**
保留 `graph_walk_seed_enabled=false` 默认关闭，由 gate 通过 overrides 启用实验；manifest 校验 `phase/source/schema_version/algorithm/sidecar_hash`，runtime 维持 `graph_walk_seed` 独立 source label、seen filtering、recency decay、score floor 与 per-user cap；gate 同时检查 default-off baseline 一致性、source identity、预算、延迟和 candidate/recall lift。

**验证结果：**
`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_graph_walk_seed.py tests/test_hybrid_demo.py` 通过，69 项测试全部通过。full gate 命令 `./.venv/Scripts/python.exe scripts/experiments/recall/run_phase_1_19_graph_walk_seed_gate.py --output outputs/recall/phase_1_19_graph_walk_seed_gate/comparison.json` 写出 comparison JSON，并因 promotion checks failed 返回 exit 1。same-run full gate 中 baseline 为 `candidate_hit_users=69`、`candidate_hit_rate_at_pool=0.096774`、`recall_at_pool=0.040439`、`candidate_generation_p95_seconds=0.49439`；default-off disabled 与 baseline 完全一致；experiment 为 `candidate_hit_users=69`、`candidate_hit_rate_at_pool=0.096774`、`recall_at_pool=0.039079`、`candidate_generation_p95_seconds=0.623431`，有 `candidate_hit_source_coverage.graph_walk_seed=2`、`recall_source_coverage.graph_walk_seed=22377`、`users_with_graph_walk_seed_hits=1530`、`graph_walk_seed_raw_candidates=1072400`、`graph_walk_seed_raw_unseen_candidates=986695`、`candidate_share=0.076823`、`max_candidates_per_user_observed=15`。gate 结果为 `passed=false`，失败项包括 `candidate_hit_users_lift=false`、`candidate_hit_rate_at_pool_lift=false`、`recall_at_pool_lift=false`、`candidate_generation_p95_budget=false`、`lopo_candidate_generation_p95_budget=false`；同时 `graph_walk_seed_hit_contribution=true`、`default_off_matches_baseline=true`、`source_identity_not_mixed_with_item_graph=true`、`source_cap_not_exceeded=true`。manifest 显示 full training 使用 `device=cuda`，`item_count=9174`、`edge_count=9442`、`walk_count=91740`、`positive_pair_count=15595800`。

**面试可讲点：**
这轮可以讲成“图游走召回旁路的工程化和否决纪律”：我不仅实现了 DeepWalk-style 训练和可校验 artifact，还用 same-run gate 证明它虽然能产生大量结构候选，但没有带来真实候选命中或 recall lift，所以明确记录为 `FAIL / no promotion`，不把工程可用误写成主路晋升。

### 2026-05-11 - 横向收口：仿真前后端契约对齐

**任务：**
在不接管 agent、前端、传统推荐底座主体实现的前提下，做一次跨 `serving`、`display`、`simulation`、前端类型和关键测试的横向收口。

### 2026-05-11 - Phase 1.20 fallback limit500 诊断核验

**任务：**
在 full run 过慢的前提下，先用 `--limit-users 500` 跑通 recall diagnostics fallback 核验，确认产物只作为诊断证据，不当作 full-run 晋升结果。

**遇到的问题：**
full run 时间成本高；same-run 分母容易漂移；必须保证 frozen / Phase 1.17 tracked diff 检查不被诊断脚本污染。

**定位方式：**
运行 `scripts/experiments/recall/phase_1_20_recall_diagnostics.py --limit-users 500`，检查 `outputs/recall/phase_1_20_recall_diagnostics_large_limit500/`、manifest `run_id=756ade477bdf7c45`、`evaluation_mode=valid_test`、分母字段和保护检查输出；核对 CSV/JSON parity、required files、raw oracle stages 与专项测试结果。

**解决方式：**
将本轮固定为 fallback limit500 口径，显式保留 `hit_rate_denominator=users_with_holdout`、`users_with_holdout=138`、`limit_users=500` 的同口径对照，并把 frozen / Phase 1.17 diff clean 作为保护门禁。

**验证结果：**
`./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_20_recall_diagnostics.py tests/test_hybrid_demo.py tests/test_ltr.py` 通过，合计 `79 passed`。`outputs/recall/phase_1_20_recall_diagnostics_large_limit500/` 产出了 limit500 artifact，baseline hash `afa923fb623402a51f17157565e204d1954fdd93814d102cf8c96e5c7a8ddff5`，CSV/JSON parity 与保护性 diff 检查 clean。

**面试可讲点：**
这轮可以讲成“把诊断本身也做成可审计门禁”：不追求一次性全量跑完，而是先用有限 fallback + 分母一致性 + 冻结产物保护，确认诊断链路可靠再谈下一步。

**遇到的问题：**
后端 `SimulationSceneRequest` / `SimulationBatchRequest` 将 `max_turns` 限制为 1-8，但前端沙盒输入仍允许 10；同时 batch scene 会携带 `metrics`，前端 `SimulationSceneResponse` 类型没有显式表达该字段，容易在后续 batch comparison 扩展时产生隐性契约漂移。

**定位方式：**
对照 `rs_core/serving/schema.py`、`rs_core/simulation/runner.py`、`frontend/src/types.ts`、`frontend/src/components/sandbox/*` 和 `tests/test_simulation_runner.py`，确认公开 display contract、session export、simulation scene / batch 主链路基本一致，缺口集中在前端输入边界和 TypeScript 类型表达。

**解决方式：**
在 `frontend/src/types.ts` 补充 `SimulationSceneMetrics` 并让 `SimulationSceneResponse.metrics` 可选，兼容单 scene 与 batch scene；把 `PersonaStatePanel` 和 `BatchSimulationPanel` 的 `max_turns` 输入上限从 10 收敛到 8，与服务端 Pydantic contract 对齐。

**验证结果：**
`npm --prefix frontend run lint` 通过；`.venv/Scripts/python.exe -m pytest tests/test_simulation_runner.py tests/test_serving_smoke.py tests/test_display_contract.py` 通过，29 项关键契约 / serving / display / simulation 测试全部通过。

**面试可讲点：**
这次工作可以讲成“多窗口并行开发后的 contract gate”：不重写任何一个模块，而是用 schema、前端类型和回归测试把 agent 交互、服务层、展示层、仿真评估串成可验证边界，防止局部功能能跑但端到端契约慢慢漂移。

### 2026-05-12 - Phase 1.17b popular=0.8 稳定性复核

**任务：**
在 frozen-pool ranking 上复核 popular=0.8 是否能稳定晋升，并对比 0.75/0.85 邻近权重。

**遇到的问题：**
单次 Phase 1.17 smoke 只能说明局部 promotion candidate，不能直接作为默认基线；还需要确认候选池稳定，且收益来自排序而不是召回。

**定位方式：**
对照 `outputs/archive/root_files/phase_1_17b_rank_weight_comparison.json` 和 `outputs/archive/root_files/phase_1_17b_popular_0_8_case_effects.json`，核对 same-run baseline、popular=0.8 和邻近 0.75/0.85 的候选池统计、Top-K 指标和 case-level 命中变化。

**解决方式：**
把 `popular=0.8` 定位为新的 frozen-pool ranking baseline，同时保留 `popular=0.75/0.85` 作为稳定性参考，不再扩大搜索到召回或全链路泛化。

**验证结果：**
same-run baseline 与 `popular=0.8` 的 candidate-hit / recall / fallback / candidate_count 完全一致，但 `hit_rate_at_k` 从 `0.019635` 提升到 `0.025245`，`ndcg_at_k` 从 `0.005876` 提升到 `0.007463`，`mrr_at_k` 从 `0.012202` 提升到 `0.013768`；`popular=0.75` 和 `0.85` 也均高于 baseline。case-level 结果显示 5 个 shared target 进入 Top-K，退出 Top-K 为 0，rank 改善 49 个、恶化 4 个。

**面试可讲点：**
这次可以讲成“固定候选池后做权重稳定性门禁”：先证明池没变，再证明邻近权重也同向，最后把结论限制在 frozen-pool ranking，不把排序增益误写成召回收益。

### 2026-05-12 - Phase 1.21 recall coverage 扩展与诊断收口

**任务：**
在冻结 baseline 之外实现 Phase 1.21 召回覆盖诊断：新增默认关闭的 semantic title/category、co-visit fallback repair、category long-tail 和 metadata neighbor source，跑通 same-holdout baseline/audit/pool-curve，并记录 ablation 的真实状态。

**遇到的问题：**
并行实现时出现过重复函数定义和 source config 覆盖风险；co-visit 噪声过滤最初会误删高频 seed；完整 ablation matrix 在 `limit_users=500` 下仍超时，不能把单 source 结论包装成晋升证据。

**定位方式：**
对照 `scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py`、`tests/test_phase_1_21_recall_coverage.py` 和 `outputs/recall/phase_1_21_recall_coverage/*/manifest.json`，核验 `evaluation_mode=valid_test`、`users_with_holdout=138`、`limit_users=500`、同一 `holdout_user_ids_hash=927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2`，并检查 ranking/rerank disabled 与 no-leakage contract。

**解决方式：**
统一 Phase 1.21 source config 装配路径，修正 co-visit 为“允许高频 seed、过滤高频 neighbor”，补齐 source/metrics schema gate 和专项测试；对 ablation 超时不做伪成功处理，而是写入 `outputs/recall/phase_1_21_recall_coverage/ablations/manifest.json`，显式标记 `status=inconclusive_timeout`。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_20_recall_diagnostics.py tests/test_phase_1_21_recall_coverage.py` 通过，合计 `19 passed`；Phase 1.21 专项 `18 passed`。pool-curve 在同一 holdout hash 下完成，pool100 `candidate_hit_users=14`、`candidate_hit_rate_at_pool=0.101449`、`recall_at_pool=0.061312`，pool200 `candidate_hit_users=19`、`candidate_hit_rate_at_pool=0.137681`、`recall_at_pool=0.069710`，`candidate_hit_users_delta=+5`、`candidate_hit_rate_at_pool_delta=+0.036232`。按召回侧指标，pool200 晋升为 recall-side experimental baseline；ablation manifest 明确为 timeout inconclusive，不能晋升单 source，排序 / Top-K 不纳入本窗口结论。

**面试可讲点：**
这次可以讲成“召回侧实验的证据纪律”：用固定分母、同一 holdout hash、no-leakage contract 和 ranking disabled gate 保证诊断可信；pool200 带来 +5 个候选命中用户，因此晋升为召回侧 experimental baseline，但由于 ablation 未完成，不把任何单一 source 包装成晋升，也不把排序 / Top-K 结果混入召回窗口结论。



### 2026-05-12 - Phase 1.22 pool200 source attribution 与 keep/prune 复核

**任务：**
复核 Phase 1.22 的 pool200 recall 源，并同步工程叙事。

**遇到的问题：**
本轮是 recall-only；ablation 只到 partial_time_limited，leave-one-source-out 全是 inconclusive_not_rerun；miss_targets / holdout targets 只能用于 diagnostics / evaluation。

**定位方式：**
对照 contract.json、source_attribution_report.json、pool200_ablation_summary.csv、source_keep_prune_decisions.csv，核对 fixed contract、holdout hash、pool100 / pool200 命中差异和 source 归因。

**解决方式：**
keep semantic_title_category_expansion / popular / semantic；reserve 其余召回源；仅 prune metadata_neighbor_recall。对 5 个 pool200-only 新命中采用 non-exclusive attribution，不把单源归因误读成唯一贡献。

**验证结果：**
source_attribution_report.json 中 all-hit attribution 为 semantic_title_category_expansion=9、semantic=9、popular=6、category=2、category_long_tail_recall=2、two_tower=2、co_visit_fallback_repair=1、itemcf_strong=1、itemcf_weak=1；新增 5 个命中里 popular=3、semantic_title_category_expansion=3。pool200_ablation_summary.csv 的非 baseline 行均为 inconclusive_not_rerun。

**面试可讲点：**
先把证据边界定死，再做源治理：合同、holdout hash、分母和 no-leakage 先锁住，再用可验证的归因和裁决表做 keep / reserve / prune。

### 2026-05-12 - Phase 1.22 pool200 æŽ’åº�å¤�æ ¸ï¼šå€™é€‰æ± æ¼‚ç§»å¯¼è‡´ INVALID

**ä»»åŠ¡ï¼š**
åœ¨å·²æ™‹å�‡çš„ pool200 å�¬å›žåŸºçº¿ä¸Šï¼Œå�ªéªŒè¯�æŽ’åº�ä¾§ `ranking_v2`ã€�`source_aware_fusion`ã€�`item_feature_rerank`ï¼Œåˆ¤æ–­æ˜¯å�¦èƒ½æŠŠå€™é€‰æ± å†…å‘½ä¸­æŽ¨è¿› Top-Kã€‚

**é�‡åˆ°çš„é—®é¢˜ï¼š**
Promoted baseline ç›®å½•å�ªæœ‰ metrics / manifest / diagnostic CSVï¼Œæ²¡æœ‰ per-user `recommendations.jsonl`ã€�`candidates.jsonl` æˆ– `ranking_hit_cases.jsonl`ï¼Œå› æ­¤æ— æ³•ç›´æŽ¥å¤�ç”¨å†»ç»“å€™é€‰æ–‡ä»¶å�šçº¯ rerankã€‚å�Žç»­ deterministic rerun å�ˆå‡ºçŽ°å€™é€‰æ± å†»ç»“å­—æ®µæ¼‚ç§»ï¼š`19/0.137681/157.112` å�˜ä¸º `17/0.123188/152.272`ã€‚

**å®šä½�æ–¹å¼�ï¼š**
å…ˆå�š baseline freeze auditï¼Œå†�è®© isolated configs é€šè¿‡éš”ç¦»éªŒè¯�ï¼šä¸‰ä»½ Phase 1.22 é…�ç½®å�ªä¿�ç•™å�•ä¸€ ranking policy å·®å¼‚ï¼Œ`candidate_pool_size=200`ï¼Œå¹¶ç§»é™¤é¢�å¤– `rank_weights`ã€‚éš�å�Žè¯»å�– `outputs/archive/root_files/pool200_ranking_optimization_comparison.json`ã€�å�„å�˜ä½“ `metrics.json` ä¸Ž `ranking_hit_cases.jsonl`ï¼Œå¯¹æ¯” promoted baseline çš„ freeze gates ä¸Ž Top-K æŒ‡æ ‡ã€‚

**è§£å†³æ–¹å¼�ï¼š**
æ²¡æœ‰æŠŠ `mrr_at_k` çš„è½»å¾®ä¸Šå�‡åŒ…è£…æˆ� partialï¼›æŒ‰é¢„å…ˆ gate è§„åˆ™æŠŠå€™é€‰æ± æ¼‚ç§»åˆ¤ä¸º `INVALID`ã€‚æœ€ç»ˆå†³ç­–æ˜¯ä¸�æ™‹å�‡ä¸‰ç§�æŽ’åº�æ–¹æ³•ï¼Œä¿�ç•™ promoted pool200 baselineã€‚

**éªŒè¯�ç»“æžœï¼š**
ä¸‰ç»„å�˜ä½“å�‡ä¸º `hit_rate_at_k=0.014493`ã€�`ndcg_at_k=0.002779`ã€�`mrr_at_k=0.006039`ï¼Œç›¸å¯¹ baseline `hit_rate_at_k=0.021739`ã€�`ndcg_at_k=0.004983` æ²¡æœ‰æœ‰æ•ˆæ��å�‡ã€‚case attribution æ˜¾ç¤ºæ¼‚ç§»æ± å†…ä¸‰ç»„æ–¹æ³• Top-K å‘½ä¸­é›†å�ˆç›¸å�Œï¼Œå�ªæœ‰ 2 ä¸ª Top-K hitsï¼Œæ²¡æœ‰ entered Top-K targetã€‚é…�ç½®éªŒè¯�ä¾§é€šè¿‡ `.venv` compileall å’Œç›¸å…³ pytestã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™æ®µå·¥ä½œä½“çŽ°çš„æ˜¯æŽ’åº�å®žéªŒçš„è¯„ä¼°çºªå¾‹ï¼šæŽ’åº�æ–¹æ³•èƒ½è·‘é€šä¸�ç­‰äºŽå�¯æ™‹å�‡ï¼Œå¿…é¡»å…ˆè¯�æ˜Žå€™é€‰æ± ç¨³å®šæˆ–æœ‰ same-run baselineã€‚å�‘çŽ°å€™é€‰æ± æ¼‚ç§»å�Žï¼Œä¸»åŠ¨æŠŠç»“è®ºé™�çº§ä¸º `INVALID`ï¼Œå¹¶æ˜Žç¡®ä¸‹ä¸€æ­¥è¦�å…ˆè¡¥ per-user frozen candidate export æˆ– same-run no-rerank baselineï¼Œç­‰éš”ç¦»é—®é¢˜ä¿®å¤�å�Žå†�è€ƒè™‘ LTRã€‚

### 2026-05-13 - Phase D semantic/title-category promotion candidate 收口

**任务：**
继续长期召回执行，把 Phase 1.21 的 family-specific observation、frozen candidates 和 dedicated ablation evidence 收口成可审查的 promotion candidate。

**遇到的问题：**
初始 ablation 结果四个实验行完全一致，暴露出 source-family 开关污染：baseline_only 继承了实验配置里已经启用的 semantic/co-visit/long-tail source，不能用于单 source 归因。

**定位方式：**
核对 `outputs/recall/phase_1_21_recall_coverage/ablations/itemcf_covisit_semantic_pool200/summary_metrics.csv`、`dedicated_ablation_evidence_manifest.json` 和 `frozen_promotion_evidence_checklist.json`；重点检查同一 holdout hash 下 baseline_only 与各 patch 的 `candidate_hit_users`、`exclusive_hit_users`、fallback、latency 和 required artifacts。

**解决方式：**
修正 ablation base config，去掉所有 source-family 开关后再逐个 patch 启用待测 source；重新生成 summary、exclusive hits、overlap、latency、fallback 和 frozen promotion checklist。随后新增 `.omc/recall/artifacts/phase_1_21_semantic_title_category_promotion_candidate/{manifest,metrics,signature}.yaml`，并把 registry schema/registry 同步到 `PROMOTION_CANDIDATE` 状态。独立 verifier 批准后，再新增 `.omc/recall/artifacts/phase_1_21_semantic_title_category_baseline_vnext/{manifest,metrics,signature}.yaml` 和 `PASS_PROMOTE_DEFAULT` registry row。

**验证结果：**
修正后 baseline_only 为 17 个 candidate-hit users；semantic/title-category 为 19 个，带来 +2 个额外 candidate-hit users；co-visit fallback 与 category long-tail 均无候选命中增量。`frozen_promotion_evidence_checklist.json` 为 `READY_FOR_PROMOTION_REVIEW`，独立 verifier 给出 APPROVE；`./.venv/Scripts/python.exe scripts/data/validate_recall_registry.py` 通过并识别 3 条记录。当前默认晋升只覆盖 semantic/title-category，回滚基线为 `phase_1_25_pool200_frozen_baseline`。

**面试可讲点：**
这次工作体现了召回实验的证据治理能力：不仅跑实验，还能发现消融污染、修正实验设计、用 frozen candidates 和 registry 固化证据边界，并在 verifier 批准后把单一有效 source 晋升为可回滚的 baseline_vNext。

### 2026-05-12 - Phase 1.23 sample-size LOPO 叙事补充

**任务：**
补写 Phase 1.23 的 sample-size sensitivity 中文叙事，明确它只是在 LOPO 内部做 recall-only sanity，不把结果误写成 valid_test 晋升证据。

**问题：**
100 / 1000 / 10000 三档样本下的 LOPO pool200 召回都很高，容易被误读成“低 recall 只是样本太少”；但这些结果和 Phase 1.21/1.22 的 valid_test holdout-hash baseline 不同口径，不能直接对比。

**定位：**
对照 `outputs/ranking/phase_1_23_sample_sensitivity/contract.json`、`metrics_by_sample.json`、`sample_size_sensitivity_summary.csv` 和 `report.json`，核对三档结果分别为 12/12=1.0、78/81=0.962963、1314/1382=0.950796，`candidate_count_avg` 依次为 52.166667、93.901235、128.83864；同时检查命中来源，发现更大样本下主要由 `itemcf_strong` / `itemcf_weak` 贡献，而不是 Phase 1.21 里解释 pool200-only 增益的 `semantic_title_category_expansion` / `popular`。

**解决：**
把叙事边界锁在 recall-only、pool200、LOPO internal split，并明确不做 ranking、Top-K、LTR rerank、holdout tuning 或 leakage 规避式包装；结论写成“数据/切分难度仍是主因，LOPO 证据不足以把 valid_test 低 recall 归因为样本规模”。

**验证：**
三档 LOPO 指标全部跑通且 fallback_rate=0.0；样本增大后候选供给确实上升，但 source 归因与 valid_test 基线不一致，说明 sample-size 变大并不自动等价于 valid_test recall 晋升。

**面试可讲点：**
这轮的价值不在“把 recall 做高”，而在“把证据边界说清楚”：我用同一 recall-only 合同验证了样本规模会影响候选供给，但也证明了 LOPO 不能直接替代 valid_test 口径，因此后续应优先做同风格 valid_test 大 split 或更严格的 leakage audit。



### 2026-05-12 - Phase 1.24 核心召回指标扩展

**任务：**
补写 Phase 1.24 的中文工程叙事，把工业召回方法和现有 source 映射到统一的观测指标框架。

**遇到的问题：**
单看 recall 数字容易把规则/热门、协同过滤、内容/语义、图召回、双塔召回混成一个黑盒，也容易把召回观测误写成排序收益。

**定位方式：**
按工业召回谱系对齐现有 source：`popular` / `category`、`itemcf_strong` / `itemcf_weak`、`semantic` / `semantic_title_category_expansion` / `category_long_tail`、`item_graph` / `graph_walk`、`two_tower`，并明确序列/多兴趣召回暂未落地。

**解决方式：**
把 Phase 1.24 定义为指标扩展，不改召回算法本身；只补 source 归因、覆盖、召回命中和分桶观察，明确不做排序、Top-K promotion、线上 CTR/CVR/GMV 伪造，也不靠 holdout / miss-target 调参。

**验证结果：**
文档已补齐，口径与前序召回诊断一致：这轮新增的是观测能力，不是算法晋升。

**面试可讲点：**
可以把这轮讲成“先拆方法谱系，再统一观测指标”。这样后续无论接规则、协同过滤、语义、图还是双塔，都能用同一套边界判断覆盖和来源，而不是把可观测误当成已提分。

### 2026-05-12 - Phase 1.25 工业排序研究收口

**任务：**
把 Phase 1.23 / 1.24 的 same-run 证据收束成工业排序研究文档，并同步补写过程日志。

**问题：**
1.23 / 1.24 都是 `VALID`，但 `hit_rate_at_k`、`ndcg_at_k`、`mrr_at_k` 全部持平，容易把实验可运行误解为默认晋升。

**定位方式：**
对照 `outputs/ranking/phase_1_23_pool200_ranking_isolation/comparison.json`、`outputs/ranking/phase_1_23_pool200_ranking_isolation/comparison.md`、`outputs/ranking/phase_1_24_pool200_semantic_near_miss_rescue/comparison.json`、`outputs/ranking/phase_1_24_pool200_semantic_near_miss_rescue/comparison.md`，核对 frozen pool200 的关键指标：`candidate_hit_rate_at_pool=0.123188`、`hit_rate_at_k=0.014493`、`ndcg_at_k=0.002779`、`mrr_at_k=0.006039`、`map_at_k=0.001208`、`candidate_hit_missed_topk_users=15`。

**解决方式：**
将研究边界收敛为工业指标概览、失败模式映射、两轮复盘和不超过 3 个轻量候选；明确不改召回、不动 `candidate_pool_size`、不做训练/集成、不晋升 LOPO。

**验证结果：**
`dic/experiments/ranking/phase_1_25/PHASE_1_25_INDUSTRIAL_RANKING_RESEARCH.md` 已落盘，内容和 frozen-pool 证据一致，且给出了后续实验的 stop gate。

**面试可讲点：**
这类工作能体现我如何把“实验做完”转成“证据说清楚”：先锁边界、再看 delta、最后才决定哪些候选值得继续。

### 2026-05-12 - Phase 1.25 pool200 召回体检与候选池健康收口

**任务：**
基于 `outputs/recall/phase_1_25_pool200_recall_health/` 的结果，补写 pool200 召回/候选生成健康叙事。

**问题：**
候选池虽然可跑通，但如果只看“有命中”容易忽略空候选、覆盖、候选规模分布和来源重叠，导致把召回健康误判为排序收益。

**定位方式：**
对照 `recall_health_report.json` / `.md`、`baseline/metrics.json`、`baseline/manifest.json`，核对 `empty_candidate_users=0`、`empty_candidate_rate=0.0`、`user_candidate_coverage_rate=1.0`、`candidate_count avg/min/p50/p90/max=157.112/67/160/200/200`、`candidate_hit_users@pool=19/138`、`catalog_candidate_coverage_count=12089`，以及 source marginal hits：`semantic=4`、`popular=3`、`semantic_title_category_expansion=2`、`two_tower=1`。

**解决方式：**
把结论锁定为“pool200 召回底座健康、候选池覆盖完整、来源贡献可解释”；只补召回体检与来源解释，不把 `candidate_recall@20/50/100/200` 或 `candidate_hit_rate@20/50/100/200` 误写成排序提升，也不引入 LTR/rerank/Top-K promotion。

**验证结果：**
`candidate_hit_rate@20/50/100/200=0.072464/0.108696/0.123188/0.137681`，`candidate_recall@20/50/100/200=0.034967/0.055921/0.05884/0.06971`；候选池无空用户、覆盖率 100%，说明召回健康问题已被体检证实可控。

**面试可讲点：**
这轮能讲成“先做候选池体检，再谈模型优化”：先用空候选、覆盖率、候选规模分布和 source overlap 判断底座是否稳定，避免把召回健康和排序收益混在一起。

### 2026-05-12 - Phase 1.25 normalized-additive 排序门禁验证

**任务：**
在 frozen pool200 候选池上验证 normalized-additive 排序平台是否只改变排序诊断，不引入召回、候选池规模、`top_k`、LTR、serving 或 frontend 合约漂移。

**问题：**
新增排序权重网格如果没有严格门禁，容易把候选池 hash/count 漂移、fallback 变化或二级指标局部变化误判成可晋升排序收益。

**定位方式：**
对照 `.omc/handoffs/team-exec-to-team-verify-phase-1-25-ranking-platform.md`、`outputs/ranking/phase_1_25_pool200_normalized_additive_limit500/comparison.json` / `.md`、`configs/ranking/phase_1_25/phase_1_25_pool200_*.yaml`、`rs_core/recsys/evaluation.py` 和 `tests/test_hybrid_demo.py`，核对 8 个变体均为 `candidate_pool_size=200`、`top_k=5`、`ltr_model=false`、`ranking_v2=false`、`item_feature_rerank=false`、`source_aware_fusion=false`。

**解决方式：**
保留 normalized-additive 为排序层诊断平台：有限权重网格、同跑 baseline、冻结候选 hash/count 对比、`strict_ranking_promotion_status` 强门禁；LTR 只允许 diagnostic-only，不允许 promotion。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -q` 通过 80/80，`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过。limit-500 对照中 8 个变体 `all_variants_valid=true`、frozen hash 均为 `e664ad5ee7b133811d19e6b28b1e99f5d1cef15b6241f1ef51d40ed73b28195b`、`user_count=500`、`candidate_count=76136`；所有非 baseline 变体均为 `PARTIAL diagnostic-only`、`promotable=false`，主指标持平：`hit_rate_at_k=0.014493`、`ndcg_at_k=0.002779`、`mrr_at_k=0.006039`、`map_at_k=0.001208`、`candidate_hit_missed_topk_users=15`。

**面试可讲点：**
这轮可以讲成“先建排序实验门禁，再决定是否晋升”：我没有因为平台跑通就包装成收益，而是用 hash/count、freeze 指标和 promotion gate 证明这只是可复用诊断能力，当前排序效果不晋升。

### 2026-05-12 - Phase A 持久化合同落地与 frozen snapshot 诊断

**任务：**
补充 Phase A 中文工程叙事，记录 recall persistence contract、schema、registry 和冻结快照的边界。

**遇到的问题：**
pool200 frozen baseline 只有 observation snapshot；缺 frozen_candidates、ablation、latency、fallback promotion artifacts，若直接写成提分结论会把合同落地误写成算法晋升。

**定位方式：**
核对 `.omc/recall/schema/recall_experiment_registry.schema.yaml`、`.omc/recall/schema/source_group_registry.schema.yaml`、`.omc/recall/registry/*.yaml`、`.omc/recall/artifacts/phase_1_25_pool200_frozen_baseline/{manifest,signature,contract,metrics}.yaml`，并运行 `./.venv/Scripts/python.exe scripts/data/validate_recall_registry.py`。

**解决方式：**
把 Phase A 定义为持久化合同落地，统一将 pool200 snapshot 标记为 `INCONCLUSIVE_MISSING_ARTIFACT`；只确认 registry/schema/manifest 的一致性，不补造晋升证据，不写 ranking/LTR/Top-K/在线收益。补齐生产路径后，`run_hybrid_demo` 会写出 `recall_registry_artifact.json`，并把路径回填到 `metrics.json`，让后续 agent 可以直接从 workflow artifact 接续 registry 治理。

**验证结果：**
`Recall registry validation passed: 1 record(s)`；相关文档已更新，叙事口径与 artifact 边界一致。生产路径测试 `./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py::test_workflow_writes_outputs_report_and_metrics` 通过，确认 workflow 产物包含 recall-only registry artifact，且缺失 promotion artifact 时仍保持 `INCONCLUSIVE_MISSING_ARTIFACT`。

**面试可讲点：**
可以讲成“先做证据合同，再做结果表达”：先让 schema、registry、artifact manifest 可校验，再决定 snapshot 能不能晋升；这样可避免把观察性产物误写成算法提升。

### 2026-05-13 - Phase B recall promotion artifact 生产路径与 source family benchmark 框架

**任务：**
把 Phase A 的静态 recall contract 推进到 workflow 生产路径：`run_hybrid_demo` 写出 promotion sidecar artifacts，并让 Phase 1.21 recall coverage baseline 产出 source family observation benchmark 框架。

**问题：**
pool200 snapshot 之前只有 registry/manifest 层证据；如果没有 workflow 级 sidecar、hash 和 benchmark 注册模板，后续 agent 很难持续比较 popular/category、ItemCF/co-visit、semantic/title-category、graph、vector/two-tower、sequence/multi-interest，也容易把缺失 ablation 的 observation 误判为 baseline_vNext。

**定位：**
检查 `rs_core/workflow/hybrid_demo.py` 的 metrics 写出顺序，发现 registry artifact 判断 latency/fallback/overlap 是否可用依赖 sidecar 文件实际存在；同时检查 `scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py`，确认 baseline 模式适合作为 source family observation benchmark 的轻量注册入口。

**解决：**
`run_hybrid_demo` 现在写出 `recall_source_coverage.json`、`recall_pool_curve.json`、`recall_latency_report.json`、`recall_fallback_report.json`、`recall_overlap_source_contribution.json`，并把路径回填到 `metrics.json` / `recall_registry_artifact.json`；dedicated leave-one-source-out ablation 仍保持 unavailable，所以 gate status 继续是 `INCONCLUSIVE_MISSING_ARTIFACT`。Phase 1.21 baseline 额外写出 `source_family_observation_benchmarks.json`，只生成 observation lane 的 source family 注册模板，不直接跑昂贵全量实验。

**验证：**
`./.venv/Scripts/python.exe scripts/data/validate_recall_registry.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_21_recall_coverage.py tests/test_hybrid_demo.py::test_workflow_writes_outputs_report_and_metrics` 通过，20 passed。测试覆盖 sidecar path/hash、forbidden ranking/online metrics、source family benchmark 六类方法和 recall-only observation contract。

**面试可讲点：**
这轮可以讲成“把召回路线探索做成可持续实验系统”：先统一 artifact、hash、gate 和 source family 模板，让后续 agent 能公平探索主流召回方法组合；但在 ablation 缺失前，不把任何组合晋升成最终路线。

**首批 observation baseline：**
在 `outputs/recall/phase_1_21_recall_coverage/source_family_baseline/` 跑通固定 holdout hash 的 pool100 source-family baseline：`users_with_holdout=138`、`candidate_hit_users=14`、`candidate_hit_rate_at_pool=0.101449`、`recall_at_pool=0.060709`、`empty_candidate_rate=0.0`、`fallback_rate=0.0`。本轮只证明 observation 框架可运行，不产生 `baseline_vNext`；下一步应按 source family 跑具体变体和 dedicated ablation。

### 2026-05-13 - Phase C 召回长期执行合同与 evidence 状态机加固

**任务：**
继续执行召回长期目标，补齐 promotion gate、diagnostic-only 隔离、source family 状态矩阵和 ablation/frozen evidence 骨架。

**问题：**
仅有 observation baseline 和模板会让后续执行误判完成度；未运行 family、缺失 frozen candidates、缺 dedicated ablation 都不能被包装成 `baseline_vNext` 晋升证据。

**定位：**
检查 recall registry schema/validator、Phase 1.21 benchmark artifact 和测试断言，重点验证 `frozen_candidates_path`、forbidden metrics、source family execution status 与 missing artifact 状态。

**解决：**
强化 schema/validator 负向校验；为六类 source family 增加 `execution_status`、`evidence_level`、artifact path/hash 和 `next_action`；为 ablation 模式输出 dedicated evidence manifest 与 frozen promotion checklist，并在缺真实 artifact 时保持 `INCONCLUSIVE_MISSING_ARTIFACT`。

**验证：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py::test_recall_registry_validator_accepts_source_alias_and_rejects_forbidden_metric_overlap` 通过；`./.venv/Scripts/python.exe -m compileall scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_21_recall_coverage.py` 通过 19/19。

**面试可讲点：**
可以讲成“长期推荐实验的防伪完成机制”：用状态机和 evidence checklist 区分模板、可运行、已执行和可晋升，确保没有真实 frozen/ablation 证据时系统自动保持不晋升。

### 2026-05-12 - Phase 1.26 持久排序实验治理底座

**任务：**
把“持续探索工业排序方法”的长期计划先收束成可执行治理底座：实验注册表、冻结候选 artifact equality、严格状态机阈值，而不是一次性堆所有模型。

**问题：**
Phase 1.25 已证明 normalized-additive 平台能跑但没有排序效果提升；如果继续新增 LTR、GBDT 或深度排序而没有统一 registry 和候选池一致性门禁，容易把候选池漂移、样本噪声或微小浮点变化误判成最终路线。

**定位方式：**
检查 `rs_core/recsys/evaluation.py` 中的 `frozen_candidate_signature()`、`compare_frozen_candidate_signatures()`、`strict_ranking_promotion_status()`，以及 `tests/test_hybrid_demo.py` 里 Phase 1.25 的冻结候选和 promotion gate 测试，确认最小集成点可以放在 evaluation 层，不需要修改召回、`candidate_pool_size`、`top_k` 或 serving/frontend contract。

**解决方式：**
新增 `frozen_candidate_artifact()`、`compare_frozen_candidate_artifacts()` 和 `build_ranking_experiment_registry_entry()`，把 canonical candidate hash/count、schema version、promotion scope、关键指标和状态统一落到 registry entry；同时把 promotion gate 从“只要 hit_rate 大于 tolerance”收紧为 `hit_rate` 绝对提升至少 `0.001`、相对提升至少 `3%`、`candidate_hit_missed_topk_users` 至少减少 1，且 NDCG/MRR/MAP 不回退。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py::test_phase_1_26_runner_writes_registry_entries_to_comparison tests/test_hybrid_demo.py::test_phase_1_26_registry_entry_records_frozen_candidate_artifact_and_scope tests/test_hybrid_demo.py::test_phase_1_26_candidate_artifact_equality_reuses_strict_signature_gate tests/test_hybrid_demo.py::test_strict_ranking_promotion_status_promote_partial_and_invalid_stop` 通过 4/4；`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_evaluation.py tests/test_hybrid_demo.py` 通过 86/86，并验证 Phase 1.25 runner 的 `comparison.json` 会实际写出 `ranking_experiment_registry`。

**面试可讲点：**
这轮可以讲成“先治理实验，再探索模型”：面对多种工业排序方法，不急着堆模型，而是先建立可复现的实验注册、候选池相等性和晋升状态机，让后续 LR/GBDT/LambdaMART/深度排序都必须在同一 frozen-pool 证据框架下竞争。

### 2026-05-13 - Phase 1.27 特征/标签/泄漏治理收口

**任务：**
补充 Phase 1.27 中文工程叙事，记录特征契约、标签切分和泄漏门禁的治理边界。

**遇到的问题：**
如果 feature contract、label split 和 leakage gate 没有被明确约束，后续 learned ranker 很容易把 holdout target、future interaction 或 promotion evidence 误用进训练和评估；验证前还遇到 `rs_core/workflow/hybrid_demo.py` 的 helper 调用不一致，必须先修复后才能继续跑验证。

**定位方式：**
对照 `dic/phases/RANKING_LONG_RUNNING_EXPLORATION_PLAN.md` 中 Phase 1.27 的 scope，确认当前要补的是 offline ranking feature contract、allowed/forbidden features、label/split/leakage gate 和 registry metadata，而不是改 `candidate_pool_size`、`top_k` 或 recall baseline；随后运行 compileall、Phase 1.27 相关 pytest 和真实 runner smoke。

**解决方式：**
把 Phase 1.27 写成治理阶段：allowed features 只保留 source、item metadata、candidate score、user history aggregates 和 near-miss diagnostics；forbidden features 排除 holdout target、future interaction，以及 valid/test 上训练后再当 promotion evidence 的字段；label split leakage gate 覆盖 target item、future interaction 和 holdout leak；registry metadata 记录 feature contract version 与作用范围，供后续 learned ranker 复用。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_evaluation.py tests/test_ltr.py` 通过 106/106；`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过；`./.venv/Scripts/python.exe scripts/experiments/ranking/run_phase_1_25_pool200_normalized_additive.py --limit-users 50` 成功生成 `outputs/ranking/phase_1_25_pool200_normalized_additive/comparison.json`，registry 中已记录 `feature_contract_version=ranking_feature_contract_v1`、`feature_contract_gate_summary.schema_version=ranking_feature_contract_gate_v1` 和 `leakage_gate_summary.schema_version=ranking_feature_leakage_gate_v1`。非 LTR 排序变体的 feature/leakage gate 明确标记为 `NOT_APPLICABLE`，LTR 训练路径会对真实 feature rows 执行 gate；验证期间没有改 `candidate_pool_size`、`top_k` 或 recall baseline，也没有把这轮叙事写成模型 lift。

**面试可讲点：**
可以讲成“先定特征契约和泄漏边界，再谈模型效果”：这轮没有追求数字上升，而是把输入契约、标签切分和泄漏门禁先做成可审计的治理层，确保后续学习排序的证据可信、可复现、可追踪。

### 2026-05-13 - Phase 7/8 多目标与在线学习 future-online 门禁

**任务：**
在长期排序计划 Phase 7/8 中收口 ESMM、MMoE、PLE、多目标排序、Bandit、RL/GRPO 和 Agent feedback 的当前边界，确保线上业务指标不会被误用为 frozen pool200 离线 promotion 证据。

**遇到的问题：**
Phase 7/8 需要 CTR/CVR/GMV 业务 label、线上或准线上评估、serving/monitoring contract、交互日志、安全探索策略和 replay/A/B 链路。当前项目还停留在 frozen pool200 离线排序证据，因此只能标记 future-online / future-agent-online，不能实现假在线实验。

**定位方式：**
读取 `dic/phases/RANKING_LONG_RUNNING_EXPLORATION_PLAN.md` 的 Phase 7/8 进入条件，并对照当前 ranking registry 能力，确认可以产出 future gate artifact，但不能把线上指标、SLO 或 A/B uplift 纳入当前离线晋升。

**解决方式：**
新增 `scripts/experiments/ranking/run_phase_7_8_future_online_gate.py`，运行 same-run baseline 以保持当前离线 artifact 完整；将 `esmm_ctr_cvr_ranker`、`mmoe_multi_task_ranker`、`ple_multi_task_ranker`、`contextual_bandit_ranker`、`rl_grpo_preference_ranker` 等方法写入 blocked registry，lane 标注为 `future-online` 或 `future-agent-online`，并在 readiness 中列出缺失条件和当前禁用证据。

**验证结果：**
`compileall` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_7_8_future_online_gate or phase_6_semantic_two_tower_ranker or phase_5_sequence_ranker"` 通过 3 个目标测试；`outputs/ranking/phase_7_8_future_online_gate_smoke/comparison.json` 验证 artifact inspection PASS、`candidate_pool_size=200`、`top_k=5`、所有 Phase 7/8 方法 blocked 且不具备当前 offline promotion eligibility，最终路线保持 `same_run_baseline`。

**面试可讲点：**
这轮可以讲成“把未来路线也纳入工程治理”：不仅能实现模型，还能识别哪些方法需要线上标签和安全探索条件，在证据不足时用 future gate 防止指标口径污染。

### 2026-05-13 - Phase 6 语义 / 双塔排序特征融合门禁

**任务：**
在长期排序计划 Phase 6 中验证 semantic-title score、two-tower score、vector similarity、DSSM 和 cross-feature fusion 的排序侧价值，继续保持 frozen pool200、`candidate_pool_size=200`、`top_k=5`、不改召回语义。

**遇到的问题：**
semantic / two_tower 已经是当前候选池的召回源，如果直接改召回或重新用 DSSM/vector artifact 生成候选，会破坏排序实验边界。与此同时，DSSM 与 raw vector similarity 虽有训练 artifact，但缺少 candidate-level rerank adapter，不能作为当前离线 promotion 证据。

**定位方式：**
对照 `configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml`、`rs_core/recsys/ranking.py`、`rs_core/recsys/ltr.py` 和 two-tower artifact，确认当前可审计输入是候选内 `source_scores` 和 source cross features；真实 smoke 产物为 `outputs/ranking/phase_6_semantic_two_tower_ranker_smoke/comparison.json`。

**解决方式：**
新增 `scripts/experiments/ranking/run_phase_6_semantic_two_tower_ranker.py`，在 same-run frozen pool200 baseline 上运行 `semantic_score_feature_rerank`、`two_tower_score_feature_rerank` 和 `semantic_two_tower_cross_feature_fusion` 三个排序对照；将 `dssm_artifact_candidate_rerank` 与 `raw_vector_similarity_feature_fusion` 写入 blocked method registry，明确 blocked 原因是 adapter 缺失和禁止候选池重生成。

**验证结果：**
`compileall` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_6_semantic_two_tower_ranker or phase_5_sequence_ranker"` 通过 2 个目标测试；Phase 6 smoke 通过并输出 artifact inspection PASS、全部 run 的 frozen candidate status PASS。指标上 baseline `hit_rate_at_k=0.037037`，semantic score rerank 降至 `0.018519`；two-tower score 与 cross-feature fusion 持平但未达到 hit-rate lift 和 missed-topk reduction 门槛，最终 `selected_route=same_run_baseline`。

**面试可讲点：**
这轮可以讲成“把 embedding/双塔从召回能力拆成排序证据来验证”：即使有 two-tower artifact，也必须在冻结候选池内证明排序收益；没有 adapter 或没有稳定 lift 的方法只能 diagnostic/blocked，不能包装成成功。

### 2026-05-13 - Phase 5 行为序列 / 注意力排序数据门禁

**任务：**
继续长期排序计划 Phase 5，判断当前数据是否足以支持 DIN / DIEN / BST / SIM 等行为序列排序模型。

**问题：**
行为序列模型依赖长历史、可靠时间顺序、session/history window 和无未来交互泄漏。当前数据有 `user_sequences` 和 timestamp，但长序列覆盖不足；如果直接训练 DIN/DIEN/BST/SIM，只能得到 toy 结果，不能作为当前离线 promotion 证据。

**定位：**
统计 `user_sequences.train.jsonl` 的序列质量：Phase 5 smoke 中 200 个用户的 `positive_len_ge_2_rate=0.575`、`positive_len_ge_10_rate=0.11`、`timestamp_ordered_rate=1.0`。结论是短序列诊断满足条件，但长序列模型未达到数据门槛。

**解决：**
新增 `scripts/experiments/ranking/run_phase_5_sequence_ranker.py`，输出 `sequence_ranker_data_readiness_v1`、Phase 0 风格 registry 和 artifact inspection。session-aware / attention history 仅为 diagnostic；DIN、DIEN、BST、SIM 标记为 blocked，并写明长序列覆盖不足和 adapter 缺失原因。

**验证：**
`./.venv/Scripts/python.exe -m compileall scripts/experiments/ranking/run_phase_5_sequence_ranker.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_5_sequence_ranker or phase_4_neural_ranker"` 通过 2/2；`outputs/ranking/phase_5_sequence_attention_ranker_smoke/comparison.json` 显示 artifact inspection PASS、短历史方法 diagnostic、DIN/DIEN/BST/SIM blocked。

**面试可讲点：**
这轮体现的是数据条件先行：面对工业序列模型，不是直接上模型名，而是先证明历史长度、时间顺序、泄漏边界和 serving adapter 是否具备，把“可诊断”和“必须 blocked”的方法分清。

### 2026-05-14 - Phase 5 正向收口与合同验证

**任务：**
同步 Phase 5 中文叙事，记录本轮 fine-rank / 序列正向收口结果。

**遇到的问题：**
Phase 5 smoke 能证明诊断链路和合同检查通过，但不能把序列/注意力方法写成 promotion；如果把 smoke 成功写成晋升，会越过 frozen candidate、top_k 和 online claims 的边界。

**定位方式：**
结合 `comparison.json` 与验证结果，核对 `candidate_pool_size=200`、`top_k=5`、`frozen_candidate_comparison.match=true`、`case_diagnostic_success=true`、`promotion_success=false`、`online_claims=[]`、`artifact_inspection=PASS`，确认本轮只有诊断证据，没有晋升证据。

**解决方式：**
把 Phase 5 结果明确收口为 diagnostic / blocked：短历史与注意力诊断保留，DIN / DIEN / BST / SIM 仍因序列覆盖和 adapter 条件不足维持 blocked，不把 positive push smoke 叙述成 promotion。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile scripts/experiments/ranking/run_phase_5_sequence_ranker.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_phase_5_fine_rank_positive_push.py -q` 通过 `7 passed`；`outputs/ranking/phase_5_fine_rank_positive_push_smoke/comparison.json` 通过 contract 检查。

**面试可讲点：**
这轮可以讲成“把序列模型也放进同一套证据门禁”：不是因为模型名更高级就放松标准，而是先用合同检查证明冻结候选、诊断成功和在线承诺为空，再决定哪些方法只能留在 diagnostic lane.

### 2026-05-13 - Phase 4 神经排序 CUDA 诊断原型

**任务：**
继续长期排序计划 Phase 4，把 MLP / RankNet 神经排序原型纳入统一实验治理，并验证 GPU 训练链路。

**问题：**
当前虽然 PyTorch CUDA 可用，但神经排序缺少 serving adapter、valid/test promotion split 和 ADR；Wide&Deep、DeepFM、DCN、xDeepFM 也缺少稳定特征交叉 schema。不能把 GPU 上能训练的 smoke 结果包装成 offline promotion。

**定位：**
用 `.venv` 检查依赖和设备，确认 `torch 2.11.0+cu128` 与 `NVIDIA GeForce RTX 4070 Ti SUPER` 可用；读取候选行导出结构，确认 `features/label/user_id` 可支持 pointwise MLP 与 pairwise RankNet 诊断训练。

**解决：**
新增 `scripts/experiments/ranking/run_phase_4_neural_ranker.py`，复用 Phase 0 registry/artifact/gpu 策略：MLP 和 RankNet 在 CUDA 上训练 diagnostic artifact；LambdaRank、ListNet/ListMLE、Wide&Deep/DeepFM/DCN/xDeepFM 因 objective、schema 或 adapter 缺失写为 blocked；所有神经方法默认不具备 promotion eligibility。

**验证：**
`./.venv/Scripts/python.exe -m compileall scripts/experiments/ranking/run_phase_4_neural_ranker.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_4_neural_ranker or phase_3_tree_ranker"` 通过 2/2；Phase 4 smoke 产物 `outputs/ranking/phase_4_neural_ranker_smoke/comparison.json` 显示 artifact inspection PASS、MLP/RankNet diagnostic、其他神经方法 blocked、最终路线仍为 same-run baseline。

**面试可讲点：**
这轮体现的是 GPU 实验纪律：真实使用 CUDA 训练，而不是 CPU toy；但训练跑通不等于排序晋升，仍必须通过 serving adapter、valid/test 口径、稳定 lift 和 ADR 才能进入 promotion。

### 2026-05-13 - Phase 3 树模型 / LambdaMART 依赖门禁

**任务：**
继续长期排序计划 Phase 3，把 GBDT / LambdaMART 路线接入统一实验治理，但只在真实依赖和训练条件满足时才允许进入 promotion。

**问题：**
当前 `.venv` 中 `sklearn`、`xgboost`、`lightgbm` 均不可用，代码中也没有真实树模型训练 adapter；现有 LTR 训练只能导出候选行或训练 pointwise/pairwise 轻量模型。直接用 deterministic stand-in 或 LOPO LTR 冒充树模型，会违反 frozen pool200 离线证据边界。

**定位：**
用 `./.venv/Scripts/python.exe` 检查树模型依赖，结果均为 missing；再检查 `rs_core/workflow/ltr_training.py`，确认 `write_candidate_rows` 可生成未来训练数据，但 `_train_ltr_model()` 只支持 pairwise perceptron 与 pointwise logistic。

**解决：**
新增 `scripts/experiments/ranking/run_phase_3_tree_ranker.py`，只运行 same-run baseline 和候选行导出；真实 `sklearn_gbdt_valid_test_promotion`、`xgboost_lambdamart_gpu_promotion`、`lightgbm_lambdamart_gpu_promotion` 统一写成 blocked method，并把依赖缺失、GPU 不可用、adapter 缺失、valid/test split 缺失写入原因。

**验证：**
`./.venv/Scripts/python.exe -m compileall scripts/experiments/ranking/run_phase_3_tree_ranker.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_3_tree_ranker or phase_2_shallow_learned_runner"` 通过 2/2。

**面试可讲点：**
这轮体现的是工程诚信和实验治理：复杂排序模型不具备依赖和训练条件时，不把 toy 实验包装成收益，而是把 blocked 原因结构化沉淀，为后续真实 GBDT/LambdaMART 接入准备数据和门禁。

### 2026-05-13 - Phase 2 浅层 learned ranker 诊断闭环

**任务：**
继续长期排序计划 Phase 2，把 pointwise logistic 和 pairwise perceptron 浅层学习排序纳入统一实验底座。

**问题：**
现有 LTR 训练是 LOPO 口径，只能证明训练/推理链路和 feature/leakage gate 可运行，不能作为 valid/test promotion evidence；线性 ranker 的独立 valid/test promotion split 还不存在，不能为了方法覆盖而伪造晋升。

**定位：**
检查 `scripts/experiments/ranking/run_phase_1_28_lightweight_learned_ranker.py` 与 `rs_core/workflow/ltr_training.py`，确认可复用 pointwise/pairwise 训练器、`feature_contract_gate` 和 `leakage_gate`。长期边界继续是 fixed recall base、frozen pool200、`candidate_pool_size=200`、`top_k=5`，LOPO-only 不晋升。

**解决：**
新增 `scripts/experiments/ranking/run_phase_2_shallow_learned_ranker.py`，输出统一 `method_registry`、`artifact_inspection`、`gpu_resource_strategy`、`ranking_experiment_registry` 和 `final_decision`。pointwise/pairwise 标记为 diagnostic，强制写入 `lopo_training_diagnostic_only`；缺少 valid/test promotion split 的 `linear_ranker_valid_test_promotion` 写为 blocked。

**验证：**
`./.venv/Scripts/python.exe -m py_compile scripts/experiments/ranking/run_phase_2_shallow_learned_ranker.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_2_shallow_learned_runner or phase_1_rule_ranking_runner or phase_0"` 通过 6/6；Phase 2 smoke 生成 `outputs/ranking/phase_2_shallow_learned_ranker_smoke/comparison.json`，artifact inspection PASS，pool/top_k 为 200/5，baseline champion，pointwise/pairwise diagnostic，linear ranker blocked，feature/leakage gates 均 PASS，最终 `BASELINE_FINAL_ROUTE`。

**面试可讲点：**
这轮体现的是“学习排序先过治理门禁，再谈晋升”：把训练闭环、泄漏检查和 registry 状态都跑通，但严格禁止把 LOPO 诊断结果写成线上或 valid/test 收益。

### 2026-05-13 - Phase 1 规则排序 champion/challenger 复验

**任务：**
在 Phase 0 排序实验底座上继续 Phase 1，系统复验 normalized additive、source-aware fusion、item feature rerank 和保守规则组合。

**问题：**
旧的规则排序实验分散在 Phase 1.23/1.25 runner 中，缺少统一的 method registry、artifact inspection 和 champion/challenger 状态输出；如果不先把规则方法收口，后续 learned ranker 或树模型很难判断自己超过的是哪个强基线。

**定位：**
检查现有 runner 与 `rs_core/recsys/ranking.py`，确认规则排序能力已有，但需要一个长期计划下的 Phase 1 专用入口；边界仍固定为 current fixed recall base、frozen pool200、`candidate_pool_size=200`、`top_k=5`，不使用在线 CTR/CVR/GMV/P95 作为当前离线晋升证据。

**解决：**
新增 `scripts/experiments/ranking/run_phase_1_rule_ranking_champion.py`，复用 Phase 0 底座字段：`method_registry`、`artifact_inspection`、`gpu_resource_strategy`、`ranking_experiment_registry`、`stability_summary` 和 `final_decision`。所有规则方法只做排序层 override，不改召回语义；未稳定过门禁的规则候选标记为 retired，baseline 继续作为 champion。

**验证：**
`./.venv/Scripts/python.exe -m py_compile scripts/experiments/ranking/run_phase_1_rule_ranking_champion.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_1_rule_ranking_runner or phase_0 or phase_1_29_terminal_runner"` 通过 6/6；小样本 smoke 生成 `outputs/ranking/phase_1_rule_ranking_champion_smoke/comparison.json`，artifact inspection PASS，pool/top_k 保持 200/5，baseline 为 champion，四个规则候选为 retired，最终 `BASELINE_FINAL_ROUTE`。

**面试可讲点：**
这轮体现的是“规则排序先成为可审计强基线”：即使规则方法没有晋升，也通过统一实验治理证明它们的边界干净、证据可复验，为下一阶段线性/pointwise/pairwise learned baseline 提供对照对象。

### 2026-05-13 - Phase 0 长期排序实验底座复用化

**任务：**
把长期排序计划的 Phase 0 落成可复用底座，让后续主流排序方法复用同一套 registry、artifact inspection 和 GPU 资源策略。

**问题：**
Phase 1.29 terminal runner 已能做 frozen pool200 对照，但 method 状态、artifact 检查和 GPU 策略还没有统一沉淀；如果后续每个方法单独判断，容易把 diagnostic-only、frozen mismatch 或 CPU toy smoke 误写成晋升证据。

**定位：**
检查 `scripts/experiments/ranking/run_phase_1_29_terminal_ranking_route.py` 的 comparison 输出，确认它需要复用 `rs_core/recsys/evaluation.py` 中的公共治理能力；硬边界仍是 fixed recall base、pool200、`candidate_pool_size=200`、`top_k=5`，线上 CTR/CVR/GMV/P95 不进入当前离线 promotion evidence。

**解决：**
在 `rs_core/recsys/evaluation.py` 增加 method registry、GPU resource summary、artifact inspection helper；runner 输出 `method_registry` 和 `gpu_resource_strategy`，并由统一 inspection 检查 artifact 路径、pool/top_k、frozen candidate match 与 diagnostic promotion violation。

**验证：**
`./.venv/Scripts/python.exe -m py_compile rs_core/recsys/evaluation.py scripts/experiments/ranking/run_phase_1_29_terminal_ranking_route.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_0 or phase_1_29_terminal_runner"` 通过 5/5。

**面试可讲点：**
这轮不是宣称排序效果提升，而是把长期排序实验的“操作系统”先做出来：统一状态机、artifact 门禁、GPU 资源策略和 frozen-pool 边界，保证后续 GBDT/LambdaMART/深度排序方法能公平比较、可复验、可追责。

### 2026-05-13 - Phase 1.31 final offline route selection

**任务：**
输出最终离线排序路线的 ADR，并把 no-promote 结论落到中文工程叙事里。

**遇到的问题：**
Phase 1.23 / 1.24 / 1.25 / 1.28 的证据都没有把模型推进到稳定 Promote；如果把训练 gate PASS、LOPO 结果或轻量 LTR 的 diagnostic smoke 误写成晋升证据，会让终局收口失真。

**定位方式：**
复核 `rs_core/recsys/evaluation.py` 的 `terminal_ranking_promotion_gate()` 与 `strict_ranking_promotion_status()`，再对照 `outputs/ranking/phase_1_28_lightweight_learned_ranker/comparison.json` 和 `comparison.md`，确认最终证据仍然只支持 `No-Promote` / `diagnostic-only`。

**解决方式：**
把最终离线路线定为 `same_run_baseline`，并在 ADR 中明确列出 excluded invalid evidence、underpowered segment、LOPO training gate PASS 但不等于晋升、以及不改召回 / 不碰线上链路的边界。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_evaluation.py tests/test_ltr.py tests/test_two_tower_training.py` 通过 117/117；`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过；`./.venv/Scripts/python.exe scripts/experiments/ranking/run_phase_1_28_lightweight_learned_ranker.py --limit-users 5` 成功生成最终比较产物。

**面试可讲点：**
把 `No-Promote` 作为显式结论写出来，比勉强找一个“看起来更好”的模型更有工程价值，因为它把边界、风险和后续方向都说清楚了。

### 2026-05-13 - Phase 1.31/1.32 排序算法 scaffold 与诊断收口

**任务：**
补齐 Phase 1.31/1.32 的中文工程叙事，记录统一算法 scaffold、规则/浅层 learned 诊断运行和树模型 blocked 准备的当前状态。

**遇到的问题：**
如果把 scaffold 成果、LOPO/diagnostic smoke 或树模型依赖检查写成晋升结论，就会越过 frozen pool200、`candidate_pool_size=200`、`top_k=5` 和 future-only 线上指标边界。

**定位方式：**
对照 `dic/phases/RANKING_LONG_RUNNING_EXPLORATION_PLAN.md` 的 Phase 1.31/1.32 计划和 `outputs/ranking/phase_1_31_ranking_algorithm_scaffold_smoke/comparison.json`、`outputs/ranking/phase_1_26_real_ranking_experiments_regression/comparison.json` 等回归产物，确认当前可写的是治理收口与诊断结论，不是模型晋升。

**解决方式：**
把 Phase 1.31 写成统一算法实验 scaffold，把 Phase 1.32 写成规则 champion 复验、浅层 learned fine-ranker 诊断和 tree/LambdaMART blocked 准备；所有方法继续走同一 registry / comparison schema，候选池和 top_k 保持不变，线上指标仍只保留为 future-only。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile rs_core/recsys/ranking.py rs_core/recsys/evaluation.py rs_core/workflow/hybrid_demo.py scripts/experiments/ranking/run_phase_1_30_physical_ranking_pipeline.py scripts/experiments/ranking/run_phase_1_26_real_ranking_experiments.py` PASS；`./.venv/Scripts/python.exe -m pytest tests/test_evaluation.py tests/test_hybrid_demo.py tests/test_ltr.py tests/test_phase_1_31_ranking_scaffold.py -q` 135 passed in 2.31s；`outputs/ranking/phase_1_30_physical_ranking_pipeline_regression/comparison.json`、`outputs/ranking/phase_1_26_real_ranking_experiments_regression/comparison.json`、`outputs/ranking/phase_1_31_ranking_algorithm_scaffold_smoke/comparison.json` 保留。

**面试可讲点：**
这轮可以讲成“先把排序实验底座做成共用协议，再在同一协议上跑规则、浅层 learned 和树模型准备”，重点是治理边界和证据格式，而不是把 smoke 结果包装成模型提升。

### 2026-05-13 - Phase 1.30 物理流水线证据与晋升边界收口

**任务：**
把 Phase 1.30 的跑通结果收口为“物理流水线证据”，并和 promotion evidence、future-online 指标明确分离。

**遇到的问题：**
这轮 smoke 已经能证明 recall→coarse→fine→rerank 的 stage 物理链路闭环，但如果把 pipeline trace、artifact inspection 或 smoke PASS 直接写成晋升结果，会把系统可观测性和模型收益混在一起；同时线上指标当前还没有进入离线证据链，不能提前写入结论。

**定位方式：**
对照 `outputs/verification/verification_phase_1_30_smoke/comparison.json` 与 `outputs/verification/verification_phase_1_26_regression/comparison.json`，复核 `candidate_pool_size=200`、`top_k=5`、`artifact_inspection=PASS`、`physical_pipeline_inspection=PASS`、`frozen_candidate_match=true`、coarse/fine/rerank stage counts 均为 3225，以及 `online_metric_claims=[]`；再确认 Phase 1.26 regression 的 LTR LOPO 仍是 `diagnostic-only`、`promotion_eligible=false`，tree/LambdaMART 仍 blocked。

**解决方式：**
把 Phase 1.30 写成物理流水线收口而不是晋升收口：明确这组证据只能证明 stage 闭环、artifact 完整和 frozen candidate match，不代表当前存在 promotion evidence；同时把 online metrics 继续留在 future-only 边界，把 LOPO/gate/smoke 统一标成 diagnostic-only。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_evaluation.py tests/test_ltr.py` 通过 130/130；Phase 1.30 smoke PASS，Phase 1.26 regression PASS。

**面试可讲点：**
这轮可以讲成“先把物理流水线和晋升证据分开治理”：系统层面我已经证明 stage 能闭环、artifact 能对齐、frozen candidate 能匹配，但我没有把这些可观测性结果伪装成模型提升，而是把它们归为诊断资产，为后续模型晋升保留干净证据边界。

### 2026-05-13 - Phase 1.28 lightweight learned ranker 最小闭环

**任务：**
把长期排序路线从治理阶段推进到第一批 learned-ranker 执行闭环：固定 pool200 候选池，复用 Phase 1.27 feature/leakage gates，只接入最轻量的 pointwise logistic 与 pairwise perceptron LTR baseline。

**问题：**
如果直接进入 GBDT、LambdaMART 或深度排序，容易在模型复杂度上过早扩张，也容易绕过 feature contract、label split 和 frozen candidate equality；同时 LOPO 训练只能作为内部 sanity，不能当 valid/test promotion evidence。

**定位方式：**
检查 `rs_core/recsys/ranking.py`，确认现有 `ltr_model` 已能加载模型并在 `rank_candidates()` 中叠加 LTR score；检查 `rs_core/recsys/ltr.py`、`rs_core/workflow/ltr_training.py` 和 `scripts/training/train_ltr_ranker.py`，确认 pointwise logistic 与 pairwise perceptron 都能产出兼容 `score_ltr()` 的线性模型，并会对真实 feature rows 执行 feature contract gate 与 leakage gate。

**解决方式：**
新增并扩展 `scripts/experiments/ranking/run_phase_1_28_lightweight_learned_ranker.py`，只跑三个 same-run 变体：`same_run_baseline`、`pointwise_logistic_lopo_ltr` 与 `pairwise_perceptron_lopo_ltr`。runner 先用 `configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml` 导出 baseline frozen candidates，再用 LOPO/internal train 训练轻量 LTR，最后在同一 pool200 口径下评估 LTR 变体，写出 `ranking_experiment_registry`、frozen candidate comparison、feature contract gate、leakage gate、model type 和 strict status；两个 LTR 变体固定 `diagnostic-only`，不允许晋升。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k phase_1_28 -vv` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_ltr.py tests/test_hybrid_demo.py` 通过 107/107；`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过；`./.venv/Scripts/python.exe scripts/experiments/ranking/run_phase_1_28_lightweight_learned_ranker.py --limit-users 50` 生成 `outputs/ranking/phase_1_28_lightweight_learned_ranker/comparison.json`。smoke 结果中 baseline、pointwise logistic 与 pairwise perceptron 变体 frozen candidate hash/count 匹配，`candidate_pool_size=200`、`top_k=5`、`fallback_rate=0.0`；两个 LTR 训练 `feature_contract_gate=PASS`、`leakage_gate=PASS`、`label_source=leave_one_positive_out_train`，model type 分别为 `pointwise_logistic_ltr_v1` 与 `pairwise_perceptron_ltr_v1`，变体状态均为 `PARTIAL diagnostic-only`、`promotable=false`。

**面试可讲点：**
可以讲成“先把 learned ranker 接入生产排序路径，再逐步升级模型”：这轮不是追求复杂模型，而是证明训练、推理、registry、frozen-pool equality 和泄漏门禁可以串成最小可审计闭环，为后续 LR/GBDT/LambdaMART/深度排序提供统一入口和证据标准。

### 2026-05-13 - Phase B promotion schema/validator 与 source family execution_status 收口

**任务：**
补写 Phase B 的中文工程叙事，记录 promotion schema/validator、diagnostic 隔离验证和 source family execution_status 收口。

**遇到的问题：**
source family observation baseline 已经能跑通，但 baseline_vNext 还缺 frozen artifacts、dedicated ablation 和完整 promotion evidence；如果把模板化骨架误写成晋升结果，会把诊断能力和算法收益混在一起。

**定位方式：**
对照 `tests/test_phase_1_21_recall_coverage.py`、`tests/test_hybrid_demo.py` 以及当前 benchmark 产物，确认已具备 promotion schema/validator、diagnostic-only execution_status、frozen-candidate equality 和 source family模板，但 family-specific ablation 和 frozen evidence 仍未补齐。

**解决方式：**
把这轮结论写成“baseline_vNext 仍不晋升”：保留 observation lane、execution_status 和 next_action 字段，下一队列先补 family-specific variants，再补 dedicated ablation/frozen evidence，最后才重新评估晋升。

**验证结果：**
当前叙事与测试口径一致，说明 benchmark scaffolding、diagnostic gate 和 frozen candidate equality 已经可复用，但 promotion 仍停留在 observation/diagnostic 层。

**面试可讲点：**
可以讲成“先把实验骨架和晋升证据分开治理”：先保证可执行、可复现，再决定是否晋升，避免把编排能力误当成模型提升。

### 2026-05-13 - Phase 1.26 长期排序路线收口

**任务：**
把长期排序主线收口成 recall→coarse rank→fine rank→rerank 的目标架构，并明确当前只推进 frozen pool200 → learned fine ranker → bounded rerank trace。

**问题：**
如果把 LOPO smoke、树模型 blocked 或线上指标混进当前结论，容易把 diagnostic-only / future-online 误写成晋升证据；同时目标架构虽然清楚，但 physical scope 还没有铺到完整 coarse/fine/rerank 全链路。

**定位方式：**
对照 `dic/OPTIMIZATION_NARRATIVE.md` 里的 Phase 1.26、Phase 1.28、Phase 1.31 以及 `scripts/experiments/ranking/run_phase_1_28_lightweight_learned_ranker.py`、`scripts/experiments/ranking/run_phase_3_tree_ranker.py` 的产物，确认 pointwise/pairwise learned ranker 已有 LOPO smoke，而树模型 / LambdaMART 仍是 blocked lane。

**解决方式：**
把这轮写成“目标架构清楚、物理边界收口”：当前只把 frozen pool200、learned fine ranker 和 bounded rerank trace 写成可执行主线；GBDT / LambdaMART 继续保留 blocked 状态，线上指标全部标记 future-online。

**验证结果：**
`outputs/ranking/phase_1_28_lightweight_learned_ranker/comparison.json` 可作为 pointwise/pairwise smoke 证据；`outputs/ranking/phase_3_tree_lambdamart_ranker_smoke/comparison.json` 保持 blocked / no promotion 口径；当前没有把任何 online metric 写入离线晋升结论。

**面试可讲点：**
可以讲成“先把排序路线图和当前证据边界分开”：目标架构可以画到 recall→coarse→fine→rerank，但真正能拿来讲证据的只有 frozen pool200、轻量 learned ranker 和 bounded rerank trace；树模型没依赖、没 adapter、没 GPU 验证时就明确 blocked，避免把未来路线写成当前成果。

### 2026-05-13 - Phase 1.32 metadata neighbor gate 与不晋升收口

**任务：**
在 `semantic_title_category_expansion` 已晋升为 recall baseline_vNext 后，对 `metadata_neighbor_recall` 做同一 holdout、同一 pool200、同一 recall-only 合同下的机会门禁和专项 ablation，判断是否应继续晋升或保留为诊断 source。

**遇到的问题：**
`metadata_neighbor_recall` 在 miss-user 诊断中有较大表面机会，但原实现按 seed 扫描完整 metadata index，长跑成本高；同时机会门只能作为聚合优先级判断，不能把 holdout target 或 miss target id 用进候选生成、query、target-driven source index construction/filtering、candidate whitelist 或参数选择。静态商品 catalog metadata 可作为非 holdout-label 派生的 train-visible item feature 建索引，但不能由 target 列表驱动筛选或调参。

**定位方式：**
读取 `outputs/recall/phase_1_21_recall_coverage/phase_1_32_metadata_neighbor_gate_20260513/audit/source_opportunity_summary.json`，确认 `baseline_miss_users=132`、`metadata_neighbor_opportunity_users=132`、门槛为 14 且 gate 通过；再对照 `ablation_narrow/baseline_only/metrics.json`、`ablation_narrow/semantic_title_category/metrics.json` 和 `metadata_only_capped/metadata_neighbor/metrics.json`，固定 `users_with_holdout=138`、`holdout_user_ids_hash=927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2`、`candidate_pool_size=200`。

**解决方式：**
将 metadata neighbor 从全量扫描改为 token/category bucket index，并增加 per-seed bucket candidate cap，使专项 ablation 可在 limit500 口径下完成；ablation matrix 支持 `ablation_experiments`，只运行需要的 source lane；测试补充 no-leakage note、miss-user gate 和 `metadata_neighbor_index_mode=bucketed_train_visible_metadata` 断言。

**验证结果：**
专项 metadata-only capped run 完成，manifest 记录 same holdout verified。结果显示 metadata lane `candidate_hit_users=17`、`candidate_hit_rate_at_pool=0.123188`、`candidate_count_avg=132.2`，虽有 `metadata_neighbor_recall` 用户覆盖 454、item 覆盖 272、召回候选 2870，但 `source_marginal_candidate_hit_users` 和 `candidate_hit_source_coverage` 均没有 metadata 贡献；对照 baseline_only 为 17，semantic/title-category 为 19 且有 2 个 marginal candidate-hit users。因此本轮结论是 `NO_PROMOTION`：metadata neighbor 工程链路和 gate 成立，但没有带来 recall-only candidate-hit lift。

**面试可讲点：**
这轮可以讲成“机会大不等于可晋升”：先用聚合 miss-user gate 判断是否值得跑，再用索引化实现控制成本，最后仍严格按 candidate-hit lift 和 source marginal contribution 裁决。metadata neighbor 通过了机会门和工程可运行性，但没有覆盖新的 holdout 命中，因此保留为诊断/后续改造方向，不污染 baseline_vNext。

### 2026-05-13 - Phase 3 树模型 / LambdaMART 依赖门禁

**任务：**
在 frozen pool200 排序口径下验证 Phase 3 tree / LambdaMART 是否具备真实训练、serving 和晋升条件，只保留可审计诊断，不把 tree smoke 写成模型收益。

**遇到的问题：**
当前环境里 GBDT / LambdaMART 相关依赖和 serving adapter 仍不完整；如果把 `sklearn` GBDT 或训练行导出当成晋升结果，就会把准备工作误写成模型效果，也会绕过 valid-test promotion gate 和 objective recovery condition。

**定位方式：**
读取 `scripts/experiments/ranking/run_phase_3_tree_ranking_experiments.py`、`tests/test_phase_3_tree_ranking_experiments.py` 和 `outputs/ranking/phase_3_tree_ranking_experiments_smoke/comparison.json`，核对 `candidate_pool_size=200`、`top_k=5`、training rows=2217、positive=16、negative=2201；同时用 `./.venv/Scripts/python.exe -m py_compile`、Phase3/Phase2/Phase1 scaffold/evaluation pytest 12 passed 和 recall regression pytest 23 passed 回归确认基础链路稳定。

**解决方式：**
把 `sklearn` GBDT 固定为 diagnostic-only，把 LambdaMART 固定为 blocked；只保留 candidate-row export、依赖检查、group/objective 恢复条件和 future 阶段的 serving 入口，不改 `merge_for_user` 和召回语义。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile` 通过；Phase3/Phase2/Phase1 scaffold/evaluation pytest 12 passed，recall regression pytest 23 passed，`limit_users=20` smoke 通过；`outputs/ranking/phase_3_tree_ranking_experiments_smoke/comparison.json` 未产生 online promotion evidence。

### 2026-05-14 - Phase 6 工业式默认全链路诊断 runner

**任务：**
把用户要求的“工业界相对较好的算法先摆到整条链路上”落成可运行诊断链路，而不是只停留在 coarse/fine/rerank 架构说明。

**遇到的问题：**
工业式链路需要同时覆盖 coarse、fine、rerank，但当前离线硬边界仍是 frozen pool200、`candidate_pool_size=200`、`top_k=5`，不能真实缩池、不能改召回语义，也不能把未来 online/Agent 指标写成当前 promotion。第一次 smoke 还暴露 normalized additive 权重越过 Phase 1.25 有限网格，直接被底座拒绝。

**定位方式：**
对照 `rs_core/recsys/ranking.py` 的 `coarse_rank_candidates → fine_rank_candidates → rerank_candidates`，确认已有 source weight、normalized additive、source-aware fusion、item-feature rerank 和 Top-K source minimums；再读取 `outputs/ranking/phase_6_industrial_ranking_chain_smoke/comparison.json`，核对 artifact inspection、frozen hash、stage assignment 和 promotion boundary。

**解决方式：**
新增 `scripts/experiments/ranking/run_phase_6_industrial_ranking_chain.py`，组合 `coarse_rank=source_weighted_metadata_shadow`、`fine_rank=normalized_additive + source_aware + item_feature full-pool scoring`、`rerank=top5 source minimum/stable tie-break`；新增 `tests/test_phase_6_industrial_ranking_chain.py`，并把 GBDT/LambdaMART、神经序列、Agent/online feedback 继续列为 blocked/future route。越界权重收回到 Phase 1.25 允许网格 `source_signal=0.2`、`item_feature=0.2`。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile scripts/experiments/ranking/run_phase_6_industrial_ranking_chain.py tests/test_phase_6_industrial_ranking_chain.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_phase_6_industrial_ranking_chain.py -q` 通过 `4 passed`；真实 smoke 产物 `outputs/ranking/phase_6_industrial_ranking_chain_smoke/comparison.json` 显示 `candidate_pool_size=200`、`top_k=5`、`artifact_inspection=PASS`、工业链路 `frozen_candidate_match=true`、`diagnostic_only=true`、`promotion_eligible=false`。

**面试可讲点：**
这轮可以讲成“把工业排序链路先接成可运行主路，同时用实验治理防止指标污染”：粗排、精排、重排都有对应算法和 artifact，但所有结论仍受 frozen pool、有限权重网格和 promotion gate 约束；发现权重越界后不是绕过检查，而是回到白名单网格重跑并验证通过。

### 2026-05-14 - Phase C 诊断门与 Phase A 收口顺序补齐

**任务：**
补充 Phase C 先行、Phase A 收口以及 learned/tree/neural 路线的中文叙事，并统一 oracle@5、target rank percentile、duplicate-source balance、win/tie/loss 的诊断口径。

**遇到的问题：**
原有长期计划主要覆盖 Phase 0/1/4/5/6 的持续实验顺序，但没有明确把 Phase C 定义成 tuning 前的诊断门，也没有把 Phase A 的合同固化位置和后续 learned/tree/neural 路线顺序写清楚，容易把诊断指标误写成晋升证据。

**定位方式：**
对照 `rs_core/recsys/evaluation.py` 的 `candidate_hit_rank_p90`、`source_overlap.multi_source_candidate_rate`、`source_pair_counts`、`source_pair_jaccard`，以及 `scripts/experiments/recall/phase_1_20_recall_diagnostics.py` 的 raw oracle stage、`scripts/experiments/ranking/run_phase_5_fine_rank_positive_push.py` 的 `coarse_to_fine_improved_count` / `coarse_to_fine_worsened_count` / `coarse_to_fine_unchanged_count`，确认这些字段可以分别承载 oracle、rank percentile、duplicate-source balance 和 win/tie/loss 的叙事。

**解决方式：**
在 `dic/phases/RANKING_LONG_RUNNING_EXPLORATION_PLAN.md` 新增 Phase C→Phase A→learned/tree/neural 的路线说明，并明确 Phase C 只做 tuning 前诊断、Phase A 负责合同与快照收口、learned/tree/neural 只有在 same-run frozen valid/test 证据通过后才进入推进讨论；同时在工程日志里补齐这些指标的口径，避免把 LOPO、stage trace 或线上指标混入当前离线晋升。

**验证结果：**
相关定义可在 `rs_core/recsys/evaluation.py`、`scripts/experiments/recall/phase_1_20_recall_diagnostics.py` 和 `scripts/experiments/ranking/run_phase_5_fine_rank_positive_push.py` 中直接对应到现有字段；本次只更新文档，没有改动 `candidate_pool_size=200`、`top_k=5` 或召回语义。

**面试可讲点：**
可以讲成“先把诊断门和晋升门拆开，再谈模型路线”：这样 Phase C 负责判断是否值得继续 tuning，Phase A 负责把合同边界固化，后续 learned/tree/neural 才能在同一证据框架里比较，不会把分析指标当成上线证据。

### 2026-05-14 - 默认离线主线收口与 Agent 手递边界

**任务：**
把长期排序路线收口为可供 Agent 系统直接交接的默认离线主线，明确当前目标是稳定可用的 handoff，而不是无限扩展算法族。

**遇到的问题：**
原有 Phase 0-8 叙事已经覆盖了实验顺序与门禁，但还缺少面向系统交接的终态说明，容易让后续 Agent 误把“继续探索更多算法”理解为默认工作目标。

**定位方式：**
对照 `dic/phases/RANKING_LONG_RUNNING_EXPLORATION_PLAN.md` 的 Phase C / Phase A / learned-tree-neural 叙事，确认当前最需要补的是默认主线职责、完成标准和 handoff 边界，而不是新增方法族。

**解决方式：**
在长期计划里补充默认离线 mainline 收口说明：把 `coarse → fine → rerank` 作为默认合同，继续锁定 `frozen pool200`、`candidate_pool_size=200`、`top_k=5` 和召回语义；Phase C 只保留诊断槽位；learned/tree/neural 只保留 future/blocked 位置；同时明确 Agent 系统只接收这条已经收口的主线，不再把方法族扩展当作默认目标。

**验证结果：**
本次仅更新中文文档与日志，没有改代码、没有改 runner、没有改评估口径，也没有动 `candidate_pool_size=200`、`top_k=5` 或召回语义。

**面试可讲点：**
可以讲成“把算法探索和系统交接分层”：先提供稳定、可复用、可交接的默认离线主线，再把更激进的 learned/tree/neural 路线留到明确门禁之后，避免 Agent 在不稳定边界上继续发散。



## 2026-05-15 - å·¥ç¨‹è§„èŒƒ v1.1ï¼šé…�ç½® contractã€�è„šæœ¬å…¥å�£ä¸Žè½»é‡� recsys å�•æµ‹

- ä»»åŠ¡ï¼šåœ¨å·¥ç¨‹è§„èŒƒ v1 åŸºç¡€ä¸Šç»§ç»­æŠŠâ€œå�£å¤´çº¦å®šâ€�è�½æˆ�å�¯æ‰§è¡Œé—¨ç¦�ï¼Œé‡�ç‚¹è¦†ç›–é…�ç½® contractã€�scripts å…¥å�£è§„èŒƒå’Œ recsys æ ¸å¿ƒè½»é‡�å�•æµ‹ã€‚
- é�‡åˆ°çš„é—®é¢˜ï¼šé…�ç½®å’Œè„šæœ¬æ•°é‡�å·²ç»�å¾ˆå¤šï¼Œå�•é� æ–‡æ¡£å¾ˆéš¾ä¿�è¯�ä¸�å‡ºçŽ°ä¸ªäººç»�å¯¹è·¯å¾„ã€�tracked ä¸´æ—¶é…�ç½®æˆ– import å�³æ‰§è¡Œçš„è„šæœ¬ï¼›å�Œæ—¶ `tests/test_hybrid_demo.py` è¿‡å¤§ï¼ŒåŸºç¡€å�¬å›ž/æŽ’åº�è¡Œä¸ºæ··åœ¨å®žéªŒæµ‹è¯•é‡Œä¸�åˆ©äºŽå¿«é€Ÿ CIã€‚
- å®šä½�æ–¹å¼�ï¼šç”¨ `git ls-files 'configs/*.yaml'` æ˜Žç¡® CI å�ªæ£€æŸ¥ tracked é…�ç½®ï¼›ç”¨ `scripts/ci/validate_engineering_contracts.py` æ‰«æ�� 110 ä¸ª tracked é…�ç½®å’Œ 48 ä¸ªè„šæœ¬ï¼Œå�‘çŽ° 4 ä¸ªåŽ†å�²å� ä½�è„šæœ¬ç¼ºå°‘ main guardï¼›ç”¨æ–°å¢žå�•æµ‹éªŒè¯� contract è¾¹ç•Œã€‚
- è§£å†³æ–¹å¼�ï¼šæ–°å¢ž `rs_core/common/engineering_contracts.py` å’Œ `scripts/ci/validate_engineering_contracts.py`ï¼Œå°†é…�ç½®å�¯åŠ è½½ã€�ç¦�æ­¢ tracked `_tmp` é…�ç½®ã€�ç¦�æ­¢ä¸ªäººæœºå™¨ç»�å¯¹è·¯å¾„ã€�è„šæœ¬ main guard å�˜ä¸ºå�¯æ‰§è¡Œæ£€æŸ¥ï¼›è¡¥é½� 4 ä¸ªå� ä½�è„šæœ¬çš„æœ€å°� `main()` éª¨æž¶ï¼›æ–°å¢ž `tests/test_recsys_core.py`ï¼Œä»Žå¤§æµ‹è¯•ä¸­æ‹†å‡º candidate mergeã€�ranking tie-breakã€�metadata neighbor recall ä¸‰ç±»åŸºç¡€è¡Œä¸ºã€‚
- éªŒè¯�ç»“æžœï¼š`scripts/ci/validate_engineering_contracts.py` é€šè¿‡ï¼Œè¾“å‡º `Engineering contracts passed: 110 configs, 48 scripts`ï¼›æ–°å¢žå�•æµ‹ `8 passed`ï¼›CI Python èŒƒå›´ ruff é€šè¿‡ï¼›unit/smoke æœ€å°�é›†å�ˆæ”¶é›† 75 ä¸ªå¹¶ `75 passed`ï¼›`npm --prefix frontend run lint` é€šè¿‡ï¼›`git diff --check` æ—  whitespace é”™è¯¯ï¼Œä»…ä¿�ç•™ Windows æ�¢è¡Œæ��ç¤ºã€‚
- é�¢è¯•å�¯è®²ç‚¹ï¼šè¿™æ¬¡ä¸�æ˜¯æ³›æ³›å†™è§„èŒƒï¼Œè€Œæ˜¯æŠŠç›®å½•/é…�ç½®/è„šæœ¬/æµ‹è¯•çº¦å®šè½¬æˆ�è‡ªåŠ¨åŒ– contract gateï¼Œå¹¶ç”¨è½»é‡�å�•æµ‹ä»Žå¤§å®žéªŒæµ‹è¯•ä¸­æŠ½å‡ºç¨³å®šæ ¸å¿ƒè¡Œä¸ºï¼Œä½“çŽ°äº†â€œè§„èŒƒæ–‡æ¡£ + å�¯æ‰§è¡Œé—¨ç¦� + å¿«é€Ÿå��é¦ˆâ€�çš„å·¥ç¨‹åŒ–ç»´æŠ¤æ€�è·¯ã€‚


### 2026-05-15 - é…�ç½®ã€�æ–‡æ¡£ä¸Žè¾“å‡ºäº§ç‰©ç›®å½•æ²»ç�†

**ä»»åŠ¡ï¼š**
æŠŠ `configs/`ã€�`dic/`ã€�`outputs/` ä¸­é•¿æœŸå †ç§¯çš„é…�ç½®ã€�æ–‡æ¡£å’Œè¿�è¡Œäº§ç‰©æŒ‰è�Œè´£é‡�æ–°åˆ†å±‚ï¼Œå¹¶è¡¥é½�æ–°å¢žæ–‡æ¡£ã€�é…�ç½®å’Œä¸€æ¬¡æ€§å®žéªŒäº§ç‰©çš„è·¯ç”±è§„èŒƒã€‚

**é�‡åˆ°çš„é—®é¢˜ï¼š**
`configs/` æ ¹ç›®å½•æ··æœ‰å¤§é‡� hybrid demoã€�phase å’Œä¸´æ—¶è°ƒå�‚é…�ç½®ï¼›`dic/` æ ¹ç›®å½•å�Œæ—¶æ‰¿è½½æž¶æž„ã€�é˜¶æ®µã€�å®žéªŒæŠ¥å‘Šå’Œå…¥å�£æ–‡æ¡£ï¼›`outputs/` é¡¶å±‚æ··å�ˆ canonical demoã€�smokeã€�verificationã€�training å’Œ root æ–‡ä»¶ï¼Œå¯¼è‡´æ­£å¼�è¯�æ�®ä¸Žä¸€æ¬¡æ€§å®žéªŒäº§ç‰©ä¸�æ˜“åŒºåˆ†ã€‚

**å®šä½�æ–¹å¼�ï¼š**
å…ˆç»Ÿè®¡ `configs/`ã€�`dic/`ã€�`outputs/` æ ¹ç›®å½•æ–‡ä»¶å’Œå­�ç›®å½•ï¼Œå†�ç”¨è·¯å¾„æ‰«æ��ç¡®è®¤æ—§å¼•ç”¨æ˜¯å�¦ä»�æŒ‡å�‘ `configs/*.yaml`ã€�`outputs/phase_*`ã€�`outputs/hybrid_demo_small*` ç­‰æ—§ç»“æž„ï¼›éš�å�Žç”¨ `scripts/ci/validate_engineering_contracts.py` æ ¡éªŒé…�ç½®å�¯åŠ è½½æ€§å’Œè„šæœ¬å…¥å�£è§„èŒƒã€‚

**è§£å†³æ–¹å¼�ï¼š**
å°†é…�ç½®åˆ†æµ�åˆ° `configs/demo/hybrid_demo/`ã€�`configs/ranking/<phase>/`ã€�`configs/recall/<phase>/`ï¼›å°†æ–‡æ¡£åˆ†æµ�åˆ° `dic/architecture/`ã€�`dic/decisions/`ã€�`dic/phases/`ã€�`dic/experiments/`ã€�`dic/guides/`ã€�`dic/standards/`ã€�`dic/archive/`ï¼›å°†è¾“å‡ºäº§ç‰©åˆ†æµ�åˆ° `outputs/agent/`ã€�`outputs/hybrid_demo/`ã€�`outputs/ranking/`ã€�`outputs/recall/`ã€�`outputs/simulation/`ã€�`outputs/training/`ã€�`outputs/verification/`ã€�`outputs/archive/root_files/`ã€‚å�Œæ—¶è¡¥å…… `DOCUMENT_ROUTING_GUIDE`ã€�`CONFIG_GUIDE`ã€�`OUTPUTS_ROUTING_GUIDE` å’Œå·¥ç¨‹è§„èŒƒä¸­çš„ä¸€æ¬¡æ€§å®žéªŒæ¸…ç�†è§„åˆ™ï¼Œå¹¶æŠŠ contract è„šæœ¬æ”¹ä¸ºæŒ‰å½“å‰� `configs/**/*.yaml` å·¥ä½œæ ‘é€’å½’æ ¡éªŒã€‚

**éªŒè¯�ç»“æžœï¼š**
`configs/` æ ¹ç›®å½•å·²æ—  `.yaml`ï¼Œæ—  `_tmp*.yaml`ï¼›`outputs/` é¡¶å±‚å�ªä¿�ç•™ `.gitkeep` å’Œ 8 ä¸ªè�Œè´£ç›®å½•ï¼›`dic/` æ ¹ç›®å½•å�ªä¿�ç•™ 4 ä¸ªå…¥å�£/é«˜é¢‘ç»´æŠ¤æ–‡æ¡£ã€‚æ—§è·¯å¾„æ‰«æ��å¯¹ `outputs/phase_*`ã€�`outputs/hybrid_demo_small*`ã€�`configs/hybrid_demo*.yaml`ã€�`configs/phase_*.yaml` æ— å‘½ä¸­ï¼›`./.venv/Scripts/python.exe scripts/ci/validate_engineering_contracts.py` é€šè¿‡ï¼Œè¾“å‡º `Engineering contracts passed: 110 configs, 49 scripts`ï¼›`./.venv/Scripts/python.exe -m pytest tests/test_engineering_contracts.py tests/test_graph_walk_training.py -q` é€šè¿‡ `7 passed`ã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™è½®å�¯ä»¥è®²æˆ�â€œæŠŠå®žéªŒåž‹é¡¹ç›®ä»Žæ–‡ä»¶å †ç§¯æ²»ç�†æˆ�å�¯å¤�ç›˜å·¥ç¨‹èµ„äº§â€�ï¼šä¸�æ˜¯å�ªç§»åŠ¨æ–‡ä»¶ï¼Œè€Œæ˜¯å�Œæ­¥å»ºç«‹æ–‡æ¡£è·¯ç”±ã€�é…�ç½® contractã€�äº§ç‰©è·¯ç”±å’Œä¸€æ¬¡æ€§å®žéªŒæ¸…ç�†è§„åˆ™ï¼Œå¹¶ç”¨æ‰«æ��å’Œ contract éªŒè¯�é˜²æ­¢è·¯å¾„è¿�ç§»å�Žå¼•ç”¨æ–­è£‚ã€‚


## 2026-05-15 - 工程规范 v1.2：测试分层 marker contract

**任务：**
把测试分层从约定升级为可执行 contract：所有 `tests/test_*.py` 必须声明文件级 `pytestmark`，普通 CI 不再维护手工测试白名单，而是按 unit/smoke marker 自动选择快速门禁测试。

**遇到的问题：**
测试文件数量增加后，缺少统一 marker 会导致慢实验、GPU 训练或重依赖测试混入普通 CI；原 CI 手工列测试文件也容易遗漏新增的 Agent、serving 或 recsys 基础测试。目录重整后，`tests/test_serving_smoke.py` 还残留对旧 demo 配置和真实本地数据产物的依赖，放入 smoke gate 后暴露出路径与数据依赖问题。

**定位方式：**
先用 `scripts/ci/validate_engineering_contracts.py` 让未标记测试显式失败，再为 32 个测试文件补齐 unit/smoke/experiment 等文件级 marker；随后用 `scripts/ci/select_tests_by_marker.py --marker unit --marker smoke` 验证 selector 不导入测试模块即可选出快速门禁集合，并通过 collect/run 暴露 serving smoke 对旧真实数据目录的依赖。

**解决方式：**
在 `rs_core/common/engineering_contracts.py` 中新增基于 AST 的 marker 解析、未标记测试检查和 selector 复用逻辑；新增 `scripts/ci/select_tests_by_marker.py`；CI 改为先选择 unit/smoke 文件，再执行 collect 和 pytest；同时把 serving smoke 中依赖真实 demo 数据的用例改为复用临时 fixture，保证普通门禁只验证服务 contract，不依赖本机历史产物。

**验证结果：**
`./.venv/Scripts/python.exe scripts/ci/validate_engineering_contracts.py` 通过，输出 `Engineering contracts passed: 110 configs, 50 scripts, 32 tests`；selector + collect 选中并收集 139 个 unit/smoke 测试；`./.venv/Scripts/python.exe -m pytest -m "unit or smoke" -q` 通过 `139 passed`；`./.venv/Scripts/python.exe -m ruff check rs_core scripts/ci/validate_engineering_contracts.py scripts/ci/select_tests_by_marker.py tests` 通过；独立 verifier 结论为 PASS。

**面试可讲点：**
这轮可以讲成“把测试治理从人工白名单升级成自描述分层 contract”：测试文件自己声明层级，CI 自动选择稳定快速门禁，实验/GPU/慢测试不会污染普通提交，同时通过 smoke fixture 化消除了对本地历史数据产物的隐式依赖。


## 2026-05-15 - 工程规范 v1.3：组合 marker 与 serving 专项门禁

**任务：**
在 v1.2 测试分层契约基础上继续细化 marker 矩阵：让服务接口测试、慢实验、GPU 实验可以通过组合 marker 独立选择，同时保留默认 `unit or smoke` 快速门禁。

**遇到的问题：**
单一 marker 只能说明测试大类，无法表达“这是 smoke 也是 serving”“这是 experiment 也是 slow/GPU”这类运行边界。随着测试数量增加，如果不把服务、慢实验和 GPU 训练路径显式组合标记，后续 CI 很容易把重实验混入普通 PR，或者无法单独验证服务 contract。

**定位方式：**
先审计 `pyproject.toml`、`.github/workflows/ci.yml` 和 32 个 `tests/test_*.py` 文件，确认现有 marker 定义齐全但实际落标还集中在 unit/smoke/experiment。再按测试职责区分服务路径、慢实验路径和 GPU/训练路径，并用 selector 分别验证 `unit/smoke` 与 `serving` 能否独立选中目标文件。

**解决方式：**
为 `tests/test_serving_smoke.py` 和 `tests/test_simulation_runner.py` 标记 `serving + smoke`，为 `tests/test_agent_runtime.py` 标记 `unit + serving`，为 `tests/test_two_tower_training.py` 标记 `experiment + gpu`，为多个重实验测试标记 `experiment + slow`；同时更新 `dic/standards/ENGINEERING_STANDARDS.md` 的组合 marker 规则，并在 `.github/workflows/ci.yml` 中新增 serving 专项 select/collect/run，默认 CI 仍不新增 GPU/slow/experiment job。

**验证结果：**
独立 verifier 只读核验通过：32 个测试文件均有文件级 `pytestmark`；`serving` selector 选出 3 个服务相关文件；默认 `unit/smoke` selector 选出 19 个文件且未包含 slow/gpu experiment；`./.venv/Scripts/python.exe scripts/ci/validate_engineering_contracts.py` 输出 `Engineering contracts passed: 110 configs, 50 scripts, 32 tests`；ruff 通过；`pytest -m "unit or smoke"` 通过 `139 passed`；`pytest -m "serving"` 通过 `34 passed`。

**面试可讲点：**
这轮可以讲成“测试矩阵治理”：不是简单给测试贴标签，而是把测试运行成本、依赖边界和 CI 入口显式建模。默认 PR 只跑快而稳定的门禁，服务 contract 可单独验证，慢实验和 GPU 训练不会无意进入普通 CI。


## 2026-05-15 - 工程规范 v1.4：scripts 瘦身最小切片

**任务：**
在工程规范 v1.x 的基础上推进 scripts 瘦身：选择一个低风险、已有测试覆盖的脚本逻辑，把稳定可复用能力下沉到 `rs_core`，让 `scripts/` 更接近“参数解析 + 流程触发”的入口层。

**遇到的问题：**
项目里不少脚本已经承载了实验流程和可复用业务逻辑。如果一次性大规模迁移，容易影响历史实验口径；但完全不迁移，又会让通用推荐逻辑散落在脚本中，后续复用和测试都变困难。

**定位方式：**
先做只读审计，优先寻找纯函数、小范围、已有测试覆盖的候选逻辑。最终选择 `scripts/data/build_recall_views.py` 中的 `unique_recent_items()`：它是 ItemCF 边构造前的最近序列去重逻辑，属于稳定推荐基础能力，且 `rs_core/recsys/candidate_merge.py` 已经集中承载候选合并与召回相关逻辑。

**解决方式：**
将 `unique_recent_items()` 下沉到 `rs_core/recsys/candidate_merge.py`，保留原有 reverse traversal、去重和 `appendleft` 的顺序语义；`scripts/data/build_recall_views.py` 改为 import 并复用该函数；同时在 `tests/test_build_recall_views.py` 新增 ItemCF 边构造用例，覆盖包含重复最近行为序列时的 pair 生成，防止迁移后语义漂移。

**验证结果：**
执行员定向验证 `./.venv/Scripts/python.exe -m pytest tests/test_build_recall_views.py tests/test_recsys_core.py -q` 通过 `6 passed`，engineering contracts 通过，ruff changed scope 通过。独立 verifier 只读核验确认：`unique_recent_items()` 仅在 `rs_core/recsys/candidate_merge.py` 定义，脚本只 import/reuse；新增测试覆盖最近去重后的 ItemCF pair；额外执行 `tests/test_build_recall_views.py tests/test_engineering_contracts.py` 通过 `12 passed`，ruff 通过，无本轮临时文件残留。

**面试可讲点：**
这轮可以讲成“脚本入口层治理的渐进式重构”：不是一口气重写实验脚本，而是用测试保护的小切片，把稳定业务能力从脚本下沉到核心包，降低复用成本，同时用定向测试和独立验证证明实验行为没有改变。


## 2026-05-15 - 工程规范 v1.5：scripts ruff 全量未使用项清理

**任务：**
在 v1.4 scripts 瘦身之后，继续把 `scripts/` 纳入更完整的 ruff 检查范围，清理历史脚本中暴露的 F401/F841 未使用导入和未使用变量。

**遇到的问题：**
提交前审计时，当前工程规范范围内的 ruff 已通过，但扩大到 `ruff check scripts` 后暴露出多个历史脚本的未使用 import / 变量。这些问题不会改变实验结果，但会阻碍后续把 scripts 纳入统一 lint 门禁。

**定位方式：**
用 `./.venv/Scripts/python.exe -m ruff check scripts` 复核失败清单，确认 19 个命中全部为 F401/F841，集中在少数脚本：`phase_1_20_recall_diagnostics.py`、`run_phase_1_26_real_learned_gbdt_ranker.py`、`run_phase_1_29_terminal_ranking_route.py`、`run_phase_c_ranking_actionability.py`、`run_phase_c_ranking_actionability_diagnostic.py`、`validate_recall_registry.py`、`verify_recall_outputs.py`。

**解决方式：**
只做最小安全清理：删除未使用 import，精简未使用 re-export import，移除未使用局部变量 `baseline_frozen`；不改业务流程、不改实验口径、不做脚本结构重构。

**验证结果：**
独立 verifier 确认 `./.venv/Scripts/python.exe -m ruff check scripts` 输出 `All checks passed!`；`./.venv/Scripts/python.exe scripts/ci/validate_engineering_contracts.py` 输出 `Engineering contracts passed: 110 configs, 50 scripts, 32 tests`；diff 中 scripts 改动均为 unused import / unused variable 清理；未发现本轮临时文件残留。

**面试可讲点：**
这轮可以讲成“扩大工程门禁覆盖面前的历史债务清理”：先用 lint 暴露低风险、可机械修复的问题，再严格限制改动类型，只清理不会影响业务行为的未使用项，为后续把 `scripts/` 全量纳入 CI lint 打基础。

### 2026-05-16 - 代表性轻量 E2E 预检收口

**任务：**
在 `outputs/recall/full_main_route_other_methods/lightweight_representative_e2e` 的代表性 full-lightweight E2E 通过后，整理方法预检结果并把结论同步到实验日志和工程叙事日志。

**遇到的问题：**
这轮只有 Popular / Category / Semantic 的轻量候选生成真正跑通，ItemCF/co-visit、UserCF、Swing、graph_walk、two_tower、MF、sequence 等方法都不能被写成已执行结果，否则会把清单里的 disabled / deferred 状态误写成 promotion。

**定位方式：**
依据代表性 E2E 的 manifest/source audit 结果核对输出目录：`500` users、`75,866` candidate rows、`0` empty users，enabled sources 仅 `popular` / `category` / `semantic`，disabled sources 明确包含 `ItemCF`、`graph`、`two_tower`、`UserCF`、`Swing`、`MF`、`sequence`、`pool500`、`pool1000`，并且没有 `itemcf` / `graph` / `pool` 输出文件，也没有 10k source path。

**解决方式：**
只把已验证的 Popular / Category / Semantic 链路写成当前代表性结果；其余方法族统一按 `defer` / `document_only` / `fallback` 收口，保留为后续受控回跑或 sidecar 补齐项，不在本轮提升状态。

**验证结果：**
工程日志与实验日志都只记录同一份可回指证据：`outputs/recall/full_main_route_other_methods/lightweight_representative_e2e`。结论边界明确为“只确认轻量三源可用”，未把 ItemCF/co-visit、UserCF、Swing、graph_walk、two_tower、MF、sequence 伪装成已跑或已晋升。

**面试可讲点：**
这段可以讲成“用 manifest/source audit 给推荐实验划边界”：不是看见 E2E 成功就默认所有方法都能晋升，而是只按已验证产物收口，确保工程日志和方法日志对同一批证据保持一致。

### 2026-05-16 - Full-safe 召回方法全家桶 Phase 0-6 收口

**任务：**
按 Team+Ralph 的连续推进要求，把召回方法全家桶从 Phase 0 合同预检推进到 Phase 6 final method matrix，补齐 ItemCF/co-visit、UserCF、Swing/session、graph/MF、two_tower/pool readiness 的受控证据，并同步 PRD、进度与召回实验日志。

**遇到的问题：**
Phase 0 一开始发现 graph/two_tower/ranking pool200 配置仍引用 10k 路径；后续 Phase 6 首次汇总又因为 Phase 0 的 holdout contract 写在嵌套字段中，被 final matrix 误判为未证明 holdout exclusion。若直接跳过这些问题，会把 scope drift 或审计格式差异带入总验收。

**定位方式：**
通过 Phase 0 manifest/source audit 定位 10k config 引用；通过 Phase 4/5 的契约测试补充 config payload 内部 10k 引用检测；通过 Phase 6 失败输出定位到 `holdout_contract.candidate_generation_uses_holdout=false` 与后续阶段 top-level `candidate_generation_uses_holdout=false` 的字段格式差异。

**解决方式：**
为 graph、two_tower、ranking pool200 创建 full-safe 配置副本并让 Phase 0 默认解析这些副本；Phase 3 使用 bounded Swing/session observation，不做无界 pair counter；Phase 4/5 只做合同/feasibility gate，不训练、不晋升、不替代 frozen pool200；Phase 6 增加兼容 Phase 0 嵌套 holdout contract 的读取逻辑，并输出 `final_method_matrix_pass` 作为最终成功产物。

**验证结果：**
最终 canonical Phase 0 manifest 为 `PASS`；Phase 1 为 `EXECUTED_PASS_OBSERVATION_ONLY` 且 `recall_at_pool_delta=0.0`、`source_marginal_hit=0`；Phase 2 为 `rejected` 且 `failure_reason=no_positive_observation_lift`；Phase 3 为 `EXECUTED_PASS_OBSERVATION_ONLY`；Phase 4 为 `EXECUTED_PASS_CONTRACT_ONLY`；Phase 5 为 `EXECUTED_PASS_FEASIBILITY_ONLY`；Phase 6 `outputs/recall/full_main_route_other_methods/final_method_matrix_pass/manifest.json` 为 `PASS`，`final_method_matrix.json` 汇总 6 个 phase、`failures=[]`、`candidate_generation_uses_holdout=false`。

**面试可讲点：**
这段可以讲成“召回方法扩展不是盲目堆方法，而是先建立可审计合同”：用 source audit 防数据泄漏，用 bounded observation 控资源，用 final matrix 把每个方法族的晋升/拒绝/延期原因结构化，最后得出“本轮无新增方法晋升，但工程上获得可复跑、可解释、可继续扩展的召回方法矩阵”。

### 2026-05-17 - Representative pool500 recall-only 试验与 Gate 收口

**任务：**
在前一轮 pool500 只做到 readiness 的基础上，按“先 representative pool500、再决定 full”的路线补齐真实 recall-only 试验、same-scope 对比、审计和 Promote/Stop Gate。

**遇到的问题：**
此前 `pool500/pool1000=READINESS_ONLY_NOT_RANKING_INPUT` 只证明没有替代 ranking pool200，并没有回答 pool500 是否真的比 pool200 多召回用户；如果直接 full 或直接接 ranking，会把扩池实验和排序主线混在一起。

**定位方式：**
固定 500 个 representative users，分别生成同 scope 的 pool200 与 pool500 recall-only 候选，并在同一 `users_with_holdout=82` 分母下比较：pool200 `candidate_hit_users=4`、`recall_at_pool=0.042683`；pool500 `candidate_hit_users=6`、`recall_at_pool=0.055459`。

**解决方式：**
新增独立 P0-P6 pool500 representative 分支：P0-P2 生成同 scope pool200/pool500 候选；P3-P4 产出 `pool500_vs_pool200_same_scope_comparison.json`、`leakage_audit.json`、`resource_audit.json`、`ranking_isolation_audit.json`；P5 只做方法贡献观察；P6 生成 `promote_stop_gate.json`。全过程不进入 ranking、不生成 pool1000、不训练 graph/MF/two_tower、不复制 full clean。

**验证结果：**
`promote_stop_gate.json` 为 `PASS`，`exclusive_hit_users_201_500=2`，新增来源为 `category=1`、`popular=1`，`recall_at_pool_delta=0.012776`；duplicate、empty、fallback 均未恶化；leakage/resource/ranking isolation audits 均为 `PASS`。`tests/test_pool500_representative.py` 为 `5 passed`，相关脚本与测试 ruff 为 `All checks passed`，独立 verifier 给出 `APPROVED` 且 0 blockers。

**面试可讲点：**
这段可以讲成“把扩池从拍脑袋变成可审计 Gate”：不是直接把 pool500 切成默认样本，而是用同用户、同分母、同召回合同对比 pool200 和 pool500，证明 201-500 区间确实带来 2 个 exclusive hit users，再用 leakage/resource/ranking isolation 三重审计保证没有数据泄漏、资源越界或排序主线污染。

### 2026-05-17 - Representative pool500 全方法轻量与 CF 观察

**任务：**
在已 PASS 的 custom index 上补齐 pool500 all-methods representative 的轻量方法、bounded ItemCF/co-visit 与 bounded UserCF 观察，输出 recall-only 方法指标和审计证据。

**遇到的问题：**
轻量 pool500 候选已经存在，但 CF 不能复用全局无界共现或 dense all-user matrix；同时 candidate generation 不能读取 valid/test/holdout，也不能触碰 10k baseline、pool1000、ranking 或 graph/MF/two_tower 训练。

**定位方式：**
核验 `custom_index/manifest.json` 为 `PASS`，D 盘剩余约 204GiB，大于 50GiB 阈值；读取既有 pool500 candidates 与 indexed train sequences 的 schema，确认可以只基于 500 个 representative users 和 10739 个 custom items 构造局部 CF 证据。

**解决方式：**
新增 `scripts/experiments/recall/run_pool500_all_methods_lightweight_cf.py`，复用已有 pool500 lightweight candidates 表示 popular/category/semantic；ItemCF/co-visit 只在 custom-index representative train sequences 上构建局部 item-item 共现邻居；UserCF 只构建 item->users 倒排并按 capped similar users 取候选，显式不生成 dense user-user matrix。

**验证结果：**
脚本运行产物 `outputs/recall/pool500_all_methods_representative/lightweight_cf_methods/manifest.json` 为 `PASS`；`method_metrics.json` 显示 lightweight `recall_at_pool=0.055459`、merged `recall_at_pool=0.055459`；`resource_audit.json` 记录 lightweight 193824 行、ItemCF 335 行、UserCF 14 行、merged 194149 行；`source_audit.json` 证明 candidate generation 只读 pool500 candidates、indexed train sequences、custom item index，valid/test 仅 evaluation-only。ruff 与 `py_compile` 均通过，独立约束核验输出 `candidate_reads_ok=true`、`artifacts_ok=true`。

**面试可讲点：**
这段可以讲成“在扩池 Gate 后继续做方法族消融，但不牺牲边界”：轻量方法提供 pool500 主体收益，CF 方法在代表性小样本上以 bounded observation 方式补充证据；即使本轮 CF 没带来 recall lift，也沉淀了可审计、可复跑、可扩展到 full pool500 前的资源与泄漏控制模板。

### 2026-05-17 - Representative pool500 全方法 custom-index Gate 收口

**任务：**
在 representative pool500 已经 Gate PASS 的基础上，按用户要求补齐主路全方法族试验：轻量源、bounded CF、Swing/session，以及 graph/MF/two_tower 的 custom-index feasibility/proxy probe，并用统一 Final Gate 决定是否允许继续 full pool500 recall-only。

**遇到的问题：**
直接跑 full pool500 或重模型训练会带来资源与范围风险；但只写 deferred 又无法回答“所有召回方法是否都试过”。需要在不复制 full clean、不读 holdout 做候选生成、不污染 ranking pool200 的前提下，为重方法构造可验证的定制索引试验边界。

**定位方式：**
先构建 `outputs/recall/pool500_all_methods_representative/custom_index/`，固定 500 users、10739 items、1289 train events；再分别检查 `lightweight_cf_methods/`、`sequence_session_methods/`、`heavy_indexed_probes/` 与 `final_gate/` 的 manifest/source_audit/resource_audit，确认候选生成不读 valid/test/holdout、无 10k source、无 pool1000、无 ranking replacement。

**解决方式：**
采用“custom index + 方法族 observation/probe + Final Gate”的路线：lightweight 表示 popular/category/semantic；ItemCF/UserCF 限定在 custom-index train scope，禁止 full global counter 与 dense all-user matrix；Swing/session 只构建 bounded pair/transition observation；graph/MF/two_tower 只做 feasibility/proxy，不训练、不晋升。Final Gate 输出 `decision=CONTINUATION_ONLY`，把允许范围限制为后续 recall-only full pool500 continuation。

**验证结果：**
`final_gate/promote_stop_gate.json` 为 `PASS`，`full_pool500_continuation_allowed=true`，但 `ranking_input_replacement_allowed=false`、`heavy_model_training_allowed_by_this_gate=false`、`pool1000_allowed=false`。`final_method_matrix.json` 覆盖 popular/category/semantic、bounded ItemCF/UserCF、Swing/session-transition、graph/MF/two_tower probes。`tests/test_pool500_all_methods_representative.py` 为 `5 passed in 0.09s`；相关 all-method scripts/tests ruff 为 `All checks passed`；独立 verifier `APPROVED` 且 0 blockers。

**面试可讲点：**
这段可以讲成“把全方法召回试验拆成安全可审计的分层 Gate”：轻量方法验证真实召回增量，CF/序列方法补充 bounded observation，重模型先做 custom-index feasibility 而不是盲目训练；最终用 source/resource/ranking isolation 三重审计把继续 full pool500 的权限限制在 recall-only，体现实验治理和工程边界控制。


## 2026-05-17 pool500 v5 artifact gate æ²»ç�†æŽ¥å…¥

- ä»»åŠ¡ï¼šå°† `pool500_recall_continuation_route` çš„ v5 artifact gate è¯­ä¹‰æŽ¥å…¥ current route registry å’Œå·¥ç¨‹å¥‘çº¦ã€‚
- é�‡åˆ°çš„é—®é¢˜ï¼šregistry éœ€è¦�è¡¨è¾¾ `FULL_POOL500_READY / DIAGNOSTIC_ONLY_PARTIAL / STOP` ä¸‰æ€�ï¼Œä½†ä¸�èƒ½è®© pool500 recall-only äº§ç‰©è¢«è¯¯ç”¨ä¸º ranking inputï¼›å�Œæ—¶è½»é‡� YAML loader ä¼šæŠŠå¼•å�·å†… `#symbol` æˆªæ–­æˆ�æ³¨é‡Šã€‚
- å®šä½�æ–¹å¼�ï¼šè¿�è¡Œ `tests/test_engineering_contracts.py` é€šè¿‡å�Žï¼Œå†�è¿�è¡Œ `scripts/ci/validate_engineering_contracts.py` å�‘çŽ° `artifact_gate_workflow` è¢«æˆªæ–­å¯¼è‡´å¥‘çº¦å¤±è´¥ã€‚
- è§£å†³æ–¹å¼�ï¼šåœ¨ registry ä¸­ç™»è®° v5 schemaã€�workflowã€�allowed decisions å’Œç¦�æ­¢å€™é€‰ç”Ÿæˆ�/æŽ’åº�æ›¿æ�¢çš„æ˜¾å¼�å­—æ®µï¼›åœ¨ `engineering_contracts.py` å¢žåŠ  pool500 continuation ä¸“é¡¹æ ¡éªŒï¼›ä¿®å¤� lightweight config loader ä»…åœ¨å¼•å�·å¤–è¯†åˆ« `#` æ³¨é‡Šã€‚
- éªŒè¯�ç»“æžœï¼š`python -m pytest tests/test_engineering_contracts.py` é€šè¿‡ 17 é¡¹ï¼›`python scripts/ci/validate_engineering_contracts.py --root ...` é€šè¿‡ 115 configsã€�67 scriptsã€�46 testsã€�1 registryã€�1 allowlistã€‚
- é�¢è¯•å�¯è®²ç‚¹ï¼šç”¨ registry + contract test æŠŠâ€œå�¬å›žäº§ç‰© readyâ€�å’Œâ€œæŽ’åº�è¾“å…¥å�¯æ›¿æ�¢â€�è§£è€¦ï¼Œé�¿å…�ç¦»çº¿å®žéªŒäº§ç‰©æ™‹å�‡æ—¶å�‘ç”Ÿè·¨é“¾è·¯è¯­ä¹‰æ±¡æŸ“ã€‚


### 2026-05-18 - pool500 sidecar 资源受控恢复与诊断接入

**任务：**
在前一次 full-train/UserCF 进程造成内存压力后，恢复 pool500 recall-only 所需的 ItemCF、UserCF、Swing sidecar，并用受控资源策略重新接入 20 用户诊断 batch。

**遇到的问题：**
UserCF 原实现会把全量 user_items、item_users 和 candidates_by_user 常驻内存，直接全量跑存在把本机内存打满的风险；ItemCF 全量脚本同样会保留全量 sequences/pair_count。另一个问题是诊断 sidecar 不能被误标为 `FULL_OUTPUT_READY`，否则可能被 route gate 当成完整可晋升来源。

**定位方式：**
先用 `.omc/tools/run_guarded_process.py` 加 `psutil` 监控 RSS/空闲内存；UserCF target20 构建日志显示峰值 RSS 约 185MB，ItemCF target500 weak/strong 峰值 RSS 约 38MB/37MB。再读取 `readiness_contract.json`、`resource_audit.json`、`per_source_readiness_contracts.json` 和 `merged_pool500_manifest.json`，确认诊断产物状态和最终 source coverage。

**解决方式：**
为 UserCF 和 ItemCF builder 增加 `target_user_limit` 诊断模式：UserCF 只为目标用户及共享目标 item 的邻居用户构造候选；ItemCF 先用 target20 发现候选被 seen-items 过滤，再扩大为 target500 source-positive 用户构建诊断 item-item 边。诊断产物统一标记 `status=DIAGNOSTIC_ONLY`、`diagnostic_output_status=DIAGNOSTIC_OUTPUT_READY`、`full_output_status=DIAGNOSTIC_OUTPUT_READY`，并修正 recall-only runner 对 artifact readiness 的继承和 marker isolation 摘要输出，避免诊断路径污染最终 bundle。

**验证结果：**
`tests/test_full_train_itemcf_sidecars.py`、`tests/test_full_train_usercf_sidecar.py`、`tests/test_full_data_pool500_recall_only.py`、`tests/test_full_data_pool500_route_gate.py` 共 65 项通过。受控 sidecar 构建成功：UserCF target20 输出 14 users/932 candidates；ItemCF target500 weak 输出 6098 edges，strong 输出 5636 edges；Swing v2 保持可用。复跑 `recall_only_target20_with_sidecars` 后仍为预期 `decision=STOP`，但 marker isolation 已 PASS，source coverage 包含 `itemcf_weak=23`、`itemcf_strong=4`、`usercf_recall=932`、`swing_recall=165`，且 `ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。

**面试可讲点：**
这段可以讲成“资源事故后的工程化恢复”：不是简单禁止全量任务，而是加 guard、限流、诊断 readiness 语义和 route gate 防误晋升，既恢复了 pool500 多召回源接入能力，又把内存、数据泄漏、ranking 替换和 artifact 晋升边界都显式写入可验证合同。

### 2026-05-18 - pool500 target100 受控诊断扩大

**任务：**
在 target20 诊断链路恢复后，将 pool500 recall-only 扩大到 100 用户诊断 batch，验证多召回源接入、资源 guard 和 route gate 边界在更大样本下是否稳定。

**遇到的问题：**
UserCF target20 只能覆盖很小的诊断范围，不能判断扩大 batch 后的候选贡献走势；同时 ItemCF/UserCF 仍是 `DIAGNOSTIC_ONLY`，如果扩大时误把它们当成 READY，会触发错误晋升风险。

**定位方式：**
先用 `.omc/tools/run_guarded_process.py` 构建 UserCF target100 sidecar，并检查 `.omc/logs/usercf_recall_target100_guarded.log`；再用同样 guard 运行 `recall_only_target100_with_sidecars`，审计 `manifest.json`、`merged_pool500_manifest.json`、`per_source_readiness_contracts.json` 和 `readiness_result.json`。

**解决方式：**
保持 ItemCF target500 与 Swing v2 sidecar 不变，新增 UserCF target100 诊断 sidecar，并在 recall-only runner 中通过 `--source-manifest` 显式覆盖 ItemCF/Swing/UserCF artifact。所有诊断来源继续保留 `status=DIAGNOSTIC_ONLY`，不替换 ranking input，不启用 pool1000。

**验证结果：**
UserCF target100 构建成功，输出 `candidate_user_count=64`、`candidate_total_count=4403`，guard 峰值 RSS 约 929MB。100 用户 batch 输出 `processed_users=100`、`candidate_rows=22146`、`underfilled_user_count=100`，source coverage 为 `category=5850`、`popular=16412`、`usercf_recall=4016`、`swing_recall=738`、`itemcf_weak=62`、`itemcf_strong=43`。最终仍为预期 `decision=STOP`，`marker_isolation_audit=PASS`，`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。focused tests 仍为 65 项通过。

**面试可讲点：**
这段可以讲成“从小样本 smoke 到受控扩大诊断”的工程推进：不是盲目跑全量，而是在资源 guard、诊断 readiness、source coverage 和 route gate 共同约束下逐步放大样本，证明链路稳定性的同时保留明确的不可晋升边界。

### 2026-05-18 - pool500 target500 受控诊断扩大

**任务：**
在 target100 诊断 batch 稳定后，继续把 pool500 recall-only 扩大到 500 用户，验证 UserCF 诊断 sidecar、ItemCF target500 sidecar 与 Swing v2 在更大样本下的资源占用和 source coverage。

**遇到的问题：**
UserCF target500 会显著扩大共享 item 邻居集合，内存增长快于 target 用户数；同时 ItemCF/UserCF 仍然不是 full-ready artifact，扩大样本只能用于诊断稳定性，不能作为 ranking input 晋升依据。

**定位方式：**
用 `.omc/tools/run_guarded_process.py` 运行 UserCF target500 构建并读取 `.omc/logs/usercf_recall_target500_guarded.log`，再运行 `recall_only_target500_with_sidecars` 并审计 `manifest.json`、`per_source_readiness_contracts.json`、`readiness_result.json`、`merged_pool500_manifest.json`。

**解决方式：**
继续采用单进程、8GB free memory、4GB RSS guard；新增 `usercf_recall_target500_guarded`，复用 `itemcf_weak_target500_guarded`、`itemcf_strong_target500_guarded` 和 `swing_recall_v2`，通过 `--source-manifest` 显式接入 500 用户 recall-only 诊断 batch。

**验证结果：**
UserCF target500 构建成功，`candidate_user_count=327`、`candidate_total_count=24056`，峰值 RSS 约 2394MB。500 用户 batch 输出 `processed_users=500`、`candidate_rows=111983`、`underfilled_user_count=500`，source coverage 为 `popular=81289`、`category=30193`、`usercf_recall=21251`、`swing_recall=3668`、`itemcf_weak=345`、`itemcf_strong=330`。最终仍为预期 `decision=STOP`，`marker_isolation_audit=PASS`，`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。focused tests 65 项通过。

**面试可讲点：**
这段可以讲成“资源受控的召回链路渐进放量”：从 20、100 到 500 用户逐级扩大，用峰值内存、source coverage、underfill 和 gate 决策共同判断稳定性，同时严格区分诊断可用和可晋升可用。

### 2026-05-18 - pool500 召回方法目录与 registry 治理

**任务：**
将 pool500 召回链路从零散实验产物整理为按方法维护的文档结构，并建立统一 registry，便于后续按 UserCF、ItemCF、Swing、semantic、two_tower 等 source 独立推进和记录。

**遇到的问题：**
此前关键信息分散在总工程日志、runner manifest 和不同输出目录中；当方法状态同时包含 READY、DIAGNOSTIC_ONLY、DEFERRED 时，容易混淆“诊断可跑”和“可正式晋升”。用户也提出希望每种方法在文件夹中维护同一个文档，方便执行和记录关键信息。

**定位方式：**
读取 `recall_only_target500_with_sidecars/manifest.json` 和 `per_source_readiness_contracts.json`，以 target500 最新证据确定各 source 状态、row_count、artifact 路径和不可晋升边界。

**解决方式：**
新增 `dic/recall_methods/<source>/METHOD.md`，为 10 个召回 source 和 `user_quality` 分层策略分别记录方法定位、readiness、适用用户、输入输出 artifact、资源画像、当前问题和下一步；同时新增 `configs/recall/pool500_method_registry.json`，集中维护 source 状态、文档路径、最新 artifact、eligible user policy 和安全策略。

**验证结果：**
已生成 11 个 `METHOD.md` 文件和 `pool500_method_registry.json`。使用项目 `.venv` 解析 registry 并校验所有 `method_doc`、`latest_artifact`、`latest_readiness_contract` 路径，结果 `source_count=10`、`missing=[]`。registry 明确保留 `decision=STOP`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`，并把 `user_quality` 标记为 `PLANNED` 调度策略而非召回 source。

**面试可讲点：**
这段可以讲成“召回实验治理和可执行知识库建设”：把多方法、多 artifact、多 readiness 状态沉淀成 per-method 文档和机器可读 registry，既方便后续按方法推进，也降低诊断产物被误晋升为生产输入的风险。

### 2026-05-18 - rs_lab 实验层与 rs_core 召回 source 薄接口治理

**任务：**
在每种 pool500 召回方法已有 `dic/recall_methods` 文档后，补齐实验层和 core 层的代码组织边界：成熟前先放在 `rs_lab` 实验治理框架中，`rs_core` 只建立稳定 source metadata 薄接口。

**遇到的问题：**
UserCF / ItemCF 仍是 `DIAGNOSTIC_ONLY`，semantic / co_visit / two_tower 仍是 `DEFERRED`，如果直接把实验 builder 或未成熟实现迁入 `rs_core`，会造成“有 core 程序就代表可正式晋升”的误解。当前仓库已有 `rs_lab` 实验脚本目录，但缺少明确治理文档；`rs_core` 也缺少按 source 暴露 readiness 和 artifact 边界的稳定 registry。

**定位方式：**
检查当前工作区目录后确认已有 `rs_lab/experiments/recall` 和 `rs_lab/experiments/ranking`，因此复用 `rs_lab` 而不是另建重复的 `rslab`。同时以 `configs/recall/pool500_method_registry.json` 为 source 状态事实源，对齐 READY、DIAGNOSTIC_ONLY、DEFERRED 三类状态和 target500 最新 artifact。

**解决方式：**
新增 `rs_lab/README.md`、`rs_lab/GOVERNANCE.md`、`rs_lab/experiments/recall/pool500/README.md`、`governance/README.md` 和 `user_quality/README.md`，明确实验晋升、资源 guard、ranking input 替换和 pool1000 的禁止边界。新增 `rs_core/recsys/recall_sources/base.py`、`registry.py`、`__init__.py`，只保存 `RecallSourceSpec` 与 source readiness 元数据，不迁移 UserCF / ItemCF / semantic 等实验构建逻辑。

**验证结果：**
新增 `tests/test_recall_source_registry.py`，校验 core registry 与 JSON registry source 名称一致、`user_quality` 不作为 candidate source、READY / DIAGNOSTIC_ONLY / DEFERRED 状态正确，并验证非 READY source 不能替代 ranking input。使用项目 `.venv` 运行 focused tests：`test_recall_source_registry.py`、`test_full_train_itemcf_sidecars.py`、`test_full_train_usercf_sidecar.py`、`test_full_data_pool500_recall_only.py`、`test_full_data_pool500_route_gate.py`，结果 70 项全部通过。

**面试可讲点：**
这段可以讲成“实验代码到核心框架的分层治理”：没有为了目录完整而把未成熟召回算法硬塞进 core，而是先建立实验层治理和 core 薄接口，让 readiness、artifact、资源和晋升边界可测试、可审计、可逐步演进。

### 2026-05-18 - pool500 READY 三源 stoploss 诊断落地

**任务：**
把已通过共识规划的“READY 三源加厚必须有止损”落成首轮可执行诊断，不直接跑 full-data、不晋升 DIAGNOSTIC_ONLY source，也不改变 ranking input 替换和 pool1000 gate。

**遇到的问题：**
当前 target500 虽然召回链路跑通，但 `underfilled_user_count=500`，说明 `category`、`popular`、`swing_recall` 三个 READY source 可能存在结构性覆盖上限。如果继续只调三源预算而没有诊断指标，容易在低收益方向上反复试验，也无法公平判断何时启动 UserCF、ItemCF 或 semantic title/category 的晋升诊断。

**定位方式：**
定位到 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 的 manifest 生成链路：主循环已拥有 `rows`、`source_rows`、`users`、`underfilled_user_count`、`source_coverage`，适合最小侵入地输出独立 audit artifact；测试扩展点在 `tests/test_full_data_pool500_recall_only.py`。

**解决方式：**
新增 `READY_STOPLOSS_SOURCES=("category", "popular", "swing_recall")` 和 `_ready_source_stoploss_audit()`，输出 `ready_source_stoploss_audit.json`，记录 READY 三源的 row_count、unique_item_count、user coverage、underfilled user coverage、marginal candidate share、ready-only capacity ratio 和 stoploss trigger reasons。manifest 顶层和 `required_artifacts` 引用该 audit，同时明确 `diagnostic_only_promotion_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。

**验证结果：**
扩展 `tests/test_full_data_pool500_recall_only.py`，断言 audit 文件存在、READY source 范围只包含 `category/popular/swing_recall`、安全边界不放行 diagnostic promotion/ranking replacement/pool1000，并覆盖 source 指标字段。使用项目 `.venv` 运行 focused suite：`test_full_data_pool500_recall_only.py`、`test_full_data_pool500_route_gate.py`、`test_recall_source_registry.py`，结果 57 项全部通过。

**面试可讲点：**
这段可以讲成“召回实验的止损机制设计”：不是盲目继续堆热门/类目召回，而是把 underfill、覆盖、边际贡献和安全边界沉淀成机器可读 audit，为后续是否并行启动重召回/语义召回晋升提供可验证证据。

### 2026-05-18 - UserCF guarded diagnostic 按 user_quality 分层落地

**任务：**
围绕 pool500 UserCF 做专项 guarded diagnostic：只从 `eligible_user_quality_manifest.json` 选取 `heavy_cf_eligible`，必要时才少量降级到 `medium_behavior`，同时保留 DIAGNOSTIC_ONLY、不替换 ranking input、不打开 pool1000。

**遇到的问题：**
现有 UserCF sidecar 虽然已有 train-only/no-holdout 基础，但默认逻辑仍可能在非 target-limit 情况下写 READY；更关键的是当前 target500 user_quality manifest 中 `heavy_cf_eligible=0`，如果 eligible 为空时退回全量用户矩阵，会违反重资源方法只服务高质量用户的边界。

**定位方式：**
读取 `dic/recall_methods/usercf_recall/METHOD.md`、`outputs/recall/pool500_user_quality/target500_train_only/eligible_user_quality_manifest.json`、`rs_lab/experiments/recall/build_full_train_usercf_sidecar.py` 和 `tests/test_full_train_usercf_sidecar.py`。用 `.venv` 统计 manifest：`profiles=500`、`heavy=0`、`medium=49`，确认主诊断应先输出 heavy-only 空结果，再用 medium20 做降级观测。

**解决方式：**
将 UserCF sidecar 升级为 `full_train_usercf_sidecar_v2` guarded diagnostic：新增 eligible manifest 过滤、`--include-medium-behavior` 显式开关、target batch checkpoint、resume 支持、RSS/free-memory samples、resource audit、readiness contract、source index manifest 和 `per_source_candidate_manifest.json`。同时修复 eligible 为空时误回退全量用户的风险，空 heavy 直接产出 `target_user_count=0` 的诊断 artifact；并在 `load_usercf_recall_sidecar()` 增加 runtime 硬校验，拒绝 `source_status != DIAGNOSTIC_ONLY`、candidate generation、ranking input replacement 或 pool1000 越权 manifest。

**验证结果：**
使用项目 `.venv` 运行 `tests/test_full_train_usercf_sidecar.py`、`tests/test_full_data_pool500_recall_only.py`、`tests/test_phase2_usercf_bounded_observation.py`，结果 22 项通过；对 `build_full_train_usercf_sidecar.py`、`candidate_merge.py` 和相关测试运行 ruff，结果通过。真实 artifact：heavy-only 输出 `target_user_count=0`、`indexed_user_count=0`、`candidate_total_count=0`、`peak_rss_mb=31`；medium20 降级诊断输出 `target_user_count=20`、`indexed_user_count=311896`、`candidate_user_count=20`、`candidate_total_count=2000`、`row_count=20`、`peak_rss_mb=552`、`underfilled_user_coverage=1.0`、`marginal_candidate_share=0.2`，readiness 仍为 `DIAGNOSTIC_ONLY` 且 `promotion_allowed=false`。

**面试可讲点：**
这段可以讲成“重资源召回的安全放量策略”：先用 user_quality 把 UserCF 从全量矩阵风险中隔离出来，再用 batch checkpoint、memory guard、resource audit 和 readiness contract 约束实验产物；即使 medium20 有候选覆盖，也因为 heavy 用户缺失和诊断边界，不把它包装成 pool500 final ready。

### 2026-05-18 - pool500 readiness gate 总控收口

**任务：**
汇总 pool500 召回各专项窗口产物，复用并重跑带 sidecar 的 target500 recall-only diagnostic，补齐 readiness gate / drift 测试和工程叙事，给出是否可宣称 final ready 的结论。

**遇到的问题：**
旧 `outputs/recall/pool500_sidecar_fix/recall_only_target500_with_sidecars/` manifest 已显示 `decision=STOP`、`underfilled_user_count=500`，但目录缺少 `ready_source_stoploss_audit.json`；同时 UserCF / ItemCF 已有 guarded diagnostic 产物，必须量化边际贡献但不能误晋升为 READY 或 ranking input replacement。

**定位方式：**
对齐 `configs/recall/pool500_method_registry.json`、`dic/recall_methods/*/METHOD.md`、`rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 和现有 target500 artifact。使用 `.venv` 读取新诊断输出：`candidate_row_count=111983`、`underfilled_user_count=500`、`underfilled_user_ratio=1.0`，READY 三源 `category/popular/swing_recall` 的 ready-only capacity ratio 仅 `0.4606`，stoploss 触发 `target_batch_underfilled`、`max_user_candidate_count_below_pool500`、`ready_source_capacity_below_pool500_budget`。

**解决方式：**
在 recall-only runner 中新增 `diagnostic_source_contribution.json`，记录 `usercf_recall`、`itemcf_weak`、`itemcf_strong` 的 row_count、user coverage、underfilled coverage、marginal_candidate_share 和 `promotion_allowed=false`；manifest 和 registry 的 `latest_diagnostic_batch` 指向新的 `outputs/recall/pool500_readiness_gate_diagnostic_500_with_sidecars/`，同时保留 `ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。没有修改 `current_route_registry.yaml`，也没有改变任何 source readiness。

**验证结果：**
使用项目 `.venv` 运行 `run_full_data_pool500_recall_only.py --limit-users 500` 并显式传入 UserCF / ItemCF weak / ItemCF strong / Swing guarded sidecar manifests，输出 `decision=STOP`。`diagnostic_source_contribution` 显示 DIAGNOSTIC_ONLY 三源合计 `row_total=21926`、`marginal_candidate_share=0.195798`，其中 `usercf_recall=21251`、`itemcf_weak=345`、`itemcf_strong=330`，三者仍 `promotion_allowed=false`。定向测试 `test_full_data_pool500_recall_only.py`、`test_pool500_method_registry_drift.py`、`test_recall_source_registry.py` 结果 `16 passed`，独立 verifier 复查通过。

**面试可讲点：**
这段可以讲成“推荐系统召回 readiness gate 的总控治理”：把各算法窗口产物统一收口为可审计 bundle，不因某个 DIAGNOSTIC_ONLY source 有边际贡献就直接晋升，而是用 underfill、source coverage、stoploss、贡献审计和禁升测试共同证明当前仍应 STOP，为下一轮专项优化提供清晰边界。

### 2026-05-18 - ItemCF strong-positive 覆盖扩大诊断

**任务：**
扩大 `itemcf_strong` 的 train-only strong-positive item pair 建索引范围，重新生成 guarded target500 diagnostic sidecar，并量化 underfilled 用户补量；保持 `DIAGNOSTIC_ONLY`，不修改 route registry、不打开 ranking input replacement 或 pool1000。

**遇到的问题：**
旧 strong target500 产物的 sidecar 边文件只有 `5636` 条边，recall-only target500 per-source `row_count=330`，无法证明对 underfilled 用户有足够补量；需要区分“强标签更干净”与“构建范围过窄导致覆盖不足”。

**定位方式：**
读取 `rs_lab/experiments/recall/build_full_train_itemcf_sidecars.py`、`dic/recall_methods/itemcf_strong/METHOD.md` 和旧 `outputs/recall/pool500_sidecar_fix/itemcf_strong_target500_guarded/*`。旧日志显示构建命令只取 `--target-user-limit 500`，实际 `users_used=212`、`unique_pair_count=2818`、`rows_written=5636`；`row_count=330` 来自 `run_full_data_pool500_recall_only.py` 的 target500 per-source 输出。

**解决方式：**
复用既有 guarded builder，不改 readiness 边界，把 strong-positive train shard 扩大到 `--target-user-limit 5000`，保持 `max-items-per-user=20`、`max-item-user-freq=500`、`top-k-per-seed=80`，用 `.omc/tools/run_guarded_process.py` 约束 free memory 与 RSS。随后用新的 `itemcf_strong_target500_guarded/source_index_manifest.json` 重跑 `recall_only_target500_with_sidecars`，只显式覆盖 ItemCF strong/weak manifests，避免越界触碰 UserCF。

**验证结果：**
`.venv` guarded sidecar 构建通过，`itemcf_strong_edges.jsonl` 从 `5636` 增至 `49816`，`users_with_source_items=5000`、`users_used=2133`、`unique_pair_count=25030`、index `unique_item_count=9690`、`peak_rss_mb=27.055`，`no_holdout_audit.status=PASS`，`readiness_contract.status=DIAGNOSTIC_ONLY`。target500 recall-only 重跑输出 `decision=STOP`、`underfilled_user_count=500`；`itemcf_strong` per-source `row_count=1845`、`user_coverage_count=157`、`underfilled_user_coverage_count=157`、`marginal_candidate_share=0.020619`、`unique_item_count=1176`。对比同批 weak：`row_count=1880`、`user_coverage_count=163`、`marginal_candidate_share=0.02101`，说明 weak 更适合补量，strong 更适合作为高置信补充源。定向测试 `tests/test_full_train_itemcf_sidecars.py` 结果 `6 passed`。

**面试可讲点：**
这段可以讲成“高置信召回源的诊断放量”：不是为了把 strong ItemCF 包装成 READY，而是在 train-only、guarded、no-holdout 的约束下扩大强正反馈共现边，证明它能给 underfilled 用户带来实际增量，同时用 readiness contract 和 STOP 结果守住线上晋升边界。

### 2026-05-24 - pool500 TwoTower 独立 method_dataset 构建器

**任务：**
为 pool500 TwoTower 补一个 dataset-only 的独立 P2b builder，只产出训练样本和负例 universe，不复用旧 two_tower source/index/embedding 链路。

**遇到的问题：**
旧 TwoTower builder 依赖 source_index_manifest、VectorIndex、embedding/index 和 candidates 输出，容易把训练前 dataset 准备与候选生成、ANN 索引、promotion readiness 混在一起；新任务还要求缺少 P1 v2 profile/bucket 时必须阻塞。

**定位方式：**
读取 P1 `build_train_only_data_governance.py`，确认可用输入为 `user_quality_profile.jsonl`、`item_quality_profile.jsonl`、`item_frequency_train.jsonl` 和 `user_sequences.train.jsonl`；对照旧 `tests/test_pool500_two_tower_method_source.py`，确认新增路径必须避开旧 source builder 和索引依赖。

**解决方式：**
新增 `rs_lab/experiments/recall/build_pool500_two_tower_method_dataset.py`，只读取 clean train sequences 与 P1 governance artifacts，输出 `two_tower_train_samples.jsonl`、`negative_item_universe.jsonl`、`method_dataset_manifest.json`、`leakage_audit.json`；负例 universe 只从 P1 item quality/frequency 派生，manifest 禁止 source/index/embedding/candidates 字段，并提供 `limit-users`、`limit-interactions`、`max-samples`、`negative-ratio`、`max-items-per-user`、`min-free-bytes` 资源上限。

**验证结果：**
新增 `tests/test_pool500_two_tower_method_dataset.py` 覆盖负例来源、输出白名单、资源 caps、manifest schema、禁用 import/字段、缺少 v2 bucket 阻塞和 CLI。验证命令：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_two_tower_method_dataset.py -q`，结果 `6 passed`；`py_compile` 对新增 builder/test 通过。

**面试可讲点：**
这段可以讲成“把重模型召回的数据准备层和候选生成层解耦”：TwoTower 先形成可审计、train-only、资源受控的 method_dataset，不提前训练、不建索引、不声明 ready，从而为后续模型训练保留干净输入合同和泄漏审计边界。

### 2026-05-20 - Agent RAG 增强计划纳入当前文档

**任务：**
把 Agent 后续需要考虑 RAG 的方向纳入当前权威文档，而不是继续停留在 `old_dic` 历史草稿中。

**遇到的问题：**
历史 `old_dic` 中已有 RAG、物品知识库、向量检索和推荐幻觉控制的设想，但当前项目规范明确 `old_dic` 只作历史参考，不能直接作为 Agent 规划依据；同时当前 Agent 文档主要强调多轮对话、反馈、展示和仿真，还缺少 RAG 在候选证据、解释 grounding 和幻觉控制中的正式位置。

**定位方式：**
检索并读取 `old_dic/historical_plans/early_agent_generative_recsys_analysis.md` 中 RAG 相关段落，再对照当前 `dic/README.md`、`dic/architecture/IMPLEMENTATION_PLAN.md` 和 `dic/architecture/ARCHITECTURE.md`，确认最合适的落点是“Agent RAG 增强”规划层，而不是召回主路或已完成能力。

**解决方式：**
在实施计划中新增 `Phase 4：Agent RAG 增强，规划中`，明确知识库构建、轻量 text / metadata retrieval、RAG retrieval tool、Prompt / Context 注入和评估门禁；在架构说明中新增 Agent RAG 增强层和模块边界；在 README 中把 RAG 写入项目主叙事，但明确它尚未落地，不替代召回或排序。

**验证结果：**
通过关键词检查和 `git diff -- dic/README.md dic/architecture/IMPLEMENTATION_PLAN.md dic/architecture/ARCHITECTURE.md` 确认新增表述只影响当前权威文档，且统一保留边界：RAG 服务商品知识检索、解释 grounding、why 问答、澄清追问和幻觉控制；推荐结果仍来自受治理的候选池与排序链路，不绕过候选池生成新商品，不写成已完成能力。

**面试可讲点：**
这段可以讲成“把生成式推荐的幻觉控制纳入 Agent 架构，而不是让 LLM 自由编商品”：底层推荐 backbone 仍负责候选和排序，RAG 只给 Agent 提供商品知识证据和可追溯上下文，让推荐解释、why 问答和多轮澄清能 grounded 到真实商品字段。

### 2026-05-21 - pool500 policy rerank guard 组合副作用修复

**任务：**
定位并修复三阶段排序 challenger 中 policy rerank guard 把唯一命中正样本推出 Top20 的问题，保持 frozen pool500 候选池语义不变。

**遇到的问题：**
旧实验中 B0/R1/coarse-only 在 Top20 都能命中唯一 overlap 正样本，但 L1 three-stage 的 Hit@20/NDCG@20/MRR@20 归零；直接表现不是召回池丢样本，而是重排阶段把正样本从 Top20 内推到 Top20 外。

**定位方式：**
复核 `outputs/ranking/pool500_three_stage_offline_smoke_20260521/challenger_interaction_labels/comparison.json`，确认 eval 45 个 positive pairs 只有 1 个进入 frozen pool500；该样本 `AFKROCEYUGLIBSDUJBFQPGGC44GA / B07P9V8GSH` 在 B0/R1 为 rank 11、coarse-only 为 rank 12、policy 后为 rank 81。结合 `rs_core/recsys/ranking.py` 检查发现多个 guard 顺序应用时，前序 guard 已标记 defer 的候选仍会被后续 guard 重新处理并参与 TopK 补位。

**解决方式：**
在 `_cap_policy_items`、`_cap_policy_group`、`_cap_rank_movement` 前先拆分 eligible 与已 deferred 候选，后续 guard 只处理仍 eligible 的候选，并把历史 deferred 候选稳定保留在后缀，避免 category_missing/source/category/rank movement 多个 guard 互相覆盖 defer 结果。新增回归测试覆盖“前序 category_missing_cap 已 defer 的候选不应被后续 source guard 补回 TopK”。

**验证结果：**
`.venv` 下运行 `tests/test_recsys_core.py tests/test_ltr.py tests/test_pool500_shadow_ranking.py tests/test_pool500_learned_ranking_challenger.py tests/test_pool500_label_artifact.py`，结果 `135 passed`。重跑同一批 aligned frozen-pool candidates 到 `outputs/ranking/pool500_three_stage_offline_smoke_20260521/challenger_interaction_labels_guardfix/`，L1 的正样本 rank 从旧结果 81 恢复到 12，Hit@20 从 0.0 恢复到 0.1；promotion gate 仍为 `NO_PROMOTE / diagnostic_only_no_promote`，因为 NDCG@20 和 MRR@20 仍低于 B0，且存在 underpowered positive users / quality guard / no primary metric lift / primary MRR regression blockers。

**面试可讲点：**
这段可以讲成“离线排序策略的 guard 组合治理”：不是看到指标归零就否定 LightGBM 或三阶段链路，而是沿着 frozen pool → coarse/fine/rerank 的排名轨迹定位到 policy guard 的组合副作用；修复后恢复命中但仍坚持 no-promote，体现了效果指标、质量约束和上线门禁分离治理。

### 2026-05-21 - pool500 LTR 低证据注入降级与 coarse 校准回退

**任务：**
继续在已冻结 `pool500_vCurrent` candidates 上优化三阶段排序，不改召回、不新增候选、不改变 frozen pool 语义；补齐 B0/R1/coarse-only/L1 ablation，并重点处理 coarse/LTR/policy guard 排序顺序带来的诊断退化。

**遇到的问题：**
policy guard 组合 bug 修复后，L1 Hit@20 已从 0 恢复到 0.1，但唯一 overlap 正样本仍从 B0/R1 的 rank 11 退到 L1 的 rank 12，NDCG@20 和 MRR@20 略低于 B0/R1。当前 eval positive overlap 只有 1 个，不能把排序结论写成可晋升效果，只能做 diagnostic 调参。

**定位方式：**
读取 `outputs/ranking/pool500_three_stage_offline_smoke_20260521/challenger_interaction_labels_guardfix/comparison.json`，确认 `positive_overlap_count=1`、`candidate_hit_rate_at_20=0.1`；唯一命中样本 `AFKROCEYUGLIBSDUJBFQPGGC44GA / B07P9V8GSH` 在 B0/R1 为 rank 11，在 coarse-only/L1 为 rank 12。局部 probe 显示退化来自 coarse policy 对 `category` source 的 0.95 校准折扣，以及 LightGBM LambdaMART 在仅 `positive_rows=1`、`positive_users=1` 时仍向排序注入负分。

**解决方式：**
把 pool500 challenger coarse policy 中 `category` source 校准从 0.95 回退到中性 1.0，避免在唯一诊断正例来自 category source 时人为压低分数；同时新增 LTR challenger eligibility，要求至少 5 条正例、2 个正例用户才允许把已训练 LTR 分数注入排序。训练产物继续记录 `positive_rows` / `positive_users`，但低证据时只保留模型诊断信息，不让 LTR 参与最终排序。

**验证结果：**
`.venv` 下运行 `tests/test_pool500_shadow_ranking.py tests/test_pool500_learned_ranking_challenger.py tests/test_recsys_core.py tests/test_ltr.py`，结果 `134 passed`。重跑 frozen candidates 到 `outputs/ranking/pool500_three_stage_offline_smoke_20260521/challenger_interaction_labels_ltr_guard/`，B0/R1/coarse-only/L1 四路在 @20 全部持平：`Hit=0.1`、`NDCG=0.004095`、`MRR=0.009091`、`Recall=0.005263`、`MAP=0.000478`；`frozen_candidate_equality.status=PASS`，`candidate_generation_allowed=false`，LTR 配置显示 `enabled=false`、reason=`underpowered_ltr_training_labels`。独立 verifier 复查通过，但仍建议 `NO_PROMOTE`，因为 no primary metric lift、正例证据不足和 category_missing quality guard 仍存在。

**面试可讲点：**
这段可以讲成“低证据排序模型的安全降级”：在 frozen candidate pool 内把召回覆盖、coarse calibration、LTR 注入和 policy guard 分层诊断，发现 learned 模型不是训练失败，而是在正例覆盖极低时不该参与线上式重排；最终用 eligibility gate 把模型从排序决策中降级为诊断证据，避免为了追指标对唯一正例过拟合。

### 2026-05-22 - hot-user smoke020 扩容召回复验

**任务：**
从既有 `hot100_global_rank_top2000_20260522` 评估用户池派生 `hot020_global_rank_top2000_20260522`，在不使用 oracle candidate、valid/test label 注入、ranking replacement 或 pool1000 的边界下，跑一版 20 用户 pool500_vnext 召回诊断。

**遇到的问题：**
`hot010_global_rank_top1000` 可用用户只有 12 个，无法自然扩成 20；因此改用 `top2000` 放宽全局 train popularity rank 约束，保留 hot-user、moderate holdout、category overlap 与 train-derived global-rank recallability 约束。

**定位方式：**
先汇总 `outputs/recall/pool500_aligned_eval_users_valid_test/` 下 hot010/hot100 manifests，确认 `hot100_global_rank_top2000_20260522` 有 30 个候选用户。派生前 20 个用户 manifest 后运行 `.venv` 下的 `run_full_data_pool500_recall_only.py --recall-profile pool500_vnext --limit-users 20`，再用 target-only valid/test positive 分母计算覆盖，避免被全量 label 分母稀释。

**解决方式：**
生成 `outputs/recall/pool500_aligned_eval_users_valid_test/hot020_global_rank_top2000_20260522/aligned_eval_users_manifest.json`，并输出召回结果到 `outputs/recall/pool500_vnext_hot020_global_rank_top2000_20260522/`。额外写出 target-only 覆盖诊断 `hot020_label_coverage_target_only.json`，只用于 evaluation-only 分析，不作为候选生成或排序输入。

**验证结果：**
召回生成成功，`quality_audit.json` 显示 20 用户、10,000 rows、每用户 500 candidates、无重复、无缺字段、无 underfill。target-only 诊断显示 20 个用户共有 79 个 valid/test positives，Recall@20=`8/79=0.101266`、Recall@50=`12/79=0.151899`、Recall@100=`15/79=0.189873`、Recall@500=`23/79=0.291139`，UserHitRate@500=`0.7`。拆分看，前 10 用户 Recall@500=`16/39=0.410256`，新增 10 用户 Recall@500=`7/40=0.175`，说明扩容主要暴露新增用户泛化弱点。`per_source_readiness_contracts.json` 还显示 `co_visit_fallback_repair` 与 `usercf_recall` 在本批次 row_count 为 0，`diagnostic_source_contribution.json` 中 `usercf_recall.user_coverage_ratio=0.0`，提示 hot020 新用户没有被这些侧路 source 覆盖。

**面试可讲点：**
这段可以讲成“评估集扩容后的稳定性诊断”：不是直接把 smoke020 作为新主指标，而是用它检查 smoke010 是否偶然有效；结果表明候选池工程质量达标，但新增用户覆盖明显下降，下一步应先补齐 UserCF/co-visit 等 source 对 hot020 用户的覆盖，再讨论排序层优化。

### 2026-05-23 - pool500 排序评价闭环 strict label gate

**任务：**
在冻结 pool500 候选池和 diagnostic-only 排序链路上补齐严格 label evaluation 闭环，使 fixed comparison report 能明确区分 `pending_label`、`label_invalid`、`label_insufficient` 与 `label_comparable`，并冻结 learned challenger 的训练/晋升入口。

**遇到的问题：**
原报告中 label coverage 口径过松，`label_invalid` / `label_insufficient` 会阻断整个 mechanism diagnostic report；summary 对 label 字段的权威投影不完整；learned challenger 仍可绕过 fixed comparison report 直接训练并写出 `agent_ready_ranked_artifact.json`。

**定位方式：**
先做 dirty workspace ownership 审计，隔离召回路线和既有叙事日志改动，只复用 `pool500_shadow_ranking.py`、`tests/test_pool500_shadow_ranking.py`、`run_pool500_learned_ranking_challenger.py` 与对应测试。独立 verifier 还发现 `full_pool_candidate_coverage_diagnostic` 曾误用 TopK union coverage，需要把 formal label gate 分母和 full-pool diagnostic metadata 分离。

**解决方式：**
在 fixed comparison report 内加入 strict label gate：explicit/manifest label 才可被 evaluator 消费，known-output discovery 只做只读提示；formal label lift 使用 all-config TopK union 覆盖率，full-pool coverage 仅作为 diagnostic metadata；正式指标固定为 `pool500_label_metrics_per_user_mean_v1` 的 per-user mean Hit/NDCG/MRR/Recall。summary 只能从权威 report 投影并过滤内部 label metadata。learned challenger 改为 Frozen mode，必须校验 report path/hash、`label_metric_eligibility=true`、规则瓶颈证据和 feature/leakage gates，即使全部通过也只输出 `would_be_eligible=true`，不训练、不晋升、不写 Agent-ready artifact。

**验证结果：**
使用项目默认 `.venv` 运行 `python -m pytest tests/test_pool500_shadow_ranking.py tests/test_ltr.py tests/test_pool500_learned_ranking_challenger.py`，最终结果 `137 passed`；`py_compile` 覆盖更新后的排序报告、测试和 learned challenger 文件。独立 verifier 复验 PASS，确认 full-pool diagnostic coverage 已使用完整 candidate file 分母，且不影响 `label_metric_eligibility`。

**面试可讲点：**
这段可以讲成“离线排序评价治理闭环”：不是直接调排序参数追求短期 lift，而是先把 label artifact、coverage denominator、summary authority 和 learned model gate 固化为可审计状态机；在 label 不可比时只允许机制诊断，在 label 可比后才解释排序指标，从而避免把诊断产物包装成可晋升效果。

### 2026-05-23 - pool500 固定离线评估用户集

**任务：**
构建固定 `pool500` 离线评估用户集，统一后续召回路线与排序路线的 eval users / labels / history split 基准，并输出 100 用户 dry-run 与正式 10,000 用户 artifact。

**遇到的问题：**
初版构建器在 dry-run 前加载全量 train history 与 valid/test label 聚合，100 用户验证也出现高内存占用且迟迟不落盘；同时 manifest 需要精确区分召回评估、纯排序评估和端到端链路评估，避免把候选池变化误解释为排序模型提升。

**定位方式：**
通过 `.venv` 下的 selector 单测、100 用户 dry-run 命令和 verifier 资源观察定位瓶颈：full-data dry-run 曾达到约 16.8GB，第一次流式优化后仍约 8.8GB，说明 label 聚合仍是内存热点。读取 `select_pool500_aligned_eval_users.py`、clean manifest 和既有 pool500 recall/ranking 脚本，确认安全输入边界是 train history + valid/test evaluation labels。

**解决方式：**
在 `rs_lab/experiments/recall/select_pool500_aligned_eval_users.py` 中新增 `build_pool500_offline_eval_users()`，输出 `manifest.json` 与 `users.jsonl`；按 history_count 分层采样 hot/warm/cold-ish，正式目标为 4000/4000/2000。将 offline 构建改为临时 SQLite 磁盘聚合 valid/test 正样本，再流式扫描 train history 生成 eligible candidates，只为最终选中用户二次补 category/head-tail 诊断，避免 oracle/label 注入候选构建。

**验证结果：**
`.venv/Scripts/python -m pytest tests/test_pool500_aligned_eval_user_selector.py -q` 结果 `5 passed`。100 用户 dry-run 输出 `outputs/eval/pool500_offline_eval_users_dry_run_100/manifest.json`，状态 `PASS`，分层 `hot=40/warm=40/cold-ish=20`。正式产物输出到 `outputs/eval/pool500_offline_eval_users_10k/`，状态 `PASS`，分层 `hot=4000/warm=4000/cold-ish=2000`，`user_set_hash=eb63bae51126aa572072415236eb8efbb14979be7b9ae7edf21d555077136b33`，无 warnings，manifest/users.jsonl 结构校验通过。

**面试可讲点：**
这段可以讲成“离线评估基准治理”：先把用户、history/label split、指标契约和候选池契约固化成可复现 artifact，再让召回和排序共享同一评估基准；同时用磁盘聚合和流式扫描把全量数据构建从高内存阻塞改成可落盘、可复验的工程流程。

### 2026-05-24 - pool500 协同召回 method dataset-only 分层

**任务：**
为 `itemcf_weak`、`itemcf_strong`、`usercf_method_dataset`、`swing_method_dataset` 新增独立 dataset-only builder，只消费 P1 train-only governance 输出，不生成候选、source index、ANN/index/embedding 或晋升产物。

**遇到的问题：**
P2 数据集需要继承 P1 分层口径，但不能调用旧 `methods/*/builder.py` 入口，也不能在 dataset 层混入候选生成语义；同时用户分层必须依赖 `quality_bucket_v2`，缺失时要阻断而不是回退到旧 `quality_bucket`。

**定位方式：**
读取 `rs_lab/experiments/recall/build_train_only_data_governance.py` 的 `derived_dataset_policies`、`item_quality_profile` 字段和现有 pool500 方法测试，确认安全输入边界为 `user_quality_profile.jsonl`、`item_quality_profile.jsonl`、`item_frequency_train.jsonl` 与 `user_sequences.train.jsonl`。

**解决方式：**
新增 `rs_lab/experiments/recall/build_pool500_method_dataset.py`，按方法输出 `method_dataset_manifest.json` 与 `method_dataset_rows.jsonl`，manifest 固化 hard schema、输入 hash、forbidden scope audit 和所有禁止晋升开关；用户侧只读取 `quality_bucket_v2`，物品侧使用 `cf_ready=true` 且 `over_hot=false` 的 train-only item profile 过滤。

**验证结果：**
使用项目默认 `.venv` 运行 `python -m pytest tests/test_pool500_method_dataset.py -q`，结果 `4 passed`；继续运行 `python -m pytest tests/test_pool500_method_dataset.py tests/test_train_only_data_governance.py -q`，结果 `15 passed`；新增文件通过 `py_compile`。

**面试可讲点：**
这段可以讲成“召回数据分层治理”：把候选生成前的一层 method dataset 独立出来，用强 schema、输入 hash、输出白名单和 v2 分层阻断规则保证协同召回只消费 train-only governance 数据，为后续候选构建和审计留出可追溯边界。


### 2026-05-24 - pool500 P2 方法特异数据集资源策略固化

**任务：**
为 pool500 P2 method-specific dataset 链路补齐资源规模策略，明确重方法使用 `governance_train_only -> method-specific dataset -> source_artifact` 的边界，同时让 Popular/Category 轻方法保留 full train-only statistics 扫描能力。

**遇到的问题：**
协同过滤和 TwoTower 数据集 manifest 之前只有选择策略与 no-promotion 语义，缺少可审计的 P2 resource scale policy；轻方法、重方法和 deferred 方法在 registry 中也缺少“输入扫描规模”和“方法特异边界”的差异化说明。

**定位方式：**
检查 `build_pool500_method_dataset.py`、`build_pool500_two_tower_method_dataset.py`、`pool500_method_registry.json` 及对应 audit/drift 测试，确认新增字段必须避开 candidate/source index/ready/promotion 等禁用语义，并保持 train-only、no-leakage、no READY claim。

**解决方式：**
在协同过滤四类方法和 TwoTower manifest 中加入安全的 `resource_scale_policy` metadata，并纳入协同过滤 `config_hash`；registry 中为 Popular/Category 写明允许 full train-only statistics input scan、无 input size cap，仅由下游 output/per-user share 控制，同时为 itemcf/usercf/swing 写入方法特异 P2 资源边界和 selection_strategy，并为 semantic seed metadata 与 co-visit fallback repair 保持 DEFERRED 的有界 P2 数据定义与方法特异 selection_strategy。

**验证结果：**
使用项目默认 `.venv` 运行 `./.venv/Scripts/python.exe -m pytest tests/test_pool500_method_dataset.py tests/test_pool500_two_tower_method_dataset.py tests/test_pool500_method_dataset_audit_evidence.py tests/test_pool500_method_registry_drift.py tests/test_pool500_lightweight_source_governance.py -q`，最终结果 `32 passed in 0.72s`。

**面试可讲点：**
这段可以讲成推荐召回工程中的“资源治理契约化”：把重方法的本地正式规模、用户/物品频次、pair support 与选择/采样策略等约束固化进可审计 manifest，同时避免把诊断数据集误用为候选生成或排序替换输入，体现离线实验到工程链路的安全边界设计。


### 2026-05-25 - ItemCF method_dataset smoke 边特征构建验证

**任务：**
验证 `itemcf_weak` 与 `itemcf_strong` 的 P2 method_dataset smoke 构建链路，确认 `itemcf_edge_features_v1` manifest、audit 统计和方法文档证据可落盘。

**遇到的问题：**
默认构建命令会读取 `outputs/recall/data_governance/train_only_v1/manifest.json`，本地当前没有该全量 governance manifest；如果直接按默认失败结果收口，会混淆“全量依赖缺失”和“smoke 链路不可用”。

**定位方式：**
先运行 targeted tests，结果 `41 passed in 0.64s`；随后构建失败定位到缺失的默认 manifest。检查 `outputs/recall/data_governance/` 后确认已有 `train_only_v1_smoke/manifest.json`，因此改用 smoke governance 作为本轮 smoke 构建输入。

**解决方式：**
使用项目 `.venv` 分别构建 `itemcf_weak` 与 `itemcf_strong`，输出到 `outputs/recall/pool500_method_datasets/itemcf_smoke_edge_features_v1/`，并在两个 METHOD 文档中记录 row/user/item/pair/edge/top-k 后 directed edge、drop reason 和特征摘要。

**验证结果：**
`outputs/recall/pool500_method_datasets/itemcf_smoke_edge_features_v1/` 下 `itemcf_weak` 与 `itemcf_strong` 的 `method_dataset_manifest.json` 均为 `status=PASS`、`schema_name=itemcf_edge_features_v1`，并通过 targeted tests / audit evidence gate：`tests/test_pool500_method_dataset.py`、`tests/test_pool500_method_registry_drift.py`、`tests/test_pool500_method_dataset_audit_evidence.py` 结果 `43 passed`。当前 smoke governance 下二者 `row_count=0`、`user_count=0`、`item_count=0`、`unique_pair_count=0`、`edge_count=0`、`directed_edge_count_after_topk=0`；weak smoke 参数保持 `max_item_user_freq=5000`、`min_pair_support=1`，dropped reason 为 `user_bucket_not_allowed=18103318`、`insufficient_pair_items=66`、`item_over_hot=1461`、`item_not_cf_ready=2317958`；strong smoke 参数为 `max_item_user_freq=3000`、`min_pair_support=2`，dropped reason 为 `user_bucket_not_allowed=18103383`、`insufficient_pair_items=1`、`item_over_hot=1461`、`item_not_cf_ready=2317958`，`pair_below_min_support=0`。本轮只证明 train-only method_dataset contract、特征 schema、forbidden-scope audit 和空输出统计可审计，不声明 recall coverage 提升、READY、promotion 或 ranking input replacement。

**面试可讲点：**
这段可以讲成“把重资源 ItemCF 从能跑 sidecar 推进到可审计的方法级数据集 contract”：即使 smoke 样本没有产出有效边，也保留了 train-only 输入、禁止 holdout/oracle、特征 schema、drop reason 和构建命令证据，避免把空输出误读成方法失败或把 smoke PASS 误读成召回晋升。


### 2026-05-25 - UserCF 三档 method_dataset 最终验收

**任务：**
验证 `usercf_v1_smoke`、`usercf_v1_diagnostic`、`usercf_v1_local_formal` 三档 UserCF method_dataset 是否满足 P2 dataset-only 契约，并补齐 focused test 证据。

**遇到的问题：**
UserCF 三档产物需要证明只是 eligible user sequence 数据集，不能夹带 candidates、source index、readiness 或 promotion 语义；同时 local_formal 规模较大，必须用 row file 实际行数复核 manifest 的 `row_count`。

**定位方式：**
逐档读取 `outputs/recall/pool500_method_datasets/*/usercf_method_dataset/method_dataset_manifest.json`，检查 `status`、`outputs.dataset_schema`、`forbidden_scope_audit.status`、四个 no-promotion/no-replacement 开关和禁用文件列表，并逐行统计 `method_dataset_rows.jsonl`。

**解决方式：**
按 smoke、diagnostic、local_formal 三档分别执行 manifest + row file 审计，确认 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`、`final_pool500_ready_claimed=false`，且目录内不存在 `candidates.jsonl`、`source_index_manifest.json`、`readiness_manifest.json`、`promotion_manifest.json`。

**验证结果：**
三档审计均为 `AUDIT_RESULT=PASS`：smoke `row_count=213/user_count=213/item_count=207/schema=eligible_user_sequence_v1`；diagnostic 改为使用 full/local_formal governance + diagnostic caps 后，`row_count=60000/user_count=60000/item_count=66263/schema=eligible_user_sequence_v1`；local_formal `row_count=90686/user_count=90686/item_count=94553/schema=eligible_user_sequence_v1`，三档 row file 实际行数均等于 manifest `row_count`。使用项目默认 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_method_dataset.py -q`，结果 `21 passed in 0.45s`。

**面试可讲点：**
这段可以讲成“推荐召回 P2 数据集契约验收”：不仅看 manifest PASS，还用实际行数、schema、forbidden-scope audit 和禁用产物缺失共同证明 UserCF 当前只提供可审计的 eligible user sequence 输入，不越界声明候选生成、排序替换或 pool500 晋升。

### 2026-05-25 - TwoTower full train-only formal dataset 与 bounded diagnostic package

**任务：**
生成缺失的 `train_only_v1` upstream governance manifest，并基于全量 clean train 数据制作 TwoTower formal method dataset、audit evidence 与 200 用户 bounded diagnostic loop package。

**遇到的问题：**
formal governance 输入最初缺少 `outputs/recall/data_governance/train_only_v1/manifest.json`，不能用 smoke/diagnostic manifest 替代。后续 full local_formal 构建还暴露两个工程瓶颈：TwoTower method dataset 每个样本复制全量 negative universe 导致运行过慢；diagnostic loop 默认把 889431 个 training item 的完整文本写入训练 vocab，导致 GB 级 JSON 和全量 topK scoring 过重。audit 首次还 BLOCKED 了 12 个 positive target 的 `title_clean` 缺失。

**定位方式：**
用 `.venv` 运行指定 builder 并检查 manifest/audit 输出：governance manifest PASS，`profiled_user_count=18103384`、`total_item_count=2320263`；formal TwoTower dataset 首次 audit blocker 为 `two_tower_positive_target_metadata_incomplete`，定位到 canonical metadata 中部分 target `title_clean` 为空但有 description/category。通过输出文件大小和进程状态确认 diagnostic bottleneck 来自完整 item vocab 与全量 item scoring。

**解决方式：**
先用 full clean manifest 生成 `outputs/recall/data_governance/train_only_v1/manifest.json`，再生成 formal method dataset。将负采样从“每样本构造 eligible negatives 全量列表”改为从 hash offset 流式扫描并跳过 history/target，保持 deterministic rotated negatives 语义但避免 O(samples × universe copy)。对 title 缺失的 target，用已有 description/features/category 文本作为 `title_clean` fallback，确保 item tower metadata contract 可消费。diagnostic loop 保持 200 用户 bounded 口径，只对样本涉及的 history/target items 构建紧凑 vocab，不生成正式 candidates/ranking/promotion/READY 产物。

**验证结果：**
formal governance 输出 PASS：`outputs/recall/data_governance/train_only_v1/manifest.json`。formal TwoTower method dataset 输出 PASS：`train_sample_count=751574`、`negative_universe_item_count=866802`、`training_item_universe_item_count=889431`。audit evidence PASS：`outputs/recall/pool500_method_datasets/audit_evidence_v1/diagnostic_audit_report.json`，`blocker_count=0`，`positive_target_metadata_incomplete_count=0`，negative leakage/duplicate/empty 均为 0。diagnostic package PASS：`outputs/recall/pool500_two_tower_diagnostic_loop/diagnostic_report.json`，`source_index_row_count=1137`、`diagnostic_topk_row_count=10000`、200 users、975 targets，Recall@20=`0.294359`、Recall@50=`0.434872`。相关测试使用 `.venv` 运行 `tests/test_pool500_two_tower_method_dataset.py tests/test_pool500_two_tower_diagnostic_loop.py`，结果 `33 passed in 0.86s`。

**面试可讲点：**
这段可以讲成“把双塔训练数据从 smoke 证据推进到 full train-only formal 包装”：先补齐 upstream governance，再用 audit 把 history→target、target universe 覆盖、负样本多样性、metadata 完备性和 no-oracle/no-label/no-promotion 边界固化下来；同时对大规模数据物化做必要的复杂度治理，避免诊断任务被全量文本和全量 scoring 拖成生产训练。


### 2026-05-26 - TwoTower formal full è®­ç»ƒè¿œç¨‹ç®—åŠ›è¿�ç§»

**ä»»åŠ¡ï¼š**
å½“æœ¬æœº full formal TwoTower è®­ç»ƒé¢„è®¡é•¿æœŸå� ç”¨ CPU/GPU/å†…å­˜æ—¶ï¼Œå°†è®­ç»ƒè¿�ç§»åˆ°æŽˆæ�ƒè¿œç¨‹æœ�åŠ¡å™¨æ‰§è¡Œï¼Œå®Œæˆ�å�Žæ‹‰å›žå¿…è¦� artifact å¹¶åœ¨æœ¬åœ°éªŒè¯�å�Žå†�æŽ¥å…¥ä¸»è·¯ã€‚

**é�‡åˆ°çš„é—®é¢˜ï¼š**
æœ¬æœº strict full/no-limit è®­ç»ƒè™½ç„¶å·²è¿›å…¥ CUDA batchï¼Œä½†æ•°æ�®ç®¡çº¿ä¸Ž Python batch æž„é€ ä½¿ GPU åˆ©ç”¨çŽ‡é•¿æœŸå��ä½Žï¼›å�³ä½¿æ”¹æˆ� streaming ä¸Ž `batch_size=1024`ï¼ŒæŒ‰å®žæµ‹é€Ÿåº¦ä»�å�¯èƒ½éœ€è¦�æ•°å¤©åˆ°å��å¤©çº§ï¼Œæ— æ³•æ»¡è¶³é�¢è¯•å‰�å¿«é€Ÿæ”¶å�£ã€‚

**å®šä½�æ–¹å¼�ï¼š**
é€šè¿‡ `gpu_device_trace.log`ã€�`nvidia-smi`ã€�è¿›ç¨‹ CPU/RAM ä¸Ž `torch_training_batches` äº‹ä»¶å®šä½�ï¼šæœ¬æœºè®­ç»ƒå·²ç¡®è®¤ä½¿ç”¨ CUDAï¼Œä½† batch å�žå��ä¸�è¶³ã€‚è¿›ä¸€æ­¥å®¡è®¡ `rs_core/recsys/two_tower.py`ï¼Œå�‘çŽ°è´Ÿé‡‡æ ·åŽŸå®žçŽ°æ¯�æ�¡æ ·æœ¬éƒ½ä¼šæž„é€ ä¸€æ¬¡å…¨ item å€™é€‰åˆ—è¡¨ï¼Œå¯¼è‡´æ¯�æ ·æœ¬éš�å¼�æ‰«æ��çº¦ 26 ä¸‡ itemï¼›å�Œæ—¶ user embedding å�Žå¤„ç�†é€�ç”¨æˆ·è°ƒç”¨ GPUã€‚

**è§£å†³æ–¹å¼�ï¼š**
å…ˆåœ¨æœ¬åœ°ä¿®å¤�è®­ç»ƒå�žå��ç“¶é¢ˆï¼šè´Ÿé‡‡æ ·æ”¹ä¸º rejection samplingï¼Œé�¿å…�æ¯�æ ·æœ¬å…¨ item æ‰«æ��ï¼›user embedding æ”¹ä¸ºæ‰¹é‡� GPU ç¼–ç �ã€‚éš�å�Žä½¿ç”¨æŽˆæ�ƒæœ�åŠ¡å™¨ `ssh luo@10.112.125.22`ï¼Œå·¥ä½œç›®å½•å›ºå®šä¸º `/home/luo/RS_agent_remote`ï¼Œå�ªè¿�ç§»æœ€å°�è®­ç»ƒé—­åŒ…ï¼šä»£ç �ã€�é…�ç½®ã€�å…¨é‡� train sequenceã€�TwoTower item vocabã€�method dataset manifest/auditï¼Œä¸�è¿�ç§» diagnostic/oracle/eval äº§ç‰©ã€‚è¿œç«¯åˆ›å»º `.venv`ï¼Œå®‰è£… CUDA PyTorchï¼Œä½¿ç”¨ `nohup .venv/bin/python scripts/launch_two_tower_remote_formal.py > logs/<run>.stdout.log 2> logs/<run>.stderr.log &` å�Žå�°å�¯åŠ¨ formal full è®­ç»ƒï¼Œå¹¶é€šè¿‡ `gpu_device_trace.log`ã€�`gpu_launch_status.json` å’Œ `nvidia-smi` ç›‘æŽ§ã€‚å¯†ç �ä¸�å¾—å†™å…¥è„šæœ¬ã€�æ—¥å¿—ã€�å‘½ä»¤å�‚æ•°æˆ–æ–‡æ¡£ã€‚

**éªŒè¯�ç»“æžœï¼š**
è¿œç«¯ preflight æ˜¾ç¤º `torch=2.11.0+cu128`ã€�`cuda_available=true`ã€�GPU ä¸º `NVIDIA GeForce RTX 4090`ã€�`strict_full_no_user_limit=true`ã€�`limit_users=null`ã€�`method_dataset_status=PASS`ã€�`method_dataset_train_only=true`ã€‚è®­ç»ƒå�‚æ•°ä¸º `epochs=3`ã€�`batch_size=16384`ã€�`user_embedding_batch_size=32768`ã€‚è¿œç«¯ä»Ž preflight åˆ° `first_batch_devices` çº¦ 12 åˆ†é’Ÿï¼›é¦–ä¸ª `torch_training_batches batch_index=1000` çº¦ 5 åˆ†é’Ÿåˆ°è¾¾ï¼Œè¯´æ˜Žæœ�åŠ¡å™¨ç‰ˆæœ¬å·²ä»Žæœ¬æœºâ€œæ•°å¤©çº§â€�å�˜ä¸ºå°�æ—¶çº§ã€‚äº§ç‰©å®Œæˆ�å�Žéœ€è¦�æ‹‰å›ž `artifact_manifest.json`ã€�`train_config.json`ã€�`train_metrics.json`ã€�model/embedding/id mapã€�`two_tower_recall_index.jsonl`ã€�GPU trace/status æ—¥å¿—ï¼Œå†�åœ¨æœ¬åœ°é‡�å»ºæˆ–éªŒè¯� `source_index_manifest.json` å�ŽæŽ¥å…¥ä¸»è·¯ã€‚

**è°ƒç”¨æ–¹å¼�è®°å½•ï¼š**
èµ„æº�é¢„ä¼°è¿‡å¤§æ—¶ï¼Œå…ˆç”¨ `ssh luo@10.112.125.22` æ£€æŸ¥ `nvidia-smi`ã€�`free -h`ã€�`df -h ~`ï¼›ç”¨ `tar -C <repo> -I 'gzip -1' -cf - <å¿…è¦�æ–‡ä»¶...> | ssh luo@10.112.125.22 'tar -C /home/luo/RS_agent_remote -xzf -'` ä¼ è¾“æœ€å°�é—­åŒ…ï¼›è¿œç«¯ç”¨ `/home/luo/RS_agent_remote/.venv` æ‰§è¡Œè®­ç»ƒ launcherï¼›å®Œæˆ�å�Žç”¨ `scp`/`rsync` ä»…æ‹‰å›ž run ç›®å½•ä¸­çš„æ­£å¼�è®­ç»ƒäº§ç‰©å’Œæ—¥å¿—ã€‚å›žä¼ å�Žä¸�ç›´æŽ¥ä¿¡ä»»è¿œç«¯ç»�å¯¹è·¯å¾„ï¼Œåº”åœ¨æœ¬åœ°é‡�æ–°æ ¡éªŒ train-only/no-leakage/row count å¹¶é‡�å»ºä¸»è·¯ source index manifestã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™æ®µå�¯ä»¥è®²æˆ�â€œèµ„æº�çº¦æ�Ÿä¸‹çš„è®­ç»ƒå·¥ç¨‹åŒ–è¿�ç§»â€�ï¼šä¸�æ˜¯ç›²ç›®ç­‰å¾…æœ¬æœºæ…¢è·‘ï¼Œè€Œæ˜¯å…ˆç”¨æ—¥å¿—å®šä½�çœŸå®žç“¶é¢ˆï¼Œå†�ç”¨ç®—æ³•çº§å°�æ”¹åŠ¨æ¶ˆé™¤è´Ÿé‡‡æ ·å¤�æ�‚åº¦é—®é¢˜ï¼Œæœ€å�ŽæŠŠ full-scope train-only formal è®­ç»ƒè¿�ç§»åˆ°æ›´å¼ºæœ�åŠ¡å™¨ï¼Œå¹¶ä¿�ç•™ manifestã€�traceã€�å›žä¼ éªŒè¯�å’Œæœ¬åœ°ä¸»è·¯æŽ¥å…¥è¾¹ç•Œï¼Œä½“çŽ°æŽ¨è��ç³»ç»Ÿè®­ç»ƒé“¾è·¯çš„èµ„æº�è¯„ä¼°ã€�å�¯å¤�çŽ°æ‰§è¡Œå’Œäº§ç‰©æ²»ç�†èƒ½åŠ›ã€‚


## 2026-05-26 - TwoTower formal full å›ºå®šè¯„ä¼°é›†åˆ�æµ‹

- ä»»åŠ¡ï¼šåœ¨ formal full TwoTower source index æŽ¥å…¥ pool500 ä¸»è·¯å�Žï¼Œç”¨å›ºå®š offline eval ç”¨æˆ·é›†éªŒè¯�å�Œå¡”å�¬å›žæ•ˆæžœã€‚
- é�‡åˆ°çš„é—®é¢˜ï¼šçŽ°æœ‰ offline eval è„šæœ¬å�‘ä¸»è·¯ runner ä¼ å…¥ `target_user_manifest_path`ï¼Œä½†ä¸»è·¯å¥‘çº¦æµ‹è¯•ç¦�æ­¢ target-user runtime overrideï¼Œç›´æŽ¥è¿�è¡Œ 10k å‰�å…ˆåœ¨ 100 ç”¨æˆ· dry-run æš´éœ²äº†æŽ¥å�£æ¼‚ç§»ã€‚
- å®šä½�æ–¹å¼�ï¼š100 ç”¨æˆ· raw eval é¦–æ¬¡å¤±è´¥äºŽ `run_full_data_pool500_recall_only()` å�‚æ•°ä¸�åŒ¹é…�ï¼›éš�å�Žé€šè¿‡ `tests/test_full_data_pool500_recall_only.py` å�‘çŽ°ä¸»è·¯ç¦�æ­¢ `target_user_manifest` å­—ç¬¦ä¸²ï¼Œç¡®è®¤ä¸�èƒ½æŠŠè¯„ä¼°ç”¨æˆ·é€‰æ‹©å�šæˆ�ä¸»è·¯è¿�è¡Œæ—¶è¦†ç›–ã€‚
- è§£å†³æ–¹å¼�ï¼šä¿�æŒ�ä¸»è·¯ runner æŽ¥å�£ä¸�å�˜ï¼Œåœ¨ offline eval è„šæœ¬ä¸­ä¸ºçœŸå®ž runner ç”Ÿæˆ�å�ªåŒ…å�«å›ºå®šè¯„ä¼°ç”¨æˆ· train history çš„ä¸´æ—¶ train-only sequence viewï¼Œå¹¶æŠŠ label/valid/test ä»�é™�å®šä¸º evaluation-onlyã€‚
- éªŒè¯�ç»“æžœï¼š`tests/test_full_data_pool500_recall_only.py` 19 passedï¼Œ`tests/test_pool500_offline_eval_baseline.py` 4 passedï¼›100 ç”¨æˆ· raw eval ä¸­ TwoTower è´¡çŒ® 2460 æ�¡å€™é€‰ä½† `raw_two_tower_unique_positive_hits=0`ï¼Œwith/without ablation çš„ HitRate@500 å�‡ä¸º 0.01ï¼Œ`marginal_unique_positive_hits=0`ï¼Œå†³ç­–ä¸º `exclude`ã€‚
- é�¢è¯•å�¯è®²ç‚¹ï¼šä¸�æ˜¯å�ªçœ‹æ¨¡åž‹è®­ç»ƒ lossï¼Œè€Œæ˜¯æŠŠæ¨¡åž‹äº§ç‰©æŽ¥å…¥å€™é€‰ä¸»è·¯å�Žç”¨å›ºå®šè¯„ä¼°é›†ã€�source-level hit å’Œ ablation gate éªŒè¯�çœŸå®žä¸šåŠ¡å�¬å›žè´¡çŒ®ï¼›å�Œæ—¶é€šè¿‡å¥‘çº¦æµ‹è¯•é�¿å…�ä¸ºäº†è¯„ä¼°ä¾¿åˆ©ç ´å��ä¸»è·¯æ•°æ�®æ²»ç�†è¾¹ç•Œã€‚


## 2026-05-26 - TwoTower å�¬å›žå¤±è´¥åŽŸå›  label-rank è¯Šæ–­

- ä»»åŠ¡ï¼šè§£é‡Š formal full TwoTower å·²æŽ¥å…¥ä¸»è·¯ä½† 100 ç”¨æˆ·å›ºå®šè¯„ä¼° raw hit ä¸º 0 çš„åŽŸå› ã€‚
- é�‡åˆ°çš„é—®é¢˜ï¼šä»…çœ‹è®­ç»ƒ loss å’Œ source å€™é€‰è´¡çŒ®æ— æ³•åˆ¤æ–­å�Œå¡”å¤±è´¥æ˜¯æŽ¥å…¥é—®é¢˜ã€�item universe è¦†ç›–é—®é¢˜ã€�ç”¨æˆ·å�‘é‡�ç¼ºå¤±ï¼Œè¿˜æ˜¯ label rank å¤ªé� å�Žã€‚
- å®šä½�æ–¹å¼�ï¼šå¯¹ 100 ä¸ªå›ºå®š eval ç”¨æˆ·é€� label è®¡ç®— TwoTower å…¨é‡� item æ‰“åˆ† rankï¼Œå¹¶è¡¥æŸ¥ç¼ºå¤± user embedding ç”¨æˆ·çš„ train-only åŽ†å�² seed æ˜¯å�¦å­˜åœ¨äºŽ item indexã€‚
- è§£å†³æ–¹å¼�ï¼šä¸�é‡�æ–°è®­ç»ƒã€�ä¸�ä½¿ç”¨ label æ³¨å…¥å€™é€‰ï¼Œå�ªç¦»çº¿è¯»å�– eval label å�š evaluation-only rank auditï¼›ç»Ÿè®¡ label in-universeã€�query vector æ�¥æº�ã€�TopK hit å’Œ rank åˆ†å¸ƒã€‚
- éªŒè¯�ç»“æžœï¼š142 ä¸ª label ä¸­å�ªæœ‰ 75 ä¸ªåœ¨ TwoTower item universeï¼›å�¯ rank label ä¸º 59 ä¸ªï¼ŒTop20/Top50 ä¸º 0ï¼ŒTop500 ä»… 4 ä¸ªï¼Œä¸­ä½� rank 39549ï¼Œå¹³å�‡ rank 66521ï¼›18 ä¸ªç¼ºå¤± user embedding çš„ç”¨æˆ·éƒ½å�ªæœ‰ 1 ä¸ª recent positiveï¼Œä¸” seed item å…¨éƒ¨ä¸�åœ¨ item indexï¼Œæ— æ³• fallbackã€‚
- é�¢è¯•å�¯è®²ç‚¹ï¼šé€šè¿‡ label-rank è¯Šæ–­æŠŠâ€œæ¨¡åž‹æ•ˆæžœå·®â€�æ‹†æˆ�å�¯æ‰§è¡Œé—®é¢˜ï¼šitem universe è¦†ç›–ä¸�è¶³ã€�å†·/å¼±ç”¨æˆ· query ç¼ºå¤±ã€�ä»¥å�Šè®­ç»ƒç›®æ ‡å¯¼è‡´æ­£æ ·æœ¬ rank å¤§å¹…é� å�Žï¼Œè€Œä¸�æ˜¯ç›²ç›®åŠ  epoch æˆ–æ‰©å¤§è®­ç»ƒã€‚


## 2026-05-26 - TwoTower min_frequency=5 å°�æ ·æœ¬è¯Šæ–­å®žéªŒ

- ä»»åŠ¡ï¼šéªŒè¯�é™�ä½Ž TwoTower item vocab é¢‘çŽ‡é—¨æ§›æ˜¯å�¦èƒ½æ”¹å–„ formal full å�Œå¡”åœ¨å›ºå®šè¯„ä¼°ç”¨æˆ·ä¸Šçš„ label è¦†ç›–å’Œ rankã€‚
- é�‡åˆ°çš„é—®é¢˜ï¼šformal full ä½¿ç”¨ `min_frequency=20`ï¼Œå¯¼è‡´ 100 ç”¨æˆ· eval label å�ªæœ‰ 52.8% åœ¨ item universeï¼Œå¼±ç”¨æˆ· seed è¦†ç›–ä¹Ÿä¸�è¶³ï¼›ä½†ç›²ç›®æ‰©å¤§ vocab ä¼šå¢žåŠ æ£€ç´¢ç©ºé—´å¹¶å�¯èƒ½ç¨€é‡ŠæŽ’åº�ä¿¡å�·ã€‚
- å®šä½�æ–¹å¼�ï¼šå…ˆæ‰«æ�� `min_frequency=20/10/5/3/2/1` çš„ train-only è¦†ç›–ï¼Œå†�æž„é€  `min_frequency=5`ã€�100 ç”¨æˆ·ã€�1 epochã€�16 ç»´ã€�20 negatives çš„å°�æ¨¡åž‹è¯Šæ–­å®žéªŒï¼Œå¹¶ç”¨å�Œä¸€ label-rank å�£å¾„æ¯”è¾ƒã€‚
- è§£å†³æ–¹å¼�ï¼šç”Ÿæˆ� train-only min_freq=5 item vocabï¼ˆ703240 itemsï¼‰ï¼Œå�ªç”¨ 100 ä¸ªå›ºå®šè¯„ä¼°ç”¨æˆ·çš„ train history è®­ç»ƒè¯Šæ–­æ¨¡åž‹ï¼›valid/test label å�ªç”¨äºŽç¦»çº¿ rank auditï¼Œä¸�è¿›å…¥è®­ç»ƒæˆ–å€™é€‰ç”Ÿæˆ�ã€‚
- éªŒè¯�ç»“æžœï¼šmin_freq=5 å°† label è¦†ç›–ä»Ž 75/142 æ��å�‡åˆ° 93/142ï¼Œç”¨æˆ· embedding è¦†ç›–ä»Ž 82/100 æ��å�‡åˆ° 95/100ï¼›ä½† rank æ˜¾è‘—å�˜å·®ï¼ŒTop500=0ã€�Top10000=2ï¼Œrank ä¸­ä½�æ•° 353964ï¼Œè¯´æ˜Žä»…æ‰©å¤§ universe ä¸�è¶³ä»¥æ”¹å–„å�¬å›žï¼Œå��è€Œæš´éœ²è®­ç»ƒç›®æ ‡/è´Ÿé‡‡æ ·ä¿¡å�·ä¸�è¶³ã€‚
- é�¢è¯•å�¯è®²ç‚¹ï¼šé€šè¿‡å°�æ ·æœ¬å�¯æŽ§å®žéªŒéªŒè¯�â€œè¦†ç›–ä¿®å¤�ä¸�æ˜¯å……åˆ†æ�¡ä»¶â€�ï¼Œé�¿å…�ç›´æŽ¥æ‰©å¤§ full æ¨¡åž‹èµ„æº�ï¼›ä¸‹ä¸€æ­¥åº”æ”¹è®­ç»ƒç›®æ ‡å’Œè´Ÿé‡‡æ ·ï¼Œè€Œä¸�æ˜¯å�•çº¯é™�ä½Ž item é¢‘çŽ‡é—¨æ§›ã€‚


## 2026-05-26 - TwoTower 小 batch 加速与远程实验配置

- 任务：为 pool500 TwoTower 训练补齐小 batch 下的吞吐优化能力，并让远程服务器训练/评估 sweep 可以直接通过配置或 CLI 控制。
- 遇到的问题：当前训练只有物理 batch size，无法在显存受限时保持较大有效 batch；AMP 也没有显式开关，远程 GPU 长跑难以稳定复用同一套配置。
- 定位方式：检查 `rs_core/recsys/two_tower.py`、`rs_core/workflow/two_tower_training.py`、`scripts/training/train_two_tower.py` 和 diagnostic runner，确认此前没有 `gradient_accumulation_steps` / `mixed_precision` 支持。
- 解决方式：在 PyTorch 训练路径加入梯度累积、CUDA AMP 安全开关、`effective_batch_size`/`optimizer_steps` 记录；CLI 和 diagnostic loop 透传同名参数；formal full 配置调整为 `batch_size=2048`、`gradient_accumulation_steps=4`、`effective_batch_size=8192`、`mixed_precision=true`，并同步采用更适合泛化的 TwoTower 调参默认值。
- 验证结果：`./.venv/Scripts/python.exe -m pytest tests/test_two_tower_training.py tests/test_pool500_two_tower_diagnostic_loop.py -q` 结果为 41 passed；`ruff check` 覆盖变更文件后通过；独立 verifier 复跑 CUDA 隐藏设备场景后通过。
- 面试可讲点：这一步不是单纯“提速”，而是把推荐模型训练从固定物理 batch 改造成可控有效 batch，并把训练吞吐、显存策略和可复现实验记录写入 artifact，为后续远程 10k/50k/150k 用户 sweep 提供工程化基础。

### 2026-05-26 - RAG 候选内证据选择器落地

- 任务：把 RAG 从规划项收敛为可用的候选内证据选择器，并补齐文档与工程叙事。
- 遇到的问题：必须同时满足解释可用、候选不变、可回滚和证据净化，不能让 label / holdout / oracle 类字段混入解释。
- 定位方式：核对 `rag.evidence_mode` 三态、`rag.max_evidence_per_item`、provenance gate，以及 shadow / explain 下的 `rag_context` 与 display payload。
- 解决方式：明确 `off` / `shadow` / `explain` 语义，保持 `candidates`、`ranking`、`final_items`、`scores` 不变，把不安全证据从 `source` / `provenance` / `source_path` / `artifact_scope` 侧拦截。
- 验证结果：`pytest tests/test_rag_core.py tests/test_agent_dialogue.py tests/test_agent_rollout_schema.py tests/test_agent_runtime.py tests/test_display_contract.py` 共 `45 passed in 0.59s`；`py_compile` 通过；最小脚本验证 `shadow` / `explain` 均有 `rag_context_exists=true`、`kept_evidence_count=3`，`explain` 的 why 使用 Audio evidence，display payload 未暴露 `rag_context` / diagnostics。
- 面试可讲点：可以讲成“先把 RAG 做成候选内证据层，再通过模式开关、证据门禁和展示边界把它做成可回滚、可审计、不会污染主链路的解释能力”。


## 2026-05-26 - Agent 联调用 `/recommend` 线上推荐入口

- 任务：为推荐 Agent tool 联调新增 stateless 线上推荐服务入口，使 Agent 可以直接传入用户历史序列并获得真实召回、排序后的商品展示结果。
- 遇到的问题：原 serving 层主要是 sessionful demo `/chat`/`/feedback`，没有无需 session 的推荐接口；离线 pool500 runner 又包含 manifest、audit、output_dir 写入等副作用，不适合直接放进请求路径。
- 定位方式：检查 `rs_core/serving/app.py`、`rs_core/serving/schema.py`、`rs_core/serving/service.py` 与 `rs_core/workflow/hybrid_demo.py`，确认可复用 `recommend_for_user(...)` 作为真实召回排序入口，并用 display builder 收敛 public payload。
- 解决方式：新增 `rs_core/workflow/online_recommendation.py` 作为纯在线 adapter；在 `RecommendationService` 增加 `recommend_from_sequence(...)`；在 FastAPI 暴露 `POST /recommend`；请求 schema 递归拒绝 `label/target_item/ground_truth/holdout` 等 evaluation-only 字段，响应不暴露 score/source/ranking/diagnostics。
- 验证结果：`tests/test_serving_recommend_from_sequence.py` 5 个新增用例通过；`test_serving_smoke.py`、`test_agent_runtime.py`、`test_pool500_fallback_completion_route.py` 回归合计 `38 passed in 1.08s`；changed serving modules `py_compile` 通过。全量包含 `test_hybrid_demo.py` 的命令仍有既有配置文件缺失失败，与本次 `/recommend` 改动无关。
- 面试可讲点：把离线推荐实验链路抽象为无副作用的在线 adapter，并通过 schema 和测试守住“评估标签不进候选生成、内部排序证据不外泄”的边界，实现了 Agent tool 可调用的真实推荐闭环。
