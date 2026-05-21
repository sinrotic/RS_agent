# semantic_title_category_expansion

## 方法定位

`semantic_title_category_expansion` 是 pool500 主路中的语义 / 标题 / 类目扩展召回源，基于用户近期 seed item 的 title token 与 category overlap 生成补充候选。当前定位是 `BATCH_SCOPED_DIAGNOSTIC` 证据源：用于证明 direct recall 中可产生稳定候选贡献，但不声明 pool500 READY，不允许替换 ranking input，也不允许进入 pool1000。

## 当前 readiness

- 状态：`DEFERRED`
- 本轮 evidence status：`BATCH_SCOPED_DIAGNOSTIC`
- source manifest：`outputs/recall/full_semantic_title_category_expansion/source_index_manifest.json`
- index_scope：`FULL_DERIVED_INDEX`
- no_holdout audit：`outputs/recall/full_semantic_title_category_expansion/no_holdout_audit.json`，状态 `PASS`
- resource audit：`outputs/recall/full_semantic_title_category_expansion/resource_audit.json`，状态 `PASS`
- 禁止授权：`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`、`full_ready_declared=false`

## 输入 artifact

- source manifest builder：`rs_lab/experiments/recall/build_full_semantic_title_category_manifest.py`
- clean full manifest：`data/processed/amazon_2023_recall_clean_full/manifest.json`
- full lightweight views manifest：`data/processed/amazon_2023_recall_views_full_lightweight/manifest.json`
- canonical items：`data/processed/amazon_2023_recall_clean_full/canonical_items.jsonl`
- semantic recall inputs：`data/processed/amazon_2023_recall_views_full_lightweight/semantic_recall_inputs.jsonl`
- semantic inverted index：`data/processed/amazon_2023_recall_views_full_lightweight/semantic_inverted_index.jsonl`

Source manifest 记录的规模：

- `canonical_items.row_count=2320263`
- `semantic_recall_inputs.row_count=2320263`
- `semantic_inverted_index.row_count=1456251`

上述输入由 source manifest 记录 sha256 与 row_count，且 no-holdout audit 未发现 holdout、valid、test、LOPO、clean_10000 输入。

## Source manifest 生成

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m rs_lab.experiments.recall.build_full_semantic_title_category_manifest --overwrite
```

关键结果：

- `source=semantic_title_category_expansion`
- `index_scope=FULL_DERIVED_INDEX`
- `source_index_manifest.json.status=PASS`
- `resource_audit.json.status=PASS`
- `no_holdout_audit.json.status=PASS`
- `candidate_generation_allowed=false`
- `ranking_input_replacement_allowed=false`
- `pool1000_allowed=false`
- `full_ready_declared=false`

## Direct recall probe 证据

受控 probe 命令：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m rs_lab.experiments.recall.run_full_data_pool500_recall_only \
  --output-dir outputs/recall/full_data_pool500_recall_only_semantic_covisit_probe_50x200k \
  --enable-semantic \
  --semantic-max-rows 200000 \
  --limit-users 50 \
  --overwrite
```

关键输出：

- `manifest.json.status=STOP`，原因是整体 readiness/underfill gate，符合“不做 READY 晋升”的预期。
- `pool500_candidates.jsonl` 总行数：6152。
- `pool500_candidates.jsonl.sources.semantic_title_category_expansion=640`。
- `source_contribution_audit.sources.semantic_title_category_expansion.row_count=640`。
- `source_contribution_audit.sources.semantic_title_category_expansion.user_coverage_count=47`，`user_coverage_ratio=0.94`。
- `source_contribution_audit.sources.semantic_title_category_expansion.marginal_candidate_share=0.104031`。
- `final_resource_audit.source_row_counts.semantic_title_category_expansion=640`。
- per-source manifest：`sources/semantic_title_category_expansion/manifest.json.status=BATCH_SCOPED_DIAGNOSTIC`。
- per-source manifest：`final_sources=[]`，`batch_scoped_evidence_only=true`。
- `per_source_readiness_contracts.semantic_title_category_expansion.status=BATCH_SCOPED_DIAGNOSTIC`。

## 语义输入覆盖

`outputs/recall/full_data_pool500_recall_only_semantic_covisit_probe_50x200k/semantic_input_manifest.json`：

- `batch_user_count=50`
- `batch_seed_item_count=92`
- `semantic_max_rows=200000`
- `item_universe_count=200092`
- `item_universe_coverage=92/92=1.0`
- `title_coverage=200068/200092=0.99988`
- `category_coverage=200092/200092=1.0`
- `clean_title_token_coverage=200036/200092=0.99972`

该覆盖率足以支撑 title/category expansion 的小批候选贡献判断。

## `--semantic-max-rows` 建议

- 旧 smoke 口径 `semantic-max-rows=5000` 已出现明显截断：`item_universe_count=5038 = 5000 + seed_count(38)`。
- 本轮 `semantic-max-rows=200000` 能稳定产出 `semantic_title_category_expansion` 候选贡献，当前作为 pool500 direct recall batch-scoped evidence 已够用。
- 本轮 50 用户 probe 中仍可见 `item_universe_count=200092 = 200000 + seed_count(92)` 的截断迹象；如后续目标变为更宽覆盖或更大用户批次，可再评估 `500000`，但不建议在本轮直接调高，因为 `1000 users × 200000 rows` 已表现为长时间重资源任务。

## 治理边界

- 只使用 full clean train-visible / full lightweight semantic outputs。
- 不使用 holdout、valid、test、LOPO、clean_10000。
- 不使用 youtube_dnn、pool1000 或 ranking replacement 证据。
- 当前 evidence 只能证明 batch-scoped candidate contribution，不能证明 full READY。
- 不设置 `ranking_input_replacement_allowed=true`、`pool1000_allowed=true`、`promotion_allowed=true`。
- 未完成更强 full-clean-safe readiness contract 前，不得宣称 READY、promotion、ranking input replacement 或 pool1000。

## 专项优化 Agent 调用说明

后续单独调用 Agent 优化本方法时，应优先围绕 title/category overlap 的覆盖率、去重后边际贡献、underfill 改善与资源边界做诊断。Agent 必须保持 `deferred_evidence_policy`，禁止使用 holdout/valid/test/clean_10000/LOPO 等证据；未形成 full-clean-safe source manifest 与 readiness contract 前，不得宣称 READY、ranking input replacement 或 pool1000。
