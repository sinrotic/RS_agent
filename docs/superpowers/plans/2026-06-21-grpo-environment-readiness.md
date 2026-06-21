# GRPO Environment Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare and verify the Qwen GRPO execution environment for this repository, with clear gates for local dry-run, local init-only checks, and full GRPO training.

**Architecture:** Keep the repository training scaffold unchanged unless a verification step exposes a code defect. Use the existing GRPO runner, resource gate, training config, and synthetic reward contract as the source of truth. Treat local Windows execution as a smoke/init environment and require a higher-VRAM Linux or remote environment for full GRPO unless the resource gate is deliberately changed with tests.

**Tech Stack:** Python 3.13, PyTorch CUDA, Hugging Face Transformers, Accelerate, Datasets, PEFT, TRL, BitsAndBytes, Qwen/Qwen3.5-4B, pytest, PowerShell.

---

## Current Readiness Summary

Current local state observed on 2026-06-21:

- Repository GRPO scaffold exists:
  - `configs/training/qwen_grpo_smoke.yaml`
  - `scripts/training/run_qwen_grpo.py`
  - `rs_core/training/grpo_runner.py`
  - `rs_core/training/resource_gate.py`
  - `rs_core/training/qwen_loader.py`
- Project `.venv` launches outside the sandbox with Python 3.13.14.
- `.venv` has `torch==2.11.0+cu128`, `transformers==5.10.2`, `accelerate==1.13.0`, `datasets==4.8.2`, and `PyYAML==6.0.3`.
- `.venv` is missing `peft`, `trl`, and `bitsandbytes`.
- PyTorch sees CUDA and the GPU:
  - GPU: NVIDIA GeForce RTX 4070 Ti SUPER
  - total VRAM: 15.99 GiB
  - free VRAM during check: 14.73 GiB
- Qwen model cache is present:
  - `C:\Users\luo\.cache\huggingface\hub\models--Qwen--Qwen3.5-4B`
- Existing GRPO dry-run executes and returns JSON, but `resource_readiness.status` is `block`.
- Full local GRPO heavy path is not ready because:
  - missing imports: `peft`, `trl`, `bitsandbytes`
  - local VRAM is 15.99 GiB, while `rs_core/training/resource_gate.py` requires 20.0 GiB minimum and recommends 24.0 GiB for `workload="grpo"`.

Verdict:

- Local GRPO scaffold dry-run: ready enough to execute.
- Local model init-only: not ready until `peft`, `trl`, and quantization support are installed and verified.
- Full local GRPO training: not ready under the current resource gate because this GPU has less than 20 GiB VRAM.
- Full GRPO training target: use a remote/Linux GPU environment with at least 24 GiB VRAM, then bring artifacts back for local verification.

## File Structure

No source code changes are required for the first environment preparation pass. These files define the existing contract and verification surface:

- `requirements-training.txt`: training-only dependency list; update only if installation discovers an incompatible package name or version.
- `configs/training/qwen_grpo_smoke.yaml`: local GRPO smoke config; keep `dry_run: true`, `local_files_only: true`, and `grpo.max_steps: 0` for local checks.
- `scripts/training/run_qwen_grpo.py`: canonical GRPO runner entry point.
- `scripts/training/smoke_qwen_training_env.py`: broader training smoke entry point that checks SFT and GRPO readiness.
- `rs_core/training/grpo_runner.py`: GRPO orchestration and heavy-path guard.
- `rs_core/training/resource_gate.py`: authoritative local hardware and dependency gate.
- `rs_core/training/qwen_loader.py`: model, tokenizer, LoRA, and quantization initialization.
- `tests/test_training_resource_gate.py`: unit tests that define expected local/remote readiness behavior.
- `tests/test_training_config.py`: unit tests for safe training config defaults.

Create these files only if execution needs durable operator notes:

- Create: `docs/superpowers/plans/2026-06-21-grpo-environment-readiness.md`

## Task 1: Capture Baseline Evidence

**Files:**
- Read: `configs/training/qwen_grpo_smoke.yaml`
- Read: `requirements-training.txt`
- Read: `rs_core/training/resource_gate.py`
- Read: `rs_core/training/grpo_runner.py`
- Read: `rs_core/training/qwen_loader.py`
- No source modifications.

- [ ] **Step 1: Verify repository GRPO files exist**

Run:

```powershell
Test-Path configs\training\qwen_grpo_smoke.yaml
Test-Path scripts\training\run_qwen_grpo.py
Test-Path rs_core\training\grpo_runner.py
Test-Path rs_core\training\resource_gate.py
Test-Path rs_core\training\qwen_loader.py
```

