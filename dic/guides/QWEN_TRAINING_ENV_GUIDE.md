# Qwen QLoRA / SFT / GRPO 训练环境 Scaffold 指南

## 当前定位

本目录下的 Qwen 训练能力仍是 **environment scaffold**：用于校验配置、依赖 import、synthetic SFT/GRPO 样本 contract 和 reward adapter。它不代表已经完成真实 Qwen 训练，也不默认生成正式训练数据、下载模型或加载大模型。

当前路线保持为：`Qwen3.5-4B + QLoRA + SFT + GRPO`。真实训练数据后续应来自 Web Demo、Simulation、Session Replay 与 Agent rollout 的可校验轨迹，而不是在 scaffold 阶段临时伪造正式数据。

## 配置入口

- `configs/training/qwen_training_base.yaml`：训练环境基础配置。
- `configs/training/qwen_qlora_sft_smoke.yaml`：SFT smoke 配置，默认 `dry_run: true` 且 `sft.max_steps: 0`。
- `configs/training/qwen_grpo_smoke.yaml`：GRPO smoke 配置，默认 `dry_run: true` 且 `grpo.max_steps: 0`。

这些配置通过 `rs_core.common.config.load_config` 加载，并由 `rs_core.training.config.load_training_config` 合并安全默认值和校验。

## 数据 contract

`rs_core/training/data_contracts.py` 提供两类 synthetic smoke 样本：

- `synthetic_sft_samples()`：镜像 `rs_core/rsagent/rollout.py` 中 `training_samples.sft_sample` 的结构。
- `synthetic_grpo_samples()`：包装 prompt、completion、target_action 和 reward_sample，服务 GRPO reward adapter smoke。

默认样本只用于 contract 校验，不是正式训练数据。

## Reward adapter

`rs_core/training/reward_adapter.py` 将 `rs_agent_reward_sample_v1` 风格的 reward/evidence 转成 GRPO 可用的标量 reward：

- 若已有 `reward.total`，直接使用并裁剪到 `[-1, 1]`。
- 若只有 `reward_evidence`，按现有 `rs_core/rsagent/reward.py` 的思路重建轻量分数。
- `grpo_reward_function()` 提供 TRL reward function 形状，用于后续接入，不在默认 dry-run 中训练。

## Dry-run 命令

所有命令使用项目默认 `.venv`：

```bash
./.venv/Scripts/python.exe scripts/training/smoke_qwen_training_env.py
./.venv/Scripts/python.exe scripts/training/run_qwen_sft.py
./.venv/Scripts/python.exe scripts/training/run_qwen_grpo.py
```

默认 dry-run 只做：

1. 加载并校验训练配置。
2. 检查 `torch`、`transformers`、`accelerate`、`datasets`、`peft`、`trl` 等依赖是否可 import。
3. 校验 synthetic SFT/GRPO 样本。
4. 计算 reward adapter 输出。

Windows 下 `bitsandbytes` 可作为 optional warning，不应导致默认 smoke 失败。

## 重路径边界

默认 dry-run 不加载 Qwen、不下载模型、不初始化 trainer。只有显式传入以下参数之一时，runner 才允许进入重路径：

- `--init-only`：只初始化 model/tokenizer 后停止。
- `--max-steps > 0`：允许进入后续训练初始化路径。

重路径仍依赖本地环境中已准备好的模型、GPU/CPU 资源和训练依赖；scaffold 阶段不自动安装依赖、不自动下载模型。

## 轻量测试

```bash
./.venv/Scripts/python.exe -m pytest tests/test_training_config.py tests/test_training_data_contracts.py tests/test_training_reward_adapter.py -q
```

这些测试不依赖 GPU、不下载模型、不加载 Qwen。

## 后续接入边界

后续正式训练前需要补齐：

- 从 Agent rollout / Simulation / Web Demo session 中导出正式 SFT 样本。
- 明确 reward evidence、人工偏好、自动指标和安全过滤的版本口径。
- 为正式训练输出建立 artifact manifest、数据血缘和无泄漏审计。
- 将 heavy runner 与资源门禁、GPU 使用策略和远端训练流程对齐。
