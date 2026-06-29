# semantic

## 方法定位

`semantic` 是 pool500 的 canonical 语义 metadata 召回 source，用于基于 train-only 商品标题、类目、描述、features 与用户/Agent 的自然语言需求生成同类商品候选。当前 recent-2y 结论已从纯 `DIAGNOSTIC_ONLY` 推进为 `READY_CANDIDATE` / guarded candidate source：允许作为受门禁保护的候选 source 接入 pool500 主路候选生成，但不得宣称 final READY，不替换 ranking input，不进入 pool1000，不自动 promotion。

`semantic_title_category_expansion` 现在不再单独作为强召回 source 晋升，而是折叠为 `semantic` 的 title/category channel：负责强化商品类型、标题核心词和类目先验，降低普通描述 token overlap 的噪声。manifest 与候选行中的 `source`、`canonical_source` 仍必须保持为 `semantic`，不能由 `semantic_title_category_expansion`、`semantic_title` 或 `full_metadata_overlap` 冒充。

## 统一配置与 runner

- 配置路径：`configs/recall/full_data_pool500/semantic/source_config.yaml`
- smoke / dry-run / source dispatch 统一入口：`scripts/experiments/recall/pool500/run_pool500_method_source.py`
- 档位：`smoke`、`recent2y_smoke`、`recent2y_formal`、`dam(diagnostic)`、`最终数据集(local_formal)`

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source semantic --tier smoke --dry-run
```

recent-2y smoke 构建：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source semantic --tier recent2y_smoke --run-id semantic_recent2y_smoke_v1 --overwrite
```

recent-2y formal target-slice 构建：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source semantic --tier recent2y_formal --run-id semantic_recent2y_formal_target10k_v1 --overwrite
```

显式 config smoke：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source semantic --config configs/recall/full_data_pool500/semantic/source_config.yaml --tier smoke --dry-run
```

## 输入 artifact

旧 full-data 输入只保留为历史参考，不能作为当前 recent-2y 结论：

- historical/default full clean manifest：`data/processed/amazon_2023_recall_clean_full/manifest.json`
- historical/default full lightweight views manifest：`data/processed/amazon_2023_recall_views_full_lightweight/manifest.json`
- historical/default eligible user manifest：`outputs/recall/pool500_main_route_direct_recall_full_promoted/eligible_user_manifest.json`

当前 recent2y smoke / formal 使用新数据路径，覆盖上面的历史默认输入：

- clean manifest：`data/processed/amazon_2023_recall_recent_2y_1m_3m/manifest.json`
- recall views manifest：`data/processed/amazon_2023_recall_recent_2y_1m_3m/recall_views/manifest.json`
- train-only governance manifest：`data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json`
- smoke eligible manifest：`outputs/recall/pool500_method_sources_newdata/eligible_users_semantic_recent2y_smoke_v1/eligible_user_manifest.json`
- formal eligible manifest：`outputs/recall/pool500_method_sources_newdata/eligible_users_semantic_recent2y_formal_v1/eligible_user_manifest.json`
- train sequences：`data/processed/amazon_2023_recall_recent_2y_1m_3m/user_sequences.train.jsonl`
- canonical items：`data/processed/amazon_2023_recall_recent_2y_1m_3m/canonical_items.jsonl`
- semantic recall inputs：`data/processed/amazon_2023_recall_recent_2y_1m_3m/recall_views/semantic_recall_inputs.jsonl`
- semantic inverted index：`data/processed/amazon_2023_recall_recent_2y_1m_3m/recall_views/semantic_inverted_index.jsonl`

## 输出契约

必须生成七件套 source artifacts：

- `method_dataset_manifest.json`
- `source_index_manifest.json`
- `candidates.jsonl`
- `coverage_audit.json`
- `undercoverage_audit.json`
- `resource_audit.json`
- `no_holdout_audit.json`

核心 identity / governance 字段：