Expected:

```text
True
True
True
True
True
```

- [ ] **Step 2: Record the active Python interpreter**

Run:

```powershell
.\.venv\Scripts\python.exe -c "import sys; print(sys.executable); print(sys.version)"
```

Expected:

```text
D:\sinrotic_code\python_project\summer\RS_agent\.venv\Scripts\python.exe
3.13.14 ...
```

- [ ] **Step 3: Record installed training packages**

Run:

```powershell
.\.venv\Scripts\python.exe -m pip show torch transformers accelerate datasets peft trl bitsandbytes PyYAML
```

Expected before dependency installation:

```text
Name: torch
Version: 2.11.0+cu128
...
Name: transformers
Version: 5.10.2
...
Name: accelerate
Version: 1.13.0
...
Name: datasets
Version: 4.8.2
...
Name: PyYAML
Version: 6.0.3
...
WARNING: Package(s) not found: bitsandbytes, peft, trl
```

- [ ] **Step 4: Record CUDA visibility**

Run:

```powershell
.\.venv\Scripts\python.exe -c "import torch; print('torch', torch.__version__); print('cuda_available', torch.cuda.is_available()); print('device_count', torch.cuda.device_count()); print('device', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none'); print('vram_total_gib', round(torch.cuda.get_device_properties(0).total_memory/1024**3,2) if torch.cuda.is_available() else 0); print('mem_info_gib', tuple(round(x/1024**3,2) for x in torch.cuda.mem_get_info(0)) if torch.cuda.is_available() else None)"
```

Expected on the current local machine:

```text
torch 2.11.0+cu128
cuda_available True
device_count 1
device NVIDIA GeForce RTX 4070 Ti SUPER
vram_total_gib 15.99
mem_info_gib (..., 15.99)
```

- [ ] **Step 5: Commit only the plan if the user wants the plan versioned**

Run:

```powershell
git add docs\superpowers\plans\2026-06-21-grpo-environment-readiness.md
git commit -m "docs: add grpo environment readiness plan"
```

Expected:

```text
[branch ...] docs: add grpo environment readiness plan
```

Skip this step unless the user explicitly asks for a commit.

## Task 2: Install Missing Training Dependencies in `.venv`

**Files:**
- Read: `requirements-training.txt`
- No source modifications unless a package version is proven incompatible.

- [ ] **Step 1: Confirm missing imports before installing**

Run:

```powershell
.\.venv\Scripts\python.exe -c "import importlib.util as u; print({name: bool(u.find_spec(name)) for name in ['torch','transformers','accelerate','datasets','peft','trl','bitsandbytes','yaml']})"
```

Expected before installation:

```text
{'torch': True, 'transformers': True, 'accelerate': True, 'datasets': True, 'peft': False, 'trl': False, 'bitsandbytes': False, 'yaml': True}
```

- [ ] **Step 2: Install the missing packages**

Run:

```powershell
.\.venv\Scripts\python.exe -m pip install peft trl bitsandbytes
```

Expected:

```text
Successfully installed ...
```

If `bitsandbytes` fails on Windows, run:

```powershell
.\.venv\Scripts\python.exe -m pip install peft trl
```

Expected:

```text
Successfully installed peft ... trl ...
```

Record the `bitsandbytes` failure text in the final execution notes. Do not edit `rs_core/training/resource_gate.py` just to bypass the blocker.

- [ ] **Step 3: Confirm imports after installation**

Run:

```powershell
.\.venv\Scripts\python.exe -c "import importlib.util as u; print({name: bool(u.find_spec(name)) for name in ['torch','transformers','accelerate','datasets','peft','trl','bitsandbytes','yaml']})"
```

Expected if all packages install:

```text
{'torch': True, 'transformers': True, 'accelerate': True, 'datasets': True, 'peft': True, 'trl': True, 'bitsandbytes': True, 'yaml': True}
```

Expected if Windows cannot support local `bitsandbytes`:

```text
{'torch': True, 'transformers': True, 'accelerate': True, 'datasets': True, 'peft': True, 'trl': True, 'bitsandbytes': False, 'yaml': True}
```

