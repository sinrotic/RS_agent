# semantic_title_category_expansion recent-2y 重建 RALPLAN

日期：2026-06-03
状态：pending execution / 单方法执行计划

## 1. RALPLAN-DR 摘要

### Principles

1. **Train-only first**：候选生成、索引构建和方法数据集只能读取 recent-2y train-visible 输入。
2. **Evidence over label leakage**：valid/test label 只用于 evaluation-only 指标，不能反向参与 token、category、seed、候选选择。
3. **Smoke/formal 分层**：smoke 只验证链路；formal 才能作为方法效果和状态判断依据。
4. **Diagnostic by default**：本方法默认保持 `TARGET_SLICE_DIAGNOSTIC`，不自动替换 ranking input，不自动进 pool1000。
5. **Drift controlled expansion**：title token 扩展必须受 category overlap、bucket cap、undercoverage audit 约束。

### Decision Drivers

1. recent-2y 数据基础已经替换旧 full-data，旧 sidecar artifact 不能作为当前结论。
2. `semantic_title_category_expansion` 是 lexical title/category metadata expansion，不是 dense semantic / two-tower / oracle repair。
3. 主路并入需要 formal 效果、互补性、资源成本和 route gate 证据；单方法窗口只能给建议，不做最终全局收口。

### Viable Options

#### Option A：保守诊断构建（推荐）

- 使用现有 `title_category_scorer`，修正 config/runner 参数口径，构建 recent-2y smoke/formal artifact。
- 优点：低资源、可解释、泄漏风险小、能快速产出可复核 manifest/stats。
- 缺点：可能 Recall 不高，更多体现覆盖/补充价值而非主力召回。

#### Option B：扩展为 BM25/dense/hybrid semantic retrieval

- 新增 BM25 或 embedding index，把 title/category 作为 query-item retrieval。
- 优点：可能提高语义覆盖。
- 缺点：需要新增索引、评估和 drift gate；资源和实现范围更大，且容易与 canonical `semantic` 混淆。

#### Option C：eval-label-driven token/category tuning

- 根据 valid/test 命中反向挑 token/category。
- 结论：不可选。违反 train-only governance 和 no-oracle/no-label-injection 约束。

### Decision

采用 Option A：先完成 recent-2y train-only 诊断级 formal artifact 与 evaluation-only 报告。若 formal 证据不足，保持 `DEFERRED` / `TARGET_SLICE_DIAGNOSTIC` 并列 blocker，不强行 READY。

## 2. 当前现状与缺口

- `configs/recall/pool500_method_registry.json` 中该方法状态为 `DEFERRED`，`latest_artifact` 指向旧 sidecar 路径，`latest_row_count=0`。
- `source_config.yaml` 已包含 recent-2y 输入，但需要统一 `source_status`、`tier_aliases` 和 smoke/formal 方法参数。
- `scripts/experiments/recall/pool500/run_pool500_method_source.py` 必须确保该 source 从 `method_config` 读取 `limit_users/seed_window/per_user/per_seed/per_token_item_limit/max_candidate_items/selection_mode`。
- `builder.py` 已能输出七件套并固定 `TARGET_SLICE_DIAGNOSTIC`，适合作为本轮构建入口。
- 缺少本轮 `RECENT2Y_SCIOMC_RESEARCH.md`、本计划、formal source artifact、evaluation-only report 和文档/registry 收口。

## 3. Dataset contract

### smoke contract

- 输入：
  - `data/processed/amazon_2023_recall_recent_2y_1m_3m/manifest.json`
  - `data/processed/amazon_2023_recall_recent_2y_1m_3m/recall_views/manifest.json`
  - `outputs/recall/pool500_method_sources_newdata/eligible_users_semantic_recent2y_smoke_v1/eligible_user_manifest.json`
- 用户：200，含 collaborative_rich、sequence_sufficient、fallback_only、cold_start 小样本。
- 参数：`seed_window=20`、`per_user=80`、`per_seed=40`、`per_token_item_limit=1000`、`max_candidate_items=30000`。
- 目的：program/schema/path/governance validation only。

### formal contract

- 输入：
  - `data/processed/amazon_2023_recall_recent_2y_1m_3m/manifest.json`
  - `data/processed/amazon_2023_recall_recent_2y_1m_3m/recall_views/manifest.json`
  - `outputs/recall/pool500_method_sources_newdata/eligible_users_semantic_recent2y_formal_v1/eligible_user_manifest.json`
