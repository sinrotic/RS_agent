# two_tower

## 方法定位
向量召回 / 双塔召回，本项目中对应 YouTubeDNN 路线。当前产物用于补齐 pool500 主路生成的 `two_tower` 召回源加载合同：它是 full-clean train-only 的主路生成 artifact，不是长期 READY 晋升结论。

## 当前 readiness
- 状态：`MAIN_ROUTE_ARTIFACT_ONLY`
- source manifest：`outputs/recall/pool500_full_sources/two_tower/source_index_manifest.json`
- recall_index_path：`outputs/recall/pool500_full_sources/two_tower/training/runs/full_clean_heavy28_20260519_0001/artifact_manifest.json`
- model_type：`youtube_dnn_two_tower_v1`
- source_name：`two_tower_youtube_dnn`
- index_scope：`FULL_DERIVED_INDEX`

## 治理契约
- 只允许作为 pool500 主路候选生成 artifact 被 runner 加载，不等于长期 READY。
- `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`、`auto_promotion_allowed=false`、`promotion_allowed=false`、`final_pool500_ready_claimed=false`。
- 不复用旧 `outputs/training/two_tower/two_tower_training/youtube_dnn/artifact_manifest.json`，不使用 holdout、valid、test、LOPO、clean_10000 或 pool1000 作为训练/晋升证据。
- user_quality 只作为 train-only 资源治理与覆盖审计 policy，不是 recall source，也不是 READY 证据。

## 输入 artifact
- full clean manifest：`data/processed/amazon_2023_recall_clean_full/manifest.json`
- train sequence：`data/processed/amazon_2023_recall_clean_full/user_sequences.train.jsonl`
- lightweight views manifest：`data/processed/amazon_2023_recall_views_full_lightweight/manifest.json`
- item universe：`category_recall_items.jsonl` + `popular_recall.jsonl`
- user_quality policy：`outputs/recall/pool500_user_quality/heavy_probe_limit5000_train_only/eligible_user_quality_manifest.json`
- 实际训练 bucket：`heavy_cf_eligible`，`user_quality_selected_user_count=28`，`user_quality_matched_user_count=28`

## 输出 artifact
- final source manifest：`outputs/recall/pool500_full_sources/two_tower/source_index_manifest.json`
- official training run：`outputs/recall/pool500_full_sources/two_tower/training/runs/full_clean_heavy28_20260519_0001/`
- model：`two_tower_model.json`
- train config：`train_config.json`
- item embeddings：`item_embeddings.jsonl`
- user embeddings：`user_embeddings.jsonl`
- raw recall index：`two_tower_recall_index.jsonl`
- artifact manifest：`artifact_manifest.json`

## lineage / hash / count
来自 `source_index_manifest.json`：
- `clean_manifest_sha256=2d17ca5b176383919da60f1e8df7abaa90504b6da78ee8b4302132148c03eba0`
- `train_sequence_sha256=d47c9a3476f35f0c8bd88947b58f8a3f0ef83383f587d8d0e3102b6dbf1baf07`
- `item_universe_sha256=1df0a078c593f1e5c4f13140b52a3bbf4f2e49ee2908e5c421610a0a5f2d68c9`
- `model_config_sha256=d68026be43661e0299e672f028b4dd386fb7d3f8c7ba83c6a6d03ac201b83580`
- `artifact_manifest_sha256=14b79fe9a454fd66c157b00f58019777bc68e2c1464f56d95f6f124b3c02244a`
- `item_embedding_row_count=2320263`
- `recall_index_row_count=2320263`
- `user_embedding_row_count=28`
- `vector_index_item_count=2320263`

## 资源画像
official heavy28 训练指标：
- backend：PyTorch / CUDA，设备 `NVIDIA GeForce RTX 4070 Ti SUPER`
- `training_seconds=418.684`
- `peak_cuda_memory_mb=2031.855`
- `users_with_training_rows=28`
- `positive_interactions=560`
- `item_count=2320263`
- `embedding_dim=32`
- `epochs=3`
- `batch_size=512`

曾尝试 `heavy_probe_limit5000_train_only` 全 policy 训练，但该路径出现重复长任务且预计资源时间过高；已停止，改为 `heavy_cf_eligible` bucket 作为受控 official artifact。

## 验证结果
- builder 单测：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_pool500_two_tower_source_manifest.py -q`，结果 `6 passed`。
- two_tower focused：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_two_tower_training.py tests/test_pool500_two_tower_source_manifest.py -q`，结果 `16 passed`。
- runner 合同回归：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_full_data_pool500_recall_only.py -q`，结果 `4 passed`。
- ruff：触及 Python 文件 `All checks passed!`。
- VectorIndex 加载校验：`is_vector_index=True`，`items=2320263`，`users=28`，`source_name=two_tower_youtube_dnn`。
- runner smoke：`outputs/recall/pool500_full_sources/two_tower/runner_smoke_20260519_0001/manifest.json`，`processed_users=5`，`candidate_rows=955`，`source_coverage.two_tower=150`。该 smoke 的 `STOP` 来自 readiness gate/underfill/swing stoploss，是预期保守状态，不影响 two_tower artifact 可加载与候选生成证据。

## 主窗口调用
```bash
--source-manifest two_tower=outputs/recall/pool500_full_sources/two_tower/source_index_manifest.json
```

## 下一步
若要从 `MAIN_ROUTE_ARTIFACT_ONLY` 继续推进到长期 READY，需要单独做更大规模 user_quality 覆盖、ANN/索引性能评估、valid/test/LOPO 外部验证和 promotion gate 审核；本次不声明 READY、ranking replacement 或 pool1000。
