# two_tower

## 方法定位

`two_tower` 是 pool500 召回层中的 embedding / ANN 候选生成方法，当前实现路线为 `youtube_dnn_two_tower_v1`。它的职责是基于用户 train-only 行为序列和 item embedding 补充向量近邻候选；不承担 ranking input replacement，也不自动晋升 pool1000 或 final pool500 ready。

本轮重建以 `amazon_2023_recall_recent_2y_1m_3m` 为当前唯一正式数据基础。旧 full-data / full-clean 产物只作为历史参考，不作为 current recent-2y 训练、效果或晋升结论。

## 当前 readiness

- 状态：`DIAGNOSTIC_ONLY`
- 当前结论：recent-2y smoke/formal 方法数据集、smoke training/source/candidate 链路、formal 687147 eligible-user epoch1/epoch5/queryv2 历史诊断均已补齐；最新稳定配置沉淀为 **sparse-aware formal + 串行 checkpoint sweep + epoch5 selected checkpoint**。
- 当前稳定证据：sparse-aware epoch5 在 valid-only direct eval 中表现最稳，500/5000/10000 valid users 的 `Recall@500` 分别为 `0.083861/0.068280/0.067054`，`HitRate@500` 分别为 `0.1020/0.0842/0.0846`；正式汇报优先引用 10000 valid users 结果（`Recall@500≈6.7%`、`HitRate@500≈8.5%`）。
- 主路接入边界：sparse-aware epoch5 已作为 pool500 recall-only 主路默认 `two_tower` diagnostic source 指针，但这只是默认诊断源切换，不等于 READY / promotion；该结果仍缺 route-level marginal lift、full pool500 candidate quality audit 和主路互补性证明。method-source 全量 valid 分母口径曾把部分用户候选生成结果稀释为 `Recall@500=0.000466`，不作为 checkpoint selection 主指标。
- 默认权限：`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`、`promotion_allowed=false`、`final_pool500_ready_claimed=false`。
- 2026-06-05 训练侧 challenger 结论：`recency_decay + example_age_decay + sampled_softmax_logq` 已在远程 GPU formal 训练并评估，但在 legacy direct-eval 口径下 `Recall@500=0.018786`、unique hits `13`，显著低于既有 epoch5/queryv2 baseline `Recall@500=0.070809`，也低于上一轮 `ns_v2_plus_recency` legacy 评估 `Recall@500=0.047688`；因此不作为新主线，只保留为 rejected diagnostic challenger。
- 2026-06-06 item side feature 20k preflight 结论：`item_quality_token + item_pop_bucket_token + item_user_count_bucket_token` 组合与三个 full-vocab 单字段消融均已完成远程 20k queryv2 同口径诊断。组合 run 因 item universe 收缩到 `340141` 导致 `queryless_user_count=22`；随后三个单字段消融均控制为 baseline item universe `499566`、`queryless_user_count=16`，但指标都只有 `Recall@500=0.024566`、`HitRate@500=0.032`、unique hits `17`，低于 epoch5/queryv2 baseline `Recall@500=0.070809`、`HitRate@500=0.092`、unique hits `49`；因此不进入 full formal，不作为新主线，只保留为 rejected diagnostic challengers。
- 2026-06-06 20k epoch 控制实验结论：baseline 20k 从 epoch1 增加到 epoch5 后，queryv2 指标仍为 `Recall@500=0.024566`、`HitRate@500=0.032`、unique hits `17`；而 687k epoch1 queryv2 已达 `Recall@500=0.052023`、unique hits `36`，687k epoch5/queryv2 达 `Recall@500=0.070809`、unique hits `49`。因此当前 gap 的主因不是 20k epoch 少，而是 20k 训练规模和有效 optimizer steps 太小；后续 preflight 需上调到更大训练规模或直接做 formal 级对照。

## SciOMC / RALPLAN 文档

- SciOMC 调研：`dic/recall_methods/two_tower/RECENT2Y_SCIOMC_RESEARCH.md`
- 低效果诊断调研：`dic/recall_methods/two_tower/RECENT2Y_LOW_EFFECT_DIAGNOSIS.md`
- RALPLAN 执行计划：`dic/recall_methods/two_tower/RECENT2Y_REBUILD_PLAN.md`

调研补充了 YouTubeDNN、DSSM、采样偏差修正、BPR、MIND、FAISS、ScaNN、PinSage 等论文/工业实践，并映射到本项目的 train-only 样本构造、负采样、ANN artifact 和 route gate。

## 治理契约

允许输入：

- `data/processed/amazon_2023_recall_recent_2y_1m_3m/manifest.json`
- `data/processed/amazon_2023_recall_recent_2y_1m_3m/canonical_interactions.train.jsonl`
- `data/processed/amazon_2023_recall_recent_2y_1m_3m/user_sequences.train.jsonl`
- `data/processed/amazon_2023_recall_recent_2y_1m_3m/canonical_items.jsonl`
- `data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/*`
- 本方法基于上述输入派生的 smoke/formal manifest 和训练产物。

禁止输入：