- [ ] **Step 4: Re-run GRPO dry-run**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\training\run_qwen_grpo.py --config configs\training\qwen_grpo_smoke.yaml
```

Expected if `bitsandbytes` is installed but local VRAM remains below the GRPO gate:

```json
{
  "mode": "grpo",
  "dry_run": true,
  "resource_readiness": {
    "workload": "grpo",
    "status": "block",
    "can_run_locally": false,
    "blockers": [
      {
        "reason": "insufficient_total_vram"
      }
    ]
  },
  "heavy_path_entered": false
}
```

Expected if `bitsandbytes` is still missing:

```json
{
  "mode": "grpo",
  "dry_run": true,
  "resource_readiness": {
    "workload": "grpo",
    "status": "block",
    "can_run_locally": false,
    "blockers": [
      {
        "reason": "missing_required_imports"
      },
      {
        "reason": "insufficient_total_vram"
      }
    ]
  },
  "heavy_path_entered": false
}
```

## Task 3: Verify Local Smoke and Inference Boundaries

**Files:**
- Read: `scripts/training/smoke_qwen_training_env.py`
- Read: `configs/training/qwen_grpo_smoke.yaml`
- No source modifications.

- [ ] **Step 1: Run broad training smoke check without model load**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\training\smoke_qwen_training_env.py --config configs\training\qwen_grpo_smoke.yaml
```

Expected:

```json
{
  "ok": true,
  "config": "qwen_grpo_smoke",
  "dry_run": true,
  "sft_sample_count": 1,
  "grpo_sample_count": 1,
  "model_load_checked": false
}
```

The exact `resource_readiness.grpo.status` may remain `block` on this machine because the GRPO VRAM requirement is 20 GiB.

- [ ] **Step 2: Decide whether local init-only is useful**

Run this read-only check first:

```powershell
.\.venv\Scripts\python.exe -c "from rs_core.training.config import load_training_config; from rs_core.training.qwen_loader import check_training_imports; from rs_core.training.resource_gate import assess_qwen_resource_readiness; c=load_training_config('configs/training/qwen_grpo_smoke.yaml'); r=assess_qwen_resource_readiness(c, workload='inference', import_status=check_training_imports()); print(r.to_dict())"
```

Expected when local inference is allowed:

```text
'workload': 'inference'
'can_run_locally': True
'blockers': []
```

If inference has blockers, do not run `--init-only`; resolve those blockers first.