- `source=semantic`
- `canonical_source=semantic`
- `source_status=READY_CANDIDATE`
- `route_integration_status=GUARDED_CANDIDATE_SOURCE`
- `candidate_generation_allowed=false`（治理上仍不等于 final ready / ranking input replacement）
- `ranking_input_replacement_allowed=false`
- `pool1000_allowed=false`
- `promotion_allowed=false`
- `full_pool500_ready_declared=false`
- `final_pool500_ready_claimed=false`

## recent-2y 已完成证据

### smoke artifact

- manifest：`outputs/recall/pool500_method_sources_newdata/semantic/semantic_recent2y_smoke_v1/source_index_manifest.json`
- status：`PASS`
- target/user coverage：`200 / 200`
- candidate rows：`16000`
- candidate count：每用户 `80`
- no-holdout：`PASS`

### lean/reference-based candidate 存储策略

`semantic` 后续 source artifact 默认使用 `candidate_metadata_policy=lean_reference`。候选行只保留用户相关轻字段：`user_id`、`item_id`、`source`、`canonical_source`、`sources`、`source_scores`、`score`、`rank`、`semantic_token_overlap`、`semantic_category_overlap`。商品 title/category/description/features/brand/store 等 item metadata 不再按 user-item 行重复写入，而是通过 `item_id` 引用 recent-2y `semantic_recall_inputs.jsonl`；token 候选查找通过 `semantic_inverted_index.jsonl` 复核。这样避免 2y 数据集中已有 metadata 在 50k/full formal 候选文件中重复膨胀。

### formal target-slice artifact

- manifest：`outputs/recall/pool500_method_sources_newdata/semantic/semantic_recent2y_formal_target10k_v1/source_index_manifest.json`
- evaluation report：`outputs/recall/pool500_method_sources_newdata/semantic/semantic_recent2y_formal_target10k_v1/evaluation_report.json`
- status：`PASS`
- scope：本地 bounded target-slice `10000` 用户，不是完整 50k/no-cap formal
- candidate rows：`800000`
- user coverage：`10000 / 10000`
- candidate count min/p50/p90/max：`80 / 80 / 80 / 80`
- unique item count：`18452`
- seed item metadata coverage：`1.0`
- runtime：约 `154.5s`
- candidates 文件大小：约 `2.9GB`
- no-holdout：`PASS`，`forbidden_inputs=[]`，候选生成未使用 holdout/valid/test/LOPO/oracle/eval label

## guarded 主路接入状态

当前 artifact 证明 `semantic` 在 recent-2y train-only target-slice 上可构建、可覆盖、可审计；description-based 诊断证明它在明确商品描述下可以稳定召回同类商品。因此它已作为 `READY_CANDIDATE` / guarded candidate source 接入 pool500 主路候选生成：

- core registry：`rs_core/recsys/recall_sources/registry.py` 中 `semantic.readiness=READY_CANDIDATE`，`candidate_generating=True`。
- JSON registry：`configs/recall/pool500_method_registry.json` 中 `semantic.status=READY_CANDIDATE`。
- 主路 runner 默认 source manifest 指向 `outputs/recall/pool500_method_sources_newdata/semantic/semantic_recent2y_formal_target10k_v1/source_index_manifest.json`。
- 主路输出新增 `semantic_description_evidence_gate.json`，并在 `manifest.json.required_artifacts` 中引用。

这仍然不是 final READY / promotion：

1. formal 范围仍是 bounded 10k target-slice，不是完整 50k/no-cap formal。
2. strict stress fixture 仍有弱词误召回样例，需要继续优化 product-type gate、category prior、phrase index 或 rerank。
3. `ranking_input_replacement_allowed=false`、`pool1000_allowed=false`、`promotion_allowed=false`、`final_pool500_ready_claimed=false` 必须保持不变。

因此当前结论是“可作为 guarded 主路候选 source 使用”，而不是“完整 pool500 READY”。

## 治理边界