- 用户：50000，collaborative_rich 10000、sequence_sufficient 30000、fallback_only 10000。
- 参数：`seed_window=50`、`per_user=120`、`per_seed=60`、`per_token_item_limit=2000`、`max_candidate_items=200000`。
- 目的：official method logic dataset under recent-2y train-only governance。

## 4. 执行步骤

1. **配置修正**
   - `source_config.yaml`：统一 `source_status=TARGET_SLICE_DIAGNOSTIC`，加入 `recent2y_smoke/recent2y_formal` tier aliases，固化 smoke/formal 参数。
   - runner：确保 `semantic_title_category_expansion` 使用 `method_config`，而不是误读 `resource_guard`。

2. **dry-run 验证**

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source semantic_title_category_expansion --tier recent2y_smoke --run-id recent2y_smoke_dry --dry-run
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source semantic_title_category_expansion --tier recent2y_formal --run-id recent2y_formal_dry --dry-run
```

3. **构建 smoke artifact**

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source semantic_title_category_expansion --tier recent2y_smoke --run-id semantic_title_category_recent2y_smoke_v1 --overwrite
```

4. **构建 formal artifact**

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source semantic_title_category_expansion --tier recent2y_formal --run-id semantic_title_category_recent2y_formal_v1 --overwrite
```

5. **formal evaluation-only 报告**
   - 读取 formal `candidates.jsonl`。
   - 读取 recent-2y `canonical_interactions.valid.jsonl` 与 `canonical_interactions.test.jsonl` 作为 evaluation-only labels。
   - 只对候选 artifact 中出现且有 label 的用户计算 Recall@20/50/100/500、HitRate@20/50/100/500、候选数、用户覆盖、正样本覆盖。
   - 报告中写明 label 不参与候选生成。

6. **文档和 registry 收口**
   - 更新 `METHOD.md`、`dataset_policy.yaml`、`source_config.yaml`、`pool500_method_registry.json`。
   - 若 formal 指标/互补性不足，保持 `DEFERRED`，不改 READY。
   - 更新 `dic/ENGINEERING_NARRATIVE_LOG.md`。

7. **测试与验证**

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_pool500_semantic_newdata_config.py tests/test_pool500_semantic_title_category_source.py tests/test_pool500_method_source_runner.py -q
```

## 5. 完成条件

- 已有 SciOMC 调研文档和本计划。
- smoke/formal artifact 七件套存在且 manifest/status/governance 字段一致。
- `no_holdout_audit.json` 为 PASS。
- formal report 给出 Recall@K/HitRate@K 或明确 label overlap 不足的 blocker。
- `METHOD.md`、`source_config.yaml`、`dataset_policy.yaml`、registry 条目已更新为 recent-2y 当前事实。
- 最终明确 readiness 和主路并入建议；不得用 smoke 或旧 artifact 晋升。

## 6. 停止条件 / blocker

- formal 构建资源超限且不能迁移 server：停止并记录资源 blocker、命令和回传清单。
- `no_holdout_audit` BLOCKED：停止，不生成晋升结论。
- formal 候选为 0 或覆盖严重不足：保持 `DEFERRED`，记录 undercoverage 原因。
- evaluation-only label 与 formal 用户交集不足：只报告 artifact coverage，不宣称 Recall 正式有效。
- 缺少 overlap/route gate 证据：不进入主路，仅建议后续全局收口评估。

## 7. ADR

**Decision**：本轮采用受控 title/category overlap scorer 构建 recent-2y smoke/formal source artifact，默认保持 diagnostic/deferred 状态。

**Drivers**：recent-2y 数据切换、train-only governance、防止旧 artifact 回流、防止 title/category 语义漂移、防止 smoke 冒充 formal。

**Alternatives considered**：

- BM25/dense/hybrid retrieval：暂不做，留给 canonical semantic/RAG 方向；
- eval-label-driven expansion：拒绝，违反治理；
- 直接晋升 READY：拒绝，缺少 formal route gate 和互补性证据。

**Consequences**：能快速获得可复核 artifact 与诊断指标，但主路并入仍需后续全局 route gate。

**Follow-ups**：若 formal 指标显示有边际价值，再做 source overlap、route gate、candidate merge regression，并考虑 BM25/hybrid 的受控增强版本。
