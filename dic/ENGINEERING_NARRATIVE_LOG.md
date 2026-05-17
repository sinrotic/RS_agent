# 工程叙事日志

本文档用于记录本项目中具有复盘价值的工程过程，目标是把开发、调试、优化和验证过程沉淀成适合面试表达的中文材料。

记录重点不是流水账，也不是私有思维链，而是可验证的工程叙事：问题是什么、如何定位、为什么这样解决、如何证明有效、面试时怎么讲。

## 记录原则

- 默认使用中文。
- 每条记录保持简洁，优先写事实和证据。
- 引用具体文件、命令、测试、指标或输出路径。
- 不记录无意义的中间尝试，不堆 raw log。
- 简单机械修改不需要单独记录。

## 条目模板

### 2026-05-14 - 固定 Phase 1 混合召回主路

**任务：**
在已补跑 graph、vector/two-tower、MF、sequence/multi-interest、source-aware 截断等实验后，按用户要求把当前效果最好的混合召回路线固定为默认主路，并同步更新配置与文档结论。

**遇到的问题：**
此前文档把 `source_balanced_fallback_preserving` 写成 observation / defer，因为它没有增加 `candidate_hit_users`；但重新对比全部 Phase 1.21 metrics 后发现，它在保持最高档 `candidate_hit_users=19` 的同时，让 target 更早进入候选池，并减少平均候选量。因此主路选择不能只看最终 pool 命中人数，还要综合前段召回位置、候选规模和尾部命中位置。

**定位方式：**
汇总 `outputs/recall/phase_1_21_recall_coverage/**/metrics.json`，按 `candidate_hit_users`、`candidate_hit_rate_at_100`、`recall_at_pool`、`candidate_hit_rank_avg/p90`、`candidate_count_avg` 对比所有已执行路线。`source_balanced_fallback_preserving` 达到 `candidate_hit_users=19`、`candidate_hit_rate_at_100=0.130435`、`candidate_hit_rank_avg=31.315789`、`candidate_hit_rank_p90=64.0`、`candidate_count_avg=126.972`，综合优于 score-sorted 和其他 graph/vector/MF/sequence 路线。

**解决方式：**
将 `configs/recall/phase_1_21/phase_1_21_recall_coverage_pool200_experimental.yaml` 固定为混合主路：启用 `semantic_title_category_expansion`、`co_visit_fallback_repair`、UserCF、Swing，并设置 `candidate_pool_strategy: balanced_source_budget`、source minimums、`popular` 上限和 fill order。文档中把 source-balanced 从 `defer` 改为 `current_main_route`，明确 graph、MF、sequence 等不进入当前主路。

**验证结果：**
已复用同合同实验 artifact：`outputs/recall/phase_1_21_recall_coverage/source_aware/comparison/source_balanced_fallback_preserving/metrics.json`。随后用固定后的 `configs/recall/phase_1_21/phase_1_21_recall_coverage_pool200_experimental.yaml` 复验，输出 `outputs/recall/phase_1_21_recall_coverage/current_main_route_pool200_source_balanced/`，holdout hash 仍为 `927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2`。该路线保持 `candidate_hit_users=19`、`candidate_hit_rate_at_pool=0.137681`，并相对 score-sorted 把 `candidate_hit_rate_at_100` 从 `0.123188` 提到 `0.130435`，`candidate_hit_rank_avg/p90` 从 `34.526316/73.0` 改善到 `31.315789/64.0`，`candidate_count_avg` 从 `136.214` 降到 `126.972`。

**面试可讲点：**
这段可以讲成“用指标治理选择混合召回主路”：不是因为某个算法名字高级就晋升，而是在同一 holdout、同一 pool200 合同下比较多路召回、前段命中、候选池体积和 source 平衡，最终把语义主增量 + 行为 fallback + 兜底源 + source-balanced 截断固定为可解释、可维护的召回主线。

### YYYY-MM-DD - 任务标题

**任务：**
简要说明这次任务要完成什么。

**遇到的问题：**
说明遇到的技术障碍、歧义、缺陷、数据问题或工程取舍。

**定位方式：**
说明如何诊断问题，引用具体文件、命令、测试、指标或输出证据。

**解决方式：**
说明采用了什么方案，为什么这个方案合理。

**验证结果：**
说明用什么测试、命令、输出文件或指标证明结果有效。

**面试可讲点：**
把这次工作提炼成面试中可以讲的工程能力、系统思维或技术亮点。

## 记录

### 2026-05-16 - Phase 0 召回方法合同预检入口

**任务：**
为召回方法全家桶 Phase 0 增加只做合同预检的入口，落盘 `manifest.json`、`source_audit.json` 和 `resolved_inputs.json`，为后续 Phase 2-5 动态输入解析提供可审计基线。

**遇到的问题：**
后续 UserCF、Swing、Sequence、Graph、MF、Two-Tower 等阶段依赖不同输入和配置，若直接猜路径或混用 ranking pool，会造成 scope drift；同时 candidate generation 必须继续禁止读取 valid/test/holdout，并把召回晋升 gate 与 ranking frozen pool200 gate 分离。

**定位方式：**
先读取 `.omc/handoffs/phase0-contract-schema-notes.md` 明确三份 JSON schema，再核验 full clean、full lightweight views、代表性 baseline、bounded ItemCF sidecar、graph/two_tower config 和 ranking pool200 config 的真实路径与 sha256。

**解决方式：**
新增 `scripts/run_phase0_contract_precheck.py`，默认输出到 `outputs/recall/full_main_route_other_methods/phase0_contract_precheck/`；脚本强制项目 `.venv`、D 盘 50GiB 水位、10k 路径拒绝、holdout read contract，并在无法解析动态输入或具体 config 文件时写 `BLOCKED_MISSING_ARTIFACT` / `INVALID_SCOPE_DRIFT`，不执行任何下游阶段。

**验证结果：**
已用项目 `.venv` 执行 `python -m pytest tests/test_phase0_contract_precheck.py`，结果 `5 passed`；执行 `python -m ruff check scripts/run_phase0_contract_precheck.py tests/test_phase0_contract_precheck.py`，结果 `All checks passed`。运行 Phase 0 入口后三份产物已写入 `outputs/recall/full_main_route_other_methods/phase0_contract_precheck/`，因当前 graph、two_tower 和 ranking pool200 具体 config 仍引用历史 10k 路径，manifest 按合同返回 `INVALID_SCOPE_DRIFT` 并写入 `failure_reason`。独立 verifier 已批准 US-001，确认 source_audit 的 `read_files` 不包含 valid/test/holdout，后续 Phase 1+ 必须先修复 full-clean-safe config 后才能继续。

**面试可讲点：**
这段可以讲成“在推荐召回实验前加合同闸门”：面对多阶段召回方法扩展，不急于跑算法，而是先把输入、配置、数据泄漏边界、资源水位和 ranking/recall gate 明确为可审计 artifact，降低后续实验复现和 scope drift 风险。

### 2026-05-16 - bounded ItemCF co-visit sidecar 代表性构建验收

**任务：**
在 full clean 真实训练序列上执行受边界约束的 ItemCF/co-visit sidecar 代表性构建，验证它只生成可审计的邻居分片产物，不复制 full clean、不生成 pool500/pool1000 或 recall views。

**遇到的问题：**
直接从 full clean 构建共现邻居存在资源和产物污染风险，需要把执行范围限制在 `limit_users<=1000`，同时继续保证 10k 路径、valid/test/holdout 读取和重型输出都被排除。

**定位方式：**
使用 `.venv` 运行 focused pytest 与 ruff，随后检查 `outputs/recall/full_main_route_other_methods/bounded_itemcf_covisit_sidecar_representative/manifest.json` 和 `source_audit.json` 中的 safety flags、输入路径、输出键与目录文件集合。

**解决方式：**
执行 `scripts/run_bounded_itemcf_covisit_sidecar_build.py`，显式传入 full clean 目录、代表性输出目录、`--limit-users 1000` 和 `--min-free-bytes 53687091200`；脚本只读取 `user_sequences.train.jsonl`，写入 manifest、source audit 和 32 个 `neighbors_shard_*.jsonl`。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_bounded_itemcf_covisit_sidecar_build.py` 结果 `7 passed`，`./.venv/Scripts/python.exe -m ruff check scripts/run_bounded_itemcf_covisit_sidecar_build.py tests/test_bounded_itemcf_covisit_sidecar_build.py` 通过。真实构建输出目录共 34 个文件，`users_scanned=1000`、`processed_users=363`、`pair_updates=5264`、`project_venv_enforced=true`、`train_only=true`、`min_free_bytes=53687091200`；核验确认无 10k source path、无 valid/test/holdout 读取、无 pool500/pool1000/recall view/full clean copy 输出。

**面试可讲点：**
这段可以讲成“把行为共现召回从 dry-run 风险评估推进到受控 sidecar 产物”：通过硬上限、磁盘水位、train-only source audit、分片输出和 focused 测试，把原本容易失控的共现邻居构建变成可审计、可复跑、可逐步扩大的离线召回资产。

### 2026-05-16 - bounded ItemCF co-visit sidecar dry-run 预检

**任务：**
在不生成邻居 sidecar、不复制 full clean、不物化 pool500/pool1000 的前提下，为 full clean 上的 ItemCF/co-visit 行为召回补一条有边界的 dry-run 预检路径，先估算 pair 行数和分片字节风险。

**遇到的问题：**
已有 ItemCF/co-visit 逻辑适合小样本或受控候选池，但 full clean 的 `user_sequences.train.jsonl` 规模达到 18103384 行，直接建邻居可能带来磁盘、内存和产物污染风险；同时必须确保不误读 valid/test/holdout、不回退到 10k 路径、不生成 full clean copy 或 pool500/pool1000 输出。

**定位方式：**
只读审查 `scripts/build_recall_views.py` 中 `build_itemcf_edges(...)`、`build_item_graph_view(...)` 和 `build_lightweight_full_safe_views(...)`，确认可复用 pair/cap 估算思路，但 dry-run 不能调用真实写邻居函数；再检查 `scripts/run_full_lightweight_recall_e2e.py` 的 10k 路径拒绝、输出目录拒绝和 `.venv` 约束，作为 sidecar 预检脚本的安全门参考。

**解决方式：**
新增 `scripts/run_bounded_itemcf_covisit_dry_run.py`，只读取 `data/processed/amazon_2023_recall_clean_full/user_sequences.train.jsonl`，强制 `limit_users<=1000`、默认 50GiB 磁盘水位、拒绝 10k 路径和已存在输出目录；脚本只维护 bounded pair counter 和 shard byte estimate，最终只写 `manifest.json`。

**验证结果：**
新增 `tests/test_bounded_itemcf_covisit_dry_run.py`，覆盖 manifest-only、train_only/holdout contract、10k 路径拒绝、输出目录拒绝、输出位于 clean_dir 内拒绝和 `limit_users>1000` 拒绝。验证命令 `./.venv/Scripts/python.exe -m pytest tests/test_bounded_itemcf_covisit_dry_run.py tests/test_full_lightweight_recall_e2e.py` 结果 `8 passed`，`./.venv/Scripts/python.exe -m ruff check scripts/run_bounded_itemcf_covisit_dry_run.py scripts/run_full_lightweight_recall_e2e.py tests/test_bounded_itemcf_covisit_dry_run.py tests/test_full_lightweight_recall_e2e.py` 通过。真实 dry-run 输出 `outputs/recall/full_main_route_other_methods/bounded_itemcf_covisit_dry_run_estimate/manifest.json`，目录仅包含 manifest；manifest 记录 `train_only=true`、`limit_users=1000`、`sampled_users=1000`、`estimated_pair_rows=10528`、`planned_shard_count=32`、D 盘剩余 `225294610432` bytes，且未生成 neighbor/shard/pool500/pool1000 产物。

**面试可讲点：**
这段可以讲成“给重型召回源加 sidecar 预检闸门”：面对千万级行为序列，不直接上线全量共现构建，而是先用只读 train、硬阈值、路径拒绝、manifest-only 和分片字节估算把风险前移，证明推荐系统离线工程不仅追求召回效果，也要控制资源边界和数据泄漏边界。

### 2026-05-15 - 全量召回轻量索引安全路径

**任务：**
为 232 万商品、5605 万去重交互的 full clean 数据补一条 Phase 0.5 + Phase 1a 的安全召回索引路径，先只构建 Popular、Category、Semantic catalog/inverted index，避免直接触发 ItemCF/item_graph 等重型全量共现逻辑。

**遇到的问题：**
旧 `scripts/build_recall_views.py` 的主流程会无条件构建 ItemCF 和 item graph，内部包含全局 pair/edge 聚合；如果直接套到 full clean，存在内存、磁盘和失败恢复风险，也不符合“不复制 full clean、不全用户物化 pool500/pool1000”的执行边界。

**定位方式：**
审查 `scripts/build_recall_views.py` 的 main 流程，确认 `build_itemcf_views(...)` 与 `build_item_graph_view(...)` 在默认路径中必跑；结合 full clean `stats.json` 中 `canonical_items_written=2320263`、`filtered_rows=56054775` 的规模判断，必须先把轻量 catalog 索引和重型行为召回拆开。

**解决方式：**
新增 `--lightweight-full-safe` 模式：只写 `popular_recall.jsonl`、`category_recall_items.jsonl`、`category_top_items.jsonl`、`semantic_recall_inputs.jsonl` 和 `semantic_inverted_index.jsonl`；通过 `_tmp` 目录构建后原子提升到目标目录；manifest/stats 记录 source signature、输入行数、磁盘水位、产物大小和 skipped heavy outputs；默认旧路径保持兼容。

**验证结果：**
新增 `tests/test_build_recall_views.py` 覆盖 lightweight 模式不会生成 `itemcf_recall_weak.jsonl`、`itemcf_recall_strong.jsonl`、`item_graph_recall.jsonl`，并检查 semantic inverted index、source row count、canonical sha256、真实 `_tmp` 证据和最终产物 hard cap。已通过 `./.venv/Scripts/python.exe -m pytest tests/test_build_recall_views.py -q`，结果 `3 passed`；通过 `./.venv/Scripts/python.exe -m ruff check scripts/build_recall_views.py tests/test_build_recall_views.py`；CLI smoke 验证 lightweight 入口可生成 manifest/stats 且不产生重型召回文件；独立 architect 复核结论为 PASS。

**面试可讲点：**
这段可以讲成“把研究型全量召回改造成可控索引层”：面对千万级交互，不是直接把小样本脚本放大运行，而是先拆出轻量 catalog 索引、显式跳过高风险共现源，并用 manifest、source signature、磁盘阈值、产物上限和原子目录提升把全量实验变成可恢复、可解释、可扩展的工程流程。

### 2026-05-16 - full clean 轻量召回索引全量落盘验收

**任务：**
在真实 `data/processed/amazon_2023_recall_clean_full` 上执行已审批的 `--lightweight-full-safe` 路径，把 Phase 1a 的 Popular、Category、Semantic catalog/inverted index 从方案推进到可消费的全量产物。

**遇到的问题：**
全量输入包含 2320263 个商品与 44843821 条 train 交互，直接运行必须同时控制磁盘、内存和范围偏离风险；尤其要防止误触发 ItemCF/item_graph、复制 full clean、覆盖 10k baseline 或遗留 `_tmp` 半成品。

**定位方式：**
执行前用 `.venv` 检查 full 输入、`canonical_interactions.train.jsonl`、`canonical_items.jsonl`、manifest/stats、10k baseline、目标输出目录和 sibling `_tmp` 目录；运行中记录 D 盘剩余空间、tmp/final 目录大小和 Python 进程 RSS，第二轮采样显示 tmp 约 6.53GiB、D 盘约 210.27GiB、主进程 RSS 约 15.7GiB，未触发 50GiB/80GiB/32GiB 停止阈值。

**解决方式：**
使用项目 `.venv` 执行 `scripts/build_recall_views.py --lightweight-full-safe`，显式设置 `--lightweight-min-free-bytes 53687091200`、`--lightweight-max-output-bytes 85899345920`、`--semantic-inverted-top-k 2000`；构建通过 `_tmp` 原子提升到 `data/processed/amazon_2023_recall_views_full_lightweight`，不生成重型召回文件。

**验证结果：**
后台构建退出码为 0，生成 `manifest.json`、`stats.json`、`popular_recall.jsonl`、`category_recall_items.jsonl`、`category_top_items.jsonl`、`semantic_recall_inputs.jsonl`、`semantic_inverted_index.jsonl`。验收脚本确认 JSON/JSONL 抽样可解析、manifest outputs 路径有效、`itemcf_recall_weak.jsonl`、`itemcf_recall_strong.jsonl`、`item_graph_recall.jsonl` 不存在、sibling `_tmp` 已清理、10k baseline 仍存在；最终输出 7 个文件、7483658110 bytes（约 6.97GiB），D 盘剩余约 209.83GiB，source signature 记录 `canonical_items.jsonl` 行数 2320263、`canonical_interactions.train.jsonl` 行数 44843821。

**面试可讲点：**
这段可以讲成“把推荐系统全量索引构建做成有安全门的批处理”：先用 consensus plan 固化资源阈值和验收标准，再用 `.venv`、原子目录提升、manifest 驱动验证、heavy output absence check 和资源监控，证明千万级数据产物不是一次性跑出来，而是可审计、可回滚、可接入后续排序链路的工程资产。

### 2026-05-15 - 工程规范 v1 与轻量 CI 门禁建设

**任务：**
为持续扩张的 RS Agent 项目建立第一版统一工程规范，覆盖目录边界、配置命名、测试分层、ruff/pytest 工具入口、CI smoke gate 和前端 lint 门禁。

**遇到的问题：**
项目已有 `architecture/ARCHITECTURE.md` 和 `PROJECT_STRUCTURE.md` 描述边界，但缺少可执行门禁；最初直接把 ruff 扩到较大范围会触发大量历史风格问题，`tests/test_serving_smoke.py` 还存在个人机器 `D:/...` 绝对路径，`pytest -m "unit or smoke"` 如果没有显式 marker 容易空跑。

**定位方式：**
检查 `rs_core/`、`tests/`、`configs/`、`frontend/package.json`、`.gitignore` 和现有 requirements，确认当前没有 `pyproject.toml`、pytest marker 配置和 GitHub Actions；通过本地验收发现 ruff baseline、pytest collect 非空检查和临时验证产物清理等实际问题。

**解决方式：**
新增 `dic/standards/ENGINEERING_STANDARDS.md` 和 `pyproject.toml`，注册 `unit/smoke/slow/gpu/experiment/serving/frontend` markers，并把 package discovery 限定为 `rs_core*`；为 8 个最小主链路测试文件添加 `pytestmark`，修复 serving smoke 的绝对路径；新增 `.github/workflows/ci.yml`，只安装 serving + dev 轻依赖，不安装 training 重依赖；ruff v1 收敛为 pyflakes/F 类真实错误门禁，并最小修复未使用导入和变量遮蔽。

**验证结果：**
已通过 `./.venv/Scripts/python.exe -m pip install -e ".[dev]" -r requirements-serving.txt`、`./.venv/Scripts/python.exe -m ruff check rs_core tests/test_serving_smoke.py tests/test_agent_runtime.py tests/test_inference_policy.py tests/test_agent_dialogue.py tests/test_agent_feedback.py tests/test_feedback_rerank.py tests/test_evaluation.py tests/test_display_contract.py`、`pytest --collect-only -m "unit or smoke"` 收集 `67` 个测试、`pytest -m "unit or smoke"` 结果 `67 passed`、`npm --prefix frontend run lint`、tracked `_tmp` 配置检查和 `git diff --check`。独立 verifier 复核结论为 PASS。

**面试可讲点：**
这段可以讲成“从研究型推荐项目向可维护工程项目演进”：不是一次性生产级重构，而是先把目录边界、配置可复现性、主链路 smoke 测试、轻量 lint 和 CI 门禁落地，既保护 Agent/推荐核心链路，又避免规范建设拖慢实验迭代。

### 2026-05-15 - 推荐 Agent 项目全面质量体检

**任务：**
对当前 RS Agent 项目做一次只读全面检查，覆盖推荐/Agent 核心链路、后端 API 契约、前端交互、测试覆盖与工程卫生，并归纳修复优先级。

**遇到的问题：**
专项审查发现当前测试和类型检查虽然能通过，但仍存在业务语义层风险：显式 dislike 商品可能被 over-filter 恢复策略带回结果，simulation 首轮展示未进入客户状态，LOPO/冻结池评估仍需数据泄漏门禁复核；同时前端交互锁、错误展示、NaN 输入和工程门禁也存在可复现性风险。

**定位方式：**
并行审查 `rs_core/rsagent/policy.py`、`rs_core/rsagent/feedback_rerank.py`、`rs_core/simulation/runner.py`、`rs_core/recsys/evaluation.py`、`rs_core/serving/app.py`、`frontend/src/views/LiveDemo.tsx`、`frontend/src/api.ts`、`frontend/src/components/sandbox/*` 与测试/配置状态。综合验证运行 `.venv/Scripts/python -m pytest tests/test_agent_feedback.py tests/test_feedback_rerank.py tests/test_simulation_runner.py tests/test_serving_smoke.py -q`，结果 `42 passed in 0.91s`；前端运行 `npm --prefix "D:/sinrotic_code/python_project/summer/RS_agent/frontend" run lint`，`tsc --noEmit` 通过。

**解决方式：**
本轮未直接修改业务代码，而是形成修复顺序：先反转“restored disliked 可保留”的测试期望并区分硬/软约束恢复，再补 simulation 首轮 `RoleState` 更新与测试，然后增加 LOPO/冻结池泄漏门禁，随后修 MAP@K 定义、前端并发锁/NaN/422 错误展示，最后整理依赖、CI 入口和工作区卫生。

**验证结果：**
验证显示当前聚焦测试与前端类型检查通过，但结论明确指出“测试通过不等于语义正确”：`tests/test_feedback_rerank.py` 仍固化了风险行为，simulation 测试未覆盖首轮状态一致性，LOPO/冻结池输入侧缺少可证明无泄漏的门禁测试。

**面试可讲点：**
这次可以讲成一次从“测试通过”走向“契约正确”的质量治理：不仅检查功能是否能跑，还从推荐反馈闭环、仿真指标可信度、离线评估泄漏、前后端契约和工程可复现性五个角度识别隐性风险，体现推荐系统项目中对实验可信度和 Agent 交互正确性的治理能力。

### 2026-05-15 - Agent Runtime 边界收口与公共契约保护

**任务：**
把推荐 Agent 的 turn loop 从 `HybridRecommendationEnvironment.converse()` 中抽出到确定性的 `AgentRuntime`，同时保留环境层对召回、候选和排序数据的所有权，并确保内部 runtime trace 不进入前端/API 展示面。

**遇到的问题：**
运行时层如果直接调用 `recommend_for_user(...)` 或加载候选/召回/排序数据，会把调度职责和推荐域逻辑混在一起；如果把 `agent_runtime_trace` 直接透传到 display/export，又会把内部诊断暴露成公共契约。

**定位方式：**
审查 `rs_core/rsagent/runtime.py`、`rs_core/workflow/hybrid_environment.py`、`rs_core/display/builder.py` 和 `rs_core/serving/service.py`，并用 `tests/test_agent_runtime.py` 的源码断言验证 runtime 禁止导入/调用推荐入口、`converse()` 禁止直接调 dialogue plan/apply 与推荐/对话分支构造。

**解决方式：**
`AgentRuntime` 只通过 host protocol 编排 `plan_dialogue`、`apply_dialogue_plan`、`build_recommendation_turn` 和 `build_dialogue_turn`；环境层继续持有 `_recommendation_step(...)`、`_dialogue_only_turn(...)` 与 `recommend_for_user(...)`；stop-check 只修复当前 turn 的 final items/ranking/diagnostics/reward evidence，不修改 active constraints，也不二次触发召回或排序。

**验证结果：**
独立复验命令 `.venv/Scripts/python.exe -m pytest tests/test_agent_runtime.py tests/test_display_contract.py tests/test_serving_smoke.py -q` 通过，结果 `26 passed`。代码审查确认 `rs_core/rsagent/runtime.py` 没有 `recommend_for_user`、候选/召回文件加载或排序 helper 调用；`HybridRecommendationEnvironment.converse()` 仅规范化输入后委托 `self.runtime.run_turn(...)`；`build_display_record(...)` 只从 `DisplayResponse` 白名单字段构建公共响应，chat/feedback/export 不包含 `agent_runtime_trace`。

**面试可讲点：**
这段可以讲成“用窄协议拆分 Agent 运行时和推荐系统内核”：运行时负责可观测的 loop、trace、memory compact、budget 和 stop-check，环境层负责推荐数据与排序执行，从而在不改变召回/排序语义的前提下获得可测试、可解释、不会污染公共 API 的 Agent 架构边界。

### 2026-05-13 - Phase 4 stage shadow metrics 最终回填

**任务：**

为 Phase 4 补齐最终验证收口：确认弱指标、coarse shadow retention、stage main-lane matrix 与 frozen candidate 一致性都已经写入中文叙事。

**遇到的问题：**

如果只看 Top-5，会把 `rank movement`、`coarse shadow retention`、`would_drop_positive` 这类信号压扁成一条结论；但这些信号本身又只能做诊断，不能被写成 promotion evidence。

**定位方式：**

对照 `scripts/run_phase_4_stage_shadow_metrics.py`、`tests/test_phase_4_stage_shadow_metrics.py` 和 `outputs/ranking/phase_4_stage_shadow_metrics_smoke/comparison.json`，核对 `candidate_pool_size=200`、`top_k=5`、`artifact_inspection=PASS`、`frozen match/hash` 未变，以及 recall / merge 语义未变。

**解决方式：**

把 stage shadow metrics 统一收口为 diagnostic/supporting，把 coarse shadow 视为 retained main lane；comparison 中回填 stage main-lane matrix，但不把弱指标升级为晋升门禁。

**验证结果：**

`./.venv/Scripts/python.exe -m py_compile scripts/run_phase_4_stage_shadow_metrics.py tests/test_phase_4_stage_shadow_metrics.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_phase_1_31_ranking_scaffold.py tests/test_phase_3_tree_ranking_experiments.py tests/test_phase_4_stage_shadow_metrics.py -q` 结果 `11 passed`；smoke 保持 `candidate_pool_size=200`、`top_k=5`、`artifact_inspection=PASS`，且没有 online promotion evidence。

**面试可讲点：**

这段可以讲成“把排序实验的最终回填做成证据分层”：我保留了 coarse shadow 和弱指标，但明确把它们限制在诊断层，不让它们冒充晋升结论。

### 2026-05-13 - Phase 4 三阶段实验计划与弱指标收口

**任务：**

把 Phase 4 的排序路线从“只看 Top-5 成败”收口成 coarse shadow / fine / rerank / future-online 四路对照，并把 `coarse_rank` 从 pass-through 占位符升级为 shadow 主路。

**遇到的问题：**

`top_k=5` 作为唯一信号太硬，候选命中本来就稀疏，单个位置的波动很容易掩盖 coarse/fine/rerank 在 rank movement、near-miss rescue、source coverage 上的真实变化；如果只盯 Top-5，很容易把诊断能力误写成晋升结论。

**定位方式：**

对照 `outputs/ranking/phase_1_26_real_ranking_experiments_smoke/comparison.json`、`outputs/verification/verification_phase_1_30_smoke/comparison.json`、`outputs/ranking/phase_1_31_ranking_algorithm_scaffold_smoke/comparison.json`、`outputs/ranking/phase_4_neural_ranker_smoke/comparison.json` 和 `outputs/ranking/phase_7_8_future_online_gate_smoke/comparison.json`，复核 `candidate_pool_size=200`、`top_k=5`、`frozen_candidate_match=true`、`artifact_inspection=PASS`、coarse/fine/rerank stage counts，以及 future-online gate 的 blocked 状态。

**解决方式：**

把 `coarse_rank` 改成 shadow coarse main lane，只保留 coarse score / trace / rank movement，不缩池、不改召回语义；同时新增弱指标口径，只把它们当作诊断和选路依据，不当作 promotion evidence。fine、rerank 和 future-online 分别保持 learned ranker、bounded rerank trace 和 future-only 门禁，避免把不同层的证据混在一起。

**验证结果：**

现有 smoke 和回归已经证明物理流水线证据稳定：`comparison.json`、`artifact_inspection=PASS`、`frozen_candidate_match=true` 都能稳定复现，Phase 4 神经排序仍是 diagnostic/blocked，Phase 7/8 仍是 future-online / future-agent-online；当前没有把任何 future-online 指标写成离线晋升证据。

**面试可讲点：**

这段可以讲成“把排序实验从单点 Top-5 成败，升级为分层诊断体系”：我把 coarse/fine/rerank/future-online 分开治理，用弱指标解释为什么某些方法值得继续跑、为什么某些方法只能诊断，避免把短期 smoke 误当成模型晋升。

### 2026-05-14 - ALS/BPR MF 依赖解锁后固定合同补跑

**任务：**
按用户要求安装矩阵分解实验依赖，并把此前 dependency-gated 的 ALS/BPR 从“可跑待执行”推进到真实 Phase 1.21 固定合同实验。

**遇到的问题：**
`implicit` 可以安装并通过 smoke；`lightfm==1.17` 在当前 Windows / Python 3.13 环境下先出现 metadata/build 失败，修复后又暴露 WARP/BPR native loss 在真实稀疏矩阵上 access violation。与此同时，原 Phase 1.21 脚本只把 ALS/BPR/LightFM 写进 registry dependency gate，没有真实候选生成路径，直接跑配置会变成“登记了但没产候选”。

**定位方式：**
用 `.venv/Scripts/python.exe` 检查 `implicit` / `lightfm` 依赖状态，并用小矩阵 smoke 确认 `implicit` 0.7.3 的 ALS/BPR 需要以 user-item CSR matrix 调用 `fit(user_items)` 和 `recommend(...)`。LightFM 先定位到 PyPI sdist 的 `__builtins__.__LIGHTFM_SETUP__` Python 3.13 兼容问题，再用 GitHub 1.17 源码重新 Cythonize；真实 Phase 1.21 矩阵复现显示 WARP/BPR/WARP-KOS 在 `_run_epoch` access violation，logistic loss 可稳定训练。随后检查 `scripts/phase_1_21_recall_coverage_experiments.py` 的 `SOURCE_CONTRACT`、`_attach_phase_sources`、`_phase_source_config`、`_raw_non_popular_candidates` 和 benchmark 执行状态判断，确认缺真实 source 接入。

**解决方式：**
新增 `als_mf_recall` / `bpr_mf_recall` / `lightfm_recall` source 合同，接入 train-only implicit ALS/BPR 与 LightFM logistic index builder，并在 `configs/recall/phase_1_21/phase_1_21_recall_coverage_mf.yaml` 中开启对应参数；LightFM 明确记录为 logistic observation，WARP/BPR native crash 不伪造成可用结果。补充函数级测试，验证 MF 候选不包含已看 seed，且 metadata 带 `train_implicit_als`、`train_implicit_bpr`、`train_lightfm_logistic`。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_21_recall_coverage.py` 结果 `25 passed`，`compileall scripts/phase_1_21_recall_coverage_experiments.py tests/test_phase_1_21_recall_coverage.py` 通过。真实固定合同输出 `outputs/recall/phase_1_21_recall_coverage/source_family/mf_implicit_als_bpr_lightfm_pool200/`：`candidate_hit_users=17`、`candidate_hit_rate_at_pool=0.123188`、`recall_at_pool=0.064151`；`als_mf_recall` 覆盖 `500` users / `1207` items 但无边际命中，`bpr_mf_recall` 覆盖 `500` users / `39` items 且只贡献 `1` 个 candidate-hit source 覆盖，`lightfm_recall` 覆盖 `454` users / `34` items 并贡献 `4` 个 candidate-hit source 覆盖，但整体仍低于当前主路 `19` hit users。

**面试可讲点：**
这段可以讲成“把依赖门控 backlog 转成真实实验”的工程治理：先用依赖安装、源码 patch 和 API smoke 证明 MF 路径边界，再补 train-only 候选生成路径和合同测试，最后用固定合同 artifact 得出 reject 结论；同时如实记录 LightFM WARP/BPR native crash 与 logistic 可运行结果，避免把常见方法名包装成虚假实验收益。

### 2026-05-13 - 剩余召回方法固定合同补跑收口

**任务：**
把 graph、vector/two-tower、MF、sequence/multi-interest 等剩余召回方法从“计划/占位”推进到可验证的 Phase 1.21 固定合同实验，并由一个串行 runner 统一跑完。

**遇到的问题：**
多个 worker 并行修改同一个 Phase 1.21 脚本，出现 `_multi_interest_patch` 未定义、multi-interest 默认权重与测试预期不一致的问题；同时 vector 配置一度仍是 pool100，不符合本轮 pool200 固定召回池口径。ALS/BPR/LightFM 也不能因为方法名常见就伪造结果，必须按依赖 gate 处理。

**定位方式：**
用 `tests/test_phase_1_21_recall_coverage.py` 暴露 `_multi_interest_patch` 缺失，随后检查 `scripts/phase_1_21_recall_coverage_experiments.py` 中 `_attach_phase_sources`、`_raw_non_popular_candidates`、`SOURCE_FAMILY_BENCHMARKS` 和新增配置文件；用 `.venv/Scripts/python.exe` 串行运行四个配置，并抽取各输出目录的 `metrics.json`、`manifest.json`、`source_family_observation_benchmarks.json`。

**解决方式：**
补齐 `multi_interest_recall` 的 patch 和元数据合同，把 vector 配置统一到 `candidate_pool_size=200`；graph 只启用可复用的 `item_graph`，`graph_walk_seed` 保持 sidecar-gated；MF 只执行纯 numpy `implicit_svd_recall`，ALS/BPR/LightFM 通过 `dependency_gate` 标记为 blocked；实验按 graph → vector → MF → sequence 串行执行，保持同一 holdout hash。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_21_recall_coverage.py` 结果 `23 passed`，`compileall` 通过。四个固定合同输出均为 `users_with_holdout=138`、`candidate_pool_size=200`、`holdout_user_ids_hash=927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2`：graph、vector/two-tower、implicit SVD MF、sequence/multi-interest 的 `candidate_hit_users` 均为 `17`、`candidate_hit_rate_at_pool=0.123188`、`recall_at_pool=0.064151`，低于当前 source-aware/semantic 主路的 `19` hit users；ALS/BPR 因缺 `implicit`、LightFM 因缺 `lightfm` 继续 `defer`。

**面试可讲点：**
这段可以讲成推荐召回实验治理：用多 agent 并行补齐实现入口，但实验执行串行化以保证可比；对能跑的方法输出同合同 artifact，对缺依赖的方法保留 dependency gate，不把 smoke、排序指标或方法名热度包装成晋升证据，最终得出“当前无新方法晋升，主路保持 source-aware/semantic”的克制结论。

### 2026-05-13 - Source-aware 召回融合截断稳定性观察

**任务：**
在确认 UserCF/Swing 只能作为 fallback 后，继续分析 `semantic_title_category_expansion + 行为 fallback` 的融合、去重和截断稳定性，判断是否需要替换当前主路。

**遇到的问题：**
单纯继续新增召回方法已经收益有限，真正风险转向多路 source 合并后的池内竞争：行为侧 source 可能增加覆盖，但也可能挤掉语义主路或热门兜底候选，因此需要 observation-only 对照，而不能直接改主 baseline。

**定位方式：**
检查 `rs_core/recsys/candidate_merge.py`，确认已有 `_limit_candidate_pool`、`balanced_source_budget`、`candidate_source_minimums/maximums` 与 `candidate_fill_order`；检查 `scripts/phase_1_21_recall_coverage_experiments.py`，确认可复用同一批 raw candidates，只比较不同截断策略。

**解决方式：**
新增 `configs/recall/phase_1_21/phase_1_21_recall_coverage_source_aware.yaml` 和 Phase 1.21 的 `--mode source-aware`，对比 `score_sorted_all_sources` 与 `source_balanced_fallback_preserving`。实现中避免每个 variant 重建 source index，改为一次生成 raw candidates、多个截断策略复用，降低长跑成本。

**验证结果：**
`tests/test_phase_1_21_recall_coverage.py` 结果 `22 passed`；`compileall rs_core scripts tests` 通过。真实固定合同运行写入 `outputs/recall/phase_1_21_recall_coverage/source_aware/`：两种策略 `candidate_hit_users` 都为 `19`、`candidate_hit_rate_at_pool=0.137681`，无 `baseline_displacement_users`；balanced 策略把 `candidate_count_avg` 从 `136.214` 降到 `126.972`，并把 `candidate_hit_rate_at_100` 从 `0.123188` 提到 `0.130435`。

**面试可讲点：**
这段可以讲成召回系统的多路融合治理：不是盲目叠 source，而是在同一 holdout 与同一 raw candidate 输入下，只替换截断策略，观察命中、位移、候选量和前段召回位置；结合后续 graph/vector/MF/sequence 对照后，最终把 `source_balanced_fallback_preserving` 固定为当前混合召回主路的默认截断策略。

### 2026-05-13 - 补跑未覆盖的轻量行为召回与矩阵分解 smoke

**任务：**
把此前标为未跑/延后的 UserCF、Swing、session transition 和矩阵分解类召回推进到可执行固定合同实验，明确哪些方法只是 fallback、哪些应 reject、哪些仍 blocked。

**遇到的问题：**
此前文档把 UserCF/Swing/session transition 记为没有成熟入口，ALS/BPR/implicit MF 记为依赖或实现不足；用户追问“还是没有跑实验吗”后，需要真正补一轮可验证实验，而不是只继续写 defer。

**定位方式：**
检查 `scripts/phase_1_21_recall_coverage_experiments.py` 的 `_attach_phase_sources`、`_raw_non_popular_candidates` 和 `source_family_observation_benchmarks.json` 生成逻辑，确认可以在 Phase 1.21 固定合同中增加训练期 source。依赖检查显示 `.venv` 中 `numpy=True`，但 `scipy=False`、`sklearn=False`、`implicit=False`、`lightfm=False`，因此 ALS/BPR 不能可靠训练。

**解决方式：**
新增 `configs/recall/phase_1_21/phase_1_21_recall_coverage_behavior_untried.yaml`，并在 Phase 1.21 脚本中接入 `usercf_recall`、`swing_recall`、`session_transition_recall` 和纯 numpy `implicit_svd_recall`。所有索引只从 `user_sequences.train.jsonl` 构建，不读取 holdout；ALS/BPR/LightFM 明确标为依赖 blocked。

**验证结果：**
补跑命令：`./.venv/Scripts/python.exe scripts/phase_1_21_recall_coverage_experiments.py --config configs/recall/phase_1_21/phase_1_21_recall_coverage_behavior_untried.yaml --output-dir outputs/recall/phase_1_21_recall_coverage/source_family/worker_behavior_untried_pool200 --mode baseline --limit-users 500`。结果 artifact 显示 `candidate_hit_users=17`、`candidate_hit_rate_at_pool=0.123188`、`recall_at_pool=0.064151`；`usercf_recall` 和 `swing_recall` 各有 `1` 个 candidate-hit source 覆盖，`session_transition_recall` 和 `implicit_svd_recall` 为 `0`。`tests/test_phase_1_21_recall_coverage.py` 结果 `21 passed`。

**面试可讲点：**
这段可以讲成“面对用户质疑没有跑实验时，快速把 deferred backlog 转成固定合同实验”：能轻量实现的先落地并输出 artifact，不能跑的 ALS/BPR 给出依赖证据；最后按召回治理口径把 UserCF/Swing 归为 fallback，把 session transition / implicit SVD reject，避免为了覆盖方法名而虚假晋升。

### 2026-05-13 - 主流召回方法实验口径与可维护结论文档收口

**任务：**
把剩余主流召回方法从口头清单推进到可维护的实验结论文档：统一 `promote/reject/defer/fallback/document_only` 决策标签、补齐 method-card diagnostics，并对当前 CPU/lightweight 可执行 source 生成固定合同 artifact。

**遇到的问题：**
旧文档和部分 registry artifact 混用了 `pending_evidence`、`observation_baseline`、A/B/C/D evidence 等旧口径；同时 UserCF、Swing、ALS/BPR/implicit MF、session transition 在当前仓库没有成熟召回入口，不能为了“跑全主流方法”伪造实验结果。

**定位方式：**
核对 `rs_core/recsys/evaluation.py`、`rs_core/recsys/types.py`、`scripts/phase_1_20_recall_diagnostics.py`、`scripts/phase_1_21_recall_coverage_experiments.py` 与 `dic/experiments/recall/RECALL_METHODS_EXPERIMENT_LOG.md`；读取 `outputs/recall/phase_1_21_recall_coverage/worker_light_20260513/` 和 `outputs/recall/phase_1_21_recall_coverage/source_family/worker_cpu_itemcf_covisit_hybrid_pool200/` 下的 manifest/metrics，确认 `valid_test`、`users_with_holdout=138`、holdout hash 和 ranking/rerank disabled checks。

**解决方式：**
在 `EvaluationSummary` 中新增 `method_card_diagnostics`，把 forbidden metrics 扩展为排序、Top-K gap、LTR/rerank 和线上业务指标；未知 `pool_displacement_risk` 默认给 `defer`，不自动晋升。文档中新增 CPU-bound CF/hybrid 与 lightweight source sweep 条目：ItemCF/co-visit 归为 `fallback`，popular/category 归为 `document_only`，UserCF/Swing/ALS/BPR/session transition 归为 `defer`。

**验证结果：**
固定合同 artifact 已重跑：pool200 CPU/hybrid `candidate_hit_users=19`、`candidate_hit_rate_at_pool=0.137681`、`recall_at_pool=0.06971`；method-card diagnostics 输出 `decision_hint=defer` 且 `can_promote=false`。验证命令：`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_21_recall_coverage.py tests/test_phase_1_20_recall_diagnostics.py tests/test_evaluation.py tests/test_hybrid_demo.py` 结果 `136 passed`；`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过。

**面试可讲点：**
这轮可以讲成“把召回方法探索做成证据治理系统”：不仅跑可执行方法，还把不能跑的方法明确落为 `defer/document_only`，并用统一 schema、artifact hash、holdout hash 和 forbidden metrics 约束防止把排序收益或历史文字误写成召回晋升。

### 2026-05-13 - 第一轮新召回 source ablation 与晋升收口

**任务：**
在 `semantic_title_category_expansion` 已成为 recall-only baseline_vNext 后，对下一轮候选 source 做第一轮可复现 ablation，判断是否有新的召回 source 可以晋升。

**遇到的问题：**
Phase 0 诊断显示 ItemCF/co-visit 重叠较高，粗类目扩池没有 lift；同时第一轮候选中的 Swing/UserCF 在当前仓库没有成熟入口，metadata neighbor 虽有函数但实现按 seed 扫描 metadata index，长跑 lane 成本偏高，不能为了“跑全方法”伪造结果。

**定位方式：**
读取 `.omc/recall/artifacts/phase_0_recall_diagnostics_20260513/selected_first_round_sources.md`、`phase0_diagnostics.json` 和 Phase 1.21 registry，确认 recall-only 口径、holdout hash 与 pool200 guardrail；再检查 `rs_core/recsys/candidate_merge.py`、`scripts/phase_1_21_recall_coverage_experiments.py`、graph/item_graph sidecar，确认可复用的是 `item_graph` 与 `graph_walk_seed`。

**解决方式：**
只对可复用的 `constrained_item_graph_walk` 做 pool200 与 source-only ablation，并把 Swing/UserCF/metadata neighbor 明确记录为未执行或后续条件型实验；所有结论只使用 candidate-hit users、baseline miss 覆盖、candidate volume 和 source overlap，不使用 Top-K/ranking/LTR/业务指标。

**验证结果：**
收口报告见 `.omc/recall/artifacts/phase_0_first_round_source_ablation_20260513/first_round_closure_report.md`。`item_graph` 与 `graph_walk_seed` 的 candidate_hit_users 都为 17，baseline_miss_coverage_users 都为 0；source-only 各自只命中 1 个用户且没有覆盖 baseline miss 用户，因此结论为 `NO_NEW_SOURCE_PROMOTED`。验证命令：`./.venv/Scripts/python.exe scripts/validate_recall_registry.py` 通过，`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_21_recall_coverage.py` 结果 `20 passed`，ablation 脚本 `py_compile` 通过。

**面试可讲点：**
这段工作体现的是召回实验治理：不是把所有主流方法都盲目接入，而是在同一 holdout、同一 candidate_pool_cap 和 recall-only 合同下做 ablation；能跑的图召回如实记录无新增覆盖，不能成熟复用的 Swing/UserCF 不伪造结果，从而保证 baseline 晋升基于可复现证据。

### 2026-05-13 - Phase 1.26 典型排序链路与真实实验底座

**任务：**
把排序阶段从“规则 gate / smoke / blocked 记录”推进到可验证的典型排序实验链路：明确目标架构为 recall → coarse rank → fine rank → rerank，并在当前离线边界下落地 `frozen pool200 → learned fine ranker → bounded rerank trace`。

**遇到的问题：**
此前阶段容易把依赖 gate、smoke 或 blocked 状态包装成“真实排序实验”，但它们没有真实训练日志、模型产物、候选一致性证明和 case diff；同时 GBDT/LambdaMART 等方法如果缺依赖、GPU 或候选级 adapter，不能伪造成当前可晋升结果。

**定位方式：**
检查 `rs_core/recsys/ranking.py`、`rs_core/workflow/ltr_training.py`、`scripts/run_phase_1_28_lightweight_learned_ranker.py` 和 `scripts/run_phase_3_tree_ranker.py`，确认已有 LTR 训练闭环可复用，而 Phase 3 tree 脚本只是依赖 gate 与 candidate-row export。验证产物见 `outputs/ranking/phase_1_26_real_ranking_experiments_smoke/comparison.json`。

**解决方式：**
在 `rs_core/recsys/ranking.py` 增加 `coarse_score`、`fine_score`、`rerank_score`、`score_trace`、stage rank 和 rank movement，先把 coarse 作为 diagnostic trace，不强制缩池；新增 `scripts/run_phase_1_26_real_ranking_experiments.py`，用 LOPO pointwise logistic / pairwise perceptron 做真实轻量 fine-ranker 训练，输出 `training_config.json`、`training_log.json`、`ltr_model.json`、`ltr_candidate_rows.jsonl`、case diff 和 comparison registry；GBDT/LambdaMART 在缺依赖、GPU 校验或候选级 adapter 时明确标为 `blocked`。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile scripts/run_phase_1_26_real_ranking_experiments.py rs_core/recsys/ranking.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -q -k "score_trace or phase_1_26_real_ranking_runner_contract"` 结果为 `3 passed, 107 deselected`；刷新 smoke 命令 `./.venv/Scripts/python.exe scripts/run_phase_1_26_real_ranking_experiments.py --output-dir outputs/ranking/phase_1_26_real_ranking_experiments_smoke --limit-users 20 --seed 20260513` 成功，`artifact_inspection.status=PASS`，baseline 与两个 learned variant 均保持 `candidate_pool_size=200`、`top_k=5`、`frozen_candidate_match=true`，feature/leakage gate 为 PASS，LTR variants 为 diagnostic-only，tree/LambdaMART 方法为 blocked。

**面试可讲点：**
这段工作体现的是推荐排序实验治理能力：先把工业排序链路拆成粗排、精排、重排的可观测阶段，再用冻结候选池保证只评估排序，不污染召回；对能真实训练的方法输出完整证据链，对依赖不足的方法如实 blocked，避免把 smoke/gate 伪装成模型效果。

### 2026-04-28 - CLI Agent 反馈闭环修复

**任务：**
推进 RS Agent 的 CLI 交互闭环，让第二轮用户反馈能真实影响推荐结果，并让 reward 能识别反馈是否产生实际效果。

**遇到的问题：**
CLI smoke 能生成 `session.json`、`session_turns.jsonl` 和 `grpo_rollouts.jsonl`，但两轮 Top-K 完全相同，`changed_after_feedback=false`；同时 reward 只要偏好解析成功就容易给较高 feedback alignment，不能区分“解析了反馈”和“反馈真的改变了推荐”。

**定位方式：**
检查 `rs_core/rsagent/cli.py`、`rs_core/workflow/hybrid_environment.py`、`rs_core/workflow/hybrid_demo.py`、`rs_core/rsagent/policy.py`、`rs_core/recsys/ranking.py` 的 feedback 链路，确认 `preferred_sources/preferred_categories` 已解析，但 CLI 使用的配置没有给 feedback source/category 足够的 ranking 权重；初始 smoke 报告见 `outputs/agent/cli/agent_cli_smoke/rs_agent_cli_baseline_comparison.md`。

**解决方式：**
在 `rs_core/rsagent/cli.py` 为 CLI 会话注入不覆盖用户配置的 feedback rank 默认权重，并把模拟反馈改成包含 fresh/again，使第二轮能过滤上一轮已曝光 item；在 `rs_core/rsagent/reward.py` 增加 `feedback_effect_observed` 证据，对后续轮次中没有过滤、boost 或换榜证据的反馈对齐分做上限约束；补充 `tests/test_agent_rollout_schema.py` 和 `tests/test_agent_reward.py` 覆盖换榜与无效反馈降分。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m rs_core.rsagent.cli --config configs/demo/hybrid_demo/hybrid_demo_electronics_1000_lopo_semantic_title.yaml --limit-users 3 --simulate-two-turn --output-dir agent_cli_smoke_after_fix` 后，报告 `outputs/agent/cli/agent_cli_smoke_after_fix/rs_agent_cli_baseline_comparison.md` 显示 `changed_after_feedback=true`，第二轮 Top-K 从 `B08JQCJZQM/B08HFNNPPJ/...` 变为 `B0B2JJV92T/B08Y1XYLVP/...`，diagnostics 中出现 `feedback_source_semantic`、`excluded_prior_turn_items` 和 `boosts_applied`。直接调用目标测试函数通过，`./.venv/Scripts/python.exe -m compileall -q rs_core tests` 通过；当前环境缺少 pytest，未运行完整 pytest 套件。

**面试可讲点：**
这次工作把 Agent 从“能记录反馈”推进到“反馈能改变策略”的闭环：先定位到配置层 feedback 权重未生效，再用可解释 diagnostics 证明过滤与 boost 发生，最后把 reward 从结果静态打分升级为包含反馈响应性的训练信号，为后续 GRPO rollout 数据打基础。
### 2026-04-28 - 项目文档入口精简与阶段状态同步

**任务：**
整理 Phase 1.5 / Phase 1.6 / Phase 1.7 的文档承接关系，避免历史总结、优化叙事和工程日志之间的信息重复。

**遇到的问题：**
Phase 1.5 历史总结、最新优化判断和工程叙事记录分散在多个文档中，容易让读者误把历史阶段总结当成当前总览，也不利于面试叙事快速定位当前结论。

**定位方式：**
对照 `dic/phases/phase_1_5/PHASE_1_5_DEMO_SUMMARY.md`、`dic/OPTIMIZATION_NARRATIVE.md` 和现有 `dic/ENGINEERING_NARRATIVE_LOG.md` 的内容边界，确认 Phase 1.5 应只保留历史总结，Phase 1.6 / 1.7 和最新判断应集中在优化文档，工程日志只记录可复述的过程条目。

**解决方式：**
在 Phase 1.5 文档开头补充阶段说明，在优化文档的当前推荐处补充 Agent 层 demo 的入口方向，并在工程日志中追加一条简短记录；随后将旧实验报告和数据画像移动到 `dic/archive/`，让 `dic/` 根目录只保留核心入口文档，减少重复维护成本。

**验证结果：**
通过核心文档的人工一致性检查，确认 README、实施计划、架构说明、目录说明、Phase 1.5 总结和优化叙事之间的阶段状态一致；`dic/` 根目录保留 7 个核心文档，59 个旧报告和数据画像已归档到 `dic/archive/`；`old_dic/` 已按英文 ASCII 目录整理为 `historical_plans/` 和 `early_data/`，避免中文路径解码异常；未执行新的实验。

**面试可讲点：**
这类工作体现的是文档架构治理能力：不仅能写内容，还能把历史总结、当前判断和过程证据拆分到正确入口，减少信息漂移，让面试叙事更容易复述和验证。

### 2026-04-28 - Agent feedback canonical 固化与 conversational MVP

**任务：**
把已有 CLI feedback smoke 固化成唯一可复现 demo，并把 Agent 从“反馈后再推荐”推进到 deterministic 多轮对话 MVP。

**遇到的问题：**
此前项目已有多份 `agent_cli_*` 输出目录，读者不容易判断哪个是 canonical 证据；同时 Agent 还偏向推荐列表输出，缺少“模糊需求追问、澄清后推荐、解释上一轮、换一批、unsupported 保留”等对话式推荐能力。

**定位方式：**
检查 `rs_core/rsagent/schema.py`、`rs_core/rsagent/policy.py`、`rs_core/workflow/hybrid_environment.py`、`rs_core/rsagent/cli.py` 和 rollout 输出链路，确认已有 session/turn、feedback constraints、reward evidence 和 rollout schema，可以在不改推荐 backbone 的前提下增加 deterministic dialogue manager。

**解决方式：**
新增 `rs_core/rsagent/dialogue.py`，用规则方式规划 `recommend_request`、`clarification_answer`、`ask_explanation`、`preference_feedback`、`unsupported` 等对话意图；扩展 `AgentSession` 保存 `ConversationState`，扩展 `AgentTurn` 保存 `assistant_response`；在 `HybridRecommendationEnvironment.converse()` 中接入对话规划，保持 `step()` 的原 feedback 行为兼容；在 CLI 增加 `--simulate-conversation`，并保留 `--inference-policy off` 作为 deterministic canonical 入口。

**验证结果：**
安装 pytest 后运行 `./.venv/Scripts/python.exe -m pytest tests/test_agent_feedback.py tests/test_agent_reward.py tests/test_agent_rollout_schema.py tests/test_agent_dialogue.py`，结果 `19 passed in 0.27s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests` 通过。canonical feedback 入口生成 `outputs/agent/canonical/agent_feedback_demo_canonical/`，检查确认 `changed_after_feedback=true`、`feedback_effect_observed=true`、有 boost/filter 证据且 `training_status=deferred_environment_reward_only`。conversational 入口生成 `outputs/agent/canonical/agent_conversation_demo_canonical/`，检查确认 turn 2 追问、turn 3 澄清后推荐、turn 4 解释、turn 5 根据反馈再推荐，rollout 逐条保留 deferred training metadata。

**面试可讲点：**
这次工作把 Agent 定位从“推荐包装器”推进到“对话式推荐编排器”：底层仍由传统推荐 backbone 负责召回和排序，Agent 在上层负责识别用户意图、必要时追问、把澄清转成结构化约束、解释推荐依据，并把多轮交互沉淀为 reward / rollout 证据，为后续 Qwen / QLoRA / GRPO 训练路线提供稳定 contract。

### 2026-04-28 - item-level feature rerank 第一版

**任务：**
在 Phase 1.7 source-level rerank 到达边界后，补一个默认关闭、可解释的 item-level feature rerank，用于把多源候选、反馈匹配、popular-only / semantic-only 等信号显式纳入排序诊断。

**遇到的问题：**
统一 semantic boost 和 semantic-only penalty 都没有提升 Top-K hit，说明问题不在 source 整体曝光，而在 item 之间的相对区分；实验初期还误用 `python -m rs_core.workflow.hybrid_demo --config ...`，该模块没有 CLI 入口，导致命令成功退出但没有生成输出。

**定位方式：**
检查 `rs_core/recsys/ranking.py` 和 `scripts/run_hybrid_demo.py`，确认真正实验入口是 `./.venv/Scripts/python.exe scripts/run_hybrid_demo.py --config ...`；对比 `outputs/hybrid_demo/hybrid_demo_small_electronics_1000_semantic_title*/metrics.json` 与 `ranking_case_summary.json`，确认 item-feature rerank 对 valid/test 和 LOPO 的影响。

**解决方式：**
在 `rank_candidates()` 中增加默认关闭的 `item_feature_rerank`，输出 `feature_score`、`item_features` 和 item_feature rerank events；新增 title semantic 的 valid/test 与 LOPO item-feature 配置，并让 report config summary 显示 `item_feature_rerank` 策略，避免实验报告漏掉关键配置。

**验证结果：**
重新生成 Phase 1.7 baseline 与 Phase 1.8 item-feature 对照后，valid/test `hit_rate_at_k` 保持 0.043478，LOPO `hit_rate_at_k` 保持 0.888889；LOPO `candidate_hit_rank_avg` 从 25.128205 改善到 23.461538，`top1_score_gap_avg` 从 24.742213 降到 24.047873。运行 `./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_agent_feedback.py tests/test_agent_dialogue.py tests/test_agent_rollout_schema.py`，结果 `42 passed in 0.30s`；`./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；独立 verifier 给出 PASS。

