# ItemCF weak 非最佳实验产物清理记录（2026-06-07）

## 保留的当前最佳实践

当前唯一保留为主路默认接入的 ItemCF weak source：

- `outputs/recall/pool500_method_sources/recent_2y/itemcf_weak/src3_dst3_user2_keep_hot_cosine_v1/source_index_manifest.json`
- 口径：`src>=3 / dst>=3 / user_after_item>=2 / keep_hot / cosine`
- row/edge count：`16,454,229`
- shard count：`64`
- 状态：`READY_GUARDED_SOURCE_ADAPTER_READY`，但仍保持 `DIAGNOSTIC_ONLY`、不打开 ranking replacement / promotion / pool1000。

当前保留的验证产物：

- `outputs/recall/full_data_pool500_recall_only/itemcf_weak_src3_dst3_user2_keep_hot_cosine_smoke1000_v2/`
- 1000-user isolated smoke：`itemcf_weak` 贡献 `19,540` 行，覆盖 `643/1000` 用户，marginal share `0.03908`。

## 删除原则

- 删除对象只限 ItemCF weak 非最佳实验数据、旧 formal/strict source、旧 src2 matrix、旧 route smoke 或远程非最佳 grid rows。
- 不删除当前 `src3_dst3_user2_keep_hot_cosine_v1` source。
- 不删除小体积 evaluation/diagnostic report，保留为后验证据。
- 删除后需重新验证当前 source loader 可用。

## 本轮已删除清单

执行状态：已删除并验证。

### 本地删除

| 路径 | 大小 | 原因 |
| --- | ---: | --- |
| `outputs/recall/pool500_method_sources/recent_2y/itemcf_weak/formal_strict_v1` | 14,272,957 B | strict formal 旧失败诊断 source，不是当前 latest artifact |
| `outputs/recall/pool500_method_sources/recent_2y/itemcf_weak/smoke_strict_v1` | 3,323,647 B | strict smoke 旧 schema 产物，不参与当前构建 |
| `outputs/recall/itemcf_matrices/recent_2y/itemcf_weak_keep_hot_src2_dst3_filter_before_build_traditional_matrix_v1` | 1,200,994,916 B | src2/dst3 旧矩阵，已被 src3/dst3 source adapter 取代 |
| `outputs/recall/itemcf_matrices/recent_2y/itemcf_weak_keep_hot_src2_dst3_traditional_matrix_v1` | 1,123,912,453 B | src2/dst3 旧矩阵，已被 src3/dst3 source adapter 取代 |
| `outputs/recall/full_data_pool500_recall_only/itemcf_formal_limit100_smoke20` | 47,033,467 B | 旧 formal smoke |
| `outputs/recall/full_data_pool500_recall_only/itemcf_formal_seedhit_smoke20` | 47,786,757 B | 旧 formal seed-hit smoke |
| `outputs/recall/full_data_pool500_recall_only/itemcf_quality_filtered_20260523_235746_smoke20` | 64,504,241 B | 旧 quality-filtered smoke |
| `outputs/recall/full_data_pool500_recall_only/itemcf_weak_sharded_full_smoke100` | 315,275,922 B | 旧 weak sharded smoke |
| `outputs/recall/full_data_pool500_recall_only/itemcf_weak_sharded_full_smoke20` | 72,619,846 B | 旧 weak sharded smoke |
| `outputs/recall/full_data_pool500_recall_only/itemcf_weak_sharded_smoke20` | 72,876,201 B | 旧 weak sharded smoke |

本地预计释放约 `2.96 GB`。

### 远程删除

| 路径 | 大小 | 原因 |
| --- | ---: | --- |
| `/mnt/data/luo/RS_agent_remote_storage/outputs/recall/pool500_method_datasets/recent_2y/itemcf_weak_cold_filtered_valgrid_20260606c/cold_u2_i2_cosine_seed200` | 19,876,715,831 B | 非最佳 grid variant |
| `/mnt/data/luo/RS_agent_remote_storage/outputs/recall/pool500_method_datasets/recent_2y/itemcf_weak_cold_filtered_valgrid_20260606c/cold_u3_i2_cosine_seed200` | 18,989,726,703 B | 非最佳 grid variant |
| `/mnt/data/luo/RS_agent_remote_storage/outputs/recall/pool500_method_sources/recent_2y/itemcf_weak/itemcf_weak/weak_denoised_v1_remote_20260606e` | 19,340,400,269 B | 旧 weak_denoised source，已被 src3/dst3 当前 source 取代 |
| `/mnt/data/luo/RS_agent_remote_storage/outputs/recall/itemcf_matrices/recent_2y/itemcf_weak_keep_hot_src2_dst3_filter_before_build_traditional_matrix_v1` | 1,200,573,551 B | src2/dst3 旧矩阵 |
| `/mnt/data/luo/RS_agent_remote_storage/outputs/recall/full_data_pool500_recall_only/itemcf_weak_src3_dst3_user2_keep_hot_cosine_smoke1000_v1` | 0 B | 失败/空 smoke 目录 |

远程预计释放约 `59.4 GB`。

## 不删除但可后续评估的对象

- 远程最佳 `cold_u2_i3_cosine_seed200` method dataset rows：约 `18.7 GB`。它是当前 source 的构建输入与审计依据，暂不删除；如果后续确认 source manifest + shard 已足够作为 canonical artifact，可再单独归档或删除 rows。
- 小体积 diagnostic/evaluation reports：保留为 valid 后验证据。

## 删除后验证

- 本地清理验证：所有登记删除路径均已不存在；当前最佳 source manifest 仍存在；当前 1000-user smoke evidence 目录仍存在。
- 远程清理验证：所有登记删除路径均已不存在；远程当前最佳 source manifest 仍存在；远程最佳 `cold_u2_i3_cosine_seed200` method dataset rows 仍保留。
- loader 验证命令：使用项目默认 `.venv/Scripts/python.exe` 调用 `load_itemcf_source_manifest(...)`。
- loader 验证结果：`manifest_exists=True`、`loaded_src_count=1`、`candidate_count=22`、sample item `B08D9BXTC4`、sample score `0.064519`。

## 配置同步

- `configs/recall/full_data_pool500/itemcf_weak/source_config.yaml`：旧 `smoke_strict_v1` 与旧 src2/dst3 matrix manifest 引用改为非当前/已清理记录，当前 source 仍指向 `src3_dst3_user2_keep_hot_cosine_v1`。
- `configs/recall/full_data_pool500/itemcf_weak/dataset_policy.yaml`：当前 matrix 改为 `null`，明确当前使用 source adapter；historical strict report 改为已清理记录。
- `configs/recall/pool500_method_registry.json`：`latest_matrix_manifest` 改为 `null`，矩阵 readiness 改为历史非选定 artifact 已删除；source readiness 保持当前 source adapter。
- `dic/recall_methods/itemcf_weak/METHOD.md`：补充旧 strict/source 与旧 matrix 已清理，当前以 `src3_dst3_user2_keep_hot_cosine_v1` source adapter 为准。
