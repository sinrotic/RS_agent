# RS Agent Online Phase 2 入口清单

> 目的：为 `RS_AGENT_POST_MIGRATION_HARDENING_PLAN.md` Phase 2 的 recall/ranking 入口收束提供可复查证据。本文只记录入口与边界现状，不代表 Phase 2 已整体完成，也不授权删除未完成的旧路径。

## 结论口径

- 新的 HTTP online service 已经走 `rs_core.serving.api.online_app` + `rs_core/online` canonical boundary。
- 旧 `rs_core/serving` 仍保留为 single-process/demo 兼容服务入口，不能直接删除。
- `OnlinePool500Recommender` 真实 pool500 runtime host 已迁入 `rs_core/online/runtime/pool500.py`；旧 `rs_core/workflow/online_recommendation.py` 在确认 active import 清零后已退役删除，不能恢复为 online 主入口。
- source canonicalization / merge 工具层与 recall source readiness registry 已物理迁入 `rs_core/online/recall` 与 `rs_core/online/recall/source_registry`；旧 `rs_core/recsys/recall`、`rs_core/recsys/recall_sources` 以及 `rs_core/recsys` active package 已删除，`scripts/recall/*` 仍是 recall artifact/index 构建入口，不是 online runtime 入口。
- `rank_candidates()`、coarse/fine/rerank、DeepFM policy gate、COLD→DeepFM 训练/诊断链路已物理迁入 `rs_core/online/ranking/`；旧 `rs_core/recsys/ranking.py` 与 `rs_core/recsys/cold_deepfm.py` active modules 已删除。
- COLD→DeepFM 仍以离线/诊断/Agent tool 路线为主，不应直接替代 public `/rank` 主路；`rs_core/online/ranking/cold_deepfm.py` 保留 diagnostic shadow wrapper，输出仍受 no-promotion contract 约束。

## Canonical online boundary

| 边界 | 文件/入口 | 当前职责 |
| --- | --- | --- |
| Online HTTP app | `rs_core.serving.api.online_app/app.py` | `create_app()` 挂载 `/ready`、`/recommend`、`/recall`、`/rank`。 |
| Online engine 注入 | `rs_core.serving.api.online_app/dependencies.py` | `get_online_engine()` 缓存并返回 `OnlineRecommendationEngine`。 |
| Canonical engine | `rs_core/online/engine/__init__.py` | 提供 `ready()`、`recommend()`、`recall()`、`rank()` public boundary。 |
| Recall boundary | `rs_core/online/engine/__init__.py` | `recall()` 通过 `RecallRequest` 校验，并输出 `RecallResult`/`RecallTrace`。 |
| Ranking boundary | `rs_core/online/engine/__init__.py` | `rank()` 通过 `RankingRequest` 校验，并输出 `RankingResult`/`RankingTrace`；COLD→DeepFM shadow 只作为 diagnostic route。 |
| Online clients | `rs_core/online/clients/__init__.py` | 轻量 client 绑定 engine，不回流旧 serving app。 |

## 仍需保留/治理的旧 online serving 入口

| 旧入口 | 文件/入口 | 现状与治理含义 |
| --- | --- | --- |
| single-process service CLI | `scripts/serving/run_service.py` | 仍启动 `rs_core.serving.api.app:app`，属于兼容/本地服务入口。 |
| serving app | `rs_core/serving/api/app.py`、`rs_core/serving/api/factory.py` | 旧 serving FastAPI 组装仍存在，后续只能在 parity/smoke 充足后退役。 |
| serving recommendation service | `rs_core/serving/application/recommendation_service.py` | 通过 `rs_core.online.runtime.build_online_pool500_recommender()` 构建 online runtime host，不再直接 import `rs_core.workflow.online_recommendation`。 |
| route registry | `rs_core/serving/runtime/config.py` | 仍读取 `current_online_service_route` 并校验 serving governance。 |
| online runtime boundary | `rs_core/online/runtime/__init__.py`、`rs_core/online/runtime/pool500.py` | `__init__.py` 保持 public builder/re-export；`pool500.py` 承载 `OnlinePool500Recommender` 真实实现。 |

## Recall 入口清单

### 已走 canonical boundary

- `rs_core.serving.api.online_app/app.py`：`/recall` 调用 `engine.recall(request)`。
- `rs_core/online/engine/__init__.py`：`OnlineRecommendationEngine.recall()` 固化 public fallback contract，并拒绝 oracle/label 字段。
- `tests/online/test_online_engine_contracts.py`：直接覆盖 recall public shape 与 evaluation-only 字段拒绝。
- `rs_core/online/recall/{canonical.py,merge.py,candidate_merge.py}`：承接原 `rs_core/recsys/recall` 的 source canonicalization、fallback merge 工具，以及原 `rs_core/recsys/candidate_merge.py` 的候选加载、召回候选生成、source budget 与候选融合能力；旧 active path 已删除。
- `rs_core/online/recall/source_registry/`：承接原 `rs_core/recsys/recall_sources` 的 `RecallSourceSpec`、readiness groups、candidate-generating source registry 与 JSON registry drift 对齐；旧 active path 和旧 `rs_core/recsys` 包根已删除。