**面试可讲点：**
这次工作体现的是从 source-level 调参升级到 feature-level 诊断：当全局 boost / penalty 不能改变同源候选内部顺序时，把多源支持、反馈匹配和单源惩罚显式做成可解释特征。结果没有夸大成 Top-K 提升，而是准确表述为“改善候选池内排名分布，为后续 Agent 反馈和学习排序提供特征接口”。

### 2026-04-28 - rollout 训练样本 contract 与 Qwen harness 对照固化

**任务：**
把已经稳定的 Agent feedback / conversation rollout 往训练前闭环推进：先显式导出 SFT / reward 样本 contract，再验证 Qwen bounded rerank evaluation harness 在无本地模型依赖时也能产出可复现对照结果。

**遇到的问题：**
此前 rollout 已记录 `prompt_context`、`reward_evidence` 和 `diagnostics`，但训练用途仍需要下游再拼字段，缺少“这一轮该学什么、reward 怎么对照”的显式 contract；同时 Qwen harness 虽已有 fake client 改善路径测试，但缺少模型不可用时 fallback 仍能完整生成三模式对照报告的测试，容易把本机环境依赖误当成评估链路能力。

**定位方式：**
检查 `rs_core/rsagent/rollout.py`、`rs_core/rsagent/schema.py`、`rs_core/rsagent/reward.py` 和 `rs_core/workflow/hybrid_demo.py`，确认已有 AgentTurn / AgentSession 字段足够生成训练样本，不需要改推荐 backbone；再检查 `tests/test_hybrid_demo.py` 中已有 `FakeHarnessQwenClient` 测试，确认还需补 `ModelUnavailableError` fallback 路径。