- 只使用 train-only 用户历史与静态 item metadata。
- 不使用 holdout、valid、test、LOPO、clean_10000、youtube_dnn、pool1000 证据作为候选生成或训练输入。
- 不用评估命中、label、oracle 反向筛选 metadata 或候选。
- 不宣称 full pool500 READY；`READY_CANDIDATE` 不等于 final READY。
- 不替换 ranking input。
- 不进入 pool1000。
- 如需晋升，后续必须另起 full-scale/server formal、Recall@K、source overlap/marginal gain 与 route gate 计划并显式验证。

## 后续优化方向

后续优化应围绕 metadata 覆盖、语义 token 质量、BM25/IDF scorer、字段权重、去重后边际贡献、underfill 改善和资源边界展开。dense embedding / hybrid ANN 可以作为 v2，但必须补齐 encoder/index reproducibility、corpus hash、index hash、远程重放和 no-holdout audit，且在通过 source gate 前不得包装为 READY 或正式 ranking 输入。

## 双 lane 边界

- **Lane A：rag_evidence** 只负责候选内证据检索、解释 grounding 和 undercoverage 诊断，不承担候选生成，不替代召回或排序。
- **Lane B：diagnostic_only / recall_candidate_source** 只允许输出 train-visible 的诊断候选与覆盖分析；若要进入后续主路，必须满足 frozen encoder reproducibility、remote reproducibility gate、dirty artifact no-promotion 和 candidate_scoped 约束。
- `candidate_generation_allowed=false`
- `ranking_input_replacement_allowed=false`
- `promotion_allowed=false`
- `candidate_scoped=true`
- 推荐在 manifest 中同时记录 `artifact_role`、`corpus_hash`、`index_hash`、`checkpoint_sha`、`tokenizer_sha`、`seed`、`build_command`、`build_env`。

## 描述式语义召回诊断

`semantic` / `semantic_title_category_expansion` 后续重点不再用单方法 valid purchase Recall 作为唯一成败判断。它们更适合作为 Agent/RAG 场景下的“自然语言描述 → 商品候选”检索能力：用户描述一个商品需求时，系统应优先召回标题、类目和商品类型真正匹配的 item。

正式诊断脚本：

```bash
./.venv/Scripts/python.exe scripts/experiments/recall/pool500/diagnose_semantic_description_recall.py --output-dir outputs/diagnostics/semantic_description_recall_strict_v2_20260608
```

诊断边界：

- 只读取 recent-2y train-visible `semantic_recall_inputs.jsonl` 与 `semantic_inverted_index.jsonl`。
- 不读取 valid/test/holdout/LOPO/oracle/eval_label。
- 不作为 promotion gate，不声明 READY，不替换 ranking input。
- 指标关注 description relevance：核心商品词、意图短语、类目先验、负例短语和 topK 严格意图命中。

### 正式模块化与等效提速

`diagnose_semantic_description_recall.py` 的检索与打分逻辑已抽到正式模块：

- `rs_core/agent/rag/semantic_description/scoring.py`：保留 `tokens`、`fixture_query_terms`、`evaluate_intent`、`score_record` 及 strict intent scorer，并加入 `PreparedFixture` / `PreparedRecord` 缓存。
- `rs_core/agent/rag/semantic_description/retrieval.py`：保留 train-visible inverted index lookup、candidate ordered unique、record loading 与 `(-score, item_id)` 排序，并将候选合并改成流式去重。
- `rs_core/agent/rag/semantic_description/engine.py`：提供 diagnostic / live retrieval 可复用入口；脚本层变成 thin wrapper。旧 `rs_core/recsys/semantic_description` active package 已删除。

等效验证：

```bash
./.venv/Scripts/python.exe -m pytest tests/test_pool500_semantic_description_diagnostic.py tests/test_semantic_description_scoring.py tests/test_semantic_description_retrieval_parity.py -q
```