- holdout / valid / test 作为训练、负采样、item vocab、source index 构建输入。
- LOPO / oracle / eval label / clean_10000 / pool1000 诊断产物。
- 旧 full-data-derived method dataset 或 source artifact。
- 任何把 label 正样本直接注入候选池的产物。

valid/test 只能用于后续评估，不得回流到候选生成或训练。

## recent-2y 方法数据集

### smoke method dataset

- manifest：`outputs/recall/pool500_method_datasets/recent_2y/two_tower/smoke/method_dataset_manifest.json`
- 状态：`PASS`
- `train_sample_count=1999`
- `eligible_user_count=500`
- `negative_universe_item_count=335024`
- `training_item_universe_item_count=335144`
- `negative_ratio_requested=3`
- `used_negative_distinct_item_count=2027`
- 用途：程序、schema、负采样、manifest 与无泄漏审计验证；不能作为正式效果结论。

### formal method dataset

- manifest：`outputs/recall/pool500_method_datasets/recent_2y/two_tower/formal/method_dataset_manifest.json`
- 状态：`PASS`
- `train_sequence_rows_scanned=6826801`
- `eligible_user_count=687147`
- `train_sample_count=2812780`
- `negative_universe_item_count=335024`
- `training_item_universe_item_count=499566`
- `negative_ratio_requested=5`
- `used_negative_distinct_item_count=335024`
- `negative_item_usage_top10_share=0.000049`
- 用户桶：`collaborative_rich=49719`、`medium_behavior=90`、`sequence_sufficient=637338`
- target coverage：`sample_target_items_in_training_universe_count=455107`、`sample_target_items_missing_training_universe_count=0`
- 当前限制：formal dataset 已用于 full epoch1/epoch5 训练；queryv2 统一 query 构造后 coverage 与 Recall@500 均有提升，但 full pool500 candidate quality audit、互补性和 route-level marginal lift 证据仍不足，不能晋升 READY。

### sparse-aware method dataset policy（local verified）

2026-06-06 增加默认隔离的 sparse-aware 数据集 tier：`sparse_aware_smoke` / `sparse_aware_formal`。该 tier 不改变既有 `smoke/formal` baseline，而是在 train-only item quality / frequency / user sequence 上先做 item universe pruning，再统计 item 筛后 user 分布，用于验证“two_tower 指标低是否由 item 长尾和 post-prune 用户稀疏导致”。

新增画像口径：

- item 侧：`governance_item_quality_bucket_v2_counts`、negative universe 的 quality/frequency/user-count/pop-rank 分桶、`trainable_positive_target_universe_*`。
- user 侧：`pre_item_filter_user_count`、`post_item_filter_user_count`、`post_item_filter_dropped_user_count`、drop reason、prune 前后 positive/transition/retention 分桶、user bucket transition matrix。
- sample 侧：`eligible_user_quality_bucket_counts`、`sample_emitting_user_quality_bucket_counts`、`train_sample_quality_bucket_counts`、target outside negative universe 分桶。
- training universe：记录 `negative_only`、`target_only`、`both` role counts 和 quality-role counts。

默认 sparse-aware item policy：target universe 包含 `embedding_ready/cf_ready/mid_frequency`，并允许 `frequency>=2 && user_count>=2` 的 `low_frequency` 作为正样本 target；negative universe 只包含 `embedding_ready/cf_ready/mid_frequency`，避免低频 item 直接进入负采样主池。post-prune 用户要求 `post_positive_count>=2`、`post_unique_item_count>=2`、`post_transition_count>=1`。

本地验证：

- `./.venv/Scripts/python.exe -m py_compile rs_lab/experiments/recall/build_pool500_two_tower_method_dataset.py scripts/training/train_two_tower.py tests/test_pool500_two_tower_method_dataset.py tests/test_two_tower_training.py`
- `./.venv/Scripts/python.exe -m pytest tests/test_pool500_two_tower_method_dataset.py -q`：`16 passed, 3 skipped`
- WMI-safe `tests/test_two_tower_training.py -q`：`48 passed`
- `tests/test_train_only_data_governance.py -q`：`13 passed`
- `tests/test_pool500_two_tower_method_source.py tests/test_pool500_two_tower_direct_eval.py tests/test_two_tower_source_manifest_guard.py -q`：`11 passed`

该改动只补数据集画像、稀疏感知 tier 和远端训练 CLI override，不产出正式效果结论；`two_tower` 仍保持 `DIAGNOSTIC_ONLY`，所有 READY/promotion/ranking replacement gate 均不因本节改变。

### sparse-aware formal selected checkpoint（stable diagnostic）

当前可沉淀的稳定配置来自远端串行 checkpoint 训练：在 sparse-aware formal dataset 上单次训练到 epoch10，并保存 epoch `1/3/5/8/10` checkpoint。valid-only direct eval 用于选择 epoch，test 不参与调参。

训练与采样配置：

