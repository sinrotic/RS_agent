# semantic recent-2y 重建计划（RALPLAN）

日期：2026-06-03
状态：已完成本地 smoke + bounded formal target-slice；保持 `DIAGNOSTIC_ONLY`，不晋升 READY。

## RALPLAN-DR 摘要

### Principles

1. **Train-only 优先**：构建 dataset/source artifact 只读取 recent-2y train-visible 输入，不读取 holdout/valid/test/LOPO/oracle/eval label。
2. **可解释优先**：本轮 `semantic` 采用 metadata/token overlap，dense/ANN 只作为后续增强，不作为当前 formal 结论。
3. **smoke/formal 分层**：smoke 只验证链路；formal 才可作为证据，但 target-slice formal 仍不自动 READY。
4. **manifest 可复核**：所有输入路径、hash、参数、覆盖、资源和 no-holdout audit 必须落盘。
5. **不硬并主路**：formal 指标、互补性或 route gate 不足时保持 `DIAGNOSTIC_ONLY` / `TARGET_SLICE_DIAGNOSTIC`。

### Decision Drivers

1. **泄漏与旧 artifact 回流风险**：semantic 历史配置曾指向 full-data/lightweight 旧产物，必须显式隔离。
2. **资源与可复现性**：dense/ANN 需要训练、编码和索引治理；当前先做轻量可审计 target-slice。
3. **主路价值证据**：semantic 必须证明覆盖/互补性，而不是凭 smoke 或旧结果晋升。

### Viable Options

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. token/full_metadata_overlap target-slice formal | 低资源、可解释、易做 no-holdout audit，可快速形成 recent-2y artifact | 同义泛化弱，可能和 category/popular overlap 高 | 本轮采用 |
| B. BM25/IDF scorer | 可抑制泛词，比简单 overlap 更稳 | 需要新增 scorer 与 corpus stats manifest，当前代码未完整实现 | 下一步增强 |
| C. dense/hybrid embedding + ANN | 语义泛化强，论文支撑充分 | 训练/编码/ANN 重资源，需独立远程复现 | 后续 v2，不作为本轮晋升依据 |

## ADR

**Decision**：本轮 `semantic` recent-2y 重建采用方案 A：基于 train-only recent-2y recall_views 的 `semantic_recall_inputs` 与 `semantic_inverted_index`，按 eligible user manifest 构建 smoke 和本地 bounded formal target-slice source artifacts，并保持 `TARGET_SLICE_DIAGNOSTIC`。

**Drivers**：可审计、资源可控、避免旧 artifact 回流、先补齐 source artifact 证据。

**Alternatives considered**：BM25/IDF、dense/hybrid ANN。前者作为 scorer 后续增强；后者需要独立远程训练/索引治理，不纳入本轮完成标准。

**Consequences**：本轮能产出可复核 artifact 和 audit 指标，但由于没有 full-scale formal、Recall@K、source overlap 和 route gate 证据，不建议 READY。

**Follow-ups**：优先补 semantic-only evaluator、source overlap/marginal gain、route gate；若继续扩大到 50k/no-cap formal，应使用 `candidate_metadata_policy=lean_reference` 避免重复写 item metadata，并迁移 server 分批执行后拉回 manifest/stats/report/artifact 本地复核。

## 当前现状与缺口

- registry 旧 `semantic` 条目曾为 `DEFERRED` 且 latest artifact 指向历史 sidecar，不能作为 recent-2y 当前结论。
- builder 已从“每用户扫描全 semantic index”优化为 token bucket candidate path，并增加 per-user candidate pool cap，避免本地 formal 过度放大。
- 本地 50k/no-cap formal 多次暴露资源风险；最终采用 10k target-slice formal 作为本窗口可复核证据。
- 当前缺口是 Recall@K、互补性、route gate 和 full-scale/server formal，不影响 source artifact audit 结论，但阻止 READY 晋升。

## 数据集与 source artifact contract

### smoke contract

- 输入：
  - `data/processed/amazon_2023_recall_recent_2y_1m_3m/manifest.json`
  - `data/processed/amazon_2023_recall_recent_2y_1m_3m/recall_views/manifest.json`
  - `outputs/recall/pool500_method_sources_newdata/eligible_users_semantic_recent2y_smoke_v1/eligible_user_manifest.json`
- 参数：`limit_users=200`、`seed_window=20`、`per_user=80`、`per_token_item_limit=1000`、`max_candidate_items=30000`。
- 输出目录：`outputs/recall/pool500_method_sources_newdata/semantic/semantic_recent2y_smoke_v1/`。
- 目的：program/schema/no-holdout validation only。

