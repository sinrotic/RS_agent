# RS Agent Phase 5 Offline 入口与 legacy 调用点清单

本文档服务于 `RS_AGENT_POST_MIGRATION_HARDENING_PLAN.md` Phase 5：记录训练、评估、仿真、实验和模型 artifact 注册入口分层、legacy 调用点与安全迁移证据。本文只描述当前事实和后续边界；旧 `rs_core/training`、`rs_core/evaluation` 与 `rs_core/simulation` 均已完成物理退役。

## 1. 当前结论

Phase 5 已完成一条轻量 canonical contract/smoke 路线：

```text
scripts/training/offline_engine_cli.py
scripts/evaluation/offline_engine_cli.py
scripts/experiments/engine_cli.py
  -> rs_core.offline.runtime.worker
  -> rs_core.offline.runtime.composition.get_offline_engine()
  -> rs_core.offline.engine.OfflineModelEngine
```

这条路线只负责 dry-run / smoke / resource estimate / artifact contract，不触发重训练、全量评估、模型加载或外部服务。

与此同时，训练真实业务实现已迁入：

```text
rs_core/offline/training/*
scripts/training/*.py
相关 tests
```

Agent evaluation artifact / scorecard 已迁入 `rs_core/offline/evaluation`，`scripts/evaluation/run_agent_evaluation.py` 与相关 tests 已切到 canonical import；simulation schema/policy/presets/runner/model client 已迁入 `rs_core/offline/simulation`，`scripts/evaluation/run_simulation_evaluation.py`、Agent sandbox facade 与相关 tests 已切到 canonical import；训练配置、数据契约、Qwen/SFT/GRPO/GPT SFT、judge、reward 与 multi-turn SFT generator 已迁入 `rs_core/offline/training`。旧 `rs_core/training`、`rs_core/evaluation` 和 `rs_core/simulation` active package 均已删除。

## 2. 入口分层

| 层级 | 当前文件 | 状态 | 说明 |
| --- | --- | --- | --- |
| canonical wrapper | `scripts/training/offline_engine_cli.py` | 已路由 | 薄封装，调用 `rs_core.offline.runtime.worker`。 |
| canonical wrapper | `scripts/evaluation/offline_engine_cli.py` | 已路由 | 薄封装，调用 `rs_core.offline.runtime.worker`。 |
| canonical wrapper/router | `scripts/experiments/engine_cli.py` | 已路由 | 默认 route 为 `offline` 时转发到 offline worker；`agent` route 只返回 Agent route marker。 |
| worker entry | `rs_core.offline.runtime.worker/main.py` | 已路由 | 提供 health、training dry-run、artifact register、evaluation smoke、resource estimate、experiment smoke、simulation smoke。 |
| worker dependency | `rs_core.offline.runtime.worker/dependencies.py` | 已路由 | 缓存并返回 `OfflineModelEngine`。 |
| canonical engine | `rs_core/offline/engine/__init__.py` | 已落地轻量 contract | 只生成 dry-run/smoke contract，不执行真实训练或全量评估。 |
| canonical contracts | `rs_core/offline/contracts/__init__.py` | 已落地轻量 contract | 定义 resource estimate、training job、model artifact、metric report、evaluation job/result、experiment run、offline simulation result。 |
| canonical implementation | `rs_core/offline/training/` | 已独立实现 | 承接 training config、data contracts、Qwen loader、resource gate、SFT/GRPO/GPT SFT runner、SFT judge、reward adapter 与 multi-turn SFT generator；`OFFLINE_DEFERRED_CONTRACT` 标记 implemented，不再 re-export 旧路径。 |
| canonical implementation | `rs_core/offline/evaluation/__init__.py` | 已独立实现 | 明确导出 Agent evaluation artifact / scorecard API，不再 re-export 旧路径。 |
| canonical implementation | `rs_core/offline/simulation/` | 已独立实现 | 承接 simulation schema/policy/presets/runner/model client；`OFFLINE_SIMULATION_CONTRACT` 标记 implemented，不再 re-export 旧路径。 |
| contract namespace | `rs_core/offline/experiments/__init__.py` | 轻量 contract | 当前只导出 `ExperimentRunContract`。 |
| retired implementation | `rs_core/training/*` | 已删除 | 训练配置、数据契约、Qwen/SFT/GRPO/GPT SFT、judge 与 reward 逻辑已迁入 `rs_core/offline/training/`。 |
| retired implementation | `rs_core/evaluation/*` | 已删除 | Agent evaluation artifact 与 scorecard 逻辑已迁入 `rs_core/offline/evaluation/`。 |
| retired implementation | `rs_core/simulation/*` | 已删除 | simulation schema / policy / presets / runner / model client 逻辑已迁入 `rs_core/offline/simulation/`。 |
| canonical script consumers | `scripts/training/*.py` | 已迁移 import | Qwen/SFT/GRPO/GPT SFT/judge/multi-turn 训练脚本直接 import `rs_core.offline.training.*`；是否执行重训练仍由 dry-run/resource gate 控制。 |
| canonical script consumer | `scripts/evaluation/run_agent_evaluation.py` | 已迁移 | 直接 import `rs_core.offline.evaluation.agent_artifact`，并通过 `rs_core.offline.simulation` 运行 simulation batch。 |
| canonical script consumer | `scripts/evaluation/run_simulation_evaluation.py` | 已迁移 | 直接 import `rs_core.offline.simulation` 和 `rs_core.offline.simulation.model_client`。 |