**解决方式：**
在 `turn_to_rollout_record()` 中新增 `training_samples` 字段，拆成 `sft_sample` 和 `reward_sample`：前者包含 user_input、assistant_response、feedback_constraints、candidate_summary、target_action、target_explanation，并用 `allowed_item_ids` 约束 selected_item_ids 只能来自当前候选；后者包含 policy_type、reward、reward_evidence、feedback_effect_observed 和 risk_flags。补充 Qwen harness fallback 测试，验证 deterministic_baseline、rule_feedback_rerank、qwen_feedback_rerank 三种模式即使 Qwen 不可用也会写出 comparison JSON/report 和 inference diagnostics。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py::test_qwen_evaluation_harness_writes_three_mode_comparison tests/test_hybrid_demo.py::test_qwen_evaluation_harness_writes_fallback_comparison_without_model_dependencies tests/test_agent_rollout_schema.py`，结果 `6 passed in 0.23s`；运行 `./.venv/Scripts/python.exe scripts/run_qwen_evaluation_harness.py --config configs/demo/hybrid_demo/hybrid_demo_electronics_1000_lopo_semantic_title.yaml --limit-users 3 --output-dir outputs/agent/qwen/qwen_evaluation_harness_ralph_fallback --qwen-model-id missing-local-qwen` 成功生成 `outputs/agent/qwen/qwen_evaluation_harness_ralph_fallback/comparison.json` 和 `comparison.md`，其中 `qwen_feedback_rerank` 的 `fallback_count=1`、`routes={"qwen_local": 1}`。当前 Qwen / QLoRA / GRPO 仍未完整训练落地，本次工作是训练前 contract 与 bounded rerank 对照验证。

**面试可讲点：**
这次工作可以讲成“先把 Agent 交互闭环产品化为可训练数据，再把大模型能力接入约束在候选集内做可回退对照”：不是直接让 LLM 生成商品，而是让它输出 bounded rerank signals，并且在模型不可用时仍保留 deterministic/rule baseline 和诊断产物，体现了推荐系统中对可控性、可复现评估和训练数据 contract 的工程意识。

### 2026-04-28 - 展示层与多角色仿真规划边界预留

**任务：**
把后续真实商品展示、前端交互、多角色模拟客户和动画回放纳入项目规划，同时不打断当前推荐 backbone、Agent feedback、reward / rollout 的主线。

**遇到的问题：**
现有架构主要覆盖数据处理、召回、排序、Agent 对话反馈和训练前 contract，但没有显式说明商品卡展示、前端消费接口、多角色模拟客户和动画回放放在哪一层，后续如果直接开发前端或仿真场景，容易让 UI 字段、模拟客户和推荐内部逻辑耦合。

**定位方式：**
检查 `dic/PROJECT_STRUCTURE.md`、`dic/architecture/ARCHITECTURE.md`、`dic/architecture/IMPLEMENTATION_PLAN.md`、`dic/README.md` 和 `dic/OPTIMIZATION_NARRATIVE.md`，确认当前文档已覆盖 Agent 主轴和训练路线，但缺少展示层、前端层、仿真层和动画层的目录与边界说明。

**解决方式：**
预留 `rs_core/display/`、`rs_core/simulation/`、`rs_core/animation/` 和 `frontend/` 目录，并在核心文档中补充展示层、前端 / 服务层、仿真 / 动画层的职责：展示层负责商品卡 contract，前端只消费服务与展示接口，模拟客户作为合成交互评估流量，动画层只做 session / rollout 可视化回放。

**验证结果：**
通过目录检查确认 `.gitkeep` 已存在于新增目录；用文档检索确认 `display`、`simulation`、`animation`、`frontend`、商品展示卡、多角色和动画回放等关键条目已出现在 `PROJECT_STRUCTURE.md`、`architecture/ARCHITECTURE.md`、`architecture/IMPLEMENTATION_PLAN.md`、`README.md` 和 `OPTIMIZATION_NARRATIVE.md`。

**面试可讲点：**
这次调整体现的是从“推荐算法 demo”扩展到“可交互、可展示、可回放、可仿真的 Agent 推荐系统”的架构意识：推荐 backbone 和 Agent 决策仍是主线，商品卡 contract 解决产品化展示，多角色模拟客户用于压力测试交互闭环，动画层用于演示和复盘，但这些外围能力不会污染推荐排序和真实用户评估。

### 2026-04-28 - 商品展示 contract 与前端安全视图

**任务：**
推进 Phase 2 的展示层，把 Agent 最终推荐结果转换成前端可直接消费的 `DisplayResponse` / `ItemDisplayCard` contract，并为后续聊天前端和商品卡 UI 提供 canonical mock 输出。

**遇到的问题：**
已有 `session.json`、`session_turns.jsonl` 和 `grpo_rollouts.jsonl` 同时包含推荐结果、ranking、diagnostics、reward 和 training_samples，适合训练与诊断，但不适合直接交给前端；如果前端直接读 rollout，容易耦合排序分数、reward 证据和内部诊断字段。

**定位方式：**
检查 `rs_core/rsagent/schema.py`、`rs_core/rsagent/rollout.py`、`rs_core/rsagent/cli.py` 和 `rs_core/recsys/types.py`，确认 `AgentDecision.final_items` 已经是展示层最稳定的入口；同时确认商品 title、price、rating、image 等 metadata 不保证齐全，因此 contract 需要 nullable 字段和缺图兜底。

**解决方式：**
在 `rs_core/rsagent/schema.py` 新增 `ItemDisplayCard` 和 `DisplayResponse`，在 `rs_core/display/builder.py` 新增展示层 builder，只从最终推荐 item 和 metadata 派生前端安全字段；在 `rs_core/rsagent/rollout.py` 为每条 rollout 增加 `display_response`，在 `rs_core/rsagent/cli.py` 额外输出 `display_responses.jsonl` 和 `display_demo.json`，同时保持原训练/诊断输出不变。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_agent_rollout_schema.py tests/test_display_contract.py`，结果 `6 passed in 0.16s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；运行 canonical display demo 生成 `outputs/agent/canonical/agent_display_demo_canonical/display_responses.jsonl` 和 `display_demo.json`；定向检查 `outputs/agent/canonical/agent_display_demo_canonical/grpo_rollouts.jsonl` 中 5 条 `display_response`，确认没有泄漏 `score`、`diagnostics`、`reward_evidence`、`training_samples` 等内部字段。

**面试可讲点：**
这次工作体现的是从算法/Agent demo 走向产品化接口的工程边界设计：训练和诊断需要保留完整内部证据，但前端只需要稳定、安全、可容错的展示 contract。通过派生 `DisplayResponse`，推荐系统可以继续维护可解释诊断和 reward contract，同时让 UI、后续动画回放和多角色仿真复用同一个前端安全视图。

### 2026-04-28 - Phase 2 single-process serving demo

**任务：**
把已有 CLI / conversational Agent demo 封装成轻量 HTTP 服务入口，让后续前端、模拟客户或展示沙盒可以通过 API 调用推荐对话能力。

**遇到的问题：**
项目已有 `HybridRecommendationEnvironment`、`DisplayResponse` 和 CLI canonical demo，但缺少服务层边界；如果直接把 `AgentTurn` 或 rollout 返回给前端，会泄露 ranking、diagnostics、reward 等内部训练/诊断字段。

**定位方式：**
检查 `rs_core/workflow/hybrid_environment.py`、`rs_core/display/builder.py`、`rs_core/rsagent/schema.py` 和 `rs_core/rsagent/cli.py`，确认服务层应复用 `env.converse()` 和 `build_display_record()`，而不是重写推荐逻辑或直接暴露 session/turn 原始结构。

**解决方式：**
新增 `rs_core/serving/service.py`、`schema.py` 和 `app.py`，实现 single-process demo service：`RecommendationService` 在进程内维护 session dict，`/session/start` 使用 UUID 创建独立 session，`/chat` 只返回展示层 `DisplayResponse` contract；新增 `scripts/run_service.py` 和 `requirements-serving.txt`，明确 FastAPI / uvicorn / httpx 依赖与 demo 服务边界。

**验证结果：**
安装 `requirements-serving.txt` 后运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py`，结果 `5 passed in 0.44s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；独立 verifier 给出 PASS，确认服务文件位于 `rs_core/serving/*`、未实现 `/feedback`、unknown session 返回 404，公开响应不含 `ranking`、`diagnostics`、`reward`、`score`。

**面试可讲点：**
这次工作把项目从 CLI 推荐 Agent demo 推进到可 HTTP 调用的服务 contract：底层推荐和 Agent 决策保持不变，服务层只做薄封装和 session 编排，对外统一返回前端安全的展示卡结构。这个边界既能支撑后续 Web Demo / 多角色模拟客户，也避免过早引入数据库、多进程状态和生产部署复杂度。

### 2026-04-28 - 最小 React 商品卡前端 Demo

**任务：**
把 Phase 2 serving demo 接到已有 Vite / React 前端骨架上，实现可交互的聊天输入、商品卡展示和反馈按钮，让推荐 Agent 从 HTTP contract 进一步变成可展示的 Web Demo。

**遇到的问题：**
前端原本主要读取 `mockData` 做静态商品卡展示；接入后端后还需要处理本地 FastAPI 与 Vite 的 CORS、后端重启导致的 session 丢失、真实 demo 数据没有固定 `frontend-demo-user` 这类联调边界。

**定位方式：**
检查 `frontend/src/App.tsx`、`frontend/src/types.ts`、`frontend/src/mockData.ts` 和 `rs_core/serving/app.py`，确认前端应只依赖 `/session/start` 和 `/chat` 的 `DisplayResponse` contract；按用户偏好通过 `omc ask gemini` 审阅前端实现，Gemini 建议保留 mock 降级、按钮转自然语言 feedback、图片兜底，并补 session 失效阻断、价格格式化和聊天记录自动滚动。

**解决方式：**
新增 `frontend/src/api.ts`，让前端启动时创建 session、提交聊天时调用 `/chat`，并继续用 `mockData` 作为后端未启动时的展示兜底；更新 `App.tsx` 渲染对话记录、assistant message、商品卡和 feedback actions；后端补本地 Vite CORS；按 Gemini 审阅意见补充 `Unknown session_id` 后禁用输入并提示刷新、数值价格格式化和消息自动滚动；修正前端默认不传固定 user，让后端选择 demo 数据中的首个用户。

**验证结果：**
运行 `npm --prefix frontend run build` 通过；运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `7 passed in 0.44s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；启动 `scripts/run_service.py` 和 `npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173` 后，用 HTTP 验证 `/health`、默认 `/session/start` 和 `/chat` 返回 `rs_agent_display_v1`，5 个商品卡且响应不含 `ranking`、`diagnostics`、`reward`、`score`，前端页面可加载。

**面试可讲点：**
这次工作把推荐 Agent 从“服务可调用”推进到“用户可交互”：前端没有读取推荐内部字段，而是只消费 `DisplayResponse`，按钮反馈也先转成自然语言走 `/chat`，避免过早扩张 `/feedback` API。通过 Gemini 审阅补齐 session 失效和展示细节，体现了前后端 contract 隔离、Demo 范围控制和跨模型协作把关的工程过程。

### 2026-04-28 - 结构化 feedback API 与前端按钮闭环

**任务：**
把 Web Demo 中的反馈按钮从“转成自然语言再走 `/chat`”升级为结构化 `/feedback` API，让按钮反馈成为可记录、可测试、可扩展的交互事件。

**遇到的问题：**
最小前端 Demo 的按钮反馈虽然可用，但语义依赖英文 prompt 映射，不利于后续统计、回放和训练样本构造；同时前端按钮如何与自由文本 `/chat` 共存、是否携带 item_id、如何处理后端重启后的 session 失效，需要明确边界。

**定位方式：**
检查 `rs_core/serving/schema.py`、`rs_core/serving/service.py`、`rs_core/serving/app.py` 和 `frontend/src/App.tsx`、`frontend/src/api.ts` 的接口边界；按用户要求通过 `omc ask gemini` 审阅前端结构化 feedback 接入方案，Gemini 明确建议输入框只走 `/chat`，快捷按钮只走 `/feedback`，移除 `ACTION_MESSAGES` 自然语言硬编码，并复用 loading 与 session 失效处理。

**解决方式：**
后端新增 `FeedbackRequest` / `FeedbackResponse` 和 `POST /feedback`，支持 `like`、`dislike`、`show_different`、`why` 四种 `action_type`，内部仍复用 `env.converse()` 与 `build_display_record()`，保持输出为 `DisplayResponse`；前端新增 `sendFeedback()`，按钮直接发送 `{session_id, action_type}`，并与 `/chat` 共用 `isLoading`、`applyDisplayUpdate()` 和 `handleRequestError()`，保留后续商品级 `item_id` 反馈的扩展空间。

**验证结果：**
运行 `npm --prefix frontend run build` 通过；运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `11 passed in 0.51s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；启动后端和前端后，用 HTTP 验证 `/health`、默认 `/session/start`、`/chat` 和 `/feedback`，`/feedback` 返回 `rs_agent_display_v1`、turn_index 更新为 2、5 个商品卡，并确认响应不含 `ranking`、`diagnostics`、`reward`、`score`。

**面试可讲点：**
这次工作把前端反馈从 prompt hack 升级为结构化事件 contract：自由文本仍由 `/chat` 处理，按钮语义由 `/feedback` 表达，后端再统一转入 Agent 决策链路。这样既保持了当前 demo 的轻量实现，又为后续 feedback 日志、session replay、多角色模拟客户和 GRPO reward 样本提供了稳定事件入口。

### 2026-04-28 - session 轨迹安全导出与 replay 基础

**任务：**
在 structured feedback API 之后补齐 `GET /session/{session_id}`，让服务层可以导出当前会话轨迹，为后续 replay、模拟客户评估和前端调试提供安全数据入口。

**遇到的问题：**
`AgentSession.to_dict()` 和 `AgentTurn.to_dict()` 会包含 `ranking`、`diagnostics`、`reward_evidence`、`reward` 等内部诊断与训练字段，不能直接作为公开 API 返回；但如果只返回最后一轮 `DisplayResponse`，又无法支撑多轮 replay 和反馈闭环复盘。

**定位方式：**
检查 `rs_core/serving/service.py`、`rs_core/serving/schema.py`、`rs_core/serving/app.py`、`rs_core/rsagent/schema.py` 和 `rs_core/display/builder.py`，确认安全边界应复用 `build_display_record()`，事件摘要只保留 `turn_index`、`user_input`、`assistant_message` 和 display 索引，不暴露 turn 原始结构。

**解决方式：**
在 `RecommendationService` 新增 `export_session()`，返回 `session_id`、`user_id`、`turn_count`、轻量 `events` 和逐轮 `display_responses`；在 serving schema 中新增 `SessionExportResponse`，并在 FastAPI 中新增 `GET /session/{session_id}`，继续复用统一的 unknown session 404 处理。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `13 passed in 2.41s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；运行 `npm --prefix frontend run build` 通过。新增测试覆盖 chat+feedback 后的 session export、unknown session 404，并递归断言公开响应不含 `ranking`、`diagnostics`、`reward`、`reward_evidence`、`score`。

**面试可讲点：**
这次工作体现的是“可回放但不泄露内部诊断”的服务 contract 设计：训练和调试侧仍保留完整 AgentTurn / rollout，公开 API 只暴露展示层和轻量事件索引。这样既能支撑后续 session replay、多角色模拟客户和前端调试，又不会把排序分数、reward 证据等内部实现绑死到前端或外部消费者。

### 2026-04-28 - session export 结构化 feedback 事件元数据

**任务：**
增强 `GET /session/{session_id}` 的 replay 事件，让反馈轮次既保留 Agent 实际收到的 `user_input`，也保留原始结构化 `action_type`、`item_id` 和 `comment`。

**遇到的问题：**
上一版 session export 已经安全，但 feedback 事件在导出中只表现为转译后的 prompt，例如 `why? item_id=...`；这对复盘 Agent 行为足够，却不利于后续按按钮类型统计、重放 UI 事件或构造结构化反馈样本。

**定位方式：**
检查 `rs_core/serving/service.py` 和 `tests/test_serving_smoke.py`，确认结构化 feedback 信息在 `/feedback` 请求边界存在，但没有被保留下来；同时确认不应修改 `AgentSession` / `AgentTurn` 训练 schema，以免把服务层事件日志和 Agent 内部状态耦合。

**解决方式：**
在 `RecommendationService` 中新增独立的 `session_events` 轻量列表：`/chat` 记录 `{type: chat}`，`/feedback` 记录 `{type: feedback, action_type, item_id, comment}`；`export_session()` 将这些 metadata 与对应 turn 的 `user_input`、`assistant_message`、`display_response_index` 合并导出。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `13 passed in 0.59s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；运行 `npm --prefix frontend run build` 通过。测试确认 chat 事件与 feedback 事件类型可区分，feedback 事件包含 `action_type/item_id/comment`，公开响应仍不含内部排序、诊断和 reward 字段。

**面试可讲点：**
这次工作体现的是把“Agent 实际输入证据”和“产品交互事件语义”分层保存：Agent 仍消费转译后的自然语言 prompt，服务层额外保留按钮事件 metadata。这样后续 replay、统计分析和训练样本构造可以使用结构化事件，而不会破坏当前轻量 demo 的 Agent schema。

### 2026-04-28 - Gemini 实现 Session Replay 前端闭环

**任务：**
在已有 React 商品卡 Demo 中接入 `GET /session/{session_id}`，把 chat、feedback、display response 串成可视化 Session Replay 时间线，并按用户要求由 Gemini 负责前端实现。

**遇到的问题：**
后端已经能安全导出 session 轨迹，但前端还只能看到当前轮商品卡，不能复盘多轮对话、按钮反馈和每轮推荐变化；同时项目要求前端实现优先交给 Gemini，而不是由我先改再让 Gemini 审阅。

**定位方式：**
对照 `frontend/src/App.tsx`、`frontend/src/api.ts`、`frontend/src/types.ts` 和后端 `SessionExportResponse` contract，明确前端只允许消费 `events` 与 `display_responses`，不能读取 `ranking`、`diagnostics`、`reward`、`score` 等内部字段；通过 Gemini CLI 直接执行前端实现，再由我做边界检查和验证。

**解决方式：**
由 Gemini 在 `frontend/src/types.ts` 增加 `SessionExportEvent` / `SessionExportResponse` 类型，在 `frontend/src/api.ts` 增加 `fetchSessionExport()`，并在 `App.tsx` 增加 `Replay Session` 按钮、loading/error 状态和只读 timeline：每轮展示 turn、chat/feedback 类型、feedback metadata、assistant message 和对应商品快照。

**验证结果：**
运行 `npm --prefix frontend run build` 通过；运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `13 passed in 0.57s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；检索 `frontend/src` 确认没有引用 `ranking`、`diagnostics`、`reward`、`reward_evidence`、`score`；通过临时本地服务 HTTP 验证 chat→feedback→session export，导出包含 `event_types=[chat, feedback]` 且无内部字段泄露。

**面试可讲点：**
这次工作把推荐 Agent demo 从“当前轮展示”推进到“完整交互轨迹可回放”：用户输入、结构化反馈、Agent 回复和商品卡变化都能按 session timeline 复盘。工程上体现了前后端 contract 隔离、内部诊断字段保护，以及用 Gemini 承担前端实现、我负责接口边界和验收整合的协作流程。

### 2026-04-28 - 多角色模拟的角色内在模型基础层

**任务：**
把“多角色模拟客户”从一次性测试脚本调整为后续模拟场景的角色内在基础层，先实现可复用的角色画像、状态和 deterministic 行为策略。

**遇到的问题：**
如果直接做批量 simulated session runner，容易把多角色模拟降级成 smoke test；但项目后续目标是类似沙盒/游戏场景的多角色客户，每个角色需要有稳定人格、购物目标、偏好、记忆、反馈风格和状态演化，才能支撑 replay、动画和更真实的 Agent 评估。

**定位方式：**
对照已有 `rs_core/simulation/` 骨架和当前 `DisplayResponse` contract，确认 simulation 层应先消费前端安全展示数据，而不是读取推荐内部 ranking/reward；同时根据用户反馈明确：角色内在状态应优先于批量评估脚本。

**解决方式：**
新增 `rs_core/simulation/schema.py`，定义 `SimulatedCustomerRole`、`RoleState`、`RoleActionType`、`RoleAction`；新增 `policy.py`，用 deterministic `RolePolicy` 根据角色偏好、预算敏感度、负偏好和当前 display items 选择 chat、why、show_different、dislike、accept 等动作；新增 `presets.py`，提供通勤实用型、礼物购买型、价格敏感型三个内置角色，并通过 `rs_core/simulation/__init__.py` 导出。

**验证结果：**
新增 `tests/test_simulation_roles.py` 覆盖初始 prompt、preset 注册、已看商品状态更新、无商品时追问、有强匹配商品时接受、谨慎角色要求解释、不同 feedback style 产生不同动作；运行 `./.venv/Scripts/python.exe -m pytest tests/test_simulation_roles.py tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `20 passed in 0.57s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过。

**面试可讲点：**
这次工作体现的是把多角色模拟从“跑几条 prompt”提升为“角色内在模型”：角色画像、目标、偏好、记忆和反馈风格决定下一步行为，且只依赖安全 `DisplayResponse`。这为后续多角色沙盒、session replay 动画、模拟客户评估和 LLM-driven role simulation 留出了清晰扩展点。

### 2026-04-28 - Simulation Scene 后端契约与前端展示闭环

**任务：**
把角色内在模型接到真实 Agent 服务层，生成可供前端展示的 simulation scene，并按用户要求由 Gemini 实现前端场景面板。

**遇到的问题：**
角色画像和策略已经存在，但还没有驱动真实 Agent session；前端也无法展示“角色如何带着目标、偏好和反馈风格与推荐 Agent 交互”的完整场景。如果前端直接造假数据，会削弱 replay 和评估价值；如果后端直接暴露 AgentTurn，则又会泄露 ranking/reward 等内部字段。

**定位方式：**
检查 `rs_core/simulation/schema.py`、`policy.py`、`presets.py`、`rs_core/serving/service.py` 和 `SessionExportResponse` contract，确认最稳妥的连接方式是让 runner 复用 `RecommendationService.chat()` / `feedback()` 和 `export_session()`，输出 role、state、actions、session 四段安全 scene contract。

**解决方式：**
新增 `rs_core/simulation/runner.py`，实现 `run_simulation_scene()`：角色先发 `initial_prompt()`，随后由 `RolePolicy` 根据每轮 `DisplayResponse` 选择 chat、feedback、show_different、why、accept 等动作，最终导出 `scene_id`、角色画像、角色状态、动作时间线和安全 session export；在 FastAPI 中新增 `POST /simulation/scene`，并让 Gemini 在前端新增 Simulation Scene 面板，支持选择 `commuter_practical`、`gift_buyer`、`price_sensitive`，展示角色卡、状态卡、动作时间线和 session summary。

**验证结果：**
新增 `tests/test_simulation_runner.py` 覆盖 runner contract、API endpoint 和 unknown role；运行 `./.venv/Scripts/python.exe -m pytest tests/test_simulation_runner.py tests/test_simulation_roles.py tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `23 passed in 0.60s`；运行 `npm --prefix frontend run build` 通过；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；检索 `frontend/src` 确认没有引用 `ranking`、`diagnostics`、`reward`、`reward_evidence`、`score`；本地 HTTP 验证 `POST /simulation/scene` 返回 `role_id=commuter_practical`、`turn_count=3`、`final_action=show_different` 且无内部字段泄露。

**面试可讲点：**
这次工作把项目从“单个用户手动 demo”推进到“角色驱动的可展示模拟场景”：角色内在状态决定交互行为，Agent 服务生成真实推荐与反馈轨迹，前端以 scene 面板展示角色、状态、动作和商品卡回放。它为后续多角色沙盒、动画展示、LLM 驱动角色和批量模拟评估提供了可复用 contract。

### 2026-04-29 - 端到端推荐 Agent 演示闭环聚合

**任务：**
把已有服务层、展示层和 React 前端推进成可一键演示的多轮闭环：用户需求进入 Agent，服务返回 `DisplayResponse` 商品卡，反馈后第二轮推荐发生变化，并能在前端按商品提交喜欢/不喜欢。

**遇到的问题：**
项目已有 `/chat`、`/feedback`、session replay 和商品卡前端，但面试演示仍需要人工分多步操作；同时测试环境当前缺少 `pytest` 和 `fastapi`，不能直接跑完整 HTTP 测试套件。

**定位方式：**
检查 `rs_core/serving/service.py`、`rs_core/serving/app.py`、`rs_core/display/builder.py`、`frontend/src/App.tsx` 和 `tests/test_serving_smoke.py`，确认可复用 `RecommendationService.chat()`、`feedback()` 与 `DisplayResponse`，不需要让前端读取 rollout、ranking、diagnostics 或 reward 字段。

**解决方式：**
在服务层新增 `run_demo_roundtrip()` 和 `/demo/e2e`，聚合 start session、首轮 chat、结构化 feedback 和变化摘要；前端新增一键闭环按钮，并把商品卡上的喜欢/不喜欢绑定到具体 `parent_asin`；补充 smoke 测试用例覆盖两轮展示、turn_index 递增、商品变化和内部字段不外泄。

**验证结果：**
补齐 serving/test 依赖后，运行 `python -m pytest tests/test_serving_smoke.py tests/test_display_contract.py -q`，结果 `15 passed in 1.35s`；运行 `python -m compileall -q rs_core tests scripts` 通过；运行 `npm --prefix frontend run build` 通过。测试覆盖 `/demo/e2e` 的两轮 `DisplayResponse`、`turn_index` 递增、商品集合变化、unknown feedback 422，以及公开响应不含 `ranking`、`diagnostics`、`reward`、`reward_evidence`、`score`。

**面试可讲点：**
这次工作把推荐 Agent 从“有接口、有前端”推进到“可一键复现闭环”：服务端用薄 orchestration 串起现有推荐和反馈能力，前端只消费展示 contract，变化摘要用于证明反馈确实影响下一轮推荐。这个实现兼顾了演示效率、前后端边界隔离和后续训练/回放数据的可解释性。

### 2026-04-29 - 批量多角色 Simulation Evaluation 闭环

**任务：**
把单个 simulation scene 扩展成批量多角色评估入口，让多个 persona 自动与推荐 Agent 交互，并生成可复现的 metrics/report 产物。

**遇到的问题：**
此前系统已经能展示单个角色与 Agent 的交互场景，但缺少多 persona、重复运行、统一指标和落盘报告；这使多角色模拟更像展示 demo，而不是能支撑评估、复盘和后续训练样本构造的闭环。

**定位方式：**
检查 `rs_core/simulation/runner.py`、`rs_core/serving/service.py`、`rs_core/serving/app.py` 和 `tests/test_simulation_runner.py`，确认最稳妥的做法是复用 `run_simulation_scene()`、`RecommendationService.chat()/feedback()/export_session()` 与安全 `DisplayResponse` contract，而不是重写推荐逻辑或暴露内部 ranking/reward 字段。

**解决方式：**
在 `rs_core/simulation/runner.py` 新增 `run_simulation_batch()`、scene metrics 和 batch summary；在 `rs_core/serving/app.py` / `schema.py` 新增 `/simulation/batch`；新增 `scripts/run_simulation_evaluation.py`，输出 `simulation_batch.json`、`metrics.json` 和中文 `simulation_eval_report.md`。公开输出继续递归阻断 `ranking`、`diagnostics`、`reward`、`reward_evidence`、`score` 等内部字段。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_simulation_runner.py tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `23 passed in 0.75s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；运行 `./.venv/Scripts/python.exe scripts/run_simulation_evaluation.py --limit-users 1 --max-turns 3 --repeats 1 --output-dir outputs/simulation/simulation_eval_smoke_default` 成功生成 `simulation_batch.json`、`metrics.json` 和 `simulation_eval_report.md`。

**面试可讲点：**
这次工作把多角色模拟从“单场景展示”推进到“可量化评估闭环”：不同 persona 可以批量驱动真实 Agent 服务，系统聚合 accept rate、平均轮数、反馈/解释/换榜行为和满意度指标，同时保持前端安全视图边界。这为后续 session replay、模拟客户评估、SFT 样本和 GRPO reward 对照提供了稳定数据基础。

### 2026-04-29 - 模型驱动模拟用户策略接入

**任务：**
让多角色模拟客户可以选择由外部模型 API 驱动下一步行为，同时保留 deterministic 规则策略作为默认路径和 fallback。

**遇到的问题：**
此前多角色模拟虽然能批量运行，但角色行为仍是规则策略，难以表现更自然的模拟用户差异；同时 API base、key、model 这类敏感或易变参数不能硬编码进代码、日志或提交文件。

**定位方式：**
检查 `rs_core/simulation/policy.py`、`rs_core/simulation/runner.py` 和 `scripts/run_simulation_evaluation.py`，确认模型能力应接在 RolePolicy 层，只决定模拟用户的 `chat/why/show_different/dislike/accept` 行为，不改变推荐候选、排序、reward 或 `DisplayResponse` contract。

**解决方式：**
新增被 `.gitignore` 保护的本地配置约定 `configs/simulation_model.local.json`，并提供非敏感模板 `configs/simulation_model.example.json`；新增 `rs_core/simulation/model_client.py`，用 OpenAI-compatible `/v1/chat/completions` 调用外部模型；在 `rs_core/simulation/policy.py` 新增 `ModelDrivenRolePolicy`，约束模型只能返回允许 action 且 item_id 必须来自当前展示商品；在 `scripts/run_simulation_evaluation.py` 增加 `--role-policy model`、`--model-config` 和 `--strict-model-policy`。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_simulation_roles.py tests/test_simulation_runner.py tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `37 passed in 0.73s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；运行 `./.venv/Scripts/python.exe scripts/run_simulation_evaluation.py --role-policy model --model-config configs/simulation_model.local.json --limit-users 1 --max-turns 2 --repeats 1 --output-dir outputs/simulation/simulation_eval_model_fallback_smoke_2` 成功生成评估产物，并在本地配置缺失时记录 deterministic fallback。

**面试可讲点：**
这次工作把模拟客户从固定规则升级为可插拔模型策略：外部模型只负责用户侧行为生成，系统用 JSON action schema、展示商品白名单和 deterministic fallback 保证可控性。这样既能提升多角色模拟的自然度，也不会让大模型越权影响推荐排序或泄露内部诊断字段。

### 2026-04-29 - 核心文档阶段状态收口

**任务：**
同步项目核心文档的当前状态，把 README、实施计划、架构说明、目录说明和优化叙事从“展示/前端/仿真仍在规划中”的旧口径，更新为“已完成第一版，下一步进入训练样本收口”的真实阶段。

**遇到的问题：**
工程日志已经记录了 `DisplayResponse`、HTTP 服务、React Web Demo、Session Replay、`/demo/e2e`、Simulation Batch 和模型驱动模拟用户，但核心入口文档仍保留 Phase 2 / Phase 3 规划中、`frontend/` 仅预留等表述，容易让读者低估项目完成度，也会削弱面试演示主线。

**定位方式：**
对照 `prd.json` 中已通过的 rollout contract / Qwen harness story，以及 `dic/ENGINEERING_NARRATIVE_LOG.md` 中 2026-04-28 至 2026-04-29 的服务、前端、replay、simulation 记录；再用关键词检索 `规划中`、`当前仅预留`、`后期规划会补` 等旧表述，定位到 `dic/README.md`、`dic/architecture/IMPLEMENTATION_PLAN.md`、`dic/architecture/ARCHITECTURE.md`、`dic/PROJECT_STRUCTURE.md` 和 `dic/OPTIMIZATION_NARRATIVE.md`。

**解决方式：**
将核心文档统一改成阶段收口口径：Phase 2 展示 contract / 服务层 / React Web Demo 已完成第一版，Phase 2.5 Session Replay 和一键 E2E 闭环已完成第一版，Phase 3 多角色 Simulation 和模型驱动模拟用户已完成第一版；同时明确 Qwen3.5-4B + 8-bit QLoRA SFT + GRPO 尚未完整训练落地，当前服务仍是 single-process demo，前端和仿真不是生产级真实用户评估。

**验证结果：**
运行关键词检查确认核心文档中不再出现 `当前仅预留`、`后期规划会补商品展示卡`、`商品展示卡 contract 与轻量前端 demo` 等过期表述；运行 `./.venv/Scripts/python.exe - <<'PY' ... PY` 校验 5 个核心 Markdown 文件均可用 UTF-8 读取、非空，且不含关键过期口径，输出 `validated 5 markdown files`。

**面试可讲点：**
这次工作体现的是阶段治理和工程叙事能力：当功能快速推进后，及时把入口文档、实施计划和架构边界同步到真实状态，避免“代码已完成但文档仍像规划”的信息漂移；同时保留训练未落地、服务非生产级、仿真非真实用户的边界，能让项目叙事可信而不夸大。

### 2026-05-07 - Phase 4 轨迹样本与 Agent 行为评估方向澄清

**任务：**
明确 Phase 4 的下一步主线：把 Web Demo 和多角色 Simulation 产生的 session 轨迹标准化为可审计的 Agent training trajectories。

**遇到的问题：**
项目已经具备 Web Demo、结构化 feedback、Session Replay、多角色 Simulation 和模型驱动模拟用户第一版，但下一阶段不能简单理解为“继续扩展示功能”或“马上训练 Qwen”。需要先把交互闭环沉淀成后续 SFT、preference learning 和 RL / GRPO 能复用的数据来源。

**定位方式：**
对照当前 `dic/architecture/IMPLEMENTATION_PLAN.md`、`dic/architecture/ARCHITECTURE.md`、`rs_core/serving/*`、`rs_core/simulation/*` 和 `scripts/run_simulation_evaluation.py`，确认已有能力已经能生成 session、feedback、display response、simulation scene / batch 和 metrics，缺口在统一 trajectory schema、样本导出、质量校验和 Agent 行为指标。

**解决方式：**
将下一阶段表述为：先把 Web Demo 和多角色 Simulation 产生的 session 轨迹标准化为可审计的 Agent training trajectories，里面同时支持 SFT 样本、preference 样本和 RL rollout 样本。这样后续 `Qwen3.5-4B + QLoRA + GRPO` 可以基于真实交互约束和反馈信号优化，而不是离线凭空构造训练数据。

**验证结果：**
本次是路线澄清与叙事记录，未修改代码、未运行新的实验。当前可验证依据是已有服务层 session export、simulation batch 输出、结构化 feedback 事件和批量评估 metrics/report 产物。

**面试可讲点：**
这条主线可以概括为“先采集和标准化交互轨迹，再做可控训练”：Agent 当时能选哪些候选、实际推荐了什么、用户或模拟用户如何反馈、下一轮是否改正，都被记录进 trajectory。后续 RL / GRPO 的 state、action、reward 和 rollout 不是人工拼出来的，而是来自可回放、可审计的推荐交互闭环。

### 2026-05-07 - 10k 数据验证 semantic_title 召回路线

**任务：**
将已有 title/category-only semantic recall 路线扩展到 10k 数据规模，验证它相对 baseline 是否真实提升传统召回效果。

**遇到的问题：**
1000 小样本上的 `semantic_title` 提升可能存在偶然性；同时用户指出“买过相似标题商品不代表还会重复购买同类商品”，因此需要在更大数据上验证 `semantic_title` 作为补充召回源是否有效，并识别它对排序融合的副作用。

**定位方式：**
基于 `data/processed/amazon_2023_base/manifest.json` 构建 `amazon_2023_recall_clean_10000` 和 `amazon_2023_recall_views_10000`；复制 1000 配置生成 `configs/demo/hybrid_demo/hybrid_demo_electronics_10000*.yaml`；运行 baseline、semantic_title、LOPO baseline、LOPO semantic_title 四组对照，并读取 `outputs/hybrid_demo/hybrid_demo_small_electronics_10000*/metrics.json` 与 `ranking_case_summary.json`。

**解决方式：**
没有新增一条完全不同的召回算法，而是把已有 `semantic_title` 路线迁移到 10k 数据上做 ablation：它使用 `title_clean`、`main_category`、`categories_flat` 的 token overlap 做确定性文本召回。第一轮只改数据路径、输出目录和报告名，不改排序权重，保证 baseline 与 semantic_title 的对照尽量干净。

**验证结果：**
valid/test 口径中，`candidate_hit_users` 从 23 提升到 60，`ranked_hit_users` 从 5 提升到 14，`hit_rate@5` 从 0.007013 提升到 0.019635；LOPO 口径中，`candidate_hit_users` 从 74 提升到 1298，`ranked_hit_users` 从 68 提升到 1044，`hit_rate@5` 从 0.049204 提升到 0.755427。副作用也很明确：LOPO 中 `itemcf_only_hit_rate@5=0.887844` 高于 hybrid semantic_title 的 0.755427，且候选命中平均排名仍偏后，说明 `semantic_title` 明显提升覆盖，但当前融合排序稀释了 ItemCF 强信号。

**面试可讲点：**
这不是简单“加文本相似召回”，而是通过 10k ablation 证明 semantic/title recall 作为增量召回源能显著提升候选覆盖；同时主动暴露局限：标题相似不等于下一次购买意图，semantic-only 候选可能压住 ItemCF。下一步应做 source-aware fusion，在保留 `semantic_title` 覆盖收益的同时保护 ItemCF 和多源一致性信号。

### 2026-05-08 - 10k source-aware fusion 排序优化

**任务：**
在 10k `semantic_title` 召回验证后，优化传统推荐 backbone 的融合排序，让文本召回带来的候选覆盖尽量转化为 Top-K 排序收益，同时保持 Agent 作为独立交互编排层，不把它简单归入精排模块。

**遇到的问题：**
`semantic_title` 已经显著提升候选池覆盖，但 LOPO 中 `itemcf_only_hit_rate@5=0.887844` 仍高于 hybrid semantic_title 的 `0.755427`，说明当前线性加权排序会稀释 ItemCF 强信号。直接强保护 ItemCF 又会伤害 valid/test，因为 valid/test 的一部分 target 主要由 semantic 命中。

**定位方式：**
在 `rs_core/recsys/ranking.py` 增加默认关闭的 `source_aware_fusion`，分别运行 10k valid/test 与 LOPO source-aware 对照；读取 `outputs/hybrid_demo/hybrid_demo_small_electronics_10000_semantic_title_source_aware/metrics.json`、`outputs/hybrid_demo/hybrid_demo_small_electronics_10000_lopo_semantic_title_source_aware/metrics.json` 和对应 `ranking_case_summary.json`，同时对比强保护版与温和版参数。

**解决方式：**
新增可解释的 source-aware fusion：对 ItemCF 候选加分，对 ItemCF + 多源候选额外加分，对 semantic-only / popular-only 做轻量惩罚，并在 `rerank_events` 中记录 `source_aware_fusion` 事件；新增 `configs/demo/hybrid_demo/hybrid_demo_electronics_10000_semantic_title_source_aware.yaml` 与 LOPO 配置。最终保留温和参数 `itemcf_source_boost=8.0`、`itemcf_multi_source_boost=4.0`、`semantic_only_penalty=4.0`、`popular_only_penalty=2.0`，并把 `source_aware_fusion` 写入实验报告的 `config_summary`。

**验证结果：**
单测 `./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_inference_policy.py` 通过，结果 `49 passed`；`./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过。强保护版在 LOPO 中将 `hit_rate@5` 从 `0.755427` 提升到 `0.810420`，但 valid/test 从 `0.019635` 降到 `0.011220`，不适合作为默认配置。温和版 valid/test 保持 `hit_rate@5=0.019635`、`ranked_hit_users=14`；LOPO 保持 `hit_rate@5=0.755427`，但 `candidate_hit_rank_avg` 从 `40.308937` 改善到 `35.738829`。这说明温和 source-aware fusion 是安全的小幅排序改善，强保护版更适合作为诊断证据而不是默认策略。

**面试可讲点：**
这次优化体现了“召回增益之后不能只看 hit-rate，还要看融合排序和评估口径 tradeoff”：强保护 ItemCF 能证明排序确实可把 LOPO target 推前，但会牺牲 valid/test 的 semantic 命中；温和版则保持主指标不受损并改善候选池内排名分布。后续如果继续提升效果，应从手写 source-aware 规则升级到可训练 ranker，学习 ItemCF、多源一致性、semantic-only、popular-only 等特征的权重，而不是继续人工调参。

### 2026-05-09 - 双塔向量召回旁路与 strict gate 收口

**任务：**
把下一阶段复杂召回重点收敛到 DSSM-style 与 YouTubeDNN-style 双塔向量召回，补齐训练 artifact、向量索引、默认关闭配置、strict promotion gate、测试和中文路线说明。

**遇到的问题：**
此前项目已验证 semantic_title 能提升候选覆盖，但复杂召回仍停留在 token overlap / POC 语义旁路；如果直接同时实现图召回、多兴趣、TDM、DeepFM / NCF，会让工程范围过大，也难以用 valid/test 与 LOPO 证明哪条路线真正有效。

**定位方式：**
对照 `.omc/specs/deep-interview-two-tower-recall-next.md` 的验收标准，检查 `rs_core/recsys/two_tower.py`、`rs_core/workflow/two_tower_training.py`、`rs_core/recsys/vector_index.py`、`rs_core/recsys/candidate_merge.py`、`rs_core/workflow/hybrid_demo.py`、`tests/test_two_tower_training.py` 和 `tests/test_hybrid_demo.py`；再读取 `outputs/training/two_tower/two_tower_training/*/artifact_manifest.json` 与四组 two-tower smoke metrics，确认当前证据是训练 `limit_users=10`、评估 `limit_users=30` 的 paired smoke，而不是完整 10k 双塔评估。

**解决方式：**
新增并更新 `tests/test_two_tower_training.py`，验证双塔训练输出完整 artifact contract、`default_enabled=false`、DSSM / YouTubeDNN 的 `model_type` 与 `source_name` 隔离、manifest 可作为 `VectorIndex` 加载，并覆盖 PyTorch backend 规则：torch 可导入时使用 `pytorch`，`backend: python_fallback` 不能绕过 PyTorch，只有 no-torch 场景才进入 `python_fallback_vector_updates`。同时更新 `dic/architecture/IMPLEMENTATION_PLAN.md`、`dic/README.md`、`dic/architecture/ARCHITECTURE.md`、`dic/PROJECT_STRUCTURE.md`，明确双塔只作为默认关闭旁路，晋升必须通过 strict gate。

**验证结果：**
训练 smoke artifact 位于 `outputs/training/two_tower/two_tower_training/dssm/artifact_manifest.json` 和 `outputs/training/two_tower/two_tower_training/youtube_dnn/artifact_manifest.json`，manifest 中 `training_backend.name=pytorch`，训练规模为 `limit_users=10`、`epochs=1`、`negative_samples=1`、`embedding_dim=8`、`hidden_dim=8`。paired smoke 评估规模为 `limit_users=30`：DSSM valid/test `candidate_hit_rate_at_pool=0.111111`、`recall_at_pool=0.111111`、`hit_rate_at_k=0.0`、`candidate_hit_users=1`、`candidate_generation_p95_seconds=0.270462`、`promotable=false`；YouTubeDNN valid/test 同为 `candidate_hit_rate_at_pool=0.111111`、`recall_at_pool=0.111111`、`hit_rate_at_k=0.0`、`candidate_hit_users=1`，`candidate_generation_p95_seconds=0.246153`、`promotable=false`。LOPO 仍是 sanity-only no promotion。当前没有完整 10k 双塔结论，不能据此宣称双塔可晋升。