- output root：`/mnt/data/luo/RS_agent_remote_storage/outputs/two_tower_sparse_aware_serial_checkpoints`
- selected checkpoint：`checkpoints/epoch_5`
- source index：`direct_eval_comparison/source_index/epoch_5/source_index_manifest.json`
- variant：`youtube_dnn`
- `embedding_dim=64`、`hidden_dim=128`、`learning_rate=0.0001`
- 串行训练 `epochs=10`，选择 `selected_epoch=5`，`checkpoint_epochs=[1,3,5,8,10]`
- `batch_size=2048`、`gradient_accumulation_steps=4`、`effective_batch_size=8192`、`mixed_precision=true`
- `negative_samples=512`、`negative_sampling_power=0.75`
- `max_samples_per_user=20`、`min_user_positives=2`、`user_history_window=80`
- `sampled_softmax_candidate_mode=batch_shared`、`sampled_softmax_correction=logq`、`explicit_negative_weight=0.0`

500-user checkpoint sweep（valid-only direct eval）显示 epoch5 最稳：

| checkpoint | Recall@500 | HitRate@500 | unique positive hits |
| ---: | ---: | ---: | ---: |
| epoch1 | 0.023734 | 0.028 | 15 |
| epoch3 | 0.075949 | 0.092 | 48 |
| epoch5 | 0.083861 | 0.102 | 53 |
| epoch8 | 0.075949 | 0.092 | 48 |
| epoch10 | 0.079114 | 0.096 | 50 |

扩大 valid-only direct eval 后，500 users 略乐观，5000/10000 users 基本稳定：

| eval users | query users | queryless users | positive denominator@500 | unique hits | Recall@500 | HitRate@500 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 500 | 480 | 20 | 632 | 53 | 0.083861 | 0.1020 |
| 5000 | 4841 | 159 | 6693 | 457 | 0.068280 | 0.0842 |
| 10000 | 9712 | 288 | 13258 | 889 | 0.067054 | 0.0846 |

10000-user valid-only 细分指标：`Recall@20=0.009127`、`Recall@50=0.017122`、`Recall@100=0.024815`、`Recall@500=0.067054`；`HitRate@20=0.0118`、`HitRate@50=0.0218`、`HitRate@100=0.0315`、`HitRate@500=0.0846`。对应 summary：`/mnt/data/luo/RS_agent_remote_storage/outputs/two_tower_sparse_aware_serial_checkpoints/direct_eval_large_valid/epoch5_valid10000_valid_only_summary.json`。

评估口径说明：method-source eval 会按全量 valid label users 作为分母；当只给部分 target users 生成候选时，未生成候选的 valid users 会被计为 0，曾导致 `candidate_user_count=480` 却以 `eval_label_user_count=95412` 稀释，得到 `Recall@500=0.000466` 的假低结果。因此 checkpoint selection 与稳定配置沉淀采用 raw direct eval 的固定 eval-user 分母。valid 只用于选 epoch 和后验效果评估，不进入训练、负采样、item vocab、source index 或候选生成。

当前治理结论保持不变：sparse-aware epoch5 是当前 two_tower 最稳定的 diagnostic 召回配置，但仍不声明 READY，不允许 candidate generation / ranking input replacement / ranking replacement / promotion / pool1000 / final pool500 ready。

### sparse-aware epoch5 主路默认诊断源接入

按用户确认的“保留现在最佳配置并入主路”要求，`two_tower` 的 pool500 recall-only 默认 source manifest 已切换到本地 canonical mirror：

- local source index manifest：`outputs/recall/pool500_method_sources/recent_2y/two_tower/sparse_aware_formal_epoch5_selected/source_index_manifest.json`
- local artifact manifest：`outputs/recall/pool500_method_sources/recent_2y/two_tower/sparse_aware_formal_epoch5_selected/artifact_manifest.json`
- local valid10000 summary：`outputs/recall/pool500_method_sources/recent_2y/two_tower/sparse_aware_formal_epoch5_selected/epoch5_valid10000_valid_only_summary.json`
- mirror audit：`outputs/recall/pool500_method_sources/recent_2y/two_tower/sparse_aware_formal_epoch5_selected/mirror_audit.json`
- remote provenance：`outputs/recall/pool500_method_sources/recent_2y/two_tower/sparse_aware_formal_epoch5_selected/remote_provenance.json`
- cleanup audit：`outputs/recall/pool500_method_sources/recent_2y/two_tower/sparse_aware_formal_epoch5_selected/cleanup_audit.json`

