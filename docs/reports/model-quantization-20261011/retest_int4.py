"""等待本次 GPU 对照结束，再复测保持原分词协议的 INT4。"""
import fcntl
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
with open('/tmp/rs-serving-tuning-gpu2.lock', 'a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    fcntl.flock(lock, fcntl.LOCK_UN)
with (root / 'int4-retest-control.log').open('w') as log:
    result = subprocess.run([sys.executable, str(root / 'compare.py'), '--variant', 'int4_autoround', '--repeat', '2'],
                            cwd=root, stdout=log, stderr=subprocess.STDOUT)
print('INT4 原分词协议复测退出码', result.returncode, flush=True)
raise SystemExit(result.returncode)