**面试可讲点：**
这次工作可以讲成“把复杂召回工程化为可验证旁路，而不是堆模型名”：DSSM 与 YouTubeDNN 都通过同一 artifact contract 进入向量索引和 candidate merge，但默认关闭；是否进入主路由 valid/test、LOPO sanity、source contribution / overlap 和 latency gate 决定。Node2Vec / DeepWalk、MIND / SDM、TDM、DeepFM / NCF 被明确延期，体现了工程范围控制和评估优先的取舍。

### 2026-05-08 - Phase 1.9 轻量 learning-to-rank baseline

**任务：**
把 source-aware fusion 的手写 source 规则升级为一个默认关闭、可训练、无新增依赖的轻量 LTR baseline，用于学习 ItemCF、多源一致性、semantic-only、popular-only 和热度/时间等排序特征权重。

**遇到的问题：**
项目当前没有 `numpy`、`sklearn`、`lightgbm` 等训练依赖，不能为了一个 baseline 引入重依赖；同时 LOPO 训练与 LOPO 评估容易形成同 split 过拟合，如果只报告 LOPO 提升会夸大泛化效果。实现时还发现 LTR 配置会在训练前启用 `ltr_model` 并尝试加载尚未生成的模型文件。

**定位方式：**
检查 `rs_core/recsys/ranking.py`、`rs_core/workflow/hybrid_demo.py` 和新训练流程，确认现有 candidate / ranking 字段已足够抽取 source indicator、source score、source interaction 和 metadata 特征；通过 200 用户 smoke 训练先验证 `scripts/train_ltr_ranker.py` 能生成模型与指标，再分别运行 10k LOPO 和 valid/test 对照，读取 `outputs/training/ltr/ltr_training_10000_lopo_semantic_title/ltr_train_metrics.json`、`outputs/hybrid_demo/hybrid_demo_small_electronics_10000_lopo_semantic_title_ltr/metrics.json` 和 `outputs/hybrid_demo/hybrid_demo_small_electronics_10000_semantic_title_ltr/metrics.json`。

**解决方式：**
新增 `rs_core/recsys/ltr.py`，实现 pure-Python pairwise perceptron、特征抽取、模型保存/加载和线性打分；新增 `rs_core/workflow/ltr_training.py` 与 `scripts/train_ltr_ranker.py` 复用 hybrid demo 的候选生成和 holdout label；在 `rank_candidates()` 中新增 `ltr_score` 和 `ltr_model` rerank event，并保持 `ltr_model.enabled=false` 时原排序不变；训练候选生成阶段临时关闭 `ltr_model`，避免训练前加载不存在的模型。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_ltr.py tests/test_hybrid_demo.py tests/test_inference_policy.py`，结果 `56 passed`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过。200 用户 smoke 训练生成 5550 行样本、111 个 positive users。10k LOPO 训练生成 64900 行样本、1298 个 positive users，模型学到 `itemcf_source=2.34`、`itemcf_multi_source=2.21`、`semantic_only=-0.85`、`popular_only=-0.54`。LOPO 评估中 `hit_rate@5` 从 `0.755427` 提升到 `0.758321`，`ranked_hit_users` 从 `1044` 到 `1048`，`candidate_hit_rank_avg` 从 `40.308937` 改善到 `32.591680`；但 valid/test `hit_rate@5` 从 `0.019635` 降到 `0.014025`，说明该模型目前更适合作为训练排序 baseline 和诊断工具，而不是默认泛化配置。

**面试可讲点：**
这次工作可以讲成“从手写规则到可训练排序器”的工程升级：先用 source-aware fusion 暴露 ItemCF 保护与 semantic 泛化之间的 tradeoff，再实现无依赖 LTR baseline 学习这些特征权重。关键不是夸大指标，而是主动用 valid/test 证明同 split LOPO 收益不能直接等同线上泛化，并给出下一步应做独立训练/验证切分、score calibration 或更强 LTR 模型的方向。

### 2026-05-08 - Phase 1.10 推荐底座工业化诊断层

**任务：**
补齐推荐 backbone 的工业化离线诊断层，用 valid/test 和 LOPO 对照判断当前瓶颈属于召回、source merge、排序/LTR 还是 latency，而不是直接根据数据量决定是否上粗排、精排或双塔。

**遇到的问题：**
已有 `hit_rate@5`、候选池命中和 LTR 对照，但指标还不足以回答“应该先优化召回还是排序”“LTR 能否默认启用”“当前是否需要粗排/双塔”。如果只看 LOPO，容易把同 split 排序收益包装成泛化提升；如果只看 valid/test hit-rate，又看不出 target 是否进入候选池、是否被排序压在 Top-K 外。

**定位方式：**
扩展 `rs_core/recsys/evaluation.py` 与 `EvaluationSummary`，加入 `recall_at_k`、`recall_at_pool`、`ndcg_at_k`、`mrr_at_k`、`map_at_k`、`candidate_hit_rank_p90`、source contribution、source overlap；在 `rs_core/workflow/hybrid_demo.py` 聚合 candidate generation / ranking / total recommendation latency，并输出 `diagnostic_gate`。随后运行 6 组 10k 对照：valid/test 与 LOPO 的 semantic_title、source-aware、LTR。

**解决方式：**
把 gate 设计为显式诊断报告：candidate pool 命中低时判为 recall bottleneck；pool 命中不低但 Top-K / NDCG / MRR 低且命中排名靠后时判为 ranking bottleneck；source contribution 与 Top-K contribution 错配或 overlap 异常时作为 source merge 诊断；候选池扩大且排序耗时上升时才考虑 latency / architecture escalation。所有 gate 同时保留绝对用户数和比例，避免小样本比例误导。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_ltr.py`，结果 `40 passed in 0.27s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过。六组实验均成功生成 metrics/report。valid/test 三组的 `candidate_hit_rate_at_pool=0.084151`、`recall_at_pool=0.034086`，gate 都指向 `phase_1_11_recall_source_merge`；LTR 在 valid/test 中 `hit@5=0.014025`，低于 semantic_title/source-aware 的 `0.019635`，不能默认启用。LOPO 中 source-aware 改善 `ndcg@5=0.314323`、`mrr@5=0.179317`，LTR 将 `hit@5` 提升到 `0.758321`，但只能作为排序诊断证据。排序 `ranking_p95_seconds` 最高约 `0.001366`，候选池约 50，当前不需要独立粗排。

**面试可讲点：**
这次工作体现的是“先诊断瓶颈，再决定架构升级”：没有因为效果低就直接上双塔、粗排或精排，而是用 Recall@pool、NDCG/MRR、source contribution、命中排名分布和 latency gate 拆清责任边界。结论是推荐 backbone 已足够支撑 Agent 工程继续推进，但还不是强推荐算法底座；下一步应优先做 recall/source merge 泛化优化，LTR 保留为诊断 baseline，双塔和复杂精排放到传统召回触顶后的 POC。

### 2026-05-12 - Phase 1.23 pool200 same-run ranking isolation

**任务：**
在 frozen pool200 上做 same-run ranking isolation，验证 `ranking_v2`、`item_feature_rerank`、`source_aware_fusion` 是否能在不漂移候选池的前提下带来真实 Top-K 收益。

**遇到的问题：**
pool200 已经冻结，如果没有 same-run isolation，任何 ranking 结果都可能混入候选池波动或 freeze 漂移，最后无法区分是排序特征有效还是采样噪声。

**定位方式：**
使用项目默认 `.venv` 跑完整对照命令，并带上 `--limit-users 500`；检查 `outputs/ranking/phase_1_23_pool200_ranking_isolation/comparison.json` 和 `outputs/ranking/phase_1_23_pool200_ranking_isolation/comparison.md`，核对 valid、freeze、candidate_hit_users、candidate_count_avg、hit_rate_at_k、ndcg_at_k、mrr_at_k 以及各变体 delta。

**解决方式：**
把评估边界锁死在 same-run frozen pool comparison，只比较 baseline、`ranking_v2`、`item_feature_rerank`、`source_aware_fusion`，不扩展召回或调参范围；若出现 freeze drift 就直接判 invalid，否则只归因到排序层。

**验证结果：**
all variants valid 且 no freeze drift。baseline `users_with_holdout=138`、`candidate_hit_users=17`、`candidate_hit_rate_at_pool=0.123188`、`candidate_count_avg=152.272`、`fallback_rate=0.0`；same-run baseline `hit_rate_at_k=0.014493`、`ndcg_at_k=0.002779`、`mrr_at_k=0.006039`。`ranking_v2`、`item_feature_rerank`、`source_aware_fusion` 的指标与 baseline 完全一致，delta 全为 0，最终判定 `VALID but NO PROMOTION`。

**面试可讲点：**
这轮最重要的是把归因边界锁死：same-run isolation 证明候选池没漂、freeze 没漂，结果仍然不变，说明当前手写排序增量还不足以把稀疏正例推入 Top-K。下一步更合理的是先按 user-level hit rank 和 feature 分布做剖析，再决定是否进入 LTR 或更强排序特征。

### 2026-05-08 - Phase 4.1 Agent 综合评估闭环与反馈重排工具

**任务：**
把 Agent 线从“只导出 trajectory 样本”调整为“能对比、能诊断、能沉淀训练信号”的综合评估闭环，并实现 enhanced Agent 的第一项可解释工具：商品级 feedback rerank。

**遇到的问题：**
Agent 不应该被简单归入传统推荐链路的精排模块，因为它还负责多轮对话、反馈理解、短期记忆、解释与训练信号沉淀；同时如果 public session export 直接暴露 ranking、diagnostics、reward、scorecard 等内部字段，会污染前端和服务 contract。另一个实现问题是 `I don't like this item item_id=...` 这类文本既包含 `like` 又包含否定，需要避免被误记成正反馈或重复记录事件。

**定位方式：**
对照 `rs_core/rsagent/schema.py`、`rs_core/rsagent/policy.py`、`rs_core/workflow/hybrid_demo.py`、`rs_core/serving/service.py`、`rs_core/simulation/runner.py` 和 rollout contract，确认最合适的边界是：推荐 backbone 继续负责候选生成与排序，Agent 层只把商品级反馈转成短期记忆和可解释排序调整；内部评估 artifact 单独导出，不进入 `RecommendationService.export_session()`。

**解决方式：**
在 `FeedbackConstraints` 中记录 `liked_item_ids`、`disliked_item_ids` 和 `item_feedback_events`；新增 `rs_core/rsagent/feedback_rerank.py`，把 like/dislike/show_different 转成 explicit filter、ItemCF 相似商品 boost/demote 和 `feedback_rerank_events`；在 hybrid workflow 中接入该工具，但最终排序仍走原 ranking pipeline。新增 `rs_core/evaluation/agent_scorecard.py` 和 `agent_artifact.py`，输出推荐效果、交互质量、反馈响应、记忆一致性、训练数据质量五维 scorecard，以及 SFT/reward/preference/trajectory training signals；新增 `scripts/run_agent_evaluation.py` 对比 baseline 与 `enhanced_feedback_rerank`。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_agent_rollout_schema.py tests/test_agent_feedback.py tests/test_feedback_rerank.py tests/test_agent_scorecard.py tests/test_agent_eval_artifact.py tests/test_simulation_runner.py tests/test_serving_smoke.py`，结果 `42 passed in 0.98s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过。测试覆盖商品级反馈解析、feedback rerank filter/boost/demote、五维 scorecard、internal artifact/training signals、baseline/enhanced runner，以及 public export 不泄露 `ranking/diagnostics/reward/tool_events/scorecard` 等内部字段。

**面试可讲点：**
这次工作可以讲成“把 Agent 从推荐输出包装器升级为可评估的交互决策层”：底座仍然负责召回和排序，Agent 负责理解用户反馈、维护短期会话记忆、调用可解释工具影响候选排序，并把每次交互沉淀为 scorecard 与训练信号。关键边界是没有宣称已经完成 SFT/GRPO，而是先建立 baseline/enhanced 对比、内部证据 artifact 和 public-safe export 隔离，为后续 Qwen/QLoRA/GRPO 训练提供可审计数据基础。

### 2026-05-13 - Phase 2 fine-rank batch 收口

**任务：**
补齐 Phase 2 fine-rank batch runner 和对应测试，并把线性 / LTR / 树模型的状态边界写回文档。

**遇到的问题：**
原先文档仍容易把 linear / pointwise / pairwise 写成 promotion-capable；tree / LambdaMART 在缺真实依赖或 adapter 时也不能被当作可晋升结果。

**定位方式：**
检查 `scripts/run_phase_2_fine_rank_algorithm_batch.py`、`tests/test_phase_2_fine_rank_algorithm_batch.py` 和现有排序路线文档，确认 fine_rank 承担 full-pool scoring，rerank 只应保留 Top-K 局部诊断 / 约束语义。