接入语义仅为“主路默认 two_tower diagnostic source 使用当前最佳 sparse-aware epoch5 配置”，不是 READY 晋升；`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`ranking_replacement_allowed=false`、`promotion_allowed=false`、`pool1000_allowed=false`、`final_pool500_ready_claimed=false` 均保持关闭。

## smoke source artifact

- smoke training config：`outputs/recall/pool500_method_sources/recent_2y/two_tower/smoke_training_config.yaml`
- artifact manifest：`outputs/recall/pool500_method_sources/recent_2y/two_tower/smoke_training_run/artifact_manifest.json`
- source index manifest：`outputs/recall/pool500_method_sources/recent_2y/two_tower/smoke_source/source_index_manifest.json`
- smoke candidate check manifest：`outputs/recall/pool500_method_sources/recent_2y/two_tower/smoke_candidates/two_tower/smoke_candidate_check_20/source_index_manifest.json`

smoke training 结果：

- backend：PyTorch / CUDA，`NVIDIA GeForce RTX 4070 Ti SUPER`
- `training_examples=3047`
- `users_with_training_rows=1000`
- `positive_interactions=4773`
- `item_count=4820`
- `embedding_dim=32`
- `epochs=1`
- `negative_samples=3`
- `training_seconds=14.936`
- `peak_cuda_memory_mb=21.148`
- `loss_history=[1.371178]`

smoke source 结果：

- `row_count=4820`
- `embedding_row_count=4820`
- `index_row_count=4820`
- `candidate_generation_allowed=false`
- `promotion_allowed=false`

20 用户 candidate check：

- `target_user_count=20`
- `candidate_row_count=20`
- `candidate_user_count=1`
- `no_holdout_audit.status=PASS`
- read paths 只包含 smoke source manifest、recent-2y manifest、`user_sequences.train.jsonl`；valid/test 仅作为 manifest 中被忽略的 evaluation-only paths。

该结果只证明链路可运行，不证明 formal 效果。

## formal full source artifact 与 blocker

本轮在授权远程服务器 `server:/home/luo/RS_agent_remote` 上补齐了 recent-2y formal 口径下的 **687147 eligible-user full epoch1** 训练、source index、candidate rows、direct eval、source overlap 和 route gate 证据。该产物读取 formal method dataset 派生的 train-only `training_item_universe`，valid/test 仅用于 evaluation-only direct eval，不进入训练、负采样、item vocab、source index 或候选生成。

full epoch5 evidence（epoch1 证据仍保留为对照）：

- training config：`outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_training_config.json`
- training artifact：`outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_full_687k_training_run_epoch5/artifact_manifest.json`
- train metrics：`outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_full_687k_training_run_epoch5/train_metrics.json`
- source index：`outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_full_687k_source_epoch5/source_index_manifest.json`
- baseline candidate rows：`outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_full_687k_candidates_epoch5/source_index_manifest.json`
- baseline direct eval：`outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_full_687k_eval_epoch5_local_verify/raw_two_tower_direct_eval_manifest.json`
- queryv2 candidate rows：`outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_full_687k_candidates_queryv2/source_index_manifest.json`
- queryv2 direct eval：`outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_full_687k_eval_queryv2_local_verify/raw_two_tower_direct_eval_manifest.json`
- queryv2 source overlap：`outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_full_687k_overlap_queryv2/source_overlap_report.json`
- queryv2 route gate：`outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_full_687k_route_gate_queryv2/manifest.json`
- queryv2 evaluation summary：`outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_full_687k_evaluation_report_queryv2.json`
- remote spill 说明：远端 `/home` 空间紧张，epoch5 training/candidate 大目录已迁移到 `server:/tmp/rs_agent_spill/two_tower/`，并在 canonical outputs 路径下保留软链接。

full epoch5 training 结果：

- `training_input_users=687147`
- `users_with_training_rows=667734`
- `training_examples=2069609`
- `positive_interactions=3415440`
- `item_count=499566`
- `user_embedding_count=687147`
- `epochs=5`
- `loss_history=[1.723716, 1.6206, 1.553363, 1.50874, 1.477235]`
- `optimizer_steps=635`
- `training_seconds=907.373`
- `peak_cuda_memory_mb=572.066`
- backend：PyTorch / CUDA，mixed precision enabled，`NVIDIA GeForce RTX 4090`

full epoch5 queryv2 source/eval 结果：

- source `row_count=499566`
- eval `user_count=500`
- `query_user_count=484`、`queryless_user_count=16`
- `query_source_counts={"recent_positive_item_sequence_average_vectors": 405, "recent_item_sequence_average_vectors": 79}`
- `queryless_reason_counts={"seed_items_missing_item_vectors": 16}`
- `candidate_rows=242000`
- `underfilled_user_rate=0.032`
- `positive_denominator_at_500=692`
- `raw_two_tower_unique_positive_hits=49`
- `recall_at_20=0.021676`
- `recall_at_50=0.027457`
- `recall_at_100=0.036127`
- `recall_at_500=0.070809`
- `hit_rate_at_500=0.092`

相对 20k preflight，full epoch5 queryv2 的 `Recall@500` 从 `0.021676` 提升到 `0.070809`，`hit_rate@500` 从 `0.028` 提升到 `0.092`；相对 epoch5 baseline direct eval，`queryless_user_count` 从 `95` 降到 `16`，`underfilled_user_rate` 从 `0.19` 降到 `0.032`，`Recall@500` 从 `0.057803` 提升到 `0.070809`，`hit_rate@500` 从 `0.076` 提升到 `0.092`，unique positive hits 从 `40` 提升到 `49`。这说明 query builder v2 有效改善 coverage 和 direct eval，但仍只是 500-user target-slice diagnostic，未完成 full pool500 candidate quality audit 和 route-level marginal lift，因此不能 READY。

source overlap / route gate：

- overlap 报告状态：`PASS`，但只作为诊断；queryv2 primary unique item count 为 `43748`，与 popular 的 item-union overlap ratio vs primary 为 `1.0`，与 category 的 comparable user 仍只有 1 个，互补性证据仍不足。
- route gate 状态：`PASS`，decision：`DIAGNOSTIC_ONLY`；原因是仍缺 full pool500 candidate quality audit 和相对 READY sources 的 route-level marginal lift 证据。

当前停止原因：旧路径如 `outputs/recall/pool500_full_sources/two_tower/...` 仍只作为历史参考；full formal epoch5/queryv2 已补齐 500-user target-slice 训练产物复用、候选生成、direct eval、overlap 和 route gate 诊断，且 query coverage 与 Recall@500 均有提升，但互补性、candidate quality audit 和 route-level marginal lift 证据仍不足。因此保持 `DIAGNOSTIC_ONLY`，不建议并入主路。

### 训练侧 challenger：recency + example-age + logQ（rejected diagnostic）

为对齐 YouTubeDNN 论文中的 freshness weighting 与 sampled softmax bias correction，本轮补充了一个默认关闭的 formal challenger：`torch_user_history_weighting=recency_decay`、`example_age_weighting=decay`、`sampled_softmax_correction=logq`，显式负例关闭以避免混合分布下的错误 logQ 校正。重任务在授权远程 GPU 上运行，artifact 保留在 `/mnt/data/luo/rs_agent_spill/two_tower/formal_recency_age_logq_20260605_gpu/`，本地仅拉回证据 JSON 到 `outputs/recall/pool500_method_diagnostics/recent_2y/two_tower/formal_recency_age_logq_20260605_gpu_evidence/`。

训练侧证据：

- backend：PyTorch / CUDA，`NVIDIA GeForce RTX 4090`，mixed precision enabled
- `training_examples=2103458`
- `item_count=499566`
- `epochs=5`
- `negative_samples=10`
- `sampled_softmax_correction=logq`
- `sampled_softmax_corrected_examples=10517290`
- `sampled_softmax_corrected_candidates=115690190`
- `example_age_weighting=decay`，`positive_timestamp_count=3464253`，`missing_timestamp_count=0`，weight p50=`0.2`、avg=`0.232093`
- `loss_history=[3.530235, 3.512029, 3.49726, 3.481742, 3.464569]`
- source index `row_count=499566`
- governance flags 仍为 false：`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`、`pool1000_allowed=false`、`final_pool500_ready_claimed=false`

legacy direct-eval 结果（远端当前 eval 脚本缺少 queryv2 fallback，因此该结果不作为 queryv2 baseline 的严格同口径复现，但可与同一 legacy 口径 challenger 对照）：

- `user_count=500`
- `query_user_count=405`、`queryless_user_count=95`
- `candidate_rows=202500`
- `underfilled_user_rate=0.19`
- `positive_denominator_at_500=692`
- `raw_two_tower_unique_positive_hits=13`
- `Recall@500=0.018786`
- `HitRate@500=0.026`

结论：该 challenger 虽然训练和治理链路成立，但效果显著低于 epoch5/queryv2 baseline，也低于上一轮 `ns_v2_plus_recency` legacy direct-eval 的 `Recall@500=0.047688`、unique hits `33`。原因上更可能是 example-age 权重过强（p50 已压到最小权重 0.2）与 logQ 校正改变了 embedding 近邻结构；当前不写入主路配置和 registry，不更新 READY，只保留为 rejected diagnostic evidence。后续若继续尝试，应先做单因素消融（仅 logQ、仅 example-age、较长 half-life / 更高 min weight），并先同步 queryv2 eval 支持后再跑正式同口径比较。

### 训练侧改进：item side feature token 与安全回归修复（local verified）

为继续向 YouTubeDNN 的 item/context side input 靠拢，本轮在默认关闭的 `side_feature_fields` 路径中加入 train-only item 侧特征支持，方法数据集的 `training_item_universe.jsonl` 会输出：

- `item_quality_token`：来自 train-only `quality_bucket_v2`。
- `item_pop_bucket_token`：来自 train-only `frequency` / `global_pop_rank` 分桶。
- `item_user_count_bucket_token`：来自 train-only `user_count` 分桶。

训练代码记录 `text_fields`、`side_feature_fields_active` 和 model/metrics 中的 active side fields；side feature token 以 `field=value` 原子 token 进入 item 初始化，避免把 `item_quality:embedding_ready` 拆成泛化文本片段。默认 `DEFAULT_TEXT_FIELDS` 不变，side token 需 challenger config 显式启用，因此不影响既有 epoch5/queryv2 baseline。

本轮同时修复了三类安全/口径回归风险：

1. 多个 sequence key 合并后按 timestamp 全局排序，避免 future positive 被错误放入 history。
2. 负采样的 `known_items` 改为完整 `recent_item_sequence`，不再只排除 capped recent window，确保 older known item 不会被采成负例。
3. side feature token 保持原子化 `field=value`，不混入普通文本 token 分词。

本地验证：

- `./.venv/Scripts/python.exe -m py_compile rs_core/offline/training/two_tower.py rs_lab/experiments/recall/build_pool500_two_tower_method_dataset.py tests/test_two_tower_training.py tests/test_pool500_two_tower_method_dataset.py` 通过。
- `./.venv/Scripts/python.exe -m pytest tests/test_pool500_two_tower_method_dataset.py tests/test_two_tower_training.py tests/test_pool500_two_tower_direct_eval.py tests/test_pool500_two_tower_method_source.py tests/test_pool500_two_tower_source_manifest.py tests/test_two_tower_source_manifest_guard.py -q`：`72 passed, 3 skipped`。
- 独立 code-reviewer / verifier 复核为 `APPROVE/PASS`，仅保留一个低风险建议：负例 rotation 可进一步把 `user_id/target_item` 纳入 offset 多样化。

当前结论：训练侧实现与本地治理验证已完成，远程 20k `item_side_light_all` preflight 已形成 queryv2 同口径诊断结论，但效果低于 epoch5/queryv2 baseline；`two_tower` 继续保持 `DIAGNOSTIC_ONLY`，不得 READY / promotion / ranking replacement。

### 训练侧 challenger：item side light all 20k preflight（rejected diagnostic）

为验证 item side input 是否能低风险改善 YouTubeDNN-like item 初始化，本轮在远程 GPU 上运行默认关闭的 `item_side_light_all` challenger，显式启用：

- `side_feature_fields=["item_quality_token", "item_pop_bucket_token", "item_user_count_bucket_token"]`
- `training_sample_path=/mnt/data/luo/rs_agent_spill/two_tower/item_side_light_all_preflight_20k_20260606/dataset/two_tower_train_samples.jsonl`
- `negative_sampling_version=side_feature_preflight_v1`
- queryv2 direct eval 固定 `seed_window=30`、`recency_decay=0.85`、`artifact_user_embedding_first=true`、`project_seed_average=true`

证据路径：

- remote run root：`server:/mnt/data/luo/rs_agent_spill/two_tower/item_side_light_all_preflight_20k_20260606/`
- local evidence：`outputs/recall/pool500_method_sources/recent_2y/two_tower/item_side_light_all_preflight_20k_20260606/`
- dataset manifest：`.../method_dataset_manifest.json`
- train metrics：`.../train_metrics.json`
- source index：`.../source_index_manifest.json`
- queryv2 direct eval：`.../raw_two_tower_direct_eval_manifest.json`

方法数据集与训练证据：

- `eligible_user_count=20000`
- `train_sample_count=81688`
- `training_item_universe_item_count=340141`
- side feature coverage：`item_quality_token=340141`、`item_pop_bucket_token=340141`、`item_user_count_bucket_token=340141`
- backend：PyTorch / CUDA，`NVIDIA GeForce RTX 4090`，mixed precision enabled
- `training_examples=6171`
- `users_with_training_rows=2010`
- `positive_interactions=9995`
- `item_count=340141`
- `epochs=1`
- `optimizer_steps=1`
- `training_seconds=434.533`
- source index `row_count=340141`
- governance flags 仍为 false：`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`、`final_pool500_ready_claimed=false`

queryv2 direct-eval 结果：

- `user_count=500`
- `query_user_count=478`、`queryless_user_count=22`
- `query_source_counts={"recent_positive_item_sequence_average_vectors": 401, "recent_item_sequence_average_vectors": 77}`
- `queryless_reason_counts={"seed_items_missing_item_vectors": 22}`
- `candidate_rows=239000`
- `underfilled_user_rate=0.044`
- `positive_denominator_at_500=692`
- `raw_two_tower_unique_positive_hits=17`
- `Recall@20=0.002890`
- `Recall@50=0.004335`
- `Recall@100=0.010116`
- `Recall@500=0.024566`
- `HitRate@500=0.034`

结论：该 challenger 的治理链路、side feature coverage 和 queryv2 eval 均成立，但效果显著低于 full epoch5/queryv2 baseline（`Recall@500=0.070809`、`HitRate@500=0.092`、unique hits `49`、queryless `16`）。同时它的 `item_count=340141` 低于 baseline `499566`，queryless 从 `16` 增至 `22`，说明 side-feature 20k 数据集的训练 item universe / seed 覆盖反而收窄。当前不进入 full formal，不写入主路配置和 registry，不更新 READY。

### 训练侧 challenger：item side full-vocab 单字段消融（rejected diagnostic）

为排除上一轮 `item_side_light_all` 的 item universe 收缩干扰，本轮基于 baseline formal `training_item_universe` 重新派生 full-vocab side-token item vocab，保持 `item_count=499566`，再分别只启用一个 side feature 字段：

- `item_quality_token`
- `item_pop_bucket_token`
- `item_user_count_bucket_token`

共享证据：

- full-vocab item manifest：`outputs/recall/pool500_method_sources/recent_2y/two_tower/item_quality_fullvocab_preflight_20k_20260606/item_vocab_manifest_side_tokens.json`
- remote full-vocab root：`server:/mnt/data/luo/rs_agent_spill/two_tower/side_feature_fullvocab_20260606/`
- 三字段 side feature coverage 均为 `499566`
- 三个单字段 run 均使用 `limit_users=20000`、`epochs=1`、`negative_samples=5`、`gradient_accumulation_steps=2`、mixed precision、queryv2 eval `seed_window=30` / `recency_decay=0.85`
- 三个 source index 均为 `FULL_DERIVED_INDEX_DIAGNOSTIC`，且 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`、`final_pool500_ready_claimed=false`