### 已迁入 online runtime 的真实能力

- `rs_core/online/runtime/pool500.py`：`OnlinePool500Recommender` 是 pool500 runtime host 的真实实现。
- `rs_core/online/runtime/pool500.py`：`recommend()` 编排 pool500、candidate retrieval、legacy fallback 与 display enrichment。
- `rs_core/online/runtime/pool500.py`：`tool_retrieve_candidates()` 仍是 Agent tool 的真实 candidate retrieval 能力。
- `rs_core/online/runtime/pool500.py`：无 online retrieval config 时仍走 legacy recall candidate fallback。
- `rs_core/online/recall/online_retrieval/`：承接原 `rs_core/recsys/online_retrieval` 的 orchestrator、provider contract、config、candidate-store providers、semantic token/vector providers 与 pool500 fallback provider；旧 active package 已删除。
- `rs_core/online/recall/candidate_store/`：承接原 `rs_core/recsys/candidate_store` 的 CandidateStore contract、Noop/Safe wrapper、MySQL/Scylla(Cassandra) backend、factory 与 row schema adapter；旧 active package 已删除。
- `rs_core/online/recall/pool500_artifacts.py`：承接原 `rs_core/recsys/pool500_artifacts.py` 的 pool500 candidate artifact loader、oracle/internal-field guard、per-user candidate index 与 readiness 输出；旧 active module 已删除。
- `rs_core/common/recsys_types.py`：承接原 `rs_core/recsys/types.py` 的 `RecallCandidate`、`MergedCandidate`、`RankingResult`、`AgentDecision`、`EvaluationSummary` 等跨 online/agent/offline shared dataclass types；旧 active module 已删除，online recall/ranking/runtime、agent 和 offline/evaluation 调用点均改走 common canonical path。
- `rs_core/online/ranking/ltr.py`：承接原 `rs_core/recsys/ltr.py` 的 LTR 特征提取、打分、轻量训练与模型读写工具；旧 active module 已删除，online ranking、COLD→DeepFM、workflow LTR training、ranking experiments 和 tests 均改走 online ranking canonical path。
- `rs_core/online/recall/vector_index.py`：承接原 `rs_core/recsys/vector_index.py` 的 two-tower/local vector index artifact loader、向量搜索、批量搜索、归一化与 dot score 工具；旧 active module 已删除，candidate merge、two-tower query/build、recall experiments 和 tests 均改走 online recall canonical path。
- `rs_core/online/recall/two_tower_source_manifest.py`：承接原 `rs_core/recsys/two_tower_source_manifest.py` 的 source index manifest schema、governance flags、路径安全和 row-count 校验；旧 active module 已删除，source index build、vector index loader、two-tower experiments 和 tests 均改走 online recall canonical path。
- `rs_core/online/recall/two_tower_query.py`：承接原 `rs_core/recsys/two_tower_query.py` 的 artifact-user-first two-tower 查询向量构建、train-only seed fallback、user tower projection 与 diagnostics；旧 active module 已删除，candidate merge、two-tower direct eval 与 pool500 two-tower builder 均改走 online recall canonical path。
- `rs_core/workflow/online_recommendation.py`：旧 import path compatibility facade 已删除；`rs_core.online.runtime.pool500` 是唯一 pool500 online runtime host。

### recall artifact/index 构建脚本入口

这些入口属于 artifact/index 生产，不是 online runtime；后续迁移应保留为 data/offline/recall build job 或显式挂到 data contract：

- `scripts/recall/build_two_tower_source_index.py`：two-tower source index 构建。
- `scripts/recall/two_tower_DSSM/build_two_tower_dssm_source_index.py`：two-tower DSSM source index 构建。
- `scripts/recall/build_two_tower_item_vocab.py`：two-tower item vocab 构建。
- `scripts/recall/build_qdrant_two_tower_index.py`：Qdrant two-tower index 构建。
- `scripts/recall/build_qdrant_rag_index.py`：Qdrant RAG index 构建。
- `scripts/recall/build_rag_bm25_index.py`：RAG BM25 index 构建。
- `scripts/recall/build_semantic_description_index.py`：semantic description index 构建。
- `scripts/recall/build_semantic_recent2y_eligible_manifests.py`：recent2y eligible manifest 构建。
- `scripts/recall/build_co_visit_recent2y_dataset_manifests.py`：co-visit dataset manifest 构建。

## Ranking 入口清单

### 已走 canonical boundary

