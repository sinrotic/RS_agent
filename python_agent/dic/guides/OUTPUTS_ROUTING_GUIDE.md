# outputs 产物路由规范

本文档说明 `outputs/` 的职责边界，避免运行产物和正式文档混在一起。

## 1. 职责边界

`outputs/` 只保存运行产物，包括指标、推荐结果、案例文件、日志和脚本自动生成报告。它不是项目主文档目录。

正式实验结论、阶段复盘、架构说明和面试叙事应写入 `dic/` 下对应目录，并在文档中引用相关 `outputs/...` 路径。

## 2. 允许留在 `outputs/` 的内容

- `metrics.json`
- `comparison.json`
- `recommendations.jsonl`
- `ranking_hit_cases.jsonl`
- `ranking_case_summary.json`
- `simulation_batch.json`
- `report.md`
- `comparison.md`
- `simulation_eval_report.md`
- 运行日志和配置快照

其中 `.md` 文件只有在脚本自动生成、用于记录某次运行结果时，才视为运行产物。

## 3. 不应新增到 `outputs/` 的内容

- 人工维护的长期说明文档。
- 架构说明。
- 技术决策 ADR。
- 阶段计划或阶段复盘。
- 面试导向工程叙事。
- 与某次运行无关的长期实验总结。

这些内容应进入 `dic/architecture/`、`dic/decisions/`、`dic/phases/` 或 `dic/experiments/`。

## 4. 新产物目录建议

新实验建议使用：

```text
outputs/<workstream>/<phase_or_topic>/<experiment_name>/run_YYYYMMDD_HHMMSS/
```

示例：

```text
outputs/ranking/phase_1_17/pool200_ltr_baseline/run_20260515_143000/
```

每个运行目录建议包含：

- `metrics.json`
- `recommendations.jsonl`
- `ranking_hit_cases.jsonl`
- `config_snapshot.json`
- `run_metadata.json`

## 5. 历史产物处理规则

- 历史 `outputs/` 原则上不大规模移动。
- 重要历史产物通过 `dic/experiments/` 或 `dic/phases/` 中的文档引用。
- 不把 `outputs/` 里的运行产物搬入 `dic/`。
- 一次性临时产物使用 `outputs/tmp/` 或 `_tmp_*` 命名。

## 6. 一次性实验清理规则

一次性 smoke、tuning、临时对照、debug demo、verifier / verification 试验，在完成验证并沉淀必要结论后，应直接清理对应的临时 output 目录、日志和中间产物。

清理前需要确认：

- 关键指标、失败原因或结论已写入 `dic/experiments/`、`dic/phases/`、`dic/OPTIMIZATION_NARRATIVE.md` 或 `dic/ENGINEERING_NARRATIVE_LOG.md`。
- 该产物不是 canonical demo、正式 10k 指标、可复现实验 artifact 或当前阶段晋升证据。
- 没有被当前 README、阶段文档、实验报告或脚本硬编码引用。

优先清理的典型目录包括：

- `outputs/tmp*`
- `outputs/_tmp*`
- `outputs/*smoke*` 中已完成验证且非晋升证据的目录
- `outputs/*verifier*`
- `outputs/verification_*`
- `outputs/*batch_tuning*`