单字段 queryv2 direct-eval 结果：

| challenger | local evidence | active side field | item_count | queryless | unique hits | Recall@500 | HitRate@500 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| quality only | `outputs/recall/pool500_method_sources/recent_2y/two_tower/item_quality_fullvocab_preflight_20k_20260606/` | `item_quality_token` | `499566` | `16` | `17` | `0.024566` | `0.032` |
| popularity only | `outputs/recall/pool500_method_sources/recent_2y/two_tower/item_pop_fullvocab_preflight_20k_20260606/` | `item_pop_bucket_token` | `499566` | `16` | `17` | `0.024566` | `0.032` |
| user-count only | `outputs/recall/pool500_method_sources/recent_2y/two_tower/item_user_count_fullvocab_preflight_20k_20260606/` | `item_user_count_bucket_token` | `499566` | `16` | `17` | `0.024566` | `0.032` |

本地验证：

- `controlled_side_feature_ablation_evidence_validation_PASS`

结论：控制 item universe 后，三个单字段 run 的 query coverage 恢复到 baseline `queryless_user_count=16`，证明上一轮 all-light 的 `queryless=22` 确实主要来自 universe 收缩；但三个 side feature 单字段的命中完全一致，且仍显著低于 full epoch5/queryv2 baseline（`Recall@500=0.070809`、`HitRate@500=0.092`、unique hits `49`）。因此 item side token 目前只作为失败消融证据，不进入 full formal，不写 registry，不更新 READY。后续如果继续模型侧优化，应优先查训练规模/训练轮数、negative sampling、sequence/multi-interest user tower，而不是继续堆这些粗粒度 item side bucket。