结果：`11 passed in 0.10s`。优化后 strict speed probe 输出位于 `outputs/diagnostics/semantic_description_recall_strict_optimized_check2_20260608/semantic_description_recall_strict_report.json`，summary 指标与优化前保持一致：`avg_strict_precision_at_5=0.5`、`avg_strict_precision_at_10=0.483`、`avg_required_precision_at_10=0.75`、`avg_bad_intent_rate_at_10=0.267`、`queries_with_strict_hit_top5=8`；总耗时从此前 `102.187s` 降到 `43.291s`。

进一步新增等价 SQLite postings + records store：

- 构建脚本：`scripts/recall/build_semantic_description_index.py`
- 查询脚本：`scripts/experiments/recall/pool500/query_semantic_description_recall.py`
- 本地 SQLite index：`outputs/diagnostics/semantic_description_index_20260608_remote/semantic_description_index.sqlite`
- manifest：`outputs/diagnostics/semantic_description_index_20260608_remote/semantic_description_index.sqlite.manifest.json`

远程受控构建全量 recent-2y index：`postings_count=787005`、`records_count=864288`、index size 约 `3.3GB`、`runtime_seconds=65.27`，manifest 保持 `label_inputs_role=not_used`、`oracle_label_injection=false`、`ranking_input_replacement_allowed=false`。SQLite strict probe 输出位于 `outputs/diagnostics/semantic_description_recall_strict_sqlite_check_20260608/semantic_description_recall_strict_report.json`，与 baseline 在 summary、query stats、top10 item/score/details 上完全一致，总耗时 `31.044s`。单条 live query CLI 示例 `ceremonial binder ivory gold foil spine` 在 `candidate_limit=5000`、`per_token_limit=2000` 下耗时 `0.927s`，输出 `outputs/diagnostics/semantic_live_cli_binder_sqlite_20260608/result.json`。

进一步构建 prepared-record SQLite index：`outputs/diagnostics/semantic_description_index_prepared_20260608_remote/semantic_description_index.prepared.sqlite`，manifest 记录 `prepared_record_cached=true`、`display_columns_cached=true`，全量 remote 构建 `postings_count=787005`、`records_count=864288`、`runtime_seconds=225.016`。prepared SQLite strict probe 输出位于 `outputs/diagnostics/semantic_description_recall_strict_prepared_sqlite_check_20260608/semantic_description_recall_strict_report.json`，相对旧 SQLite strict report 在 summary、query stats、top10 item/score/details 上完全一致。live CLI 已改为直接调用 retrieval API，不再走诊断 report 生成链路；同一 binder query 在 `candidate_limit=5000` 下检索耗时约 `662ms`、CLI wall time `0.894s`，在 `candidate_limit=2000` 下检索耗时约 `265ms` 且该 probe top10 与 5000 完全一致，在 `candidate_limit=1000` 下检索耗时约 `148ms` 但 top10 已发生变化。

继续追加 trusted local performance cache：将 prepared record 拆成 columnar 字段，并为本地可信索引增加 `prepared_columnar_pickle` BLOB，避免 live query 时重复解析大 JSON payload；同时把 query token IDF/role weight 预计算到 fixture 级别，并缓存 padded phrase text。pickle SQLite strict probe 输出位于 `outputs/diagnostics/semantic_description_recall_strict_pickle_sqlite_check_20260608/semantic_description_recall_strict_report.json`，相对 prepared SQLite report 继续保持 summary、query stats、top10 item/score/details 完全一致。binder query in-process warm latency 进一步降为：`candidate_limit=2000` 约 `180ms`，`candidate_limit=5000` 约 `466ms`；CLI 分别约 `191ms` retrieval / `0.467s` wall、`466ms` retrieval / `0.688s` wall。汇总证据：`outputs/diagnostics/semantic_live_latency_prepared_sqlite_20260608/summary.json`。因此 Agent 实时接入建议复用 in-process `SQLiteSemanticDescriptionStore`，默认走 precision-first `candidate_limit=1000` 快线；本次 binder probe 默认 1000 的 in-process warm latency 约 `85ms`，CLI retrieval latency `93ms`、wall time `0.328s`。当 topK 置信度弱、候选 underfill、query 过泛或需要更保守召回面时，再自动升档到 `candidate_limit=2000` / `5000`。

