"""完整业务耗时复测退化时，核验本次进程后恢复原 BF16。"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import time

root = Path(__file__).resolve().parent
live = Path('/home/luo/RS_agent_java/model_deploy')
spec = importlib.util.spec_from_file_location('runtime', '/tmp/rs-serving-tuning-20261011/deploy.py')
runtime = importlib.util.module_from_spec(spec); spec.loader.exec_module(runtime)
report = json.loads((root / 'deployment-state.json').read_text())
assert report['promoted'] and report['quantization'] == 'w8a16_middle'
assert hashlib.sha256((live / '.env').read_bytes()).hexdigest() == report['deployed_env_sha256']
original_path = Path(report['backup']) / '.env'
assert original_path.parent.parent == live
original = original_path.read_bytes()
assert hashlib.sha256(original).hexdigest() == report['baseline_sha256']['.env']
pid = report['launcher_pid']
args = Path(f'/proc/{pid}/cmdline').read_bytes().decode().split('\0')
assert args[:2] == ['bash', str(live / 'start_qwen35_4b_vllm.sh')]
assert Path(f'/proc/{pid}/cwd').resolve() == live
assert os.getpgid(pid) == pid
api_pid = json.loads((root / 'live-state.json').read_text())['processes'][0]['pid']
assert os.getpgid(api_pid) == pid
runtime.wait_idle()
(root / 'deployment-initial.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
os.killpg(pid, signal.SIGTERM)
deadline = time.monotonic() + 90
api_cmdline = Path(f'/proc/{api_pid}/cmdline')
while time.monotonic() < deadline:
    active = api_cmdline.exists() and bool(api_cmdline.read_bytes())
    if not active and not runtime.health():
        break
    time.sleep(1)
assert not (api_cmdline.exists() and api_cmdline.read_bytes()) and not runtime.health(), '旧模型仍在服务，停止后续操作'
runtime.atomic_write(live / '.env', original, 0o600)
restored = runtime.launch('quantization-20261011-business-rollback.log')
runtime.wait_idle()
runtime.canonical_process()
report.update(promoted=False, rollback=True, health=runtime.health(), restored_launcher_pid=restored.pid,
              rollback_reason='热运行复杂推荐明显变慢、工具轮次增加，编程键盘没有完整最终回答；约10%解码优势不能抵消业务退化')
(root / 'deployment-state.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print('已恢复原 BF16，配置摘要和服务健康通过核验', flush=True)