### 训练规模与 epoch 控制诊断：20k epoch5 baseline（scale blocker）

为定位 20k preflight 长期停在 `Recall@500≈0.02` 的原因，本轮补做 baseline no-side-feature 的 20k epoch5 控制实验，并把既有 20k epoch1、687k epoch1、687k epoch5 统一到 queryv2 同口径比较。

证据路径：

- remote run root：`server:/mnt/data/luo/rs_agent_spill/two_tower/baseline_20k_epoch5_20260606/`
- local evidence：`outputs/recall/pool500_method_sources/recent_2y/two_tower/baseline_20k_epoch5_20260606/`
- 20k epoch1 queryv2 local verify：`outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_preflight_20k_eval_queryv2_local_verify/raw_two_tower_direct_eval_manifest.json`
- 687k epoch1 queryv2 local verify：`outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_full_687k_eval_epoch1_queryv2_local_verify/raw_two_tower_direct_eval_manifest.json`
- 687k epoch5 queryv2 local verify：`outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_full_687k_eval_queryv2_local_verify/raw_two_tower_direct_eval_manifest.json`

同口径结果：

| run | epochs | optimizer steps | item_count | queryless | unique hits | Recall@500 | HitRate@500 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 20k epoch1 + queryv2 | `1` | `4` | `499566` | `16` | `17` | `0.024566` | `0.032` |
| 20k epoch5 + queryv2 | `5` | `5` | `499566` | `16` | `17` | `0.024566` | `0.032` |
| 687k epoch1 + queryv2 | `1` | `127` | `499566` | `16` | `36` | `0.052023` | `0.064` |
| 687k epoch5 + queryv2 | `5` | `635` | `499566` | `16` | `49` | `0.070809` | `0.092` |