## 3. 已路由到 OfflineModelEngine 的入口

- `scripts/training/offline_engine_cli.py`：薄封装，调用 `rs_core.offline.runtime.worker`。
- `scripts/evaluation/offline_engine_cli.py`：薄封装，调用 `rs_core.offline.runtime.worker`。
- `scripts/experiments/engine_cli.py`：默认 `--route offline` 时调用 `rs_core.offline.runtime.worker`。
- `rs_core.offline.runtime.worker/main.py`：所有子命令都只调用 `OfflineModelEngine` 的 lightweight contract/smoke 方法。
- `tests/contracts/test_architecture_migration_boundaries.py::test_script_wrappers_route_to_new_engines`：固定上述 wrapper route 不回退。
- `tests/offline/test_offline_engine_contracts.py`：固定 dry-run training、heavy job refusal、artifact/evaluation public-safe、experiment/simulation smoke 和 module execution 无 RuntimeWarning。

## 4. Training canonical import 状态

### 4.1 Training scripts

这些脚本已直接使用 `rs_core.offline.training.*`，旧 `rs_core.training.*` 调用点清零：

- `scripts/training/smoke_qwen_training_env.py`
- `scripts/training/run_qwen_sft.py`
- `scripts/training/run_qwen_grpo.py`
- `scripts/training/run_gpt_sft_api.py`
- `scripts/training/judge_sft_samples.py`
- `scripts/training/generate_multi_turn_sft.py`

当前 canonical training 能力包括 training config、data contracts、Qwen loader、resource gate、reward adapter、SFT runner、GRPO runner、GPT SFT runner、SFT judge 与 multi-turn SFT generator。脚本迁移不等于默认执行真实训练；Qwen/SFT/GRPO/GPT SFT 仍必须通过 dry-run、`--init-only`、`--max-steps` 和资源门禁控制重路径。

### 4.2 Evaluation / simulation scripts

- `scripts/evaluation/run_agent_evaluation.py` 已切到 `rs_core.offline.evaluation.agent_artifact` 和 `rs_core.offline.simulation`，不再依赖旧 `rs_core.evaluation` / `rs_core.simulation`。
- `scripts/evaluation/run_simulation_evaluation.py` 已切到 `rs_core.offline.simulation` 与 `rs_core.offline.simulation.model_client`，不再依赖旧 `rs_core.simulation`。

### 4.3 Tests

测试层已改为对 canonical offline training/evaluation/simulation 入口做直接覆盖：

- `tests/agent/test_multi_turn_sft_generator.py`
- `tests/agent/test_agent_scorecard.py`
- `tests/agent/test_agent_eval_artifact.py`
- `tests/agent/test_agent_simulation_contract.py`
- `tests/test_simulation_runner.py`
- `tests/test_simulation_roles.py`
- `tests/test_gpt_sft_api.py`
- `tests/test_training_config.py`
- `tests/test_training_data_contracts.py`
- `tests/test_training_resource_gate.py`
- `tests/test_training_reward_adapter.py`

## 5. 建议迁移顺序

后续推进应按“先入口、后实现；先 smoke/dry-run、后真实执行；先资源门禁、后重任务”的顺序：