**解决方式：**
在路线图里把 Phase 2 改成 fine_rank full-pool scoring 口径，learned rows 统一降为 diagnostic-only，tree/LambdaMART 标记 blocked/preparation；同时补写 batch runner 和测试文档，避免 promotion 口径漂移。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile scripts/run_phase_2_fine_rank_algorithm_batch.py tests/test_phase_2_fine_rank_algorithm_batch.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_phase_2_fine_rank_algorithm_batch.py -q` 结果 `3 passed`。

**面试可讲点：**
这次工作可以讲成“把排序实验入口和晋升边界一起收口”：不仅补了 fine_rank batch runner，还明确 learned / tree / rerank 各自只能走什么证据，防止把诊断、准备和 promotion 混写成同一种结论。

### 2026-05-09 - Phase 1.11 recall/source merge 验证收口

**任务：**
验证 Phase 1.11 在 10k `semantic_title` 数据上的 recall/source merge 改动，并把结果更新到中文优化叙事和工程日志。

**遇到的问题：**
Phase 1.11 的目标是提升 valid/test 候选池覆盖，但完整重跑后 valid/test 反而退化：`candidate_hit_rate_at_pool` 从 baseline `0.084151` 降到 `0.061711`，`candidate_hit_users` 从 60 降到 44。与此同时 LOPO 指标提升，说明这组召回/source merge 参数更适合可控内部 holdout，不代表真实 valid/test 泛化改善。

**定位方式：**
先运行 `./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py` 和 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 做代码级验证；再重跑 baseline 与 Phase 1.11 四组 demo，并读取 `outputs/hybrid_demo/hybrid_demo_small_electronics_10000_semantic_title*/metrics.json`。baseline valid/test 复现 `candidate_hit_rate_at_pool=0.084151`、`recall_at_pool=0.034086`、`candidate_hit_users=60`、`hit_rate_at_k=0.019635`；Phase 1.11 valid/test 为 `candidate_hit_rate_at_pool=0.061711`、`recall_at_pool=0.024854`、`candidate_hit_users=44`、`hit_rate_at_k=0.018233`；Phase 1.11 LOPO 为 `candidate_hit_rate_at_pool=0.941389`、`hit_rate_at_k=0.793054`、`fallback_rate=0.0`。

**解决方式：**
保留默认关闭、配置隔离的 Phase 1.11 实现和测试，但不把它作为默认策略推进；优化叙事中明确记录 valid/test gate 未通过，并把下一步收敛为 ablation：拆分 semantic IDF、popular cap、balanced source budget、ItemCF seed expansion/decay，定位是哪一路导致真实切分候选命中下降。

**验证结果：**
`tests/test_hybrid_demo.py` 结果为 `41 passed in 0.31s`，`compileall` 通过。Phase 1.11 valid/test 未达到 full target（`candidate_hit_rate_at_pool>=0.100000`、`recall_at_pool>=0.040000`、`candidate_hit_users>=66`）或 partial target（`candidate_hit_rate_at_pool>=0.092`、`recall_at_pool>=0.037`）；LOPO sanity 通过并提升，但 candidate generation p95 升到约 5 秒，说明当前 seed-aware semantic 全量扫描在 10k demo 上已有明显延迟代价。

**面试可讲点：**
这次工作可以讲成“用 gate 否决了一个看起来合理的召回增强方案”：代码测试通过、LOPO 也变好，但真实 valid/test 变差，所以不能因为局部指标好看就推进复杂策略。面试重点是实验纪律和诊断能力：把代码正确性、内部 sanity、真实泛化 gate、延迟成本分开判断，并把失败结果转化为下一轮 ablation 计划。

### 2026-05-09 - Phase 1.12 two_tower recall POC

**任务：**
在 Phase 1.11 组合召回方案未通过 valid/test gate 后，新增一路默认关闭、配置隔离的 `two_tower` U2I 召回 POC，并用 valid/test 与 LOPO 同时验证它是否值得继续推进。

**遇到的问题：**
双塔是典型 U2I 召回路线，但当前项目还不适合直接引入完整训练式双塔、ANN 服务和重依赖；同时 Phase 1.11 已证明“LOPO 变好”不能等价于真实 valid/test 泛化改善，所以新召回源必须用默认关闭 POC 和 gate 指标约束，不能直接替换推荐 backbone。

**定位方式：**
对比 `semantic_title` baseline 与 two_tower POC 的 10k 实验输出：valid/test baseline 为 `candidate_hit_rate_at_pool=0.084151`、`recall_at_pool=0.034086`、`candidate_hit_users=60`、`hit_rate_at_k=0.019635`；two_tower POC 为 `candidate_hit_rate_at_pool=0.086957`、`recall_at_pool=0.035813`、`candidate_hit_users=62`、`hit_rate_at_k=0.022440`。LOPO baseline 为 `candidate_hit_rate_at_pool=0.939219`、`hit_rate_at_k=0.755427`；two_tower POC 为 `candidate_hit_rate_at_pool=0.939942`、`hit_rate_at_k=0.757598`。

**解决方式：**
在 `rs_core/recsys/candidate_merge.py` 增加轻量 deterministic token-IDF / cosine-style `two_tower` 候选源，用商品文本构造 item tower、用最近 positive seed 聚合 user tower，并过滤 seen item；在 `rs_core/workflow/hybrid_demo.py` 增加默认关闭加载和配置摘要；新增 valid/test 与 LOPO 隔离配置，保持 LTR disabled，不污染既有 baseline。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py` 结果为 `46 passed`，`./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过。two_tower POC 在 valid/test 上小幅提升候选覆盖和 hit@5，并在 LOPO 上保持 sanity 不退化；但 `diagnostic_gate` 仍指向 `phase_1_11_recall_source_merge`，且 candidate generation p95 升到约 `1.31s`，因此只能保留为默认关闭实验源，不能宣称已经解除召回瓶颈。

**面试可讲点：**
这次工作可以讲成“在不过度工程化的前提下验证一个经典召回架构方向”：先用轻量 POC 验证双塔式 U2I 召回是否有增量，再用 valid/test、LOPO、source contribution 和 latency gate 同时约束结论。亮点不是盲目上复杂模型，而是把架构升级做成可隔离、可回滚、可量化的实验路径，并诚实记录小幅收益与未通过 gate 的边界。

### 2026-05-09 - PyTorch 双塔 10k CUDA batch 评估

**任务：**
把 DSSM-style 与 YouTubeDNN-style 双塔召回从 smoke 证据推进到同等 10k 数据规模评估，并判断是否可以从默认关闭旁路晋升。

**遇到的问题：**
初始训练环境装成了 `torch 2.11.0+cpu`，无法使用用户机器上的 GPU；切换 CUDA wheel 后又发现训练实现虽然使用 PyTorch，但仍是逐样本循环，GPU 利用率和显存占用都很低。完整 10k 结果出来后，两个双塔在 valid/test 的候选池覆盖都低于 `semantic_title` baseline。

**定位方式：**
用 `nvidia-smi` 和 `.venv` 中的 `torch.cuda.is_available()` 确认 GPU 与 CUDA wheel 状态；检查 `rs_core/recsys/two_tower.py` 发现模型和张量未显式放到 CUDA，且训练 loop 按样本逐条 forward/backward。随后用 2000 用户样本对比 batch size 128/512/1024，并读取 `outputs/training/two_tower/two_tower_training/*/train_metrics.json` 和 10k `metrics.json`。

**解决方式：**
将训练改为自动选择 CUDA device，并把 DSSM / YouTubeDNN 的 forward 改成 batch tensor 计算；训练指标记录 `batch_size`、`training_seconds`、`peak_cuda_memory_mb` 和 `batch_training=true`。batch tuning 后选择 DSSM `batch_size=512`、YouTubeDNN `batch_size=128`，并同步到 valid/test 与 LOPO 配置。一次性 tuning / smoke 目录已清理，只保留正式 10k artifact 与报告。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_two_tower_training.py tests/test_hybrid_demo.py` -> `57 passed`，`./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过。正式训练记录显示 DSSM `device=cuda`、`training_seconds=18.890`、`peak_cuda_memory_mb=26.164`，YouTubeDNN `device=cuda`、`training_seconds=19.649`、`peak_cuda_memory_mb=31.814`。10k valid/test 中，baseline `candidate_hit_rate_at_pool=0.084151`、`recall_at_pool=0.034086`、`candidate_hit_users=60`；DSSM 为 `0.071529 / 0.029375 / 51`，YouTubeDNN 为 `0.077139 / 0.031527 / 55`，均 `promotable=false`。YouTubeDNN LOPO 提升到 `candidate_hit_rate_at_pool=0.954414`、`hit@5=0.788712`，但 LOPO 只作为 sanity，不作为晋升依据。

**面试可讲点：**
这次工作体现的是实验工程纪律：先修正环境和训练效率，避免把 CPU/逐样本实现误判为模型效果；再用同等 10k 数据规模、valid/test 与 LOPO 双口径判断是否晋升。结论没有包装成“双塔有效”，而是明确指出训练式双塔在 LOPO 有能力信号，但真实 valid/test 召回覆盖下降，下一步应做 source overlap 和 candidate budget ablation，而不是继续盲目加大模型。

### 2026-05-09 - 公共安全推荐解释工具

**任务：**
为 recommendation_explain_tool 补一条工程叙事，说明解释层如何与推荐、展示和反馈边界分离。

**遇到的问题：**
旧逻辑如果直接把 `ranking`、`source`、`diagnostics`、`reward` 或训练侧字段拼成公开解释，会把内部排序依据、召回来源和评估痕迹暴露到 assistant/display 文本里；同时 `why` 请求若不携带结构化 `item_id`，很难稳定对齐最近一次推荐结果。最终补齐精确 `source` 禁词时，还发现展示 badge 中的 `multi_source` 会进入公开 payload，因此需要同步改成不暴露内部来源概念的 `blended_signal`。

**定位方式：**
对照 `rs_core/rsagent/explanation.py`、`rs_core/rsagent/dialogue.py` 和相关测试，确认解释入口已经从推荐链路里拆出来，应该只基于最新一次 display-safe 推荐商品生成公开文本，而不是回读历史 ranking 或内部诊断对象。

**解决方式：**
从最新的 display-safe 推荐商品生成确定性的中文解释，围绕当前展示 item 的 `parent_asin`、标题、类目和已知反馈约束组织文案；`why` 请求如果带 `item_id`，就结构化传入并只解释最近一次推荐列表中的对应商品，找不到时返回公共兜底文案，不去猜测内部状态。公开展示层同步把 `multi_source` badge 改为 `blended_signal`，避免前端 contract 暴露内部来源语义。

**验证结果：**
已完成的验证范围覆盖解释行为测试、`why` 带/不带 `item_id` 的对话测试、过期 item 的公开兜底、display-safe 边界检查，以及和 `/feedback` / 对话联动的回归测试。实际验证证据为 `python -m pytest tests/test_display_contract.py tests/test_agent_dialogue.py tests/test_agent_feedback.py tests/test_serving_smoke.py tests/test_simulation_runner.py tests/test_simulation_roles.py` -> `58 passed`；`python -m compileall rs_core tests scripts` -> completed successfully。

**面试可讲点：**
这次工作可以讲成“把推荐解释从内部诊断文本收敛成面向用户的 public-safe 解释层”。重点不是多暴露来源，而是让解释始终绑定最新公开商品卡和结构化反馈约束，在能说清推荐理由的同时，不泄露 `ranking`、`reward`、`training` 之类内部信息。

### 2026-05-09 - Phase 4.3 constraint_filter_tool 工程叙事

**任务：**
为 Phase 4.3 的 `constraint_filter_tool` 补一条可复述的工程叙事，说明商品级约束过滤如何接入 Agent 反馈链路并保持公开接口安全。

**遇到的问题：**
约束过滤一开始容易被误解成“再加一层排序规则”，但实际需要的是在反馈重排前先把明显冲突的候选过滤掉，否则 like/dislike/show_different 这些信号会和候选集约束互相打架，导致解释、评估和训练样本都不稳定。

**定位方式：**
对照 `rs_core/rsagent/feedback_rerank.py`、`rs_core/rsagent/policy.py` 和相关测试，确认 `constraint_filter.py` 当前主要由测试直接导入，生产路径已经在 `policy.py` 中串起；同时核对公开服务层和 simulation 侧输出，确保过滤逻辑只影响候选集，不外泄内部排序/诊断字段。

**解决方式：**
将约束过滤保持为独立、可测试的工具实现，并在 `policy.py` 的生产路径中统一调用，让它先于反馈重排生效；这样既能显式处理 hard constraints，又能保留后续 `feedback_rerank`、scorecard 和 training artifact 的一致性。当前还有一个非阻塞观察：`constraint_filter.py` 主要由测试直接导入，后续可以考虑把测试入口和生产接口合并成更清晰的单一路径。

**验证结果：**
`python -m pytest tests/test_constraint_filter_tool.py tests/test_agent_feedback.py tests/test_feedback_rerank.py tests/test_agent_reward.py tests/test_agent_eval_artifact.py tests/test_agent_scorecard.py tests/test_serving_smoke.py tests/test_display_contract.py tests/test_agent_rollout_schema.py tests/test_simulation_runner.py tests/test_simulation_roles.py` -> `73 passed`；`python -m compileall rs_core scripts tests` -> completed successfully。

**面试可讲点：**
这段工作可以讲成“把约束过滤从排序规则里拆出来，变成反馈重排前的独立安全闸门”：先保证候选集合法，再谈个性化重排和解释输出。这样做的价值是边界更清楚、测试更稳定、公开接口更安全，也更方便后续把过滤信号沉淀进评估和训练数据。

### 2026-05-09 - 10k 默认晋升硬门禁复核

**任务：**
基于已验证的 8 组 10k 实验结果，整理 valid/test 默认晋升硬门禁证据表，并更新中文优化叙事，避免把 LOPO sanity 或配置变体误写成默认提升。

**遇到的问题：**
`semantic_title`、source-aware 和 LTR 变体在指标上相对 baseline 有明显收益，但默认晋升不能只看 `candidate_hit_rate_at_pool`、`recall_at_pool` 或 `hit@5`；本轮硬门禁还要求 `metrics.latency.candidate_generation_p95_seconds <= baseline * 1.2`。同时 `semantic_title` 只是实验配置变体，不是独立 source key；`user_profile` 也不是 10k 独立召回源，不能混入召回来源叙事。

**定位方式：**
使用 worker-1 的 source 边界审计结论和 worker-2 的 8 组 verified metrics。实验统一入口为 `./.venv/Scripts/python.exe scripts/run_hybrid_demo.py --config <config>`；默认晋升只看 valid/test，LOPO 只作为 sanity / 诊断。valid/test baseline 的 `candidate_generation_p95_seconds≈0.000637s`，硬阈值约 `0.000764s`。

**解决方式：**
在 `dic/OPTIMIZATION_NARRATIVE.md` 增加“10k 默认晋升硬门禁复核”小节，分别列出 valid/test 与 LOPO 表格，并显式写清：合法 source key 只有 `popular`、`category`、`itemcf_weak`、`itemcf_strong`、`semantic`；`two_tower` POC 不纳入本次默认 gate；LOPO 不能替代 valid/test 晋升口径。

**验证结果：**
valid/test 中 baseline 为 `candidate_hit_rate_at_pool=0.032258`、`recall_at_pool=0.010322`、`hit@5=0.007013`、`candidate_hit_users=23`、`p95≈0.000637s`；`semantic_title` / source-aware / LTR 分别达到 `candidate_hit_rate_at_pool=0.084151`、`recall_at_pool=0.034086`、`candidate_hit_users=60`，但 p95 分别约 `0.402541s`、`0.400739s`、`0.388379s`，全部超过硬延迟阈值。LOPO 三个增强变体也全部超过以 LOPO baseline `p95≈0.000775s` 计算的硬延迟阈值。因此本轮结论是：不做默认晋升，只保留为召回 / 排序诊断证据。

**面试可讲点：**
这次工作体现的是 gate discipline：即使召回覆盖和 hit@5 变好，也必须同时满足泛化口径和 latency budget 才能默认晋升。LOPO 可以证明模块能力和排序诊断价值，但不能代替 valid/test；配置变体、偏好信号和真实 source key 也必须分清，避免实验叙事夸大。

### 2026-05-09 - Phase 4.4 Agent tool contract cleanup

**任务：**
收敛 Agent 工具链路的公开契约，把约束过滤、反馈重排、评分卡、训练产物和仿真评估的边界理顺，避免把内部排序、诊断和训练字段泄露到服务层或展示层。

**遇到的问题：**
Phase 4.4 之前，`constraint_filter.py` 的测试入口和 `policy.py` 的生产路径存在重复实现，事件字段形态也不完全一致；同时 reward、artifact、scorecard 各自手写 `constraint_filter_events` / `feedback_rerank_events` 聚合逻辑，后续新增工具时容易漂移。公开接口如果误混入 `ranking`、`diagnostics`、`reward`、`scorecard`、`tool_events` 等内部字段，也会破坏 display/session contract。

**定位方式：**
回看 `rs_core/rsagent/constraint_filter.py`、`rs_core/rsagent/policy.py`、`rs_core/rsagent/reward.py`、`rs_core/evaluation/agent_artifact.py`、`rs_core/evaluation/agent_scorecard.py` 和对应测试，确认真正需要修的是“工具实现入口”和“事件聚合边界”，而不是再加新的排序策略。重点检查 direct module test 与 production workflow 是否共享同一套约束过滤行为，以及公开导出是否只保留 display-safe / session-safe 字段。

**解决方式：**
将 `constraint_filter.py` 改成委托生产 `policy.constraint_filter_tool`，保留 direct import contract 但不再维护第二套过滤逻辑；新增 `rs_core/rsagent/tools.py`，集中定义工具事件 key 和 diagnostics/turn/rollout 事件收集 helper，让 reward、artifact、scorecard 复用同一套聚合逻辑；公开服务、展示、session export 和仿真输出仍只消费 display-safe 结果，不暴露内部 tool events。

**验证结果：**
`python -m pytest tests/test_constraint_filter_tool.py tests/test_agent_feedback.py tests/test_feedback_rerank.py tests/test_agent_reward.py tests/test_agent_eval_artifact.py tests/test_agent_scorecard.py tests/test_agent_rollout_schema.py tests/test_serving_smoke.py tests/test_display_contract.py tests/test_simulation_roles.py tests/test_simulation_runner.py -q && python -m compileall -q rs_core scripts` -> `75 passed`，`compileall` exit `0`。验证同时覆盖约束过滤、商品级反馈重排、训练/评估产物、公开服务 contract 和仿真链路，确认内部字段没有外泄。

**面试可讲点：**
这次工作可以讲成“把 Agent 工具链从能跑，收敛到能审计、能复用、能公开”：先把约束过滤放到反馈重排之前，确保候选合法；再把评分卡、reward 和 training artifact 留在内部；最后让服务层、解释层和仿真层都共享同一套 display-safe contract。这样既方便后续继续扩展工具，也避免训练、评估和前端看到不同版本的推荐真相。

### 2026-05-09 - 弱底座上的 Agent 机制验证

**任务：**
在当前推荐底座还不完善的情况下，不验证最终推荐效果绝对值，而是验证 Agent 工具机制、评估产物和 public/internal 边界是否可靠。

**遇到的问题：**
目标测试通过后，小规模 `run_agent_evaluation.py` 端到端 smoke 暴露出更底层的问题：即使用 electronics smoke 数据和已知存在行为序列的用户，服务层仍没有产出展示商品，导致模拟用户只能连续发 chat，`feedback_rerank` / `constraint_filter` 等工具事件无法在端到端场景中触发。因此这轮不能把 baseline/enhanced 分数当作推荐效果结论。

**定位方式：**
先运行覆盖 Agent 工具链的目标测试，得到 `83 passed`，确认 constraint filter、feedback rerank、explanation、reward/artifact/scorecard 和 public 边界的机制契约稳定；再运行 `scripts/run_agent_evaluation.py --config configs/demo/hybrid_demo/hybrid_demo_electronics.yaml --roles commuter_practical --max-turns 3 --repeats 1`，输出 artifact/scorecard/training signals，但 scorecard 显示 `recommendation_effectiveness=0.0`、`tool_event_count=0`。随后用固定用户 `AFKZENTNBQ7A7V7UXW5JJI6UGRYQ` 重跑，结果仍然没有 display items；最后直接调用 `RecommendationService.chat()` 探针，确认每轮 `candidates=0`、`ranking=0`、`final_items=0`。

**解决方式：**
本轮不强行调参或伪造推荐结果，而是把验证结论改为“机制级通过，端到端候选供给未通过”。当前可确认的是：Agent 工具和评估产物在单元/集成层稳定，evaluation runner 能产出 `agent_evaluation.json`、`scorecard.json`、`training_signals.json` 和 report；但真实端到端场景还需要先修复候选生成/对话入口，让服务层能稳定返回商品，之后再验证工具事件数量、拒绝商品复现率和 enhanced 相对 baseline 的机制收益。

**验证结果：**
`python -m pytest tests/test_constraint_filter_tool.py tests/test_agent_feedback.py tests/test_feedback_rerank.py tests/test_agent_dialogue.py tests/test_agent_reward.py tests/test_agent_eval_artifact.py tests/test_agent_scorecard.py tests/test_agent_rollout_schema.py tests/test_serving_smoke.py tests/test_display_contract.py tests/test_simulation_roles.py tests/test_simulation_runner.py -q` -> `83 passed in 1.20s`。两次 agent evaluation 均成功落盘，但 `tool_event_count=0`、`feedback_count=0`、`why_count=0`、展示 `items=[]`；直接 service 探针也确认 `candidates/ranking/final_items` 均为 0。

**面试可讲点：**
这次验证体现的是弱底座阶段的评估纪律：不因为评估脚本能跑通就宣称 Agent 效果提升，而是把结论拆成“机制契约已稳定”和“端到端候选供给仍阻塞”。这能说明项目不是盲目堆 Agent 能力，而是用测试、artifact 和 smoke run 找到下一步真正该修的瓶颈。

### 2026-05-09 - Phase 4.6 空候选恢复与 E2E 机制验证

**任务：**
在弱推荐底座上补齐空候选场景的有界恢复，先让 Agent E2E 机制验证可继续推进，而不是直接把结果解释成训练效果。

**遇到的问题：**
端到端 smoke 在弱底座上出现 `candidates=0`、`final_items=0`，模拟用户和 feedback 工具链都被卡住；如果不处理这一层，后续 `feedback_rerank`、`constraint_filter` 和展示闭环都无法触发。

**定位方式：**
沿着 `merge_for_user` 的候选合并路径排查，确认问题出在 `popular` fallback 之后仍做了严格 seen 过滤，导致热门候选也被清空；随后结合 smoke 输出核对 `tool_event_count=6`、两种变体的 `display_item_counts=[2,1,1,1]`，确认是候选供给问题而不是评估器失效。

**解决方式：**
在 `rs_core/recsys/candidate_merge.py` 增加有界 empty-pool recovery：先保留 seen 过滤的主路径，再对 `popular` fallback 做受控补回，保证弱底座至少能产出可交互的最小候选池；同时让增强 rerank 尊重 `constraint_filter_restored`，避免恢复候选后又把同一批商品误删，保持机制验证的最小闭环。

**验证结果：**
运行 `python -m pytest tests/test_simulation_roles.py tests/test_simulation_runner.py` 等 24 个 simulation 相关测试通过，`python -m compileall -q rs_core tests scripts` 通过；seeded evaluation 输出中两个变体都稳定得到 `display_item_counts=[2,1,1,1]`，`tool_event_count=6`，说明候选恢复后 Agent 交互链路重新打通。

**面试可讲点：**
这次工作可以讲成“先修复候选供给，再谈 Agent 机制验证”：我没有把空候选问题包装成训练提升，而是把它定义为评估前置条件，先用有界恢复把 E2E 机制链路打通。它 unblocks 的是 Agent E2E 机制验证，不是 SFT / RL 结果本身。

### 2026-05-10 - 前端工作台重构与 Persona Sprite 素材库

**任务：**
把 RS Agent 前端从单页商品卡 demo 扩展为 Dashboard + Tabs 工作台：Live User Demo 负责真人用户与推荐 Agent 对话、商品卡反馈和 Session Replay，Agent Sandbox 负责多角色 Persona Agent 自动交互、状态面板、timeline 和批量对比。

**遇到的问题：**
前端需要同时展示“推荐 Agent”和“多角色 Persona Agent”的关系，但不能让像素小人和沙盒 UI 反过来污染推荐决策、feedback payload、ranking、reward 或公开 display contract；同时 Codex / Gemini 调用链需要修复后才能按用户要求让 Gemini 执行前端、Codex 处理图像生成封装。

**定位方式：**
对照 `frontend/src/App.tsx`、`frontend/src/api.ts`、`frontend/src/types.ts`、`rs_core/serving/schema.py` 和 `/simulation/batch` contract，确认前端只应消费服务层与展示层字段；用 `Grep frontend/src "dicebear|ranking|reward|diagnostics|score"` 检查外部头像和内部字段泄露风险，并用 `omc ask gemini/codex` 验证外部 CLI 调用链恢复。

**解决方式：**
由 Gemini 执行前端组件拆分，新增 `frontend/src/views/LiveDemo.tsx`、`frontend/src/views/Sandbox.tsx`、商品卡 / 聊天 / replay / feedback 组件，以及 sandbox 下的 persona 状态、timeline、batch comparison 组件；手动把外部 Dicebear URL 收敛为本地 `frontend/src/assets/persona-sprites/manifest.json` 和 `PersonaSprite` 展示组件。Codex 侧新增 `scripts/generate_persona_sprites.py`，读取 manifest prompt 并通过 OpenAI Images API 兼容接口生成 PNG，默认模型为 `gpt-image-2`，支持 `--dry-run`、`--check`、`--force` 和 secret-safe 错误提示。

**验证结果：**
`npm --prefix frontend run build` 通过，Vite 生产构建完成；`./.venv/Scripts/python.exe -m py_compile scripts/generate_persona_sprites.py`、`./.venv/Scripts/python.exe scripts/generate_persona_sprites.py --help` 和 `--dry-run` 均通过，dry-run 识别 5 个 persona 输出目标；`Grep frontend/src "dicebear|ranking|reward|diagnostics|score"` 无匹配。未在本轮使用浏览器做人工视觉验收，后续如需要可启动 Vite dev server 进行交互检查；真实 PNG 生成仍需要配置 `OPENAI_API_KEY` 或兼容图片 API key。

**面试可讲点：**
这次工作可以讲成“把推荐 Agent demo 产品化成可演示工作台，同时守住 display-safe 边界”：Live Demo 面向真实用户交互闭环，Sandbox 面向多角色模拟评估，Persona Sprite 只作为展示层素材库按 `role_id` 取用，不进入推荐策略。实现上还体现了多模型协作分工：Gemini 做前端实现，Codex 做图像生成封装，我负责 contract 边界、集成修正和验证。


### 2026-05-11 - Phase 1.17 rank_weights 冻结池调权结果

**任务：**
在固定召回候选池上验证 Phase 1.17 的 rank_weights 调整是否真的带来 Top-K 排序增益，并把 promotion / no_gain 的结论写成可复述的中文证据记录。

**遇到的问题：**
这轮所有非 baseline 配置都保持了同样的候选池命中、fallback 和候选均值，说明变化只可能发生在排序层；同时并不是每个“指标变好”的配置都应该晋升，必须按 same-run baseline 判断 `hit_rate_at_k`、`ndcg_at_k` 和 `mrr_at_k`，避免把 partial 改善误写成 promotion。

**定位方式：**
以 `outputs/archive/root_files/phase_1_17_rank_weight_comparison.json`、`outputs/archive/root_files/phase_1_17_rank_weight_required_matrix.json`、`outputs/archive/root_files/phase_1_17_rank_weight_required_matrix.csv` 和 `dic/experiments/ranking/PHASE_1_17_RANK_WEIGHT_*.md` 为证据，逐项核对 same-run baseline 与各调权变体的 `candidate_hit_users`、`candidate_hit_rate_at_pool`、`recall_at_pool`、`ranked_hit_users`、`hit_rate_at_k`、`ndcg_at_k`、`mrr_at_k`、`candidate_hit_rank_p50/p90` 和 `promotion_status`。baseline 为 `candidate_hit_users=69`、`candidate_hit_rate_at_pool=0.096774`、`recall_at_pool=0.040439`、`fallback_rate=0.0`、`candidate_count_avg=97.936752`、`hit_rate_at_k=0.019635`、`ndcg_at_k=0.005876`、`mrr_at_k=0.012202`、`rank p50=18`、`rank p90=55`。

**解决方式：**
按决策矩阵把结果分成三类：`popular_0_8`、`popular_0_9`、`semantic_1_3` 归入 PROMOTION；`semantic_1_0`、`semantic_1_1`、`popular_1_1`、`two_tower_1_0`、`two_tower_1_1`、`two_tower_1_3` 归入 NO_GAIN；没有 PARTIAL_DIAGNOSTIC。这样可以把真正有 Top-K 增益的轻量调权和无收益调权分开，避免后续阶段误继承错误配置。

**验证结果：**
本轮比较矩阵显示所有非 baseline 配置都与 baseline 保持相同的候选池统计，没有 INVALID；`popular_0_8` 的 `hit_rate_at_k=0.025245`，较 baseline 提升 `+0.005610`，同时 `ndcg_at_k` 提升 `+0.001587`、`mrr_at_k` 提升 `+0.001566`，是最强候选；`popular_0_9` 和 `semantic_1_3` 也达到 PROMOTION，但提升幅度更小；其余配置未超过 same-run baseline，不应晋升。

**面试可讲点：**
这轮最重要的不是“又调高了一个分数”，而是建立了固定候选池上的调权裁决纪律：先证明候选池稳定，再用 same-run baseline 判断是否晋升。`popular_0_8` 说明在当前阶段，适度下调 popular 权重比继续放大 semantic 或 two_tower 更有效；这类结论比单纯报一个更高的 hit@k 更适合拿到面试里解释“为什么这样做”。

### 2026-05-10 - Phase 1.13 YouTubeDNN 召回主路与排序承接复核

**任务：**
验证 `semantic_title + YouTubeDNN` 在 10k valid/test 下是否可以进入召回主路，并区分候选池覆盖与最终 Top-K 排序承接。

**遇到的问题：**
初始结论把“Top-K 未达标”误写成“two_tower 不应进入主路”。这混淆了召回层和排序层：YouTubeDNN 的职责是把目标商品召回进候选池，Top-K 则应由后续排序完成。

**定位方式：**
对照 pool100 验收口径复跑 Phase 1.13 valid/test，并读取 `metrics.json`。pool50 配置会导致候选池指标先天偏低，因此修正为 pool100 后重新比较 `candidate_hit_rate_at_pool`、`candidate_hit_users` 与 `hit_rate_at_k`。

**解决方式：**
保留 YouTubeDNN 作为召回主路候选源；同时把 `source_aware_fusion`、`item_feature_rerank` 和旧 LTR 的结论限定为“排序承接未通过”，不再用排序失败否定召回效果。Phase 1.13 隔离配置继续保留，后续排序阶段基于固定召回池另行优化。

**验证结果：**
pool100 valid/test 候选池达标：`candidate_hit_rate_at_pool=0.105189`、`recall_at_pool=0.042043`、`candidate_hit_users=75`、`fallback_rate=0.0`。排序承接未达标：pool100 rerank `hit_rate_at_k=0.015428`，very conservative `hit_rate_at_k=0.016830`，均低于 `0.019635`。candidate generation p95 约 `0.41s`，说明召回主路落地还需要检索性能优化。

**面试可讲点：**
这次复核体现的是推荐系统分层诊断：召回层看 candidate pool hit，排序层看 Top-K hit，系统层看 latency。YouTubeDNN 能进入召回主路，但排序模型需要后续独立训练和验证；不能因为 Top-K 暂时没提升，就否定召回源对候选覆盖的贡献。

### 2026-05-11 - Phase 1.14 ranking v2 / LTR v2 固定召回池验证

**任务：**
在固定 `semantic_title + YouTubeDNN pool100` 召回池上验证 ranking v2 / LTR v2，判断它是否能把已经进入候选池的命中商品推入 Top-K。

**遇到的问题：**
valid/test 候选池覆盖达到验收线，但 Top-K 排序没有承接住新增候选；同时 LOPO sanity 指标较好，容易被误写成晋升依据，需要明确 LOPO 只作 sanity。

**定位方式：**
先运行 `./.venv/Scripts/python.exe -m pytest tests/test_ltr.py tests/test_hybrid_demo.py -q` 与 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts`，再用 `scripts/train_ltr_ranker.py` 训练 valid/test 与 LOPO 各自独立的 LTR v2 artifact，最后运行两个 Phase 1.14 full demo 并读取 `metrics.json`。

**解决方式：**
保留 `semantic_title + YouTubeDNN pool100` 作为召回池口径；对 valid/test 与 LOPO 分别使用独立训练输出目录，避免覆盖旧产物或混用模型。文档结论按 valid/test 晋升口径书写，不用 LOPO 包装成功。

**验证结果：**
测试通过：`65 passed in 0.24s`，`compileall` 通过。valid/test 指标为 `candidate_hit_rate_at_pool=0.105189`、`recall_at_pool=0.042043`、`candidate_hit_users=75`、`hit_rate_at_k=0.001403`、`fallback_rate=0.0`、`candidate_generation_p95_seconds=0.472091`、`ranking_p95_seconds=0.002814`；其中候选池达标，但 `hit_rate_at_k` 低于 baseline `0.019635` 和目标 `0.023843`，ranking v2 / LTR v2 未通过。LOPO sanity 为 `candidate_hit_rate_at_pool=0.956585`、`hit_rate_at_k=0.811143`、`candidate_hit_users=1322`，只能说明同分布 sanity 通过，不能作为晋升依据。

**面试可讲点：**
这次验证体现的是排序阶段的评估纪律：固定召回池后，只看排序是否把命中候选推入 Top-K。结果证明 ranking v2 / LTR v2 反而把 valid/test 命中候选压低，说明下一步应检查训练样本和 label 口径，而不是用 LOPO 高分掩盖泛化失败。

### 2026-05-11 - Phase 1.15 冻结 YouTubeDNN pool100 与隔离 ablation

**任务：**
冻结 `semantic_title + YouTubeDNN pool100` 召回基线，补齐隔离的 gate / config / test 覆盖，并根据 verify-worker 的 #3 / #5 / #7 结果更新 Phase 1.15 叙事。

**遇到的问题：**
frozen 基线本身已经能跑通，容易把“能跑完”误写成“默认晋升”；semantic IDF 版本在 `rs_core/recsys/candidate_merge.py` 里先出现过 hang，修复后虽然能跑完，但 valid/test 命中和 latency 都没有过门禁。如果把 ablation 结果混进 final，会把诊断实验误当成主路方案。

**定位方式：**
把 `PHASE_1_15_FROZEN_YOUTUBEDNN_POOL100.md`、`PHASE_1_15_VALID_FINAL_CANDIDATE.md`、`PHASE_1_15_LOPO_SANITY.md` 和 `PHASE_1_15_ABLATION_SEMANTIC_IDF_BUDGET.md` 放在同一口径下对比，只看 `candidate_hit_rate_at_pool`、`hit_rate_at_k`、`candidate_generation_p95_seconds` 和 `ranking_p95_seconds`，并固定 `candidate_pool_size=100`、`top_k=5`、`YouTubeDNN pool100` 不变。

**解决方式：**
把 `YouTubeDNN pool100` 固定为 Phase 1.15 的 recall baseline，只允许 isolated gate / config / test 继续做对照；semantic IDF hang 修复后，ablation 仍只保留为诊断证据，不进入 final。

**验证结果：**
frozen baseline valid/test 为 `candidate_hit_rate_at_pool=0.106592`、`hit_rate_at_k=0.019635`、`candidate_generation_p95_seconds=0.461527s`；final valid/test candidate 仍是 `0.106592 / 0.019635`，`candidate_generation_p95_seconds=0.485096s`，没有比 frozen 带来同跑增益。LOPO sanity 为 `candidate_hit_rate_at_pool=0.959479`、`hit_rate_at_k=0.798119`、`candidate_generation_p95_seconds=0.39457s`，只能证明同分布 sanity 通过。semantic IDF ablation 为 `candidate_hit_rate_at_pool=0.100982`、`hit_rate_at_k=0.00561`、`candidate_generation_p95_seconds=0.777899s`、`ranking_p95_seconds=0.000721s`，没有超过 frozen，也没有过 latency gate。

**面试可讲点：**
这轮可以讲成“先冻结能站得住的 baseline，再用隔离 ablation 证明哪些变体不该进主线”。它的价值不是再造一个高分配置，而是把默认晋升的证据边界收紧，避免把 LOPO 或局部优化误写成主路收益。

### 2026-05-11 - Phase 1.16 item_graph recall 生成与接入验证

**任务：**
在 Phase 1.15 冻结基线之后，引入并验证 `item_graph` 召回路径，确认它是否真的能带来新的 valid/test 候选，而不是重复现有 recall 覆盖。

**遇到的问题：**
`item_graph` 虽然能够生成并接入 views，但很容易和已有 recall source 高重叠；如果只看 LOPO，会把同分布上的高分误写成晋升证据。

**定位方式：**
同时对照 frozen baseline、item_graph 接入后结果和 LOPO sanity，只看 `candidate_hit_rate_at_pool`、`recall_at_pool`、`hit_rate_at_k`、`candidate_generation_p95_seconds`、`fallback_rate` 以及 item_graph diagnostics，确保 valid/test 才是默认晋升口径。

**解决方式：**
生成 `item_graph_recall.jsonl` 并接入 views 重建流程，保留 frozen baseline 对照；用 item_graph diagnostics 检查 seed 命中、raw candidate/unseen 规模和 source coverage，但不把强 LOPO sanity 误写成默认晋升。

**验证结果：**
`./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_simulation_runner.py tests/test_ltr.py -q` 通过，61 项测试全部通过。frozen baseline 与 item_graph 接入后的 valid/test 指标完全持平：`candidate_hit_users=76`、`candidate_hit_rate_at_pool=0.106592`、`recall_at_pool=0.042219`、`hit_rate_at_k=0.019635`，但 `candidate_generation_p95_seconds` 从 `0.461527` 降到 `0.411992`。item_graph diagnostics 显示 `users_with_item_graph_seed_hits=1514`、`raw_candidates=55776`、`raw_unseen=22286`、`candidate_hit_source_coverage.item_graph=1`。LOPO sanity 为 `candidate_hit_rate_at_pool=0.970333`、`hit_rate_at_k=0.813314`、`item_graph candidate hits=1341`，只能作为同分布诊断证据。

**面试可讲点：**
这轮可以讲成“新增召回源不等于默认晋升”。我先把 item_graph 的生成、接入和诊断链路做实，再用 valid/test 与 LOPO 分开裁决：工程链路是通的，但主口径没有增益，所以结论必须是 fail/no promotion。

### 2026-05-11 - Phase 1.18 two_tower_seed item-neighbor 召回旁路验证

**任务：**
在冻结的 `semantic_title + YouTubeDNN pool100` 召回主路之外，新增默认关闭的 `two_tower_seed` I2I 召回旁路，验证已有 YouTubeDNN item embedding 的离线 nearest-neighbor sidecar 是否能带来新的 valid/test 候选覆盖。

**遇到的问题：**
初始实现中 builder 输出 `{item_id, neighbors}`，但 runtime loader 仍按旧 `src_item/dst_item/score` schema 读取；同时 sidecar 输出路径如果和 embedding 输入路径或 manifest 路径重合，会误删或覆盖 artifact。实验层面，LOPO sanity 对该旁路有明显贡献，但默认晋升必须看 same-run valid/test，而不能用 LOPO 高分包装成功。

**定位方式：**
检查 `rs_core/workflow/two_tower_training.py`、`scripts/build_two_tower_neighbors.py`、`rs_core/recsys/candidate_merge.py` 和 `tests/test_hybrid_demo.py`，确认 sidecar schema 不一致；随后用独立 code-reviewer 复核 Phase 1.18 改动，发现 sidecar path distinctness 风险。最终通过 `outputs/recall/phase_1_18_two_tower_seed_gate/comparison.json` 对照 frozen baseline、Phase 1.18 valid/test 和 LOPO sanity。

**解决方式：**
将 runtime loader 改为解析 `{item_id, neighbors:[{item_id, score, rank}]}`，并在 `fail_on_missing_sidecar=true` 时校验 manifest 的 `phase/source/schema_version`；为 sidecar builder 增加输入、sidecar、manifest 三个路径必须互异的 fail-closed 校验；新增 Phase 1.18 valid/test 与 LOPO 隔离配置，保持排序增强全部 disabled；新增 `scripts/run_phase_1_18_recall_gate.py` 生成 same-run gate artifact。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_two_tower_training.py tests/test_hybrid_demo.py tests/test_build_recall_views.py` 通过，75 项测试全部通过；`compileall` 针对更新脚本和模块通过。完整 gate 命令 `./.venv/Scripts/python.exe scripts/run_phase_1_18_recall_gate.py --skip-sidecar-build --output outputs/recall/phase_1_18_two_tower_seed_gate/comparison.json` 写出 comparison JSON 并因 gate 未通过返回 exit 1。same-run frozen baseline 为 `candidate_hit_users=76`、`candidate_hit_rate_at_pool=0.106592`、`recall_at_pool=0.042219`、`fallback_rate=0.0`、`candidate_generation_p95_seconds=0.427404`；Phase 1.18 为 `75 / 0.105189 / 0.041066 / 0.0 / 0.452250`，且 `candidate_hit_source_coverage.two_tower_seed=8`。LOPO sanity 为 `candidate_hit_rate_at_pool=0.957308`、`hit_rate_at_k=0.796671`、`two_tower_seed candidate hits=184`，只能作为 sanity。

**面试可讲点：**
这次工作体现的是召回实验的工程化和否决纪律：我把双塔 item embedding 扩展为可离线构建、可 manifest 校验、可默认关闭接入的 I2I 旁路，但最终没有因为它有真实 source contribution 或 LOPO 高分就晋升。valid/test 候选池覆盖下降说明它和现有主路的组合方式仍不泛化，因此结论必须是 `FAIL / no promotion`，保留为负向实验和后续 budget/overlap 分析依据。

### 2026-05-12 - Phase 1.18 决策复核：popular=0.8 保持不晋升

**任务：**
复核 Phase 1.18 的 second-order rank-weight 组合结论，确认是否存在可晋升到主路的权重配置，并基于失败归因判断下一阶段该往哪条线推进。

**遇到的问题：**
没有任何 second-order rank-weight 组合在 `hit_rate_at_k` 上超过 `popular=0.8`；失败主要集中在候选 miss，而不是排序细节，说明继续细调权重的边际收益很低。

**定位方式：**
复核决策审查结果与失败归因统计，重点看 `hit_rate_at_k` 对照和 candidate miss / rank miss 的占比，确认问题是否来自排序还是召回覆盖。

**解决方式：**
维持 `popular=0.8` 作为当前排序基线，不晋升 second-order rank-weight 组合；将后续探索方向切换到 recall/source coverage，而不是继续堆排序权重。

**验证结果：**
决策结论为 `NO_PROMOTION_KEEP_POPULAR_0_8`。failure attribution 显示 `candidate miss = 644/713 (90.3226%)`，说明瓶颈主要在候选覆盖；当前阶段没有证据支持继续推进 second-order rank-weight 组合晋升。

**面试可讲点：**
这一步能讲成“先用指标复核锁定最稳基线，再用失败归因判断下一步该加权还是补召回”。最终没有把局部排序优化当成主线，而是把资源转向 recall/source coverage，这样更符合收益来源。

### 2026-05-11 - Phase 1.19 DeepWalk graph_walk_seed 结构召回旁路验证

**任务：**
在冻结的 `semantic_title + YouTubeDNN pool100` 召回主路之外，新增默认关闭的 `graph_walk_seed` 结构召回旁路，用 DeepWalk-style 图游走从正反馈序列中学习 item embedding，并通过 same-run gate 判断是否能带来新的 valid/test 候选覆盖。

**遇到的问题：**
新 source 必须和已有 `item_graph` 保持 source identity 隔离；训练产物不能只是临时 sidecar，需要 manifest/hash/device 等可复现证据；smoke gate 返回 exit 1 时需要区分“门禁未通过”和“脚本崩溃”。

**定位方式：**
复核 `rs_core/workflow/graph_walk_training.py`、`rs_core/recsys/candidate_merge.py`、`rs_core/workflow/hybrid_demo.py` 和 `scripts/run_phase_1_19_graph_walk_seed_gate.py`，确认训练、manifest 校验、runtime opt-in 和 gate 检查边界；读取 `outputs/recall/phase_1_19_graph_walk_seed_gate_smoke_verifier/comparison.json` 对照 baseline、experiment、source-only 和 without_graph_walk 指标。

**解决方式：**
保留 `graph_walk_seed_enabled=false` 默认关闭，由 gate 通过 overrides 启用实验；manifest 校验 `phase/source/schema_version/algorithm/sidecar_hash`，runtime 维持 `graph_walk_seed` 独立 source label、seen filtering、recency decay、score floor 与 per-user cap；gate 同时检查 default-off baseline 一致性、source identity、预算、延迟和 candidate/recall lift。

**验证结果：**
`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_graph_walk_seed.py tests/test_hybrid_demo.py` 通过，69 项测试全部通过。full gate 命令 `./.venv/Scripts/python.exe scripts/run_phase_1_19_graph_walk_seed_gate.py --output outputs/recall/phase_1_19_graph_walk_seed_gate/comparison.json` 写出 comparison JSON，并因 promotion checks failed 返回 exit 1。same-run full gate 中 baseline 为 `candidate_hit_users=69`、`candidate_hit_rate_at_pool=0.096774`、`recall_at_pool=0.040439`、`candidate_generation_p95_seconds=0.49439`；default-off disabled 与 baseline 完全一致；experiment 为 `candidate_hit_users=69`、`candidate_hit_rate_at_pool=0.096774`、`recall_at_pool=0.039079`、`candidate_generation_p95_seconds=0.623431`，有 `candidate_hit_source_coverage.graph_walk_seed=2`、`recall_source_coverage.graph_walk_seed=22377`、`users_with_graph_walk_seed_hits=1530`、`graph_walk_seed_raw_candidates=1072400`、`graph_walk_seed_raw_unseen_candidates=986695`、`candidate_share=0.076823`、`max_candidates_per_user_observed=15`。gate 结果为 `passed=false`，失败项包括 `candidate_hit_users_lift=false`、`candidate_hit_rate_at_pool_lift=false`、`recall_at_pool_lift=false`、`candidate_generation_p95_budget=false`、`lopo_candidate_generation_p95_budget=false`；同时 `graph_walk_seed_hit_contribution=true`、`default_off_matches_baseline=true`、`source_identity_not_mixed_with_item_graph=true`、`source_cap_not_exceeded=true`。manifest 显示 full training 使用 `device=cuda`，`item_count=9174`、`edge_count=9442`、`walk_count=91740`、`positive_pair_count=15595800`。

**面试可讲点：**
这轮可以讲成“图游走召回旁路的工程化和否决纪律”：我不仅实现了 DeepWalk-style 训练和可校验 artifact，还用 same-run gate 证明它虽然能产生大量结构候选，但没有带来真实候选命中或 recall lift，所以明确记录为 `FAIL / no promotion`，不把工程可用误写成主路晋升。

### 2026-05-11 - 横向收口：仿真前后端契约对齐

**任务：**
在不接管 agent、前端、传统推荐底座主体实现的前提下，做一次跨 `serving`、`display`、`simulation`、前端类型和关键测试的横向收口。

### 2026-05-11 - Phase 1.20 fallback limit500 诊断核验

**任务：**
在 full run 过慢的前提下，先用 `--limit-users 500` 跑通 recall diagnostics fallback 核验，确认产物只作为诊断证据，不当作 full-run 晋升结果。

**遇到的问题：**
full run 时间成本高；same-run 分母容易漂移；必须保证 frozen / Phase 1.17 tracked diff 检查不被诊断脚本污染。

**定位方式：**
运行 `scripts/run_phase_1_20_recall_diagnostics.py --limit-users 500`，检查 `outputs/recall/phase_1_20_recall_diagnostics_large_limit500/`、manifest `run_id=756ade477bdf7c45`、`evaluation_mode=valid_test`、分母字段和保护检查输出；核对 CSV/JSON parity、required files、raw oracle stages 与专项测试结果。

**解决方式：**
将本轮固定为 fallback limit500 口径，显式保留 `hit_rate_denominator=users_with_holdout`、`users_with_holdout=138`、`limit_users=500` 的同口径对照，并把 frozen / Phase 1.17 diff clean 作为保护门禁。

**验证结果：**
`./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_20_recall_diagnostics.py tests/test_hybrid_demo.py tests/test_ltr.py` 通过，合计 `79 passed`。`outputs/recall/phase_1_20_recall_diagnostics_large_limit500/` 产出了 limit500 artifact，baseline hash `afa923fb623402a51f17157565e204d1954fdd93814d102cf8c96e5c7a8ddff5`，CSV/JSON parity 与保护性 diff 检查 clean。

**面试可讲点：**
这轮可以讲成“把诊断本身也做成可审计门禁”：不追求一次性全量跑完，而是先用有限 fallback + 分母一致性 + 冻结产物保护，确认诊断链路可靠再谈下一步。

**遇到的问题：**
后端 `SimulationSceneRequest` / `SimulationBatchRequest` 将 `max_turns` 限制为 1-8，但前端沙盒输入仍允许 10；同时 batch scene 会携带 `metrics`，前端 `SimulationSceneResponse` 类型没有显式表达该字段，容易在后续 batch comparison 扩展时产生隐性契约漂移。

**定位方式：**
对照 `rs_core/serving/schema.py`、`rs_core/simulation/runner.py`、`frontend/src/types.ts`、`frontend/src/components/sandbox/*` 和 `tests/test_simulation_runner.py`，确认公开 display contract、session export、simulation scene / batch 主链路基本一致，缺口集中在前端输入边界和 TypeScript 类型表达。

**解决方式：**
在 `frontend/src/types.ts` 补充 `SimulationSceneMetrics` 并让 `SimulationSceneResponse.metrics` 可选，兼容单 scene 与 batch scene；把 `PersonaStatePanel` 和 `BatchSimulationPanel` 的 `max_turns` 输入上限从 10 收敛到 8，与服务端 Pydantic contract 对齐。

**验证结果：**
`npm --prefix frontend run lint` 通过；`.venv/Scripts/python.exe -m pytest tests/test_simulation_runner.py tests/test_serving_smoke.py tests/test_display_contract.py` 通过，29 项关键契约 / serving / display / simulation 测试全部通过。

**面试可讲点：**
这次工作可以讲成“多窗口并行开发后的 contract gate”：不重写任何一个模块，而是用 schema、前端类型和回归测试把 agent 交互、服务层、展示层、仿真评估串成可验证边界，防止局部功能能跑但端到端契约慢慢漂移。

### 2026-05-12 - Phase 1.17b popular=0.8 稳定性复核

**任务：**
在 frozen-pool ranking 上复核 popular=0.8 是否能稳定晋升，并对比 0.75/0.85 邻近权重。

**遇到的问题：**
单次 Phase 1.17 smoke 只能说明局部 promotion candidate，不能直接作为默认基线；还需要确认候选池稳定，且收益来自排序而不是召回。

**定位方式：**
对照 `outputs/archive/root_files/phase_1_17b_rank_weight_comparison.json` 和 `outputs/archive/root_files/phase_1_17b_popular_0_8_case_effects.json`，核对 same-run baseline、popular=0.8 和邻近 0.75/0.85 的候选池统计、Top-K 指标和 case-level 命中变化。

**解决方式：**
把 `popular=0.8` 定位为新的 frozen-pool ranking baseline，同时保留 `popular=0.75/0.85` 作为稳定性参考，不再扩大搜索到召回或全链路泛化。

**验证结果：**
same-run baseline 与 `popular=0.8` 的 candidate-hit / recall / fallback / candidate_count 完全一致，但 `hit_rate_at_k` 从 `0.019635` 提升到 `0.025245`，`ndcg_at_k` 从 `0.005876` 提升到 `0.007463`，`mrr_at_k` 从 `0.012202` 提升到 `0.013768`；`popular=0.75` 和 `0.85` 也均高于 baseline。case-level 结果显示 5 个 shared target 进入 Top-K，退出 Top-K 为 0，rank 改善 49 个、恶化 4 个。

**面试可讲点：**
这次可以讲成“固定候选池后做权重稳定性门禁”：先证明池没变，再证明邻近权重也同向，最后把结论限制在 frozen-pool ranking，不把排序增益误写成召回收益。

### 2026-05-12 - Phase 1.21 recall coverage 扩展与诊断收口

**任务：**
在冻结 baseline 之外实现 Phase 1.21 召回覆盖诊断：新增默认关闭的 semantic title/category、co-visit fallback repair、category long-tail 和 metadata neighbor source，跑通 same-holdout baseline/audit/pool-curve，并记录 ablation 的真实状态。

**遇到的问题：**
并行实现时出现过重复函数定义和 source config 覆盖风险；co-visit 噪声过滤最初会误删高频 seed；完整 ablation matrix 在 `limit_users=500` 下仍超时，不能把单 source 结论包装成晋升证据。

**定位方式：**
对照 `scripts/phase_1_21_recall_coverage_experiments.py`、`tests/test_phase_1_21_recall_coverage.py` 和 `outputs/recall/phase_1_21_recall_coverage/*/manifest.json`，核验 `evaluation_mode=valid_test`、`users_with_holdout=138`、`limit_users=500`、同一 `holdout_user_ids_hash=927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2`，并检查 ranking/rerank disabled 与 no-leakage contract。

**解决方式：**
统一 Phase 1.21 source config 装配路径，修正 co-visit 为“允许高频 seed、过滤高频 neighbor”，补齐 source/metrics schema gate 和专项测试；对 ablation 超时不做伪成功处理，而是写入 `outputs/recall/phase_1_21_recall_coverage/ablations/manifest.json`，显式标记 `status=inconclusive_timeout`。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_20_recall_diagnostics.py tests/test_phase_1_21_recall_coverage.py` 通过，合计 `19 passed`；Phase 1.21 专项 `18 passed`。pool-curve 在同一 holdout hash 下完成，pool100 `candidate_hit_users=14`、`candidate_hit_rate_at_pool=0.101449`、`recall_at_pool=0.061312`，pool200 `candidate_hit_users=19`、`candidate_hit_rate_at_pool=0.137681`、`recall_at_pool=0.069710`，`candidate_hit_users_delta=+5`、`candidate_hit_rate_at_pool_delta=+0.036232`。按召回侧指标，pool200 晋升为 recall-side experimental baseline；ablation manifest 明确为 timeout inconclusive，不能晋升单 source，排序 / Top-K 不纳入本窗口结论。