20k epoch5 训练 loss 从 `[1.769754, 1.754555, 1.742768, 1.727976, 1.712921]` 下降，但 direct eval 命中不变；source/eval manifest 仍保持 `no_oracle_label_injection=true`，valid/test 仅 evaluation-only，source governance flags 不允许 promotion/READY。

结论：20k preflight 的低效果不能靠简单增加 epoch 修复；20k 下有效 optimizer step 太少，模型可学习的协同行为覆盖不足。full 687k epoch1 已显著高于 20k epoch5，说明训练规模是主要 blocker；epoch5 对 full 规模有进一步增益。后续不应再用 20k 作为 two_tower 效果准入判断，只可作为链路 smoke；模型侧实验至少需要更大规模 preflight（例如 100k/200k）或 formal 级训练，且继续保持 queryv2、train-only 和 diagnostic-only 治理。

本地验证：

- `two_tower_scale_epoch_diagnosis_validation_PASS`

后续优先事项：

1. 继续处理 query coverage 尾部问题：queryv2 已将 `queryless_user_rate` 从 `0.19` 降到 `0.032`，剩余 16 个用户的原因均为 `seed_items_missing_item_vectors`，后续需检查 train-only item universe / seed 覆盖口径。
2. 做 route-level marginal lift：与 popular/category/ItemCF/Swing/UserCF 等 READY sources 比较独有候选、独有命中和 route-level Recall 增益。
3. 做 full pool500 candidate quality audit：当前 queryv2 仍是 500-user target-slice diagnostic，不能替代主路准入证据。
4. 如需继续 two_tower 模型侧优化，再做 negative sampling v2 / hard negatives / sequence 或 multi-interest user tower。
5. 只有 formal 指标、candidate quality audit、overlap/unique-hit 和 route gate 均通过后，才考虑晋升 READY。