- [ ] **Step 3: Run local model init-only only if inference readiness has no blockers**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\training\run_qwen_grpo.py --config configs\training\qwen_grpo_smoke.yaml --init-only
```

Expected if the local model and quantization stack initialize:

```json
{
  "mode": "grpo",
  "heavy_path_entered": true,
  "model_type": "...",
  "tokenizer_type": "...",
  "lora_config_type": "LoraConfig"
}
```

Expected if the GRPO resource gate blocks local heavy path:

```text
RuntimeError: Local GRPO resource gate blocked heavy path: ...
```

That error means the code is following the current safety gate; it is not a failed smoke check.

## Task 4: Prepare the Remote Full-GRPO Environment

**Files:**
- Copy/read on remote: `requirements-training.txt`
- Copy/read on remote: `configs/training/qwen_grpo_smoke.yaml`
- Copy/read on remote: `scripts/training/run_qwen_grpo.py`
- Copy/read on remote: `rs_core/training/*.py`
- No local source modifications.

- [ ] **Step 1: Provision a remote/Linux GPU environment**

Minimum target:

```text
OS: Linux
Python: 3.10, 3.11, 3.12, or 3.13
GPU VRAM: >= 24 GiB recommended
Disk free: >= 60 GiB
RAM: >= 24 GiB
CUDA visible to PyTorch
```

Run on remote:

```bash
nvidia-smi
python --version
```

Expected:

```text
NVIDIA-SMI ...
CUDA Version: ...
Python 3...
```

- [ ] **Step 2: Create an isolated remote virtual environment**

Run on remote from the repository root:

```bash
python -m venv .venv-grpo
source .venv-grpo/bin/activate
python -m pip install --upgrade pip
```

Expected:

```text
Successfully installed pip-...
```

- [ ] **Step 3: Install training dependencies on remote**

Run on remote:

```bash
python -m pip install -r requirements-training.txt
python -m pip install -e .
```

Expected:

```text
Successfully installed ...
Successfully installed rs-agent-0.1.0
```

- [ ] **Step 4: Verify remote dependency imports**

Run on remote:

```bash
python -c "import importlib.util as u; print({name: bool(u.find_spec(name)) for name in ['torch','transformers','accelerate','datasets','peft','trl','bitsandbytes','yaml']})"
```

Expected:

```text
{'torch': True, 'transformers': True, 'accelerate': True, 'datasets': True, 'peft': True, 'trl': True, 'bitsandbytes': True, 'yaml': True}
```

- [ ] **Step 5: Verify remote CUDA through PyTorch**

Run on remote:

```bash
python -c "import torch; print('torch', torch.__version__); print('cuda_available', torch.cuda.is_available()); print('device_count', torch.cuda.device_count()); print('device', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none'); print('vram_total_gib', round(torch.cuda.get_device_properties(0).total_memory/1024**3,2) if torch.cuda.is_available() else 0)"
```

Expected:

```text
cuda_available True
device_count 1
vram_total_gib 24.0
```

The actual `vram_total_gib` may be higher than 24.0.

- [ ] **Step 6: Prepare Qwen model cache on remote**

Run on remote:

```bash
python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='Qwen/Qwen3.5-4B')"
```

Expected:

```text
Fetching ... files
...
```

After download, keep `configs/training/qwen_grpo_smoke.yaml` with:

```yaml
model:
  model_id: Qwen/Qwen3.5-4B
  local_files_only: true
```

- [ ] **Step 7: Run remote GRPO dry-run**

Run on remote:

```bash
python scripts/training/run_qwen_grpo.py --config configs/training/qwen_grpo_smoke.yaml
```

Expected:

```json
{
  "mode": "grpo",
  "dry_run": true,
  "sample_count": 1,
  "rewards": [
    0.7
  ],
  "resource_readiness": {
    "workload": "grpo",
    "status": "pass",
    "can_run_locally": true,
    "blockers": []
  },
  "heavy_path_entered": false
}
```

- [ ] **Step 8: Run remote init-only**

Run on remote:

```bash
python scripts/training/run_qwen_grpo.py --config configs/training/qwen_grpo_smoke.yaml --init-only
```

Expected:

```json
{
  "mode": "grpo",
  "heavy_path_entered": true,
  "model_type": "...",
  "tokenizer_type": "...",
  "lora_config_type": "LoraConfig"
}
```

- [ ] **Step 9: Run a one-step remote GRPO trainer initialization**

Run on remote:

```bash
python scripts/training/run_qwen_grpo.py --config configs/training/qwen_grpo_smoke.yaml --max-steps 1
```

Expected:

```json
{
  "mode": "grpo",
  "dry_run": false,
  "heavy_path_entered": true,
  "trainer_class": "GRPOTrainer"
}
```

This current repository path initializes the trainer class but does not yet perform a full dataset-backed training loop. Treat this as an execution-environment gate, not as completed GRPO training.

## Task 5: Run Regression Tests for the Existing Training Scaffold

**Files:**
- Test: `tests/test_training_config.py`
- Test: `tests/test_training_data_contracts.py`
- Test: `tests/test_training_reward_adapter.py`
- Test: `tests/test_training_resource_gate.py`

- [ ] **Step 1: Run focused training unit tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_training_config.py tests\test_training_data_contracts.py tests\test_training_reward_adapter.py tests\test_training_resource_gate.py -q
```

Expected:

```text
... passed
```

- [ ] **Step 2: Run GRPO dry-run after tests**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\training\run_qwen_grpo.py --config configs\training\qwen_grpo_smoke.yaml
```

Expected on this local machine until a higher-VRAM environment is used:

```json
{
  "mode": "grpo",
  "dry_run": true,
  "heavy_path_entered": false,
  "resource_readiness": {
    "workload": "grpo",
    "status": "block",
    "can_run_locally": false
  }
}
```

- [ ] **Step 3: Commit dependency documentation only if files changed**

Run only if `requirements-training.txt` or docs were edited:

```powershell
git status --short
git add requirements-training.txt docs\superpowers\plans\2026-06-21-grpo-environment-readiness.md
git commit -m "docs: document grpo environment readiness"
```

Expected:

```text
[branch ...] docs: document grpo environment readiness
```

Skip this step unless the user explicitly asks for a commit.

## Self-Review

Spec coverage:

- Checked whether the current GRPO environment is ready.
- Identified current ready state: dry-run can execute.
- Identified current blockers: missing `peft`, `trl`, `bitsandbytes`; local VRAM below the GRPO gate.
- Provided a local dependency preparation path.
- Provided a remote full-GRPO environment path.
- Included exact files, commands, and expected outputs.

Placeholder scan:

- No `TBD`, `TODO`, `implement later`, or unspecified validation steps remain.

Type and command consistency:

- Commands consistently use `.venv\Scripts\python.exe` for local Windows checks.
- Commands consistently use `python` inside the activated remote Linux virtual environment.
- GRPO runner command consistently targets `scripts/training/run_qwen_grpo.py` with `configs/training/qwen_grpo_smoke.yaml`.
