import os
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "java_agent/deploy/remote/model/start_qwen35_4b_vllm.sh"
BASH = str(Path("D:/software/Git/bin/bash.exe")) if os.name == "nt" else shutil.which("bash")


@pytest.mark.parametrize("probe_exit", [0, 1])
@pytest.mark.parametrize("tuning", [False, True])
def test_readiness_requires_successful_structured_output_probe(tmp_path, probe_exit, tuning):
    if not BASH or not Path(BASH).exists():
        pytest.skip("bash unavailable")
    runtime = tmp_path / "runtime.sh"
    runtime.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$CAPTURE_ARGS"\n', encoding="utf-8")
    runtime.chmod(0o755)
    warmup = tmp_path / "warmup.py"
    warmup.write_text("pass\n", encoding="utf-8")
    probe = tmp_path / "probe.py"
    probe.write_text(f"import sys\nsys.exit({probe_exit})\n", encoding="utf-8")
    ready = tmp_path / "ready"
    ready.write_text("stale", encoding="utf-8")
    args_file = tmp_path / "runtime-args.txt"
    env = {
        **os.environ,
        "VLLM_BIN": runtime.as_posix(), "PYTHON_BIN": sys.executable.replace("\\", "/"),
        "WARMUP_SCRIPT": warmup.as_posix(), "PROBE_SCRIPT": probe.as_posix(),
        "VLLM_READY_FILE": ready.as_posix(), "VLLM_PREFIX_KEEPALIVE": "false",
        "VLLM_ENFORCE_STRICT_TOOL_CALLING": "true", "VLLM_STRUCTURED_OUTPUT_PROBE": "true",
        "VLLM_STRUCTURED_OUTPUTS_BACKEND": "xgrammar", "CAPTURE_ARGS": args_file.as_posix(),
        "VLLM_EXTRA_WARMUP_CONCURRENCY": "0",
    }
    if tuning:
        env.update({"VLLM_LANGUAGE_MODEL_ONLY": "true", "VLLM_MAX_NUM_BATCHED_TOKENS": "4096",
                    "VLLM_MAX_NUM_SEQS": "16", "VLLM_JSON_COMPACT_OUTPUT": "true",
                    "VLLM_SPECULATIVE_CONFIG": '{"method":"mtp","num_speculative_tokens":1}'})
    result = subprocess.run([BASH, SCRIPT.as_posix()], env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == probe_exit, result.stderr
    assert ready.exists() == (probe_exit == 0)
    args = args_file.read_text().splitlines()
    assert args[args.index("--max-model-len") + 1] == "16384"
    structured = json.loads(args[args.index("--structured-outputs-config") + 1])
    assert structured == ({"backend": "xgrammar", "disable_any_whitespace": True} if tuning else {"backend": "xgrammar"})
    if tuning:
        assert "--language-model-only" in args
        assert args[args.index("--max-num-batched-tokens") + 1] == "4096"
        assert args[args.index("--max-num-seqs") + 1] == "16"
        assert args[args.index("--speculative-config") + 1] == '{"method":"mtp","num_speculative_tokens":1}'
    else:
        assert "--speculative-config" not in args
        assert "--language-model-only" not in args


@pytest.mark.parametrize("extra_probe_exit", [0, 1])
def test_extra_shape_probe_must_finish_before_ready(tmp_path, extra_probe_exit):
    if not BASH or not Path(BASH).exists():
        pytest.skip("bash unavailable")
    runtime = tmp_path / "runtime.sh"
    runtime.write_text('#!/usr/bin/env bash\nexit 0\n', encoding="utf-8")
    warmup = tmp_path / "warmup.py"
    warmup.write_text("pass\n", encoding="utf-8")
    ready = tmp_path / "ready"
    calls = tmp_path / "calls.jsonl"
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import json, os, pathlib, sys\n"
        "assert not pathlib.Path(os.environ['VLLM_READY_FILE']).exists()\n"
        "n = int(sys.argv[sys.argv.index('--warmup-concurrency') + 1])\n"
        "report = sys.argv[sys.argv.index('--report-file') + 1]\n"
        "with open(os.environ['PROBE_CALLS'], 'a') as f: f.write(json.dumps([n, report]) + '\\n')\n"
        f"sys.exit({extra_probe_exit} if n == 16 else 0)\n", encoding="utf-8")
    env = {**os.environ, "VLLM_BIN": runtime.as_posix(), "PYTHON_BIN": sys.executable.replace("\\", "/"),
        "WARMUP_SCRIPT": warmup.as_posix(), "PROBE_SCRIPT": probe.as_posix(),
        "VLLM_READY_FILE": ready.as_posix(), "VLLM_PREFIX_KEEPALIVE": "false",
        "VLLM_STRUCTURED_OUTPUT_PROBE": "true", "VLLM_ENFORCE_STRICT_TOOL_CALLING": "true",
        "VLLM_WARMUP_CONCURRENCY": "8", "VLLM_EXTRA_WARMUP_CONCURRENCY": "16", "PROBE_CALLS": calls.as_posix()}
    result = subprocess.run([BASH, SCRIPT.as_posix()], env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == extra_probe_exit, result.stderr
    assert ready.exists() == (extra_probe_exit == 0)
    assert [json.loads(row) for row in calls.read_text().splitlines()] == [
        [8, ready.as_posix() + '.structured-output.json'], [16, ready.as_posix() + '.extra-warmup.json']]


@pytest.mark.parametrize("refill_exit", [0, 1])
def test_final_prefix_refill_is_after_probes_and_blocks_readiness_on_failure(tmp_path, refill_exit):
    if not BASH or not Path(BASH).exists():
        pytest.skip("bash unavailable")
    runtime = tmp_path / "runtime.sh"
    runtime.write_text('#!/usr/bin/env bash\nexit 0\n', encoding="utf-8")
    ready, calls = tmp_path / "ready", tmp_path / "calls.txt"
    warmup = tmp_path / "warmup.py"
    warmup.write_text(
        "import os, pathlib, sys\n"
        "assert not pathlib.Path(os.environ['VLLM_READY_FILE']).exists()\n"
        "path = pathlib.Path(os.environ['CALLS'])\n"
        "second = path.exists()\n"
        "with path.open('a') as f: f.write('refill\\n' if second else 'initial\\n')\n"
        f"sys.exit({refill_exit} if second else 0)\n", encoding="utf-8")
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import os, sys\n"
        "with open(os.environ['CALLS'], 'a') as f: f.write(sys.argv[sys.argv.index('--warmup-concurrency')+1]+'\\n')\n",
        encoding="utf-8")
    env = {**os.environ, "VLLM_BIN": runtime.as_posix(), "PYTHON_BIN": sys.executable.replace("\\", "/"),
        "WARMUP_SCRIPT": warmup.as_posix(), "PROBE_SCRIPT": probe.as_posix(), "CALLS": calls.as_posix(),
        "VLLM_READY_FILE": ready.as_posix(), "VLLM_PREFIX_KEEPALIVE": "false",
        "VLLM_STRUCTURED_OUTPUT_PROBE": "true", "VLLM_ENFORCE_STRICT_TOOL_CALLING": "true",
        "VLLM_WARMUP_CONCURRENCY": "8", "VLLM_EXTRA_WARMUP_CONCURRENCY": "16"}
    result = subprocess.run([BASH, SCRIPT.as_posix()], env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == refill_exit, result.stderr
    assert ready.exists() == (refill_exit == 0)
    assert calls.read_text().splitlines() == ['initial', '8', '16', 'refill']

