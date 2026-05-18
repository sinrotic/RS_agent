# pool500 召回实验区

本目录用于承载 pool500 召回相关的实验治理、诊断 batch 说明、source 状态记录和后续用户质量分层规划。

## 当前状态

- target20 / target100 / target500 recall-only 诊断链路已跑通。
- 最新 target500 batch 的 route gate 仍为 `STOP`。
- 所有 500 个诊断用户仍 underfilled。
- 当前产物不能替代 ranking input。
- 当前不允许直接扩大到 pool1000。

## source 状态概览

- `READY`：`category`、`popular`、`swing_recall`
- `DIAGNOSTIC_ONLY`：`usercf_recall`、`itemcf_weak`、`itemcf_strong`
- `DEFERRED`：`semantic`、`semantic_title_category_expansion`、`co_visit_fallback_repair`、`two_tower`

## 目录角色

- `governance/`：记录 pool500 source、artifact、gate 和资源边界。
- `user_quality/`：规划优质用户筛选与重矩阵调度策略。

详细方法文档仍维护在 `dic/recall_methods/<source>/METHOD.md`。
