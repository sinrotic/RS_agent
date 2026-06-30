# itemcf_strong 低效策略产物清理记录（2026-06-06）

## 清理原则

- 只清理本地实验结果、候选边、checkpoint、诊断输出等可再生成产物。
- 保留代码、测试、配置、方法文档、OMC plan/handoff 等工程记录。
- 保留主线配置，不修改 `configs/recall/full_data_pool500/itemcf_strong*`、`dic/recall_methods/itemcf_strong/METHOD.md`、脚本和测试。
- 清理操作通过 Python 脚本执行，并生成机器可读 audit：`outputs/cleanup_records/itemcf_strong_bad_strategy_cleanup_20260606.json`。

## 清理原因

itemcf_strong 相关多轮 guarded / relaxed / newdata supplemental 实验均保持 `DIAGNOSTIC_ONLY`，未晋升 pool500 主路；部分 relaxed/supplemental 产物规模较大但效果信号不足，保留完整边文件和 checkpoint 的价值低于磁盘占用。

## 待清理对象类型

- `outputs/recall/pool500_sidecar_fix/itemcf_strong_*` guarded / expanded 诊断产物。
- `outputs/recall/pool500_itemcf_weak_strong_diagnostic` weak/strong 对照产物。
- `outputs/recall/pool500_method_sources/itemcf_strong*` 历史 diagnostic source 产物。
- `outputs/recall/pool500_recall_sources/*/itemcf_strong` 质量过滤/扫描实验产物。
- `outputs/recall/pool500_method_sources_newdata/itemcf_strong*` recent2y strict/relaxed 低效产物。
- `outputs/eval/pool500_itemcf_weak_strong_top100_hot7_warm3_20260526*` 旧 rank probe 产物。
- `data/processed/amazon_2023_recall_views_10000/itemcf_recall_strong.jsonl` 旧 views_10000 派生结果。
- `outputs/recall/pool500_method_datasets/itemcf_weighted_formal_v1_strong.*.log` 一次性构建日志。

## 保留对象

- `scripts/experiments/recall/pool500/build_itemcf_strong_method_source.py`
- `scripts/experiments/recall/pool500/evaluate_itemcf_strong_purchase_labels.py`
- `scripts/experiments/recall/pool500/build_itemcf_strong_augcf_lite_method_dataset.py`
- `tests/test_pool500_itemcf_strong_method_source.py`
- `configs/recall/full_data_pool500/itemcf_strong_custom_dataset_manifest.json`
- `dic/recall_methods/itemcf_strong/METHOD.md`
- `.omc/plans/*itemcf*strong*.md` 和 `.omc/handoffs/*itemcf*strong*.md`

## 清理后结论

itemcf_strong 保留为历史诊断和可复现实验方向，不保留低效候选边/大规模 checkpoint 结果；后续如需复跑，应从保留的脚本、配置和方法文档重新生成。