默认 1000 candidate 的随机商品 prompt probe 输出位于 `outputs/diagnostics/semantic_random_prompt_default1000_20260608/report.json`。该 probe 从 recent-2y train-visible 商品中抽 8 个样例，由标题/类目人工写自然语言需求，不使用 label/oracle 构造 query；结果为 `query_count=8`、`source_top10_count=2`、`avg_strict_precision_at_10=0.562`、`avg_required_precision_at_10=0.738`、`avg_bad_intent_rate_at_10=0.212`、batch 平均约 `171ms/query`。这说明默认 1000 在明确商品词上能召回高相关同类商品，但对防水连接器、GoPro 型号配件、车机车型适配、电视附件排除等弱词/型号约束仍需要 Agent query rewrite 与质量门禁 fallback。

Agent/serving 主路已接入 optimized live retrieval：`HybridRecommendationEnvironment.from_config()` 可通过 `semantic_description_live.enabled=true` 初始化单例 `SemanticDescriptionRecallEngine` 与 SQLite store；`retrieve_candidates` pre-recommendation 工具优先把用户自然语言 query 走 `semantic_live` source，并把结果作为 `extra_candidates` 合并进 `recommend_for_user()` 的正常候选池与排序链路。默认仍是 precision-first：`candidate_limit=1000`、`per_token_limit=2000`；tool 输出保持 compact，public display 不暴露 source/diagnostic/tool 字段。回归证据：`./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_agent_tools.py tests/test_semantic_description_index_store.py -q`，结果 `46 passed in 0.93s`。

当前 guarded evidence：

- random6 输出：`outputs/diagnostics/semantic_description_random6_20260608/semantic_description_recall_strict_report.json`
- random6 gate：`outputs/diagnostics/semantic_description_random6_20260608/semantic_description_evidence_gate.json`
- random6 decision：`PASS_GUARDED_CANDIDATE`
- `query_count=6`
- `avg_strict_precision_at_5=0.9`
- `avg_strict_precision_at_10=0.9`
- `avg_required_precision_at_10=1.0`
- `avg_bad_intent_rate_at_10=0.1`
- `queries_with_strict_hit_top5=6`

当前 strict stress 诊断：

- strict 输出：`outputs/diagnostics/semantic_description_recall_strict_v2_20260608/README.md`
- strict gate：`outputs/diagnostics/semantic_description_recall_strict_v2_20260608/semantic_description_evidence_gate.json`
- strict decision：`DIAGNOSTIC_ONLY`
- `query_count=12`
- `avg_strict_precision_at_5=0.5`
- `avg_strict_precision_at_10=0.483`
- `avg_required_precision_at_10=0.75`
- `avg_bad_intent_rate_at_10=0.267`
- `queries_with_strict_hit_top5=8`

结论：

- 明确标题/类目强约束的描述表现较好，例如 `wireless_mouse`、`gaming_keyboard`、`usb_c_hub`、`medical_clipboard`，random6 已通过 guarded candidate gate。
- 弱词或商品类型歧义明显的描述仍会偏移，例如 `yoga_mat` 被 storage strap / anti-fatigue mat 干扰，`dog_chew_toy` 被 cord protector / dog collar holder 干扰，`baby_stroller_organizer` 被 stroller fan 干扰，`cat_litter_mat` 缺少真正 mat 结果。
- 这说明语义召回已经具备“按描述找同类商品”的主路候选能力，但 strict stress 仍是优化 backlog；不能只靠 token overlap，也不能把 guarded candidate gate 包装成 final READY。
