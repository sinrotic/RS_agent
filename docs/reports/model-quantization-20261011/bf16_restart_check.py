"""等待自动恢复后，在相同重启/预热条件下补测 BF16 的两条复杂请求。"""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parent
live = Path('/home/luo/RS_agent_java/model_deploy')
spec = importlib.util.spec_from_file_location('runtime', '/tmp/rs-serving-tuning-20261011/deploy.py')
runtime = importlib.util.module_from_spec(spec); spec.loader.exec_module(runtime)
deadline = time.monotonic() + 660
while time.monotonic() < deadline:
    state = json.loads((root / 'deployment-state.json').read_text())
    if state['candidate'] == 'w8a16_middle8' and state.get('rollback') and not state['promoted'] and runtime.health():
        runtime.canonical_process()
        expected = json.loads((root / 'baseline-deployment.json').read_text())['sha256']
        for name, digest in expected.items():
            assert hashlib.sha256((live / name).read_bytes()).hexdigest() == digest
        runtime.wait_idle()
        break
    time.sleep(2)
else:
    raise TimeoutError('正式 BF16 没有恢复，未进行补测')
print('BF16 恢复和原运行文件摘要已核验，开始相同复杂输入补测', flush=True)
subprocess.run([sys.executable, str(root / 'narrow_warm.py'), '--label', 'bf16-restart-complex'], check=True, cwd=root)