**面试可讲点：**
这次可以讲成“召回侧实验的证据纪律”：用固定分母、同一 holdout hash、no-leakage contract 和 ranking disabled gate 保证诊断可信；pool200 带来 +5 个候选命中用户，因此晋升为召回侧 experimental baseline，但由于 ablation 未完成，不把任何单一 source 包装成晋升，也不把排序 / Top-K 结果混入召回窗口结论。



### 2026-05-12 - Phase 1.22 pool200 source attribution 与 keep/prune 复核

**任务：**
复核 Phase 1.22 的 pool200 recall 源，并同步工程叙事。

**遇到的问题：**
本轮是 recall-only；ablation 只到 partial_time_limited，leave-one-source-out 全是 inconclusive_not_rerun；miss_targets / holdout targets 只能用于 diagnostics / evaluation。

**定位方式：**
对照 contract.json、source_attribution_report.json、pool200_ablation_summary.csv、source_keep_prune_decisions.csv，核对 fixed contract、holdout hash、pool100 / pool200 命中差异和 source 归因。

**解决方式：**
keep semantic_title_category_expansion / popular / semantic；reserve 其余召回源；仅 prune metadata_neighbor_recall。对 5 个 pool200-only 新命中采用 non-exclusive attribution，不把单源归因误读成唯一贡献。

**验证结果：**
source_attribution_report.json 中 all-hit attribution 为 semantic_title_category_expansion=9、semantic=9、popular=6、category=2、category_long_tail_recall=2、two_tower=2、co_visit_fallback_repair=1、itemcf_strong=1、itemcf_weak=1；新增 5 个命中里 popular=3、semantic_title_category_expansion=3。pool200_ablation_summary.csv 的非 baseline 行均为 inconclusive_not_rerun。

**面试可讲点：**
先把证据边界定死，再做源治理：合同、holdout hash、分母和 no-leakage 先锁住，再用可验证的归因和裁决表做 keep / reserve / prune。

### 2026-05-12 - Phase 1.22 pool200 æŽ’åº�å¤�æ ¸ï¼šå€™é€‰æ± æ¼‚ç§»å¯¼è‡´ INVALID

**ä»»åŠ¡ï¼š**
åœ¨å·²æ™‹å�‡çš„ pool200 å�¬å›žåŸºçº¿ä¸Šï¼Œå�ªéªŒè¯�æŽ’åº�ä¾§ `ranking_v2`ã€�`source_aware_fusion`ã€�`item_feature_rerank`ï¼Œåˆ¤æ–­æ˜¯å�¦èƒ½æŠŠå€™é€‰æ± å†…å‘½ä¸­æŽ¨è¿› Top-Kã€‚

**é�‡åˆ°çš„é—®é¢˜ï¼š**
Promoted baseline ç›®å½•å�ªæœ‰ metrics / manifest / diagnostic CSVï¼Œæ²¡æœ‰ per-user `recommendations.jsonl`ã€�`candidates.jsonl` æˆ– `ranking_hit_cases.jsonl`ï¼Œå› æ­¤æ— æ³•ç›´æŽ¥å¤�ç”¨å†»ç»“å€™é€‰æ–‡ä»¶å�šçº¯ rerankã€‚å�Žç»­ deterministic rerun å�ˆå‡ºçŽ°å€™é€‰æ± å†»ç»“å­—æ®µæ¼‚ç§»ï¼š`19/0.137681/157.112` å�˜ä¸º `17/0.123188/152.272`ã€‚

**å®šä½�æ–¹å¼�ï¼š**
å…ˆå�š baseline freeze auditï¼Œå†�è®© isolated configs é€šè¿‡éš”ç¦»éªŒè¯�ï¼šä¸‰ä»½ Phase 1.22 é…�ç½®å�ªä¿�ç•™å�•ä¸€ ranking policy å·®å¼‚ï¼Œ`candidate_pool_size=200`ï¼Œå¹¶ç§»é™¤é¢�å¤– `rank_weights`ã€‚éš�å�Žè¯»å�– `outputs/archive/root_files/pool200_ranking_optimization_comparison.json`ã€�å�„å�˜ä½“ `metrics.json` ä¸Ž `ranking_hit_cases.jsonl`ï¼Œå¯¹æ¯” promoted baseline çš„ freeze gates ä¸Ž Top-K æŒ‡æ ‡ã€‚

**è§£å†³æ–¹å¼�ï¼š**
æ²¡æœ‰æŠŠ `mrr_at_k` çš„è½»å¾®ä¸Šå�‡åŒ…è£…æˆ� partialï¼›æŒ‰é¢„å…ˆ gate è§„åˆ™æŠŠå€™é€‰æ± æ¼‚ç§»åˆ¤ä¸º `INVALID`ã€‚æœ€ç»ˆå†³ç­–æ˜¯ä¸�æ™‹å�‡ä¸‰ç§�æŽ’åº�æ–¹æ³•ï¼Œä¿�ç•™ promoted pool200 baselineã€‚

**éªŒè¯�ç»“æžœï¼š**
ä¸‰ç»„å�˜ä½“å�‡ä¸º `hit_rate_at_k=0.014493`ã€�`ndcg_at_k=0.002779`ã€�`mrr_at_k=0.006039`ï¼Œç›¸å¯¹ baseline `hit_rate_at_k=0.021739`ã€�`ndcg_at_k=0.004983` æ²¡æœ‰æœ‰æ•ˆæ��å�‡ã€‚case attribution æ˜¾ç¤ºæ¼‚ç§»æ± å†…ä¸‰ç»„æ–¹æ³• Top-K å‘½ä¸­é›†å�ˆç›¸å�Œï¼Œå�ªæœ‰ 2 ä¸ª Top-K hitsï¼Œæ²¡æœ‰ entered Top-K targetã€‚é…�ç½®éªŒè¯�ä¾§é€šè¿‡ `.venv` compileall å’Œç›¸å…³ pytestã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™æ®µå·¥ä½œä½“çŽ°çš„æ˜¯æŽ’åº�å®žéªŒçš„è¯„ä¼°çºªå¾‹ï¼šæŽ’åº�æ–¹æ³•èƒ½è·‘é€šä¸�ç­‰äºŽå�¯æ™‹å�‡ï¼Œå¿…é¡»å…ˆè¯�æ˜Žå€™é€‰æ± ç¨³å®šæˆ–æœ‰ same-run baselineã€‚å�‘çŽ°å€™é€‰æ± æ¼‚ç§»å�Žï¼Œä¸»åŠ¨æŠŠç»“è®ºé™�çº§ä¸º `INVALID`ï¼Œå¹¶æ˜Žç¡®ä¸‹ä¸€æ­¥è¦�å…ˆè¡¥ per-user frozen candidate export æˆ– same-run no-rerank baselineï¼Œç­‰éš”ç¦»é—®é¢˜ä¿®å¤�å�Žå†�è€ƒè™‘ LTRã€‚

### 2026-05-13 - Phase D semantic/title-category promotion candidate 收口

**任务：**
继续长期召回执行，把 Phase 1.21 的 family-specific observation、frozen candidates 和 dedicated ablation evidence 收口成可审查的 promotion candidate。

**遇到的问题：**
初始 ablation 结果四个实验行完全一致，暴露出 source-family 开关污染：baseline_only 继承了实验配置里已经启用的 semantic/co-visit/long-tail source，不能用于单 source 归因。

**定位方式：**
核对 `outputs/recall/phase_1_21_recall_coverage/ablations/itemcf_covisit_semantic_pool200/summary_metrics.csv`、`dedicated_ablation_evidence_manifest.json` 和 `frozen_promotion_evidence_checklist.json`；重点检查同一 holdout hash 下 baseline_only 与各 patch 的 `candidate_hit_users`、`exclusive_hit_users`、fallback、latency 和 required artifacts。

**解决方式：**
修正 ablation base config，去掉所有 source-family 开关后再逐个 patch 启用待测 source；重新生成 summary、exclusive hits、overlap、latency、fallback 和 frozen promotion checklist。随后新增 `.omc/recall/artifacts/phase_1_21_semantic_title_category_promotion_candidate/{manifest,metrics,signature}.yaml`，并把 registry schema/registry 同步到 `PROMOTION_CANDIDATE` 状态。独立 verifier 批准后，再新增 `.omc/recall/artifacts/phase_1_21_semantic_title_category_baseline_vnext/{manifest,metrics,signature}.yaml` 和 `PASS_PROMOTE_DEFAULT` registry row。

**验证结果：**
修正后 baseline_only 为 17 个 candidate-hit users；semantic/title-category 为 19 个，带来 +2 个额外 candidate-hit users；co-visit fallback 与 category long-tail 均无候选命中增量。`frozen_promotion_evidence_checklist.json` 为 `READY_FOR_PROMOTION_REVIEW`，独立 verifier 给出 APPROVE；`./.venv/Scripts/python.exe scripts/validate_recall_registry.py` 通过并识别 3 条记录。当前默认晋升只覆盖 semantic/title-category，回滚基线为 `phase_1_25_pool200_frozen_baseline`。

**面试可讲点：**
这次工作体现了召回实验的证据治理能力：不仅跑实验，还能发现消融污染、修正实验设计、用 frozen candidates 和 registry 固化证据边界，并在 verifier 批准后把单一有效 source 晋升为可回滚的 baseline_vNext。

### 2026-05-12 - Phase 1.23 sample-size LOPO 叙事补充

**任务：**
补写 Phase 1.23 的 sample-size sensitivity 中文叙事，明确它只是在 LOPO 内部做 recall-only sanity，不把结果误写成 valid_test 晋升证据。

**问题：**
100 / 1000 / 10000 三档样本下的 LOPO pool200 召回都很高，容易被误读成“低 recall 只是样本太少”；但这些结果和 Phase 1.21/1.22 的 valid_test holdout-hash baseline 不同口径，不能直接对比。

**定位：**
对照 `outputs/ranking/phase_1_23_sample_sensitivity/contract.json`、`metrics_by_sample.json`、`sample_size_sensitivity_summary.csv` 和 `report.json`，核对三档结果分别为 12/12=1.0、78/81=0.962963、1314/1382=0.950796，`candidate_count_avg` 依次为 52.166667、93.901235、128.83864；同时检查命中来源，发现更大样本下主要由 `itemcf_strong` / `itemcf_weak` 贡献，而不是 Phase 1.21 里解释 pool200-only 增益的 `semantic_title_category_expansion` / `popular`。

**解决：**
把叙事边界锁在 recall-only、pool200、LOPO internal split，并明确不做 ranking、Top-K、LTR rerank、holdout tuning 或 leakage 规避式包装；结论写成“数据/切分难度仍是主因，LOPO 证据不足以把 valid_test 低 recall 归因为样本规模”。

**验证：**
三档 LOPO 指标全部跑通且 fallback_rate=0.0；样本增大后候选供给确实上升，但 source 归因与 valid_test 基线不一致，说明 sample-size 变大并不自动等价于 valid_test recall 晋升。

**面试可讲点：**
这轮的价值不在“把 recall 做高”，而在“把证据边界说清楚”：我用同一 recall-only 合同验证了样本规模会影响候选供给，但也证明了 LOPO 不能直接替代 valid_test 口径，因此后续应优先做同风格 valid_test 大 split 或更严格的 leakage audit。



### 2026-05-12 - Phase 1.24 核心召回指标扩展

**任务：**
补写 Phase 1.24 的中文工程叙事，把工业召回方法和现有 source 映射到统一的观测指标框架。

**遇到的问题：**
单看 recall 数字容易把规则/热门、协同过滤、内容/语义、图召回、双塔召回混成一个黑盒，也容易把召回观测误写成排序收益。

**定位方式：**
按工业召回谱系对齐现有 source：`popular` / `category`、`itemcf_strong` / `itemcf_weak`、`semantic` / `semantic_title_category_expansion` / `category_long_tail`、`item_graph` / `graph_walk`、`two_tower`，并明确序列/多兴趣召回暂未落地。

**解决方式：**
把 Phase 1.24 定义为指标扩展，不改召回算法本身；只补 source 归因、覆盖、召回命中和分桶观察，明确不做排序、Top-K promotion、线上 CTR/CVR/GMV 伪造，也不靠 holdout / miss-target 调参。

**验证结果：**
文档已补齐，口径与前序召回诊断一致：这轮新增的是观测能力，不是算法晋升。

**面试可讲点：**
可以把这轮讲成“先拆方法谱系，再统一观测指标”。这样后续无论接规则、协同过滤、语义、图还是双塔，都能用同一套边界判断覆盖和来源，而不是把可观测误当成已提分。

### 2026-05-12 - Phase 1.25 工业排序研究收口

**任务：**
把 Phase 1.23 / 1.24 的 same-run 证据收束成工业排序研究文档，并同步补写过程日志。

**问题：**
1.23 / 1.24 都是 `VALID`，但 `hit_rate_at_k`、`ndcg_at_k`、`mrr_at_k` 全部持平，容易把实验可运行误解为默认晋升。

**定位方式：**
对照 `outputs/ranking/phase_1_23_pool200_ranking_isolation/comparison.json`、`outputs/ranking/phase_1_23_pool200_ranking_isolation/comparison.md`、`outputs/ranking/phase_1_24_pool200_semantic_near_miss_rescue/comparison.json`、`outputs/ranking/phase_1_24_pool200_semantic_near_miss_rescue/comparison.md`，核对 frozen pool200 的关键指标：`candidate_hit_rate_at_pool=0.123188`、`hit_rate_at_k=0.014493`、`ndcg_at_k=0.002779`、`mrr_at_k=0.006039`、`map_at_k=0.001208`、`candidate_hit_missed_topk_users=15`。

**解决方式：**
将研究边界收敛为工业指标概览、失败模式映射、两轮复盘和不超过 3 个轻量候选；明确不改召回、不动 `candidate_pool_size`、不做训练/集成、不晋升 LOPO。

**验证结果：**
`dic/experiments/ranking/phase_1_25/PHASE_1_25_INDUSTRIAL_RANKING_RESEARCH.md` 已落盘，内容和 frozen-pool 证据一致，且给出了后续实验的 stop gate。

**面试可讲点：**
这类工作能体现我如何把“实验做完”转成“证据说清楚”：先锁边界、再看 delta、最后才决定哪些候选值得继续。

### 2026-05-12 - Phase 1.25 pool200 召回体检与候选池健康收口

**任务：**
基于 `outputs/recall/phase_1_25_pool200_recall_health/` 的结果，补写 pool200 召回/候选生成健康叙事。

**问题：**
候选池虽然可跑通，但如果只看“有命中”容易忽略空候选、覆盖、候选规模分布和来源重叠，导致把召回健康误判为排序收益。

**定位方式：**
对照 `recall_health_report.json` / `.md`、`baseline/metrics.json`、`baseline/manifest.json`，核对 `empty_candidate_users=0`、`empty_candidate_rate=0.0`、`user_candidate_coverage_rate=1.0`、`candidate_count avg/min/p50/p90/max=157.112/67/160/200/200`、`candidate_hit_users@pool=19/138`、`catalog_candidate_coverage_count=12089`，以及 source marginal hits：`semantic=4`、`popular=3`、`semantic_title_category_expansion=2`、`two_tower=1`。

**解决方式：**
把结论锁定为“pool200 召回底座健康、候选池覆盖完整、来源贡献可解释”；只补召回体检与来源解释，不把 `candidate_recall@20/50/100/200` 或 `candidate_hit_rate@20/50/100/200` 误写成排序提升，也不引入 LTR/rerank/Top-K promotion。

**验证结果：**
`candidate_hit_rate@20/50/100/200=0.072464/0.108696/0.123188/0.137681`，`candidate_recall@20/50/100/200=0.034967/0.055921/0.05884/0.06971`；候选池无空用户、覆盖率 100%，说明召回健康问题已被体检证实可控。

**面试可讲点：**
这轮能讲成“先做候选池体检，再谈模型优化”：先用空候选、覆盖率、候选规模分布和 source overlap 判断底座是否稳定，避免把召回健康和排序收益混在一起。

### 2026-05-12 - Phase 1.25 normalized-additive 排序门禁验证

**任务：**
在 frozen pool200 候选池上验证 normalized-additive 排序平台是否只改变排序诊断，不引入召回、候选池规模、`top_k`、LTR、serving 或 frontend 合约漂移。

**问题：**
新增排序权重网格如果没有严格门禁，容易把候选池 hash/count 漂移、fallback 变化或二级指标局部变化误判成可晋升排序收益。

**定位方式：**
对照 `.omc/handoffs/team-exec-to-team-verify-phase-1-25-ranking-platform.md`、`outputs/ranking/phase_1_25_pool200_normalized_additive_limit500/comparison.json` / `.md`、`configs/ranking/phase_1_25/phase_1_25_pool200_*.yaml`、`rs_core/recsys/evaluation.py` 和 `tests/test_hybrid_demo.py`，核对 8 个变体均为 `candidate_pool_size=200`、`top_k=5`、`ltr_model=false`、`ranking_v2=false`、`item_feature_rerank=false`、`source_aware_fusion=false`。

**解决方式：**
保留 normalized-additive 为排序层诊断平台：有限权重网格、同跑 baseline、冻结候选 hash/count 对比、`strict_ranking_promotion_status` 强门禁；LTR 只允许 diagnostic-only，不允许 promotion。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -q` 通过 80/80，`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过。limit-500 对照中 8 个变体 `all_variants_valid=true`、frozen hash 均为 `e664ad5ee7b133811d19e6b28b1e99f5d1cef15b6241f1ef51d40ed73b28195b`、`user_count=500`、`candidate_count=76136`；所有非 baseline 变体均为 `PARTIAL diagnostic-only`、`promotable=false`，主指标持平：`hit_rate_at_k=0.014493`、`ndcg_at_k=0.002779`、`mrr_at_k=0.006039`、`map_at_k=0.001208`、`candidate_hit_missed_topk_users=15`。

**面试可讲点：**
这轮可以讲成“先建排序实验门禁，再决定是否晋升”：我没有因为平台跑通就包装成收益，而是用 hash/count、freeze 指标和 promotion gate 证明这只是可复用诊断能力，当前排序效果不晋升。

### 2026-05-12 - Phase A 持久化合同落地与 frozen snapshot 诊断

**任务：**
补充 Phase A 中文工程叙事，记录 recall persistence contract、schema、registry 和冻结快照的边界。

**遇到的问题：**
pool200 frozen baseline 只有 observation snapshot；缺 frozen_candidates、ablation、latency、fallback promotion artifacts，若直接写成提分结论会把合同落地误写成算法晋升。

**定位方式：**
核对 `.omc/recall/schema/recall_experiment_registry.schema.yaml`、`.omc/recall/schema/source_group_registry.schema.yaml`、`.omc/recall/registry/*.yaml`、`.omc/recall/artifacts/phase_1_25_pool200_frozen_baseline/{manifest,signature,contract,metrics}.yaml`，并运行 `./.venv/Scripts/python.exe scripts/validate_recall_registry.py`。

**解决方式：**
把 Phase A 定义为持久化合同落地，统一将 pool200 snapshot 标记为 `INCONCLUSIVE_MISSING_ARTIFACT`；只确认 registry/schema/manifest 的一致性，不补造晋升证据，不写 ranking/LTR/Top-K/在线收益。补齐生产路径后，`run_hybrid_demo` 会写出 `recall_registry_artifact.json`，并把路径回填到 `metrics.json`，让后续 agent 可以直接从 workflow artifact 接续 registry 治理。

**验证结果：**
`Recall registry validation passed: 1 record(s)`；相关文档已更新，叙事口径与 artifact 边界一致。生产路径测试 `./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py::test_workflow_writes_outputs_report_and_metrics` 通过，确认 workflow 产物包含 recall-only registry artifact，且缺失 promotion artifact 时仍保持 `INCONCLUSIVE_MISSING_ARTIFACT`。

**面试可讲点：**
可以讲成“先做证据合同，再做结果表达”：先让 schema、registry、artifact manifest 可校验，再决定 snapshot 能不能晋升；这样可避免把观察性产物误写成算法提升。

### 2026-05-13 - Phase B recall promotion artifact 生产路径与 source family benchmark 框架

**任务：**
把 Phase A 的静态 recall contract 推进到 workflow 生产路径：`run_hybrid_demo` 写出 promotion sidecar artifacts，并让 Phase 1.21 recall coverage baseline 产出 source family observation benchmark 框架。

**问题：**
pool200 snapshot 之前只有 registry/manifest 层证据；如果没有 workflow 级 sidecar、hash 和 benchmark 注册模板，后续 agent 很难持续比较 popular/category、ItemCF/co-visit、semantic/title-category、graph、vector/two-tower、sequence/multi-interest，也容易把缺失 ablation 的 observation 误判为 baseline_vNext。

**定位：**
检查 `rs_core/workflow/hybrid_demo.py` 的 metrics 写出顺序，发现 registry artifact 判断 latency/fallback/overlap 是否可用依赖 sidecar 文件实际存在；同时检查 `scripts/phase_1_21_recall_coverage_experiments.py`，确认 baseline 模式适合作为 source family observation benchmark 的轻量注册入口。

**解决：**
`run_hybrid_demo` 现在写出 `recall_source_coverage.json`、`recall_pool_curve.json`、`recall_latency_report.json`、`recall_fallback_report.json`、`recall_overlap_source_contribution.json`，并把路径回填到 `metrics.json` / `recall_registry_artifact.json`；dedicated leave-one-source-out ablation 仍保持 unavailable，所以 gate status 继续是 `INCONCLUSIVE_MISSING_ARTIFACT`。Phase 1.21 baseline 额外写出 `source_family_observation_benchmarks.json`，只生成 observation lane 的 source family 注册模板，不直接跑昂贵全量实验。

**验证：**
`./.venv/Scripts/python.exe scripts/validate_recall_registry.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_21_recall_coverage.py tests/test_hybrid_demo.py::test_workflow_writes_outputs_report_and_metrics` 通过，20 passed。测试覆盖 sidecar path/hash、forbidden ranking/online metrics、source family benchmark 六类方法和 recall-only observation contract。

**面试可讲点：**
这轮可以讲成“把召回路线探索做成可持续实验系统”：先统一 artifact、hash、gate 和 source family 模板，让后续 agent 能公平探索主流召回方法组合；但在 ablation 缺失前，不把任何组合晋升成最终路线。

**首批 observation baseline：**
在 `outputs/recall/phase_1_21_recall_coverage/source_family_baseline/` 跑通固定 holdout hash 的 pool100 source-family baseline：`users_with_holdout=138`、`candidate_hit_users=14`、`candidate_hit_rate_at_pool=0.101449`、`recall_at_pool=0.060709`、`empty_candidate_rate=0.0`、`fallback_rate=0.0`。本轮只证明 observation 框架可运行，不产生 `baseline_vNext`；下一步应按 source family 跑具体变体和 dedicated ablation。

### 2026-05-13 - Phase C 召回长期执行合同与 evidence 状态机加固

**任务：**
继续执行召回长期目标，补齐 promotion gate、diagnostic-only 隔离、source family 状态矩阵和 ablation/frozen evidence 骨架。

**问题：**
仅有 observation baseline 和模板会让后续执行误判完成度；未运行 family、缺失 frozen candidates、缺 dedicated ablation 都不能被包装成 `baseline_vNext` 晋升证据。

**定位：**
检查 recall registry schema/validator、Phase 1.21 benchmark artifact 和测试断言，重点验证 `frozen_candidates_path`、forbidden metrics、source family execution status 与 missing artifact 状态。

**解决：**
强化 schema/validator 负向校验；为六类 source family 增加 `execution_status`、`evidence_level`、artifact path/hash 和 `next_action`；为 ablation 模式输出 dedicated evidence manifest 与 frozen promotion checklist，并在缺真实 artifact 时保持 `INCONCLUSIVE_MISSING_ARTIFACT`。

**验证：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py::test_recall_registry_validator_accepts_source_alias_and_rejects_forbidden_metric_overlap` 通过；`./.venv/Scripts/python.exe -m compileall scripts/phase_1_21_recall_coverage_experiments.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_21_recall_coverage.py` 通过 19/19。

**面试可讲点：**
可以讲成“长期推荐实验的防伪完成机制”：用状态机和 evidence checklist 区分模板、可运行、已执行和可晋升，确保没有真实 frozen/ablation 证据时系统自动保持不晋升。

### 2026-05-12 - Phase 1.26 持久排序实验治理底座

**任务：**
把“持续探索工业排序方法”的长期计划先收束成可执行治理底座：实验注册表、冻结候选 artifact equality、严格状态机阈值，而不是一次性堆所有模型。

**问题：**
Phase 1.25 已证明 normalized-additive 平台能跑但没有排序效果提升；如果继续新增 LTR、GBDT 或深度排序而没有统一 registry 和候选池一致性门禁，容易把候选池漂移、样本噪声或微小浮点变化误判成最终路线。

**定位方式：**
检查 `rs_core/recsys/evaluation.py` 中的 `frozen_candidate_signature()`、`compare_frozen_candidate_signatures()`、`strict_ranking_promotion_status()`，以及 `tests/test_hybrid_demo.py` 里 Phase 1.25 的冻结候选和 promotion gate 测试，确认最小集成点可以放在 evaluation 层，不需要修改召回、`candidate_pool_size`、`top_k` 或 serving/frontend contract。

**解决方式：**
新增 `frozen_candidate_artifact()`、`compare_frozen_candidate_artifacts()` 和 `build_ranking_experiment_registry_entry()`，把 canonical candidate hash/count、schema version、promotion scope、关键指标和状态统一落到 registry entry；同时把 promotion gate 从“只要 hit_rate 大于 tolerance”收紧为 `hit_rate` 绝对提升至少 `0.001`、相对提升至少 `3%`、`candidate_hit_missed_topk_users` 至少减少 1，且 NDCG/MRR/MAP 不回退。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py::test_phase_1_26_runner_writes_registry_entries_to_comparison tests/test_hybrid_demo.py::test_phase_1_26_registry_entry_records_frozen_candidate_artifact_and_scope tests/test_hybrid_demo.py::test_phase_1_26_candidate_artifact_equality_reuses_strict_signature_gate tests/test_hybrid_demo.py::test_strict_ranking_promotion_status_promote_partial_and_invalid_stop` 通过 4/4；`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_evaluation.py tests/test_hybrid_demo.py` 通过 86/86，并验证 Phase 1.25 runner 的 `comparison.json` 会实际写出 `ranking_experiment_registry`。

**面试可讲点：**
这轮可以讲成“先治理实验，再探索模型”：面对多种工业排序方法，不急着堆模型，而是先建立可复现的实验注册、候选池相等性和晋升状态机，让后续 LR/GBDT/LambdaMART/深度排序都必须在同一 frozen-pool 证据框架下竞争。

### 2026-05-13 - Phase 1.27 特征/标签/泄漏治理收口

**任务：**
补充 Phase 1.27 中文工程叙事，记录特征契约、标签切分和泄漏门禁的治理边界。

**遇到的问题：**
如果 feature contract、label split 和 leakage gate 没有被明确约束，后续 learned ranker 很容易把 holdout target、future interaction 或 promotion evidence 误用进训练和评估；验证前还遇到 `rs_core/workflow/hybrid_demo.py` 的 helper 调用不一致，必须先修复后才能继续跑验证。

**定位方式：**
对照 `dic/phases/RANKING_LONG_RUNNING_EXPLORATION_PLAN.md` 中 Phase 1.27 的 scope，确认当前要补的是 offline ranking feature contract、allowed/forbidden features、label/split/leakage gate 和 registry metadata，而不是改 `candidate_pool_size`、`top_k` 或 recall baseline；随后运行 compileall、Phase 1.27 相关 pytest 和真实 runner smoke。

**解决方式：**
把 Phase 1.27 写成治理阶段：allowed features 只保留 source、item metadata、candidate score、user history aggregates 和 near-miss diagnostics；forbidden features 排除 holdout target、future interaction，以及 valid/test 上训练后再当 promotion evidence 的字段；label split leakage gate 覆盖 target item、future interaction 和 holdout leak；registry metadata 记录 feature contract version 与作用范围，供后续 learned ranker 复用。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_evaluation.py tests/test_ltr.py` 通过 106/106；`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过；`./.venv/Scripts/python.exe scripts/run_phase_1_25_pool200_normalized_additive.py --limit-users 50` 成功生成 `outputs/ranking/phase_1_25_pool200_normalized_additive/comparison.json`，registry 中已记录 `feature_contract_version=ranking_feature_contract_v1`、`feature_contract_gate_summary.schema_version=ranking_feature_contract_gate_v1` 和 `leakage_gate_summary.schema_version=ranking_feature_leakage_gate_v1`。非 LTR 排序变体的 feature/leakage gate 明确标记为 `NOT_APPLICABLE`，LTR 训练路径会对真实 feature rows 执行 gate；验证期间没有改 `candidate_pool_size`、`top_k` 或 recall baseline，也没有把这轮叙事写成模型 lift。

**面试可讲点：**
可以讲成“先定特征契约和泄漏边界，再谈模型效果”：这轮没有追求数字上升，而是把输入契约、标签切分和泄漏门禁先做成可审计的治理层，确保后续学习排序的证据可信、可复现、可追踪。

### 2026-05-13 - Phase 7/8 多目标与在线学习 future-online 门禁

**任务：**
在长期排序计划 Phase 7/8 中收口 ESMM、MMoE、PLE、多目标排序、Bandit、RL/GRPO 和 Agent feedback 的当前边界，确保线上业务指标不会被误用为 frozen pool200 离线 promotion 证据。

**遇到的问题：**
Phase 7/8 需要 CTR/CVR/GMV 业务 label、线上或准线上评估、serving/monitoring contract、交互日志、安全探索策略和 replay/A/B 链路。当前项目还停留在 frozen pool200 离线排序证据，因此只能标记 future-online / future-agent-online，不能实现假在线实验。

**定位方式：**
读取 `dic/phases/RANKING_LONG_RUNNING_EXPLORATION_PLAN.md` 的 Phase 7/8 进入条件，并对照当前 ranking registry 能力，确认可以产出 future gate artifact，但不能把线上指标、SLO 或 A/B uplift 纳入当前离线晋升。

**解决方式：**
新增 `scripts/run_phase_7_8_future_online_gate.py`，运行 same-run baseline 以保持当前离线 artifact 完整；将 `esmm_ctr_cvr_ranker`、`mmoe_multi_task_ranker`、`ple_multi_task_ranker`、`contextual_bandit_ranker`、`rl_grpo_preference_ranker` 等方法写入 blocked registry，lane 标注为 `future-online` 或 `future-agent-online`，并在 readiness 中列出缺失条件和当前禁用证据。

**验证结果：**
`compileall` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_7_8_future_online_gate or phase_6_semantic_two_tower_ranker or phase_5_sequence_ranker"` 通过 3 个目标测试；`outputs/ranking/phase_7_8_future_online_gate_smoke/comparison.json` 验证 artifact inspection PASS、`candidate_pool_size=200`、`top_k=5`、所有 Phase 7/8 方法 blocked 且不具备当前 offline promotion eligibility，最终路线保持 `same_run_baseline`。

**面试可讲点：**
这轮可以讲成“把未来路线也纳入工程治理”：不仅能实现模型，还能识别哪些方法需要线上标签和安全探索条件，在证据不足时用 future gate 防止指标口径污染。

### 2026-05-13 - Phase 6 语义 / 双塔排序特征融合门禁

**任务：**
在长期排序计划 Phase 6 中验证 semantic-title score、two-tower score、vector similarity、DSSM 和 cross-feature fusion 的排序侧价值，继续保持 frozen pool200、`candidate_pool_size=200`、`top_k=5`、不改召回语义。

**遇到的问题：**
semantic / two_tower 已经是当前候选池的召回源，如果直接改召回或重新用 DSSM/vector artifact 生成候选，会破坏排序实验边界。与此同时，DSSM 与 raw vector similarity 虽有训练 artifact，但缺少 candidate-level rerank adapter，不能作为当前离线 promotion 证据。

**定位方式：**
对照 `configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml`、`rs_core/recsys/ranking.py`、`rs_core/recsys/ltr.py` 和 two-tower artifact，确认当前可审计输入是候选内 `source_scores` 和 source cross features；真实 smoke 产物为 `outputs/ranking/phase_6_semantic_two_tower_ranker_smoke/comparison.json`。

**解决方式：**
新增 `scripts/run_phase_6_semantic_two_tower_ranker.py`，在 same-run frozen pool200 baseline 上运行 `semantic_score_feature_rerank`、`two_tower_score_feature_rerank` 和 `semantic_two_tower_cross_feature_fusion` 三个排序对照；将 `dssm_artifact_candidate_rerank` 与 `raw_vector_similarity_feature_fusion` 写入 blocked method registry，明确 blocked 原因是 adapter 缺失和禁止候选池重生成。

**验证结果：**
`compileall` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_6_semantic_two_tower_ranker or phase_5_sequence_ranker"` 通过 2 个目标测试；Phase 6 smoke 通过并输出 artifact inspection PASS、全部 run 的 frozen candidate status PASS。指标上 baseline `hit_rate_at_k=0.037037`，semantic score rerank 降至 `0.018519`；two-tower score 与 cross-feature fusion 持平但未达到 hit-rate lift 和 missed-topk reduction 门槛，最终 `selected_route=same_run_baseline`。