### formal target-slice contract

- 输入：同 smoke，但 eligible manifest 改为 `outputs/recall/pool500_method_sources_newdata/eligible_users_semantic_recent2y_formal_v1/eligible_user_manifest.json`。
- 参数：`limit_users=10000`、`seed_window=50`、`per_user=80`、`per_seed=40`、`per_token_item_limit=300`、`max_candidate_items=5000`、`per_user_candidate_pool_limit=300`、`candidate_metadata_policy=lean_reference`。
- 输出目录：`outputs/recall/pool500_method_sources_newdata/semantic/semantic_recent2y_formal_target10k_v1/`。
- 目的：本地可复核 source artifact audit；不等同完整 50k/no-cap formal，不自动 READY。

## 执行结果

1. **配置修正**
   - `source_status` 固定为 `TARGET_SLICE_DIAGNOSTIC`。
   - 增加 `recent2y_smoke` / `recent2y_formal` tier aliases。
   - formal 参数收敛为本地 bounded 10k target-slice，并记录 full-scale/server blocker。

2. **smoke 构建与验证**
   ```bash
   D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source semantic --tier recent2y_smoke --run-id semantic_recent2y_smoke_v1 --overwrite
   ```
   结果：`source_index_manifest.status=PASS`，`candidate_row_count=16000`，`user_coverage_count=200`，`no_holdout_audit=PASS`。

3. **formal target-slice 构建与验证**
   ```bash
   D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source semantic --tier recent2y_formal --run-id semantic_recent2y_formal_target10k_v1 --overwrite
   ```
   结果：`source_index_manifest.status=PASS`，`candidate_row_count=800000`，`user_coverage_count=10000`，每用户候选数 min/p50/p90/max 均为 80。

4. **formal artifact audit**
   - `coverage_audit.status=PASS`，`seed_item_metadata_coverage=1.0`，`unique_item_count=18452`。
   - `undercoverage_audit.status=DIAGNOSTIC_ONLY_AUDIT`，`undercovered_user_count=0`。
   - `resource_audit.status=PASS`，runtime 约 `154.5s`，candidates 文件约 `2.9GB`。
   - `no_holdout_audit.status=PASS`，`forbidden_inputs=[]`，候选生成未使用 holdout/valid/test/LOPO/oracle/eval label。
   - `evaluation_report.json` 记录为 artifact-audit-only：尚未接入 Recall@K/overlap/route gate evaluator。

5. **文档与配置收口**
   - 更新 `dic/recall_methods/semantic/METHOD.md`。
   - 更新 `configs/recall/full_data_pool500/semantic/source_config.yaml`。
   - 更新 `configs/recall/full_data_pool500/semantic/dataset_policy.yaml`。
   - 更新 `configs/recall/pool500_method_registry.json` 中 `semantic` 条目。
   - 追加 `dic/ENGINEERING_NARRATIVE_LOG.md`。

## 验证命令

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_pool500_semantic_newdata_config.py tests/test_pool500_method_source_runner.py -q
```

可选 artifact 检查：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe - <<'PY'
import json
from pathlib import Path
for p in [
    Path('outputs/recall/pool500_method_sources_newdata/semantic/semantic_recent2y_smoke_v1/source_index_manifest.json'),
    Path('outputs/recall/pool500_method_sources_newdata/semantic/semantic_recent2y_formal_target10k_v1/source_index_manifest.json'),
]:
    m=json.loads(p.read_text(encoding='utf-8'))
    print(p, m['status'], m['candidate_row_count'], m['user_coverage_count'], m['candidate_generation_allowed'])
PY
```

## 完成条件结论

- SciOMC 调研与 RALPLAN 计划文档：已完成。
- smoke/formal source artifacts：已完成 smoke 与本地 10k formal target-slice，七件套存在且 audit 通过。
- formal 可复核证据：已有 artifact audit report；Recall@K/overlap/route gate 仍是 blocker。
- readiness：保持 `DIAGNOSTIC_ONLY` / `TARGET_SLICE_DIAGNOSTIC`，不 READY，不并入主路。
- METHOD、source_config、dataset_policy、registry：已按当前证据更新。
- 未使用旧 full-data artifact、oracle label 或 smoke 结果冒充 formal 结论。

## 停止条件 / blocker 判断

- 50k/no-cap formal 本地资源风险高：迁移 server 分批执行。
- no-holdout audit 若 BLOCKED：停止并修正输入路径。
- formal candidate_row_count 为 0 或 user coverage 过低：保持 DEFERRED/DIAGNOSTIC_ONLY。
- offline eval/route gate 缺失：不建议 READY，仅给出 diagnostic artifact。