1. 保持三个 canonical wrapper 入口不变，继续让它们只走 `rs_core.offline.runtime.worker`。
2. 先迁移边界更清晰的轻量脚本：`smoke_qwen_training_env.py`、`generate_multi_turn_sft.py`、`judge_sft_samples.py`。
3. 再处理重训练相关脚本：`run_qwen_sft.py`、`run_qwen_grpo.py`、`run_gpt_sft_api.py`；迁移前必须保留或增强资源门禁，不能默认加载大模型或启动训练。
4. `scripts/evaluation/run_agent_evaluation.py` 与真实 scorecard/artifact 逻辑已完成 canonical evaluation 迁移；simulation 脚本、Agent sandbox facade 与 tests 已完成 canonical offline simulation 迁移。
5. `rs_core/offline/training`、`rs_core/offline/evaluation` 与 `rs_core/offline/simulation` 均已从 star-export facade 改为明确 canonical API。
6. 旧 `rs_core/training` 已完成 import census 清零、focused smoke 和资源门禁测试后物理退役；后续重点转为训练脚本是否全部 worker 化、成熟实验迁移和模型 artifact 注册。

## 6. 当前不应勾选的 Phase 5 项

- `scripts/training`、`scripts/experiments` 已全部只依赖 offline engine。
- Qwen SFT / GRPO / GPT SFT 重训练脚本已完成 offline worker 化。
- DeepFM / COLD 真实训练输出已统一注册 model artifact。

## 7. 验证证据

当前 census 记录 Phase 5 lightweight contract/smoke、training/evaluation/simulation 物理迁移边界；lightweight contract/smoke 的已验证命令记录在 `RS_AGENT_MIGRATION_VALIDATION_EVIDENCE.md`，training/evaluation/simulation 迁移另以 focused tests、ruff、AST census 和 path-not-exists guard 验证：

```bash
.venv/Scripts/python.exe -m pytest tests/offline/test_offline_engine_contracts.py tests/contracts/test_architecture_migration_boundaries.py::test_worker_entrypoints_are_engine_backed_and_lightweight -q
# 6 passed in 0.64s

.venv/Scripts/python.exe scripts/ci/run_migration_hardening_checks.py --skip-compose-config
# 417 passed in 17.52s
# OpenAPI snapshots are up to date
# generated frontend\src\types\index.ts
# All checks passed!

.venv/Scripts/python.exe -m pytest tests/agent/test_agent_scorecard.py tests/agent/test_agent_eval_artifact.py tests/offline/test_offline_engine_contracts.py tests/contracts/test_architecture_migration_boundaries.py -q
# 48 passed

.venv/Scripts/python.exe -m ruff check rs_core/offline/evaluation scripts/evaluation/run_agent_evaluation.py tests/agent/test_agent_scorecard.py tests/agent/test_agent_eval_artifact.py tests/offline/test_offline_engine_contracts.py tests/contracts/test_architecture_migration_boundaries.py
# All checks passed!

# AST census: rs_core.evaluation import in rs_core/tests/scripts
# []

.venv/Scripts/python.exe -m pytest tests/test_simulation_runner.py tests/test_simulation_roles.py tests/agent/test_agent_simulation_contract.py tests/agent/test_multi_turn_sft_generator.py tests/offline/test_offline_engine_contracts.py tests/contracts/test_architecture_migration_boundaries.py -q
# 108 passed in 15.64s

.venv/Scripts/python.exe -m ruff check rs_core/offline/simulation rs_core/agent/simulation rs_core/serving/api/routers/simulation.py rs_core/training/multi_turn_sft_generator.py scripts/evaluation/run_simulation_evaluation.py scripts/evaluation/run_agent_evaluation.py tests/test_simulation_runner.py tests/test_simulation_roles.py tests/agent/test_agent_simulation_contract.py tests/agent/test_multi_turn_sft_generator.py tests/offline/test_offline_engine_contracts.py tests/contracts/test_architecture_migration_boundaries.py
# All checks passed!

# AST census: rs_core.simulation import in rs_core/tests/scripts
# []

.venv/Scripts/python.exe -m pytest tests/test_training_config.py tests/test_training_data_contracts.py tests/test_training_reward_adapter.py tests/test_training_resource_gate.py tests/test_gpt_sft_api.py tests/agent/test_multi_turn_sft_generator.py tests/offline/test_offline_engine_contracts.py tests/contracts/test_architecture_migration_boundaries.py
# 117 passed in 12.28s

# AST census: rs_core.training import in rs_core/tests/scripts
# []
```