**面试可讲点：**
这轮可以讲成“把 embedding/双塔从召回能力拆成排序证据来验证”：即使有 two-tower artifact，也必须在冻结候选池内证明排序收益；没有 adapter 或没有稳定 lift 的方法只能 diagnostic/blocked，不能包装成成功。

### 2026-05-13 - Phase 5 行为序列 / 注意力排序数据门禁

**任务：**
继续长期排序计划 Phase 5，判断当前数据是否足以支持 DIN / DIEN / BST / SIM 等行为序列排序模型。

**问题：**
行为序列模型依赖长历史、可靠时间顺序、session/history window 和无未来交互泄漏。当前数据有 `user_sequences` 和 timestamp，但长序列覆盖不足；如果直接训练 DIN/DIEN/BST/SIM，只能得到 toy 结果，不能作为当前离线 promotion 证据。

**定位：**
统计 `user_sequences.train.jsonl` 的序列质量：Phase 5 smoke 中 200 个用户的 `positive_len_ge_2_rate=0.575`、`positive_len_ge_10_rate=0.11`、`timestamp_ordered_rate=1.0`。结论是短序列诊断满足条件，但长序列模型未达到数据门槛。

**解决：**
新增 `scripts/run_phase_5_sequence_ranker.py`，输出 `sequence_ranker_data_readiness_v1`、Phase 0 风格 registry 和 artifact inspection。session-aware / attention history 仅为 diagnostic；DIN、DIEN、BST、SIM 标记为 blocked，并写明长序列覆盖不足和 adapter 缺失原因。

**验证：**
`./.venv/Scripts/python.exe -m compileall scripts/run_phase_5_sequence_ranker.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_5_sequence_ranker or phase_4_neural_ranker"` 通过 2/2；`outputs/ranking/phase_5_sequence_attention_ranker_smoke/comparison.json` 显示 artifact inspection PASS、短历史方法 diagnostic、DIN/DIEN/BST/SIM blocked。

**面试可讲点：**
这轮体现的是数据条件先行：面对工业序列模型，不是直接上模型名，而是先证明历史长度、时间顺序、泄漏边界和 serving adapter 是否具备，把“可诊断”和“必须 blocked”的方法分清。

### 2026-05-14 - Phase 5 正向收口与合同验证

**任务：**
同步 Phase 5 中文叙事，记录本轮 fine-rank / 序列正向收口结果。

**遇到的问题：**
Phase 5 smoke 能证明诊断链路和合同检查通过，但不能把序列/注意力方法写成 promotion；如果把 smoke 成功写成晋升，会越过 frozen candidate、top_k 和 online claims 的边界。

**定位方式：**
结合 `comparison.json` 与验证结果，核对 `candidate_pool_size=200`、`top_k=5`、`frozen_candidate_comparison.match=true`、`case_diagnostic_success=true`、`promotion_success=false`、`online_claims=[]`、`artifact_inspection=PASS`，确认本轮只有诊断证据，没有晋升证据。

**解决方式：**
把 Phase 5 结果明确收口为 diagnostic / blocked：短历史与注意力诊断保留，DIN / DIEN / BST / SIM 仍因序列覆盖和 adapter 条件不足维持 blocked，不把 positive push smoke 叙述成 promotion。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile scripts/run_phase_5_sequence_ranker.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_phase_5_fine_rank_positive_push.py -q` 通过 `7 passed`；`outputs/ranking/phase_5_fine_rank_positive_push_smoke/comparison.json` 通过 contract 检查。

**面试可讲点：**
这轮可以讲成“把序列模型也放进同一套证据门禁”：不是因为模型名更高级就放松标准，而是先用合同检查证明冻结候选、诊断成功和在线承诺为空，再决定哪些方法只能留在 diagnostic lane.

### 2026-05-13 - Phase 4 神经排序 CUDA 诊断原型

**任务：**
继续长期排序计划 Phase 4，把 MLP / RankNet 神经排序原型纳入统一实验治理，并验证 GPU 训练链路。

**问题：**
当前虽然 PyTorch CUDA 可用，但神经排序缺少 serving adapter、valid/test promotion split 和 ADR；Wide&Deep、DeepFM、DCN、xDeepFM 也缺少稳定特征交叉 schema。不能把 GPU 上能训练的 smoke 结果包装成 offline promotion。

**定位：**
用 `.venv` 检查依赖和设备，确认 `torch 2.11.0+cu128` 与 `NVIDIA GeForce RTX 4070 Ti SUPER` 可用；读取候选行导出结构，确认 `features/label/user_id` 可支持 pointwise MLP 与 pairwise RankNet 诊断训练。

**解决：**
新增 `scripts/run_phase_4_neural_ranker.py`，复用 Phase 0 registry/artifact/gpu 策略：MLP 和 RankNet 在 CUDA 上训练 diagnostic artifact；LambdaRank、ListNet/ListMLE、Wide&Deep/DeepFM/DCN/xDeepFM 因 objective、schema 或 adapter 缺失写为 blocked；所有神经方法默认不具备 promotion eligibility。

**验证：**
`./.venv/Scripts/python.exe -m compileall scripts/run_phase_4_neural_ranker.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_4_neural_ranker or phase_3_tree_ranker"` 通过 2/2；Phase 4 smoke 产物 `outputs/ranking/phase_4_neural_ranker_smoke/comparison.json` 显示 artifact inspection PASS、MLP/RankNet diagnostic、其他神经方法 blocked、最终路线仍为 same-run baseline。

**面试可讲点：**
这轮体现的是 GPU 实验纪律：真实使用 CUDA 训练，而不是 CPU toy；但训练跑通不等于排序晋升，仍必须通过 serving adapter、valid/test 口径、稳定 lift 和 ADR 才能进入 promotion。

### 2026-05-13 - Phase 3 树模型 / LambdaMART 依赖门禁

**任务：**
继续长期排序计划 Phase 3，把 GBDT / LambdaMART 路线接入统一实验治理，但只在真实依赖和训练条件满足时才允许进入 promotion。

**问题：**
当前 `.venv` 中 `sklearn`、`xgboost`、`lightgbm` 均不可用，代码中也没有真实树模型训练 adapter；现有 LTR 训练只能导出候选行或训练 pointwise/pairwise 轻量模型。直接用 deterministic stand-in 或 LOPO LTR 冒充树模型，会违反 frozen pool200 离线证据边界。

**定位：**
用 `./.venv/Scripts/python.exe` 检查树模型依赖，结果均为 missing；再检查 `rs_core/workflow/ltr_training.py`，确认 `write_candidate_rows` 可生成未来训练数据，但 `_train_ltr_model()` 只支持 pairwise perceptron 与 pointwise logistic。

**解决：**
新增 `scripts/run_phase_3_tree_ranker.py`，只运行 same-run baseline 和候选行导出；真实 `sklearn_gbdt_valid_test_promotion`、`xgboost_lambdamart_gpu_promotion`、`lightgbm_lambdamart_gpu_promotion` 统一写成 blocked method，并把依赖缺失、GPU 不可用、adapter 缺失、valid/test split 缺失写入原因。

**验证：**
`./.venv/Scripts/python.exe -m compileall scripts/run_phase_3_tree_ranker.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_3_tree_ranker or phase_2_shallow_learned_runner"` 通过 2/2。

**面试可讲点：**
这轮体现的是工程诚信和实验治理：复杂排序模型不具备依赖和训练条件时，不把 toy 实验包装成收益，而是把 blocked 原因结构化沉淀，为后续真实 GBDT/LambdaMART 接入准备数据和门禁。

### 2026-05-13 - Phase 2 浅层 learned ranker 诊断闭环

**任务：**
继续长期排序计划 Phase 2，把 pointwise logistic 和 pairwise perceptron 浅层学习排序纳入统一实验底座。

**问题：**
现有 LTR 训练是 LOPO 口径，只能证明训练/推理链路和 feature/leakage gate 可运行，不能作为 valid/test promotion evidence；线性 ranker 的独立 valid/test promotion split 还不存在，不能为了方法覆盖而伪造晋升。

**定位：**
检查 `scripts/run_phase_1_28_lightweight_learned_ranker.py` 与 `rs_core/workflow/ltr_training.py`，确认可复用 pointwise/pairwise 训练器、`feature_contract_gate` 和 `leakage_gate`。长期边界继续是 fixed recall base、frozen pool200、`candidate_pool_size=200`、`top_k=5`，LOPO-only 不晋升。

**解决：**
新增 `scripts/run_phase_2_shallow_learned_ranker.py`，输出统一 `method_registry`、`artifact_inspection`、`gpu_resource_strategy`、`ranking_experiment_registry` 和 `final_decision`。pointwise/pairwise 标记为 diagnostic，强制写入 `lopo_training_diagnostic_only`；缺少 valid/test promotion split 的 `linear_ranker_valid_test_promotion` 写为 blocked。

**验证：**
`./.venv/Scripts/python.exe -m py_compile scripts/run_phase_2_shallow_learned_ranker.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_2_shallow_learned_runner or phase_1_rule_ranking_runner or phase_0"` 通过 6/6；Phase 2 smoke 生成 `outputs/ranking/phase_2_shallow_learned_ranker_smoke/comparison.json`，artifact inspection PASS，pool/top_k 为 200/5，baseline champion，pointwise/pairwise diagnostic，linear ranker blocked，feature/leakage gates 均 PASS，最终 `BASELINE_FINAL_ROUTE`。

**面试可讲点：**
这轮体现的是“学习排序先过治理门禁，再谈晋升”：把训练闭环、泄漏检查和 registry 状态都跑通，但严格禁止把 LOPO 诊断结果写成线上或 valid/test 收益。

### 2026-05-13 - Phase 1 规则排序 champion/challenger 复验

**任务：**
在 Phase 0 排序实验底座上继续 Phase 1，系统复验 normalized additive、source-aware fusion、item feature rerank 和保守规则组合。

**问题：**
旧的规则排序实验分散在 Phase 1.23/1.25 runner 中，缺少统一的 method registry、artifact inspection 和 champion/challenger 状态输出；如果不先把规则方法收口，后续 learned ranker 或树模型很难判断自己超过的是哪个强基线。

**定位：**
检查现有 runner 与 `rs_core/recsys/ranking.py`，确认规则排序能力已有，但需要一个长期计划下的 Phase 1 专用入口；边界仍固定为 current fixed recall base、frozen pool200、`candidate_pool_size=200`、`top_k=5`，不使用在线 CTR/CVR/GMV/P95 作为当前离线晋升证据。

**解决：**
新增 `scripts/run_phase_1_rule_ranking_champion.py`，复用 Phase 0 底座字段：`method_registry`、`artifact_inspection`、`gpu_resource_strategy`、`ranking_experiment_registry`、`stability_summary` 和 `final_decision`。所有规则方法只做排序层 override，不改召回语义；未稳定过门禁的规则候选标记为 retired，baseline 继续作为 champion。

**验证：**
`./.venv/Scripts/python.exe -m py_compile scripts/run_phase_1_rule_ranking_champion.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_1_rule_ranking_runner or phase_0 or phase_1_29_terminal_runner"` 通过 6/6；小样本 smoke 生成 `outputs/ranking/phase_1_rule_ranking_champion_smoke/comparison.json`，artifact inspection PASS，pool/top_k 保持 200/5，baseline 为 champion，四个规则候选为 retired，最终 `BASELINE_FINAL_ROUTE`。

**面试可讲点：**
这轮体现的是“规则排序先成为可审计强基线”：即使规则方法没有晋升，也通过统一实验治理证明它们的边界干净、证据可复验，为下一阶段线性/pointwise/pairwise learned baseline 提供对照对象。

### 2026-05-13 - Phase 0 长期排序实验底座复用化

**任务：**
把长期排序计划的 Phase 0 落成可复用底座，让后续主流排序方法复用同一套 registry、artifact inspection 和 GPU 资源策略。

**问题：**
Phase 1.29 terminal runner 已能做 frozen pool200 对照，但 method 状态、artifact 检查和 GPU 策略还没有统一沉淀；如果后续每个方法单独判断，容易把 diagnostic-only、frozen mismatch 或 CPU toy smoke 误写成晋升证据。

**定位：**
检查 `scripts/run_phase_1_29_terminal_ranking_route.py` 的 comparison 输出，确认它需要复用 `rs_core/recsys/evaluation.py` 中的公共治理能力；硬边界仍是 fixed recall base、pool200、`candidate_pool_size=200`、`top_k=5`，线上 CTR/CVR/GMV/P95 不进入当前离线 promotion evidence。

**解决：**
在 `rs_core/recsys/evaluation.py` 增加 method registry、GPU resource summary、artifact inspection helper；runner 输出 `method_registry` 和 `gpu_resource_strategy`，并由统一 inspection 检查 artifact 路径、pool/top_k、frozen candidate match 与 diagnostic promotion violation。

**验证：**
`./.venv/Scripts/python.exe -m py_compile rs_core/recsys/evaluation.py scripts/run_phase_1_29_terminal_ranking_route.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_0 or phase_1_29_terminal_runner"` 通过 5/5。

**面试可讲点：**
这轮不是宣称排序效果提升，而是把长期排序实验的“操作系统”先做出来：统一状态机、artifact 门禁、GPU 资源策略和 frozen-pool 边界，保证后续 GBDT/LambdaMART/深度排序方法能公平比较、可复验、可追责。

### 2026-05-13 - Phase 1.31 final offline route selection

**任务：**
输出最终离线排序路线的 ADR，并把 no-promote 结论落到中文工程叙事里。

**遇到的问题：**
Phase 1.23 / 1.24 / 1.25 / 1.28 的证据都没有把模型推进到稳定 Promote；如果把训练 gate PASS、LOPO 结果或轻量 LTR 的 diagnostic smoke 误写成晋升证据，会让终局收口失真。

**定位方式：**
复核 `rs_core/recsys/evaluation.py` 的 `terminal_ranking_promotion_gate()` 与 `strict_ranking_promotion_status()`，再对照 `outputs/ranking/phase_1_28_lightweight_learned_ranker/comparison.json` 和 `comparison.md`，确认最终证据仍然只支持 `No-Promote` / `diagnostic-only`。

**解决方式：**
把最终离线路线定为 `same_run_baseline`，并在 ADR 中明确列出 excluded invalid evidence、underpowered segment、LOPO training gate PASS 但不等于晋升、以及不改召回 / 不碰线上链路的边界。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_evaluation.py tests/test_ltr.py tests/test_two_tower_training.py` 通过 117/117；`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过；`./.venv/Scripts/python.exe scripts/run_phase_1_28_lightweight_learned_ranker.py --limit-users 5` 成功生成最终比较产物。

**面试可讲点：**
把 `No-Promote` 作为显式结论写出来，比勉强找一个“看起来更好”的模型更有工程价值，因为它把边界、风险和后续方向都说清楚了。

### 2026-05-13 - Phase 1.31/1.32 排序算法 scaffold 与诊断收口

**任务：**
补齐 Phase 1.31/1.32 的中文工程叙事，记录统一算法 scaffold、规则/浅层 learned 诊断运行和树模型 blocked 准备的当前状态。

**遇到的问题：**
如果把 scaffold 成果、LOPO/diagnostic smoke 或树模型依赖检查写成晋升结论，就会越过 frozen pool200、`candidate_pool_size=200`、`top_k=5` 和 future-only 线上指标边界。

**定位方式：**
对照 `dic/phases/RANKING_LONG_RUNNING_EXPLORATION_PLAN.md` 的 Phase 1.31/1.32 计划和 `outputs/ranking/phase_1_31_ranking_algorithm_scaffold_smoke/comparison.json`、`outputs/ranking/phase_1_26_real_ranking_experiments_regression/comparison.json` 等回归产物，确认当前可写的是治理收口与诊断结论，不是模型晋升。

**解决方式：**
把 Phase 1.31 写成统一算法实验 scaffold，把 Phase 1.32 写成规则 champion 复验、浅层 learned fine-ranker 诊断和 tree/LambdaMART blocked 准备；所有方法继续走同一 registry / comparison schema，候选池和 top_k 保持不变，线上指标仍只保留为 future-only。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile rs_core/recsys/ranking.py rs_core/recsys/evaluation.py rs_core/workflow/hybrid_demo.py scripts/run_phase_1_30_physical_ranking_pipeline.py scripts/run_phase_1_26_real_ranking_experiments.py` PASS；`./.venv/Scripts/python.exe -m pytest tests/test_evaluation.py tests/test_hybrid_demo.py tests/test_ltr.py tests/test_phase_1_31_ranking_scaffold.py -q` 135 passed in 2.31s；`outputs/ranking/phase_1_30_physical_ranking_pipeline_regression/comparison.json`、`outputs/ranking/phase_1_26_real_ranking_experiments_regression/comparison.json`、`outputs/ranking/phase_1_31_ranking_algorithm_scaffold_smoke/comparison.json` 保留。

**面试可讲点：**
这轮可以讲成“先把排序实验底座做成共用协议，再在同一协议上跑规则、浅层 learned 和树模型准备”，重点是治理边界和证据格式，而不是把 smoke 结果包装成模型提升。

### 2026-05-13 - Phase 1.30 物理流水线证据与晋升边界收口

**任务：**
把 Phase 1.30 的跑通结果收口为“物理流水线证据”，并和 promotion evidence、future-online 指标明确分离。

**遇到的问题：**
这轮 smoke 已经能证明 recall→coarse→fine→rerank 的 stage 物理链路闭环，但如果把 pipeline trace、artifact inspection 或 smoke PASS 直接写成晋升结果，会把系统可观测性和模型收益混在一起；同时线上指标当前还没有进入离线证据链，不能提前写入结论。

**定位方式：**
对照 `outputs/verification/verification_phase_1_30_smoke/comparison.json` 与 `outputs/verification/verification_phase_1_26_regression/comparison.json`，复核 `candidate_pool_size=200`、`top_k=5`、`artifact_inspection=PASS`、`physical_pipeline_inspection=PASS`、`frozen_candidate_match=true`、coarse/fine/rerank stage counts 均为 3225，以及 `online_metric_claims=[]`；再确认 Phase 1.26 regression 的 LTR LOPO 仍是 `diagnostic-only`、`promotion_eligible=false`，tree/LambdaMART 仍 blocked。

**解决方式：**
把 Phase 1.30 写成物理流水线收口而不是晋升收口：明确这组证据只能证明 stage 闭环、artifact 完整和 frozen candidate match，不代表当前存在 promotion evidence；同时把 online metrics 继续留在 future-only 边界，把 LOPO/gate/smoke 统一标成 diagnostic-only。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_evaluation.py tests/test_ltr.py` 通过 130/130；Phase 1.30 smoke PASS，Phase 1.26 regression PASS。

**面试可讲点：**
这轮可以讲成“先把物理流水线和晋升证据分开治理”：系统层面我已经证明 stage 能闭环、artifact 能对齐、frozen candidate 能匹配，但我没有把这些可观测性结果伪装成模型提升，而是把它们归为诊断资产，为后续模型晋升保留干净证据边界。

### 2026-05-13 - Phase 1.28 lightweight learned ranker 最小闭环

**任务：**
把长期排序路线从治理阶段推进到第一批 learned-ranker 执行闭环：固定 pool200 候选池，复用 Phase 1.27 feature/leakage gates，只接入最轻量的 pointwise logistic 与 pairwise perceptron LTR baseline。

**问题：**
如果直接进入 GBDT、LambdaMART 或深度排序，容易在模型复杂度上过早扩张，也容易绕过 feature contract、label split 和 frozen candidate equality；同时 LOPO 训练只能作为内部 sanity，不能当 valid/test promotion evidence。

**定位方式：**
检查 `rs_core/recsys/ranking.py`，确认现有 `ltr_model` 已能加载模型并在 `rank_candidates()` 中叠加 LTR score；检查 `rs_core/recsys/ltr.py`、`rs_core/workflow/ltr_training.py` 和 `scripts/train_ltr_ranker.py`，确认 pointwise logistic 与 pairwise perceptron 都能产出兼容 `score_ltr()` 的线性模型，并会对真实 feature rows 执行 feature contract gate 与 leakage gate。

**解决方式：**
新增并扩展 `scripts/run_phase_1_28_lightweight_learned_ranker.py`，只跑三个 same-run 变体：`same_run_baseline`、`pointwise_logistic_lopo_ltr` 与 `pairwise_perceptron_lopo_ltr`。runner 先用 `configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml` 导出 baseline frozen candidates，再用 LOPO/internal train 训练轻量 LTR，最后在同一 pool200 口径下评估 LTR 变体，写出 `ranking_experiment_registry`、frozen candidate comparison、feature contract gate、leakage gate、model type 和 strict status；两个 LTR 变体固定 `diagnostic-only`，不允许晋升。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k phase_1_28 -vv` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_ltr.py tests/test_hybrid_demo.py` 通过 107/107；`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过；`./.venv/Scripts/python.exe scripts/run_phase_1_28_lightweight_learned_ranker.py --limit-users 50` 生成 `outputs/ranking/phase_1_28_lightweight_learned_ranker/comparison.json`。smoke 结果中 baseline、pointwise logistic 与 pairwise perceptron 变体 frozen candidate hash/count 匹配，`candidate_pool_size=200`、`top_k=5`、`fallback_rate=0.0`；两个 LTR 训练 `feature_contract_gate=PASS`、`leakage_gate=PASS`、`label_source=leave_one_positive_out_train`，model type 分别为 `pointwise_logistic_ltr_v1` 与 `pairwise_perceptron_ltr_v1`，变体状态均为 `PARTIAL diagnostic-only`、`promotable=false`。

**面试可讲点：**
可以讲成“先把 learned ranker 接入生产排序路径，再逐步升级模型”：这轮不是追求复杂模型，而是证明训练、推理、registry、frozen-pool equality 和泄漏门禁可以串成最小可审计闭环，为后续 LR/GBDT/LambdaMART/深度排序提供统一入口和证据标准。

### 2026-05-13 - Phase B promotion schema/validator 与 source family execution_status 收口

**任务：**
补写 Phase B 的中文工程叙事，记录 promotion schema/validator、diagnostic 隔离验证和 source family execution_status 收口。

**遇到的问题：**
source family observation baseline 已经能跑通，但 baseline_vNext 还缺 frozen artifacts、dedicated ablation 和完整 promotion evidence；如果把模板化骨架误写成晋升结果，会把诊断能力和算法收益混在一起。

**定位方式：**
对照 `tests/test_phase_1_21_recall_coverage.py`、`tests/test_hybrid_demo.py` 以及当前 benchmark 产物，确认已具备 promotion schema/validator、diagnostic-only execution_status、frozen-candidate equality 和 source family模板，但 family-specific ablation 和 frozen evidence 仍未补齐。

**解决方式：**
把这轮结论写成“baseline_vNext 仍不晋升”：保留 observation lane、execution_status 和 next_action 字段，下一队列先补 family-specific variants，再补 dedicated ablation/frozen evidence，最后才重新评估晋升。

**验证结果：**
当前叙事与测试口径一致，说明 benchmark scaffolding、diagnostic gate 和 frozen candidate equality 已经可复用，但 promotion 仍停留在 observation/diagnostic 层。

**面试可讲点：**
可以讲成“先把实验骨架和晋升证据分开治理”：先保证可执行、可复现，再决定是否晋升，避免把编排能力误当成模型提升。

### 2026-05-13 - Phase 1.26 长期排序路线收口

**任务：**
把长期排序主线收口成 recall→coarse rank→fine rank→rerank 的目标架构，并明确当前只推进 frozen pool200 → learned fine ranker → bounded rerank trace。

**问题：**
如果把 LOPO smoke、树模型 blocked 或线上指标混进当前结论，容易把 diagnostic-only / future-online 误写成晋升证据；同时目标架构虽然清楚，但 physical scope 还没有铺到完整 coarse/fine/rerank 全链路。

**定位方式：**
对照 `dic/OPTIMIZATION_NARRATIVE.md` 里的 Phase 1.26、Phase 1.28、Phase 1.31 以及 `scripts/run_phase_1_28_lightweight_learned_ranker.py`、`scripts/run_phase_3_tree_ranker.py` 的产物，确认 pointwise/pairwise learned ranker 已有 LOPO smoke，而树模型 / LambdaMART 仍是 blocked lane。

**解决方式：**
把这轮写成“目标架构清楚、物理边界收口”：当前只把 frozen pool200、learned fine ranker 和 bounded rerank trace 写成可执行主线；GBDT / LambdaMART 继续保留 blocked 状态，线上指标全部标记 future-online。

**验证结果：**
`outputs/ranking/phase_1_28_lightweight_learned_ranker/comparison.json` 可作为 pointwise/pairwise smoke 证据；`outputs/ranking/phase_3_tree_lambdamart_ranker_smoke/comparison.json` 保持 blocked / no promotion 口径；当前没有把任何 online metric 写入离线晋升结论。

**面试可讲点：**
可以讲成“先把排序路线图和当前证据边界分开”：目标架构可以画到 recall→coarse→fine→rerank，但真正能拿来讲证据的只有 frozen pool200、轻量 learned ranker 和 bounded rerank trace；树模型没依赖、没 adapter、没 GPU 验证时就明确 blocked，避免把未来路线写成当前成果。

### 2026-05-13 - Phase 1.32 metadata neighbor gate 与不晋升收口

**任务：**
在 `semantic_title_category_expansion` 已晋升为 recall baseline_vNext 后，对 `metadata_neighbor_recall` 做同一 holdout、同一 pool200、同一 recall-only 合同下的机会门禁和专项 ablation，判断是否应继续晋升或保留为诊断 source。

**遇到的问题：**
`metadata_neighbor_recall` 在 miss-user 诊断中有较大表面机会，但原实现按 seed 扫描完整 metadata index，长跑成本高；同时机会门只能作为聚合优先级判断，不能把 holdout target 或 miss target id 用进候选生成、query、target-driven source index construction/filtering、candidate whitelist 或参数选择。静态商品 catalog metadata 可作为非 holdout-label 派生的 train-visible item feature 建索引，但不能由 target 列表驱动筛选或调参。

**定位方式：**
读取 `outputs/recall/phase_1_21_recall_coverage/phase_1_32_metadata_neighbor_gate_20260513/audit/source_opportunity_summary.json`，确认 `baseline_miss_users=132`、`metadata_neighbor_opportunity_users=132`、门槛为 14 且 gate 通过；再对照 `ablation_narrow/baseline_only/metrics.json`、`ablation_narrow/semantic_title_category/metrics.json` 和 `metadata_only_capped/metadata_neighbor/metrics.json`，固定 `users_with_holdout=138`、`holdout_user_ids_hash=927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2`、`candidate_pool_size=200`。

**解决方式：**
将 metadata neighbor 从全量扫描改为 token/category bucket index，并增加 per-seed bucket candidate cap，使专项 ablation 可在 limit500 口径下完成；ablation matrix 支持 `ablation_experiments`，只运行需要的 source lane；测试补充 no-leakage note、miss-user gate 和 `metadata_neighbor_index_mode=bucketed_train_visible_metadata` 断言。

**验证结果：**
专项 metadata-only capped run 完成，manifest 记录 same holdout verified。结果显示 metadata lane `candidate_hit_users=17`、`candidate_hit_rate_at_pool=0.123188`、`candidate_count_avg=132.2`，虽有 `metadata_neighbor_recall` 用户覆盖 454、item 覆盖 272、召回候选 2870，但 `source_marginal_candidate_hit_users` 和 `candidate_hit_source_coverage` 均没有 metadata 贡献；对照 baseline_only 为 17，semantic/title-category 为 19 且有 2 个 marginal candidate-hit users。因此本轮结论是 `NO_PROMOTION`：metadata neighbor 工程链路和 gate 成立，但没有带来 recall-only candidate-hit lift。

**面试可讲点：**
这轮可以讲成“机会大不等于可晋升”：先用聚合 miss-user gate 判断是否值得跑，再用索引化实现控制成本，最后仍严格按 candidate-hit lift 和 source marginal contribution 裁决。metadata neighbor 通过了机会门和工程可运行性，但没有覆盖新的 holdout 命中，因此保留为诊断/后续改造方向，不污染 baseline_vNext。

### 2026-05-13 - Phase 3 树模型 / LambdaMART 依赖门禁

**任务：**
在 frozen pool200 排序口径下验证 Phase 3 tree / LambdaMART 是否具备真实训练、serving 和晋升条件，只保留可审计诊断，不把 tree smoke 写成模型收益。

**遇到的问题：**
当前环境里 GBDT / LambdaMART 相关依赖和 serving adapter 仍不完整；如果把 `sklearn` GBDT 或训练行导出当成晋升结果，就会把准备工作误写成模型效果，也会绕过 valid-test promotion gate 和 objective recovery condition。

**定位方式：**
读取 `scripts/run_phase_3_tree_ranking_experiments.py`、`tests/test_phase_3_tree_ranking_experiments.py` 和 `outputs/ranking/phase_3_tree_ranking_experiments_smoke/comparison.json`，核对 `candidate_pool_size=200`、`top_k=5`、training rows=2217、positive=16、negative=2201；同时用 `./.venv/Scripts/python.exe -m py_compile`、Phase3/Phase2/Phase1 scaffold/evaluation pytest 12 passed 和 recall regression pytest 23 passed 回归确认基础链路稳定。

**解决方式：**
把 `sklearn` GBDT 固定为 diagnostic-only，把 LambdaMART 固定为 blocked；只保留 candidate-row export、依赖检查、group/objective 恢复条件和 future 阶段的 serving 入口，不改 `merge_for_user` 和召回语义。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile` 通过；Phase3/Phase2/Phase1 scaffold/evaluation pytest 12 passed，recall regression pytest 23 passed，`limit_users=20` smoke 通过；`outputs/ranking/phase_3_tree_ranking_experiments_smoke/comparison.json` 未产生 online promotion evidence。

### 2026-05-14 - Phase 6 工业式默认全链路诊断 runner

**任务：**
把用户要求的“工业界相对较好的算法先摆到整条链路上”落成可运行诊断链路，而不是只停留在 coarse/fine/rerank 架构说明。

**遇到的问题：**
工业式链路需要同时覆盖 coarse、fine、rerank，但当前离线硬边界仍是 frozen pool200、`candidate_pool_size=200`、`top_k=5`，不能真实缩池、不能改召回语义，也不能把未来 online/Agent 指标写成当前 promotion。第一次 smoke 还暴露 normalized additive 权重越过 Phase 1.25 有限网格，直接被底座拒绝。

**定位方式：**
对照 `rs_core/recsys/ranking.py` 的 `coarse_rank_candidates → fine_rank_candidates → rerank_candidates`，确认已有 source weight、normalized additive、source-aware fusion、item-feature rerank 和 Top-K source minimums；再读取 `outputs/ranking/phase_6_industrial_ranking_chain_smoke/comparison.json`，核对 artifact inspection、frozen hash、stage assignment 和 promotion boundary。

