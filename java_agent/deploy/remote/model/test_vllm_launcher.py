"""不加载模型，验证量化参数传递与预热期间的进程清理（POSIX）。"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


@unittest.skipUnless(os.name == "posix", "启动器使用 POSIX bash 和进程信号")
class LauncherTest(unittest.TestCase):
    def test_kernel_warmup_finishes_before_ready_and_failure_cleans_model(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory(prefix="rs-vllm-kernel-test-") as raw:
                directory = Path(raw)
                fake_model = directory / "fake-vllm"
                fake_model.write_text("#!/usr/bin/python3\nimport time\ntime.sleep(60)\n")
                fake_model.chmod(0o700)
                warmup = directory / "warmup.py"
                warmup.write_text(
                    "import os,sys\nfrom pathlib import Path\n"
                    "p=Path(os.environ['TEST_WARMUP_RECORD'])\n"
                    "with p.open('a') as f: f.write(('prefix' if '--no-kernel-warmup' in sys.argv else 'kernel')+'\\n')\n"
                    "if '--no-kernel-warmup' not in sys.argv and os.environ['TEST_FAIL']=='true': sys.exit(7)\n")
                env = os.environ.copy()
                env.update(VLLM_BIN=str(fake_model), PYTHON_BIN=sys.executable,
                    WARMUP_SCRIPT=str(warmup), VLLM_STRUCTURED_OUTPUT_PROBE="false",
                    VLLM_PREFIX_KEEPALIVE="false", VLLM_KERNEL_WARMUP="true",
                    VLLM_READY_FILE=str(directory / "ready"), TEST_WARMUP_RECORD=str(directory / "calls"),
                    TEST_FAIL=str(fail).lower())
                launcher = os.environ.get("TEST_LAUNCHER", str(Path(__file__).with_name("start_qwen35_4b_vllm.sh")))
                process = subprocess.Popen(["bash", launcher], env=env, start_new_session=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    for _ in range(100):
                        if process.poll() is not None or (directory / "ready").exists():
                            break
                        time.sleep(.02)
                    self.assertEqual((directory / "calls").read_text().splitlines(), ["prefix", "kernel"])
                    self.assertEqual((directory / "ready").exists(), not fail)
                    if fail:
                        self.assertEqual(process.wait(timeout=2), 7)
                    else:
                        self.assertIsNone(process.poll())
                        process.terminate()
                        process.wait(timeout=2)
                finally:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=2)

    def test_quantization_arguments_and_stop_during_warmup(self):
        with tempfile.TemporaryDirectory(prefix="rs-vllm-launcher-test-") as raw:
            directory = Path(raw)
            fake_model = directory / "fake-vllm"
            fake_model.write_text(
                "#!/usr/bin/python3\nimport json,os,time\nfrom pathlib import Path\n"
                "Path(os.environ['TEST_MODEL_RECORD']).write_text(json.dumps({'pid':os.getpid(),'args':__import__('sys').argv[1:]}))\n"
                "time.sleep(60)\n")
            fake_model.chmod(0o700)
            warmup = directory / "warmup.py"
            warmup.write_text("import os,time\nfrom pathlib import Path\nPath(os.environ['TEST_WARMUP_RECORD']).write_text(str(os.getpid()))\ntime.sleep(60)\n")
            quantization = {"ignore": ["lm_head", "re:.*visual.*"]}
            env = os.environ.copy()
            env.update({"VLLM_BIN": str(fake_model), "PYTHON_BIN": sys.executable,
                        "WARMUP_SCRIPT": str(warmup), "VLLM_STRUCTURED_OUTPUT_PROBE": "false",
                        "VLLM_PREFIX_KEEPALIVE": "false", "VLLM_READY_FILE": str(directory / "ready"),
                        "VLLM_QUANTIZATION": "fp8_per_block", "VLLM_QUANTIZATION_CONFIG": json.dumps(quantization),
                        "TEST_MODEL_RECORD": str(directory / "model.json"),
                        "TEST_WARMUP_RECORD": str(directory / "warmup.pid")})
            launcher = os.environ.get("TEST_LAUNCHER", str(Path(__file__).with_name("start_qwen35_4b_vllm.sh")))
            process = subprocess.Popen(["bash", launcher], env=env, start_new_session=True,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for _ in range(100):
                    if (directory / "model.json").exists() and (directory / "warmup.pid").exists():
                        break
                    time.sleep(.02)
                model = json.loads((directory / "model.json").read_text())
                warmup_pid = int((directory / "warmup.pid").read_text())
                args = model["args"]
                process.terminate()
                process.wait(timeout=2)
                for _ in range(100):
                    alive = [pid for pid in [model["pid"], warmup_pid]
                             if Path(f"/proc/{pid}/cmdline").exists() and Path(f"/proc/{pid}/cmdline").read_bytes()]
                    if not alive:
                        break
                    time.sleep(.02)
                self.assertFalse(alive, "停止启动器后模型或预热进程仍在运行")
                self.assertFalse((directory / "ready").exists())
                self.assertEqual(args[args.index("--quantization") + 1], "fp8_per_block")
                self.assertEqual(json.loads(args[args.index("--quantization-config") + 1]), quantization)
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=2)


if __name__ == "__main__":
    unittest.main()