## 评估要求

formal READY 晋升前至少需要：

- Recall@20/50/100/500、hit-rate。
- candidate rows、用户覆盖率、underfilled user rate。
- 用户桶分层指标。
- in-universe denominator 与 eval positive missing rate。
- 与 popular/category/ItemCF/Swing 的 source overlap、独有覆盖和独有命中。
- 训练/索引资源：训练秒数、GPU/显存、artifact size、search latency/QPS。

## 验证命令与结果

已执行：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m rs_lab.experiments.recall.build_pool500_two_tower_method_dataset --clean-manifest data/processed/amazon_2023_recall_recent_2y_1m_3m/manifest.json --governance-manifest data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json --output-dir outputs/recall/pool500_method_datasets/recent_2y/two_tower/smoke --scale-tier smoke --overwrite
# PASS, train_sample_count=1999

D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m rs_lab.experiments.recall.build_pool500_two_tower_method_dataset --clean-manifest data/processed/amazon_2023_recall_recent_2y_1m_3m/manifest.json --governance-manifest data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json --output-dir outputs/recall/pool500_method_datasets/recent_2y/two_tower/formal --scale-tier formal --overwrite
# PASS, train_sample_count=2812780

D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m scripts.training.train_two_tower --config outputs/recall/pool500_method_sources/recent_2y/two_tower/smoke_training_config.yaml --output-dir outputs/recall/pool500_method_sources/recent_2y/two_tower/smoke_training_run --variant youtube_dnn --compact-inputs --epochs 1
# PASS, artifact_manifest written

D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m scripts.recall.build_two_tower_source_index --training-run-dir outputs/recall/pool500_method_sources/recent_2y/two_tower/smoke_training_run --item-vocab-manifest data/processed/amazon_2023_sciomc_twotower_recent2y/smoke/two_tower_item_vocab_minfreq1_manifest.json --output-dir outputs/recall/pool500_method_sources/recent_2y/two_tower/smoke_source --output-source-manifest outputs/recall/pool500_method_sources/recent_2y/two_tower/smoke_source/source_index_manifest.json --config outputs/recall/pool500_method_sources/recent_2y/two_tower/smoke_training_config.yaml --clean-manifest data/processed/amazon_2023_sciomc_twotower_recent2y/smoke/manifest.json --train-sequence data/processed/amazon_2023_sciomc_twotower_recent2y/smoke/user_sequences.train.jsonl --overwrite
# PASS, row_count=4820

D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m scripts.training.train_two_tower --config outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_training_config.json --output-dir outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_preflight_20k_training_run --variant youtube_dnn --item-vocab-manifest outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_training_item_vocab_manifest.json --user-quality-manifest outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_eligible_user_manifest.json --user-quality-bucket all_eligible --limit-users 20000 --compact-inputs --epochs 1 --gradient-accumulation-steps 2 --mixed-precision --progress-log outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_preflight_20k_training_progress.jsonl
# PASS, formal_preflight_20k artifact_manifest written, item_count=499566

D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m scripts.recall.build_two_tower_source_index --training-run-dir outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_preflight_20k_training_run --item-vocab-manifest outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_training_item_vocab_manifest.json --output-dir outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_preflight_20k_source --output-source-manifest outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_preflight_20k_source/source_index_manifest.json --config outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_training_config.json --clean-manifest data/processed/amazon_2023_recall_recent_2y_1m_3m/manifest.json --train-sequence data/processed/amazon_2023_recall_recent_2y_1m_3m/user_sequences.train.jsonl --overwrite
# PASS, row_count=499566

D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m rs_lab.experiments.recall.run_pool500_two_tower_direct_eval --source-index-manifest outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_preflight_20k_source/source_index_manifest.json --eval-users outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_eval_users_500.jsonl --train-sequences data/processed/amazon_2023_recall_recent_2y_1m_3m/user_sequences.train.jsonl --label-paths data/processed/amazon_2023_recall_recent_2y_1m_3m/canonical_interactions.valid.jsonl data/processed/amazon_2023_recall_recent_2y_1m_3m/canonical_interactions.test.jsonl --output-manifest outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_preflight_20k_eval/raw_two_tower_direct_eval_manifest.json --metric-ks 20,50,100,500 --seed-window 30 --recency-decay 0.85 --batch-size 128 --item-block-size 50000
# PASS, recall_at_500=0.021676, hit_rate_at_500=0.028
```

## 下一步

- 针对 queryv2 剩余 16 个 `seed_items_missing_item_vectors` 用户，检查 train-only seed/item universe 覆盖缺口，避免再把 queryless 问题当作纯训练轮数问题。
- 做 route-level marginal lift：与 popular/category/ItemCF/Swing/UserCF 等 READY sources 比较独有命中和主路边际增益。
- 做 full pool500 candidate quality audit；通过前不晋升 READY。
- 如果后续继续模型侧优化，再考虑 negative sampling v2、hard negatives、sequence/multi-interest user tower。