**解决方式：**
新增 `scripts/run_phase_6_industrial_ranking_chain.py`，组合 `coarse_rank=source_weighted_metadata_shadow`、`fine_rank=normalized_additive + source_aware + item_feature full-pool scoring`、`rerank=top5 source minimum/stable tie-break`；新增 `tests/test_phase_6_industrial_ranking_chain.py`，并把 GBDT/LambdaMART、神经序列、Agent/online feedback 继续列为 blocked/future route。越界权重收回到 Phase 1.25 允许网格 `source_signal=0.2`、`item_feature=0.2`。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile scripts/run_phase_6_industrial_ranking_chain.py tests/test_phase_6_industrial_ranking_chain.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_phase_6_industrial_ranking_chain.py -q` 通过 `4 passed`；真实 smoke 产物 `outputs/ranking/phase_6_industrial_ranking_chain_smoke/comparison.json` 显示 `candidate_pool_size=200`、`top_k=5`、`artifact_inspection=PASS`、工业链路 `frozen_candidate_match=true`、`diagnostic_only=true`、`promotion_eligible=false`。

**面试可讲点：**
这轮可以讲成“把工业排序链路先接成可运行主路，同时用实验治理防止指标污染”：粗排、精排、重排都有对应算法和 artifact，但所有结论仍受 frozen pool、有限权重网格和 promotion gate 约束；发现权重越界后不是绕过检查，而是回到白名单网格重跑并验证通过。

### 2026-05-14 - Phase C 诊断门与 Phase A 收口顺序补齐

**任务：**
补充 Phase C 先行、Phase A 收口以及 learned/tree/neural 路线的中文叙事，并统一 oracle@5、target rank percentile、duplicate-source balance、win/tie/loss 的诊断口径。

**遇到的问题：**
原有长期计划主要覆盖 Phase 0/1/4/5/6 的持续实验顺序，但没有明确把 Phase C 定义成 tuning 前的诊断门，也没有把 Phase A 的合同固化位置和后续 learned/tree/neural 路线顺序写清楚，容易把诊断指标误写成晋升证据。

**定位方式：**
对照 `rs_core/recsys/evaluation.py` 的 `candidate_hit_rank_p90`、`source_overlap.multi_source_candidate_rate`、`source_pair_counts`、`source_pair_jaccard`，以及 `scripts/phase_1_20_recall_diagnostics.py` 的 raw oracle stage、`scripts/run_phase_5_fine_rank_positive_push.py` 的 `coarse_to_fine_improved_count` / `coarse_to_fine_worsened_count` / `coarse_to_fine_unchanged_count`，确认这些字段可以分别承载 oracle、rank percentile、duplicate-source balance 和 win/tie/loss 的叙事。

**解决方式：**
在 `dic/phases/RANKING_LONG_RUNNING_EXPLORATION_PLAN.md` 新增 Phase C→Phase A→learned/tree/neural 的路线说明，并明确 Phase C 只做 tuning 前诊断、Phase A 负责合同与快照收口、learned/tree/neural 只有在 same-run frozen valid/test 证据通过后才进入推进讨论；同时在工程日志里补齐这些指标的口径，避免把 LOPO、stage trace 或线上指标混入当前离线晋升。

**验证结果：**
相关定义可在 `rs_core/recsys/evaluation.py`、`scripts/phase_1_20_recall_diagnostics.py` 和 `scripts/run_phase_5_fine_rank_positive_push.py` 中直接对应到现有字段；本次只更新文档，没有改动 `candidate_pool_size=200`、`top_k=5` 或召回语义。

**面试可讲点：**
可以讲成“先把诊断门和晋升门拆开，再谈模型路线”：这样 Phase C 负责判断是否值得继续 tuning，Phase A 负责把合同边界固化，后续 learned/tree/neural 才能在同一证据框架里比较，不会把分析指标当成上线证据。

### 2026-05-14 - 默认离线主线收口与 Agent 手递边界

**任务：**
把长期排序路线收口为可供 Agent 系统直接交接的默认离线主线，明确当前目标是稳定可用的 handoff，而不是无限扩展算法族。

**遇到的问题：**
原有 Phase 0-8 叙事已经覆盖了实验顺序与门禁，但还缺少面向系统交接的终态说明，容易让后续 Agent 误把“继续探索更多算法”理解为默认工作目标。

**定位方式：**
对照 `dic/phases/RANKING_LONG_RUNNING_EXPLORATION_PLAN.md` 的 Phase C / Phase A / learned-tree-neural 叙事，确认当前最需要补的是默认主线职责、完成标准和 handoff 边界，而不是新增方法族。

**解决方式：**
在长期计划里补充默认离线 mainline 收口说明：把 `coarse → fine → rerank` 作为默认合同，继续锁定 `frozen pool200`、`candidate_pool_size=200`、`top_k=5` 和召回语义；Phase C 只保留诊断槽位；learned/tree/neural 只保留 future/blocked 位置；同时明确 Agent 系统只接收这条已经收口的主线，不再把方法族扩展当作默认目标。

**验证结果：**
本次仅更新中文文档与日志，没有改代码、没有改 runner、没有改评估口径，也没有动 `candidate_pool_size=200`、`top_k=5` 或召回语义。

**面试可讲点：**
可以讲成“把算法探索和系统交接分层”：先提供稳定、可复用、可交接的默认离线主线，再把更激进的 learned/tree/neural 路线留到明确门禁之后，避免 Agent 在不稳定边界上继续发散。



## 2026-05-15 - å·¥ç¨‹è§„èŒƒ v1.1ï¼šé…�ç½® contractã€�è„šæœ¬å…¥å�£ä¸Žè½»é‡� recsys å�•æµ‹

- ä»»åŠ¡ï¼šåœ¨å·¥ç¨‹è§„èŒƒ v1 åŸºç¡€ä¸Šç»§ç»­æŠŠâ€œå�£å¤´çº¦å®šâ€�è�½æˆ�å�¯æ‰§è¡Œé—¨ç¦�ï¼Œé‡�ç‚¹è¦†ç›–é…�ç½® contractã€�scripts å…¥å�£è§„èŒƒå’Œ recsys æ ¸å¿ƒè½»é‡�å�•æµ‹ã€‚
- é�‡åˆ°çš„é—®é¢˜ï¼šé…�ç½®å’Œè„šæœ¬æ•°é‡�å·²ç»�å¾ˆå¤šï¼Œå�•é� æ–‡æ¡£å¾ˆéš¾ä¿�è¯�ä¸�å‡ºçŽ°ä¸ªäººç»�å¯¹è·¯å¾„ã€�tracked ä¸´æ—¶é…�ç½®æˆ– import å�³æ‰§è¡Œçš„è„šæœ¬ï¼›å�Œæ—¶ `tests/test_hybrid_demo.py` è¿‡å¤§ï¼ŒåŸºç¡€å�¬å›ž/æŽ’åº�è¡Œä¸ºæ··åœ¨å®žéªŒæµ‹è¯•é‡Œä¸�åˆ©äºŽå¿«é€Ÿ CIã€‚
- å®šä½�æ–¹å¼�ï¼šç”¨ `git ls-files 'configs/*.yaml'` æ˜Žç¡® CI å�ªæ£€æŸ¥ tracked é…�ç½®ï¼›ç”¨ `scripts/validate_engineering_contracts.py` æ‰«æ�� 110 ä¸ª tracked é…�ç½®å’Œ 48 ä¸ªè„šæœ¬ï¼Œå�‘çŽ° 4 ä¸ªåŽ†å�²å� ä½�è„šæœ¬ç¼ºå°‘ main guardï¼›ç”¨æ–°å¢žå�•æµ‹éªŒè¯� contract è¾¹ç•Œã€‚
- è§£å†³æ–¹å¼�ï¼šæ–°å¢ž `rs_core/common/engineering_contracts.py` å’Œ `scripts/validate_engineering_contracts.py`ï¼Œå°†é…�ç½®å�¯åŠ è½½ã€�ç¦�æ­¢ tracked `_tmp` é…�ç½®ã€�ç¦�æ­¢ä¸ªäººæœºå™¨ç»�å¯¹è·¯å¾„ã€�è„šæœ¬ main guard å�˜ä¸ºå�¯æ‰§è¡Œæ£€æŸ¥ï¼›è¡¥é½� 4 ä¸ªå� ä½�è„šæœ¬çš„æœ€å°� `main()` éª¨æž¶ï¼›æ–°å¢ž `tests/test_recsys_core.py`ï¼Œä»Žå¤§æµ‹è¯•ä¸­æ‹†å‡º candidate mergeã€�ranking tie-breakã€�metadata neighbor recall ä¸‰ç±»åŸºç¡€è¡Œä¸ºã€‚
- éªŒè¯�ç»“æžœï¼š`scripts/validate_engineering_contracts.py` é€šè¿‡ï¼Œè¾“å‡º `Engineering contracts passed: 110 configs, 48 scripts`ï¼›æ–°å¢žå�•æµ‹ `8 passed`ï¼›CI Python èŒƒå›´ ruff é€šè¿‡ï¼›unit/smoke æœ€å°�é›†å�ˆæ”¶é›† 75 ä¸ªå¹¶ `75 passed`ï¼›`npm --prefix frontend run lint` é€šè¿‡ï¼›`git diff --check` æ—  whitespace é”™è¯¯ï¼Œä»…ä¿�ç•™ Windows æ�¢è¡Œæ��ç¤ºã€‚
- é�¢è¯•å�¯è®²ç‚¹ï¼šè¿™æ¬¡ä¸�æ˜¯æ³›æ³›å†™è§„èŒƒï¼Œè€Œæ˜¯æŠŠç›®å½•/é…�ç½®/è„šæœ¬/æµ‹è¯•çº¦å®šè½¬æˆ�è‡ªåŠ¨åŒ– contract gateï¼Œå¹¶ç”¨è½»é‡�å�•æµ‹ä»Žå¤§å®žéªŒæµ‹è¯•ä¸­æŠ½å‡ºç¨³å®šæ ¸å¿ƒè¡Œä¸ºï¼Œä½“çŽ°äº†â€œè§„èŒƒæ–‡æ¡£ + å�¯æ‰§è¡Œé—¨ç¦� + å¿«é€Ÿå��é¦ˆâ€�çš„å·¥ç¨‹åŒ–ç»´æŠ¤æ€�è·¯ã€‚


### 2026-05-15 - é…�ç½®ã€�æ–‡æ¡£ä¸Žè¾“å‡ºäº§ç‰©ç›®å½•æ²»ç�†

**ä»»åŠ¡ï¼š**
æŠŠ `configs/`ã€�`dic/`ã€�`outputs/` ä¸­é•¿æœŸå †ç§¯çš„é…�ç½®ã€�æ–‡æ¡£å’Œè¿�è¡Œäº§ç‰©æŒ‰è�Œè´£é‡�æ–°åˆ†å±‚ï¼Œå¹¶è¡¥é½�æ–°å¢žæ–‡æ¡£ã€�é…�ç½®å’Œä¸€æ¬¡æ€§å®žéªŒäº§ç‰©çš„è·¯ç”±è§„èŒƒã€‚

**é�‡åˆ°çš„é—®é¢˜ï¼š**
`configs/` æ ¹ç›®å½•æ··æœ‰å¤§é‡� hybrid demoã€�phase å’Œä¸´æ—¶è°ƒå�‚é…�ç½®ï¼›`dic/` æ ¹ç›®å½•å�Œæ—¶æ‰¿è½½æž¶æž„ã€�é˜¶æ®µã€�å®žéªŒæŠ¥å‘Šå’Œå…¥å�£æ–‡æ¡£ï¼›`outputs/` é¡¶å±‚æ··å�ˆ canonical demoã€�smokeã€�verificationã€�training å’Œ root æ–‡ä»¶ï¼Œå¯¼è‡´æ­£å¼�è¯�æ�®ä¸Žä¸€æ¬¡æ€§å®žéªŒäº§ç‰©ä¸�æ˜“åŒºåˆ†ã€‚

**å®šä½�æ–¹å¼�ï¼š**
å…ˆç»Ÿè®¡ `configs/`ã€�`dic/`ã€�`outputs/` æ ¹ç›®å½•æ–‡ä»¶å’Œå­�ç›®å½•ï¼Œå†�ç”¨è·¯å¾„æ‰«æ��ç¡®è®¤æ—§å¼•ç”¨æ˜¯å�¦ä»�æŒ‡å�‘ `configs/*.yaml`ã€�`outputs/phase_*`ã€�`outputs/hybrid_demo_small*` ç­‰æ—§ç»“æž„ï¼›éš�å�Žç”¨ `scripts/validate_engineering_contracts.py` æ ¡éªŒé…�ç½®å�¯åŠ è½½æ€§å’Œè„šæœ¬å…¥å�£è§„èŒƒã€‚

**è§£å†³æ–¹å¼�ï¼š**
å°†é…�ç½®åˆ†æµ�åˆ° `configs/demo/hybrid_demo/`ã€�`configs/ranking/<phase>/`ã€�`configs/recall/<phase>/`ï¼›å°†æ–‡æ¡£åˆ†æµ�åˆ° `dic/architecture/`ã€�`dic/decisions/`ã€�`dic/phases/`ã€�`dic/experiments/`ã€�`dic/guides/`ã€�`dic/standards/`ã€�`dic/archive/`ï¼›å°†è¾“å‡ºäº§ç‰©åˆ†æµ�åˆ° `outputs/agent/`ã€�`outputs/hybrid_demo/`ã€�`outputs/ranking/`ã€�`outputs/recall/`ã€�`outputs/simulation/`ã€�`outputs/training/`ã€�`outputs/verification/`ã€�`outputs/archive/root_files/`ã€‚å�Œæ—¶è¡¥å…… `DOCUMENT_ROUTING_GUIDE`ã€�`CONFIG_GUIDE`ã€�`OUTPUTS_ROUTING_GUIDE` å’Œå·¥ç¨‹è§„èŒƒä¸­çš„ä¸€æ¬¡æ€§å®žéªŒæ¸…ç�†è§„åˆ™ï¼Œå¹¶æŠŠ contract è„šæœ¬æ”¹ä¸ºæŒ‰å½“å‰� `configs/**/*.yaml` å·¥ä½œæ ‘é€’å½’æ ¡éªŒã€‚

**éªŒè¯�ç»“æžœï¼š**
`configs/` æ ¹ç›®å½•å·²æ—  `.yaml`ï¼Œæ—  `_tmp*.yaml`ï¼›`outputs/` é¡¶å±‚å�ªä¿�ç•™ `.gitkeep` å’Œ 8 ä¸ªè�Œè´£ç›®å½•ï¼›`dic/` æ ¹ç›®å½•å�ªä¿�ç•™ 4 ä¸ªå…¥å�£/é«˜é¢‘ç»´æŠ¤æ–‡æ¡£ã€‚æ—§è·¯å¾„æ‰«æ��å¯¹ `outputs/phase_*`ã€�`outputs/hybrid_demo_small*`ã€�`configs/hybrid_demo*.yaml`ã€�`configs/phase_*.yaml` æ— å‘½ä¸­ï¼›`./.venv/Scripts/python.exe scripts/validate_engineering_contracts.py` é€šè¿‡ï¼Œè¾“å‡º `Engineering contracts passed: 110 configs, 49 scripts`ï¼›`./.venv/Scripts/python.exe -m pytest tests/test_engineering_contracts.py tests/test_graph_walk_training.py -q` é€šè¿‡ `7 passed`ã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™è½®å�¯ä»¥è®²æˆ�â€œæŠŠå®žéªŒåž‹é¡¹ç›®ä»Žæ–‡ä»¶å †ç§¯æ²»ç�†æˆ�å�¯å¤�ç›˜å·¥ç¨‹èµ„äº§â€�ï¼šä¸�æ˜¯å�ªç§»åŠ¨æ–‡ä»¶ï¼Œè€Œæ˜¯å�Œæ­¥å»ºç«‹æ–‡æ¡£è·¯ç”±ã€�é…�ç½® contractã€�äº§ç‰©è·¯ç”±å’Œä¸€æ¬¡æ€§å®žéªŒæ¸…ç�†è§„åˆ™ï¼Œå¹¶ç”¨æ‰«æ��å’Œ contract éªŒè¯�é˜²æ­¢è·¯å¾„è¿�ç§»å�Žå¼•ç”¨æ–­è£‚ã€‚


## 2026-05-15 - 工程规范 v1.2：测试分层 marker contract

**任务：**
把测试分层从约定升级为可执行 contract：所有 `tests/test_*.py` 必须声明文件级 `pytestmark`，普通 CI 不再维护手工测试白名单，而是按 unit/smoke marker 自动选择快速门禁测试。

**遇到的问题：**
测试文件数量增加后，缺少统一 marker 会导致慢实验、GPU 训练或重依赖测试混入普通 CI；原 CI 手工列测试文件也容易遗漏新增的 Agent、serving 或 recsys 基础测试。目录重整后，`tests/test_serving_smoke.py` 还残留对旧 demo 配置和真实本地数据产物的依赖，放入 smoke gate 后暴露出路径与数据依赖问题。

**定位方式：**
先用 `scripts/validate_engineering_contracts.py` 让未标记测试显式失败，再为 32 个测试文件补齐 unit/smoke/experiment 等文件级 marker；随后用 `scripts/select_tests_by_marker.py --marker unit --marker smoke` 验证 selector 不导入测试模块即可选出快速门禁集合，并通过 collect/run 暴露 serving smoke 对旧真实数据目录的依赖。

**解决方式：**
在 `rs_core/common/engineering_contracts.py` 中新增基于 AST 的 marker 解析、未标记测试检查和 selector 复用逻辑；新增 `scripts/select_tests_by_marker.py`；CI 改为先选择 unit/smoke 文件，再执行 collect 和 pytest；同时把 serving smoke 中依赖真实 demo 数据的用例改为复用临时 fixture，保证普通门禁只验证服务 contract，不依赖本机历史产物。

**验证结果：**
`./.venv/Scripts/python.exe scripts/validate_engineering_contracts.py` 通过，输出 `Engineering contracts passed: 110 configs, 50 scripts, 32 tests`；selector + collect 选中并收集 139 个 unit/smoke 测试；`./.venv/Scripts/python.exe -m pytest -m "unit or smoke" -q` 通过 `139 passed`；`./.venv/Scripts/python.exe -m ruff check rs_core scripts/validate_engineering_contracts.py scripts/select_tests_by_marker.py tests` 通过；独立 verifier 结论为 PASS。

**面试可讲点：**
这轮可以讲成“把测试治理从人工白名单升级成自描述分层 contract”：测试文件自己声明层级，CI 自动选择稳定快速门禁，实验/GPU/慢测试不会污染普通提交，同时通过 smoke fixture 化消除了对本地历史数据产物的隐式依赖。


## 2026-05-15 - 工程规范 v1.3：组合 marker 与 serving 专项门禁

**任务：**
在 v1.2 测试分层契约基础上继续细化 marker 矩阵：让服务接口测试、慢实验、GPU 实验可以通过组合 marker 独立选择，同时保留默认 `unit or smoke` 快速门禁。

**遇到的问题：**
单一 marker 只能说明测试大类，无法表达“这是 smoke 也是 serving”“这是 experiment 也是 slow/GPU”这类运行边界。随着测试数量增加，如果不把服务、慢实验和 GPU 训练路径显式组合标记，后续 CI 很容易把重实验混入普通 PR，或者无法单独验证服务 contract。

**定位方式：**
先审计 `pyproject.toml`、`.github/workflows/ci.yml` 和 32 个 `tests/test_*.py` 文件，确认现有 marker 定义齐全但实际落标还集中在 unit/smoke/experiment。再按测试职责区分服务路径、慢实验路径和 GPU/训练路径，并用 selector 分别验证 `unit/smoke` 与 `serving` 能否独立选中目标文件。

**解决方式：**
为 `tests/test_serving_smoke.py` 和 `tests/test_simulation_runner.py` 标记 `serving + smoke`，为 `tests/test_agent_runtime.py` 标记 `unit + serving`，为 `tests/test_two_tower_training.py` 标记 `experiment + gpu`，为多个重实验测试标记 `experiment + slow`；同时更新 `dic/standards/ENGINEERING_STANDARDS.md` 的组合 marker 规则，并在 `.github/workflows/ci.yml` 中新增 serving 专项 select/collect/run，默认 CI 仍不新增 GPU/slow/experiment job。

**验证结果：**
独立 verifier 只读核验通过：32 个测试文件均有文件级 `pytestmark`；`serving` selector 选出 3 个服务相关文件；默认 `unit/smoke` selector 选出 19 个文件且未包含 slow/gpu experiment；`./.venv/Scripts/python.exe scripts/validate_engineering_contracts.py` 输出 `Engineering contracts passed: 110 configs, 50 scripts, 32 tests`；ruff 通过；`pytest -m "unit or smoke"` 通过 `139 passed`；`pytest -m "serving"` 通过 `34 passed`。

**面试可讲点：**
这轮可以讲成“测试矩阵治理”：不是简单给测试贴标签，而是把测试运行成本、依赖边界和 CI 入口显式建模。默认 PR 只跑快而稳定的门禁，服务 contract 可单独验证，慢实验和 GPU 训练不会无意进入普通 CI。


## 2026-05-15 - 工程规范 v1.4：scripts 瘦身最小切片

**任务：**
在工程规范 v1.x 的基础上推进 scripts 瘦身：选择一个低风险、已有测试覆盖的脚本逻辑，把稳定可复用能力下沉到 `rs_core`，让 `scripts/` 更接近“参数解析 + 流程触发”的入口层。

**遇到的问题：**
项目里不少脚本已经承载了实验流程和可复用业务逻辑。如果一次性大规模迁移，容易影响历史实验口径；但完全不迁移，又会让通用推荐逻辑散落在脚本中，后续复用和测试都变困难。

**定位方式：**
先做只读审计，优先寻找纯函数、小范围、已有测试覆盖的候选逻辑。最终选择 `scripts/build_recall_views.py` 中的 `unique_recent_items()`：它是 ItemCF 边构造前的最近序列去重逻辑，属于稳定推荐基础能力，且 `rs_core/recsys/candidate_merge.py` 已经集中承载候选合并与召回相关逻辑。

**解决方式：**
将 `unique_recent_items()` 下沉到 `rs_core/recsys/candidate_merge.py`，保留原有 reverse traversal、去重和 `appendleft` 的顺序语义；`scripts/build_recall_views.py` 改为 import 并复用该函数；同时在 `tests/test_build_recall_views.py` 新增 ItemCF 边构造用例，覆盖包含重复最近行为序列时的 pair 生成，防止迁移后语义漂移。

**验证结果：**
执行员定向验证 `./.venv/Scripts/python.exe -m pytest tests/test_build_recall_views.py tests/test_recsys_core.py -q` 通过 `6 passed`，engineering contracts 通过，ruff changed scope 通过。独立 verifier 只读核验确认：`unique_recent_items()` 仅在 `rs_core/recsys/candidate_merge.py` 定义，脚本只 import/reuse；新增测试覆盖最近去重后的 ItemCF pair；额外执行 `tests/test_build_recall_views.py tests/test_engineering_contracts.py` 通过 `12 passed`，ruff 通过，无本轮临时文件残留。

**面试可讲点：**
这轮可以讲成“脚本入口层治理的渐进式重构”：不是一口气重写实验脚本，而是用测试保护的小切片，把稳定业务能力从脚本下沉到核心包，降低复用成本，同时用定向测试和独立验证证明实验行为没有改变。


## 2026-05-15 - 工程规范 v1.5：scripts ruff 全量未使用项清理

**任务：**
在 v1.4 scripts 瘦身之后，继续把 `scripts/` 纳入更完整的 ruff 检查范围，清理历史脚本中暴露的 F401/F841 未使用导入和未使用变量。

**遇到的问题：**
提交前审计时，当前工程规范范围内的 ruff 已通过，但扩大到 `ruff check scripts` 后暴露出多个历史脚本的未使用 import / 变量。这些问题不会改变实验结果，但会阻碍后续把 scripts 纳入统一 lint 门禁。

**定位方式：**
用 `./.venv/Scripts/python.exe -m ruff check scripts` 复核失败清单，确认 19 个命中全部为 F401/F841，集中在少数脚本：`phase_1_20_recall_diagnostics.py`、`run_phase_1_26_real_learned_gbdt_ranker.py`、`run_phase_1_29_terminal_ranking_route.py`、`run_phase_c_ranking_actionability.py`、`run_phase_c_ranking_actionability_diagnostic.py`、`validate_recall_registry.py`、`verify_recall_outputs.py`。

**解决方式：**
只做最小安全清理：删除未使用 import，精简未使用 re-export import，移除未使用局部变量 `baseline_frozen`；不改业务流程、不改实验口径、不做脚本结构重构。

**验证结果：**
独立 verifier 确认 `./.venv/Scripts/python.exe -m ruff check scripts` 输出 `All checks passed!`；`./.venv/Scripts/python.exe scripts/validate_engineering_contracts.py` 输出 `Engineering contracts passed: 110 configs, 50 scripts, 32 tests`；diff 中 scripts 改动均为 unused import / unused variable 清理；未发现本轮临时文件残留。

**面试可讲点：**
这轮可以讲成“扩大工程门禁覆盖面前的历史债务清理”：先用 lint 暴露低风险、可机械修复的问题，再严格限制改动类型，只清理不会影响业务行为的未使用项，为后续把 `scripts/` 全量纳入 CI lint 打基础。

### 2026-05-16 - 代表性轻量 E2E 预检收口

**任务：**
在 `outputs/recall/full_main_route_other_methods/lightweight_representative_e2e` 的代表性 full-lightweight E2E 通过后，整理方法预检结果并把结论同步到实验日志和工程叙事日志。

**遇到的问题：**
这轮只有 Popular / Category / Semantic 的轻量候选生成真正跑通，ItemCF/co-visit、UserCF、Swing、graph_walk、two_tower、MF、sequence 等方法都不能被写成已执行结果，否则会把清单里的 disabled / deferred 状态误写成 promotion。

**定位方式：**
依据代表性 E2E 的 manifest/source audit 结果核对输出目录：`500` users、`75,866` candidate rows、`0` empty users，enabled sources 仅 `popular` / `category` / `semantic`，disabled sources 明确包含 `ItemCF`、`graph`、`two_tower`、`UserCF`、`Swing`、`MF`、`sequence`、`pool500`、`pool1000`，并且没有 `itemcf` / `graph` / `pool` 输出文件，也没有 10k source path。

**解决方式：**
只把已验证的 Popular / Category / Semantic 链路写成当前代表性结果；其余方法族统一按 `defer` / `document_only` / `fallback` 收口，保留为后续受控回跑或 sidecar 补齐项，不在本轮提升状态。

**验证结果：**
工程日志与实验日志都只记录同一份可回指证据：`outputs/recall/full_main_route_other_methods/lightweight_representative_e2e`。结论边界明确为“只确认轻量三源可用”，未把 ItemCF/co-visit、UserCF、Swing、graph_walk、two_tower、MF、sequence 伪装成已跑或已晋升。

**面试可讲点：**
这段可以讲成“用 manifest/source audit 给推荐实验划边界”：不是看见 E2E 成功就默认所有方法都能晋升，而是只按已验证产物收口，确保工程日志和方法日志对同一批证据保持一致。

### 2026-05-16 - Full-safe 召回方法全家桶 Phase 0-6 收口

**任务：**
按 Team+Ralph 的连续推进要求，把召回方法全家桶从 Phase 0 合同预检推进到 Phase 6 final method matrix，补齐 ItemCF/co-visit、UserCF、Swing/session、graph/MF、two_tower/pool readiness 的受控证据，并同步 PRD、进度与召回实验日志。

**遇到的问题：**
Phase 0 一开始发现 graph/two_tower/ranking pool200 配置仍引用 10k 路径；后续 Phase 6 首次汇总又因为 Phase 0 的 holdout contract 写在嵌套字段中，被 final matrix 误判为未证明 holdout exclusion。若直接跳过这些问题，会把 scope drift 或审计格式差异带入总验收。

**定位方式：**
通过 Phase 0 manifest/source audit 定位 10k config 引用；通过 Phase 4/5 的契约测试补充 config payload 内部 10k 引用检测；通过 Phase 6 失败输出定位到 `holdout_contract.candidate_generation_uses_holdout=false` 与后续阶段 top-level `candidate_generation_uses_holdout=false` 的字段格式差异。

**解决方式：**
为 graph、two_tower、ranking pool200 创建 full-safe 配置副本并让 Phase 0 默认解析这些副本；Phase 3 使用 bounded Swing/session observation，不做无界 pair counter；Phase 4/5 只做合同/feasibility gate，不训练、不晋升、不替代 frozen pool200；Phase 6 增加兼容 Phase 0 嵌套 holdout contract 的读取逻辑，并输出 `final_method_matrix_pass` 作为最终成功产物。

**验证结果：**
最终 canonical Phase 0 manifest 为 `PASS`；Phase 1 为 `EXECUTED_PASS_OBSERVATION_ONLY` 且 `recall_at_pool_delta=0.0`、`source_marginal_hit=0`；Phase 2 为 `rejected` 且 `failure_reason=no_positive_observation_lift`；Phase 3 为 `EXECUTED_PASS_OBSERVATION_ONLY`；Phase 4 为 `EXECUTED_PASS_CONTRACT_ONLY`；Phase 5 为 `EXECUTED_PASS_FEASIBILITY_ONLY`；Phase 6 `outputs/recall/full_main_route_other_methods/final_method_matrix_pass/manifest.json` 为 `PASS`，`final_method_matrix.json` 汇总 6 个 phase、`failures=[]`、`candidate_generation_uses_holdout=false`。

**面试可讲点：**
这段可以讲成“召回方法扩展不是盲目堆方法，而是先建立可审计合同”：用 source audit 防数据泄漏，用 bounded observation 控资源，用 final matrix 把每个方法族的晋升/拒绝/延期原因结构化，最后得出“本轮无新增方法晋升，但工程上获得可复跑、可解释、可继续扩展的召回方法矩阵”。

### 2026-05-17 - Representative pool500 recall-only 试验与 Gate 收口

**任务：**
在前一轮 pool500 只做到 readiness 的基础上，按“先 representative pool500、再决定 full”的路线补齐真实 recall-only 试验、same-scope 对比、审计和 Promote/Stop Gate。

**遇到的问题：**
此前 `pool500/pool1000=READINESS_ONLY_NOT_RANKING_INPUT` 只证明没有替代 ranking pool200，并没有回答 pool500 是否真的比 pool200 多召回用户；如果直接 full 或直接接 ranking，会把扩池实验和排序主线混在一起。

**定位方式：**
固定 500 个 representative users，分别生成同 scope 的 pool200 与 pool500 recall-only 候选，并在同一 `users_with_holdout=82` 分母下比较：pool200 `candidate_hit_users=4`、`recall_at_pool=0.042683`；pool500 `candidate_hit_users=6`、`recall_at_pool=0.055459`。

**解决方式：**
新增独立 P0-P6 pool500 representative 分支：P0-P2 生成同 scope pool200/pool500 候选；P3-P4 产出 `pool500_vs_pool200_same_scope_comparison.json`、`leakage_audit.json`、`resource_audit.json`、`ranking_isolation_audit.json`；P5 只做方法贡献观察；P6 生成 `promote_stop_gate.json`。全过程不进入 ranking、不生成 pool1000、不训练 graph/MF/two_tower、不复制 full clean。

**验证结果：**
`promote_stop_gate.json` 为 `PASS`，`exclusive_hit_users_201_500=2`，新增来源为 `category=1`、`popular=1`，`recall_at_pool_delta=0.012776`；duplicate、empty、fallback 均未恶化；leakage/resource/ranking isolation audits 均为 `PASS`。`tests/test_pool500_representative.py` 为 `5 passed`，相关脚本与测试 ruff 为 `All checks passed`，独立 verifier 给出 `APPROVED` 且 0 blockers。

**面试可讲点：**
这段可以讲成“把扩池从拍脑袋变成可审计 Gate”：不是直接把 pool500 切成默认样本，而是用同用户、同分母、同召回合同对比 pool200 和 pool500，证明 201-500 区间确实带来 2 个 exclusive hit users，再用 leakage/resource/ranking isolation 三重审计保证没有数据泄漏、资源越界或排序主线污染。

### 2026-05-17 - Representative pool500 全方法轻量与 CF 观察

**任务：**
在已 PASS 的 custom index 上补齐 pool500 all-methods representative 的轻量方法、bounded ItemCF/co-visit 与 bounded UserCF 观察，输出 recall-only 方法指标和审计证据。

**遇到的问题：**
轻量 pool500 候选已经存在，但 CF 不能复用全局无界共现或 dense all-user matrix；同时 candidate generation 不能读取 valid/test/holdout，也不能触碰 10k baseline、pool1000、ranking 或 graph/MF/two_tower 训练。

**定位方式：**
核验 `custom_index/manifest.json` 为 `PASS`，D 盘剩余约 204GiB，大于 50GiB 阈值；读取既有 pool500 candidates 与 indexed train sequences 的 schema，确认可以只基于 500 个 representative users 和 10739 个 custom items 构造局部 CF 证据。

**解决方式：**
新增 `scripts/run_pool500_all_methods_lightweight_cf.py`，复用已有 pool500 lightweight candidates 表示 popular/category/semantic；ItemCF/co-visit 只在 custom-index representative train sequences 上构建局部 item-item 共现邻居；UserCF 只构建 item->users 倒排并按 capped similar users 取候选，显式不生成 dense user-user matrix。

**验证结果：**
脚本运行产物 `outputs/recall/pool500_all_methods_representative/lightweight_cf_methods/manifest.json` 为 `PASS`；`method_metrics.json` 显示 lightweight `recall_at_pool=0.055459`、merged `recall_at_pool=0.055459`；`resource_audit.json` 记录 lightweight 193824 行、ItemCF 335 行、UserCF 14 行、merged 194149 行；`source_audit.json` 证明 candidate generation 只读 pool500 candidates、indexed train sequences、custom item index，valid/test 仅 evaluation-only。ruff 与 `py_compile` 均通过，独立约束核验输出 `candidate_reads_ok=true`、`artifacts_ok=true`。

**面试可讲点：**
这段可以讲成“在扩池 Gate 后继续做方法族消融，但不牺牲边界”：轻量方法提供 pool500 主体收益，CF 方法在代表性小样本上以 bounded observation 方式补充证据；即使本轮 CF 没带来 recall lift，也沉淀了可审计、可复跑、可扩展到 full pool500 前的资源与泄漏控制模板。

### 2026-05-17 - Representative pool500 全方法 custom-index Gate 收口

**任务：**
在 representative pool500 已经 Gate PASS 的基础上，按用户要求补齐主路全方法族试验：轻量源、bounded CF、Swing/session，以及 graph/MF/two_tower 的 custom-index feasibility/proxy probe，并用统一 Final Gate 决定是否允许继续 full pool500 recall-only。

**遇到的问题：**
直接跑 full pool500 或重模型训练会带来资源与范围风险；但只写 deferred 又无法回答“所有召回方法是否都试过”。需要在不复制 full clean、不读 holdout 做候选生成、不污染 ranking pool200 的前提下，为重方法构造可验证的定制索引试验边界。

**定位方式：**
先构建 `outputs/recall/pool500_all_methods_representative/custom_index/`，固定 500 users、10739 items、1289 train events；再分别检查 `lightweight_cf_methods/`、`sequence_session_methods/`、`heavy_indexed_probes/` 与 `final_gate/` 的 manifest/source_audit/resource_audit，确认候选生成不读 valid/test/holdout、无 10k source、无 pool1000、无 ranking replacement。

**解决方式：**
采用“custom index + 方法族 observation/probe + Final Gate”的路线：lightweight 表示 popular/category/semantic；ItemCF/UserCF 限定在 custom-index train scope，禁止 full global counter 与 dense all-user matrix；Swing/session 只构建 bounded pair/transition observation；graph/MF/two_tower 只做 feasibility/proxy，不训练、不晋升。Final Gate 输出 `decision=CONTINUATION_ONLY`，把允许范围限制为后续 recall-only full pool500 continuation。

**验证结果：**
`final_gate/promote_stop_gate.json` 为 `PASS`，`full_pool500_continuation_allowed=true`，但 `ranking_input_replacement_allowed=false`、`heavy_model_training_allowed_by_this_gate=false`、`pool1000_allowed=false`。`final_method_matrix.json` 覆盖 popular/category/semantic、bounded ItemCF/UserCF、Swing/session-transition、graph/MF/two_tower probes。`tests/test_pool500_all_methods_representative.py` 为 `5 passed in 0.09s`；相关 all-method scripts/tests ruff 为 `All checks passed`；独立 verifier `APPROVED` 且 0 blockers。

**面试可讲点：**
这段可以讲成“把全方法召回试验拆成安全可审计的分层 Gate”：轻量方法验证真实召回增量，CF/序列方法补充 bounded observation，重模型先做 custom-index feasibility 而不是盲目训练；最终用 source/resource/ranking isolation 三重审计把继续 full pool500 的权限限制在 recall-only，体现实验治理和工程边界控制。