- `rs_core.serving.api.online_app/app.py`：`/rank` 调用 `engine.rank(RankingRequest(...))`。
- `rs_core/online/engine/__init__.py`：`OnlineRecommendationEngine.rank()` 执行稳定去重 + 截断 fallback，并输出 public `RankingTrace`；当 `cold_deepfm_shadow.enabled=true` 时调用 canonical diagnostic wrapper。
- `rs_core/online/ranking/ranking.py`：`rank_candidates()`、`coarse_rank_candidates()`、`fine_rank_candidates()`、`rerank_candidates()`、DeepFM policy gate 与 artifact 解析的 canonical owner。
- `rs_core/online/ranking/cold_deepfm.py`：`rank_with_cold()`、`rank_with_deepfm()`、`run_cold_deepfm_chain()`、`rank_with_cold_deepfm_shadow_contract()` 的 canonical owner。
- `rs_core/online/ranking/__init__.py`：只 re-export `rs_core.online.ranking.ranking` 与 `rs_core.online.ranking.cold_deepfm`，不再 re-export `rs_core.recsys.*`。
- `tests/online/test_online_engine_contracts.py`：覆盖 rank 去重、public trace、COLD→DeepFM shadow no-promotion。

### 已改写到 canonical ranking 的调用点

- `rs_core/workflow/hybrid_demo.py`、`rs_core/workflow/pool500_shadow_ranking.py`：仍属于 workflow legacy 编排，但 ranking 调用已改为 `rs_core.online.ranking.rank_candidates()`。
- `rs_core/offline/evaluation/ranking.py`：承接原 `rs_core/recsys/evaluation.py` 的离线 ranking/recall 评估、冻结候选签名、ranking registry、promotion gate 与 artifact inspection 能力；旧 active module 已删除，workflow、agent、rs_lab ranking/recall 实验和 tests 均改走 offline evaluation canonical path。
- `rs_lab/experiments/recall/run_pool500_learned_ranking_challenger.py`、`phase_1_20_recall_diagnostics.py`、`phase_1_21_recall_coverage_experiments.py`：实验入口已改用 canonical ranking。
- `rs_lab/experiments/ranking/run_pool500_cold_deepfm_chain.py`、`run_cold_deepfm_offline_train_eval.py`、`build_pool500_cold_deepfm_dataset.py`：已改用 `rs_core.online.ranking.cold_deepfm`。
- ranking/core/feedback/inference/online tests 已改用 `rs_core.online.ranking` 或 `rs_core.online.ranking.cold_deepfm`。

### 已删除的旧 ranking modules

- `rs_core/recsys/ranking.py`：已删除，由 architecture path-not-exists guard 防止恢复。
- `rs_core/recsys/cold_deepfm.py`：已删除，由 architecture path-not-exists guard 防止恢复。
- AST census 目标：`rs_core.recsys.ranking` 与 `rs_core.recsys.cold_deepfm` 正向 import 为 0。

## Phase 2 后续边界

- `OnlinePool500Recommender` runtime host 已物理迁入 `rs_core/online/runtime/pool500.py`；旧 `rs_core/workflow/online_recommendation.py` 已在旧 import path 清零后删除，后续通过 architecture boundary 的 path-not-exists guard 防止回流。
- `CandidatePoolClient` / `ArtifactClient` 已接入 fallback recall 与 COLD→DeepFM diagnostic shadow 读取；真实 pool500 runtime 中更深的 source index / display enrichment 仍待后续分层迁移。
- `rs_core/recsys` active package 已完成物理收束：通用 Milvus/vector store client、schema、filter、payload 与 build utils 已迁入 `rs_core/data/vectorstores/`，two-tower source/index build 与 backfill helpers 已迁入 `rs_core/online/recall/vectorstores/`；`recall_sources/*` 已迁入 `rs_core/online/recall/source_registry/`；`evaluation.py` 已迁入 `rs_core/offline/evaluation/ranking.py`，`types.py` 已迁入 `rs_core/common/recsys_types.py`，`ltr.py` 已迁入 `rs_core/online/ranking/ltr.py`，`vector_index.py` 已迁入 `rs_core/online/recall/vector_index.py`，`two_tower_source_manifest.py` 已迁入 `rs_core/online/recall/two_tower_source_manifest.py`，`two_tower_query.py` 已迁入 `rs_core/online/recall/two_tower_query.py`，`two_tower.py` 训练实现已迁入 `rs_core/offline/training/two_tower.py`，`candidate_merge.py` 已迁入 `rs_core/online/recall/candidate_merge.py`，`candidate_store/*` 已迁入 `rs_core/online/recall/candidate_store/`，`pool500_artifacts.py` 已迁入 `rs_core/online/recall/pool500_artifacts.py`；旧 `rs_core/recsys` 包根由 path-not-exists guard 防恢复。
- COLD→DeepFM canonical implementation 已落在 online ranking，但仍保持 diagnostic/no-promotion 约束；更进一步的 public ranking integration 仍需单独设计和验证。
