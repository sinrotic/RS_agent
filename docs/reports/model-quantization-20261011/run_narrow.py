"""正式 BF16 完成恢复后，在 GPU 2 试验只量化第 8～15 层 MLP。"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
from clone import configure

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('runtime', '/tmp/rs-serving-tuning-20261011/deploy.py')
runtime = importlib.util.module_from_spec(spec); spec.loader.exec_module(runtime)
deadline = time.monotonic() + 660
while time.monotonic() < deadline:
    state = json.loads((root / 'deployment-state.json').read_text())
    if state.get('rollback') and not state['promoted'] and runtime.health():
        runtime.canonical_process()
        break
    time.sleep(2)
else:
    raise TimeoutError('BF16 恢复未完成，未启动下一候选')
configure(18092)
print('BF16 已恢复，仅启动隔离的较小量化范围', flush=True)
result = subprocess.run([sys.executable, str(root / 'compare.py'), '--variant', 'w8a16_middle8'], cwd=root)
raise SystemExit(result.returncode)
