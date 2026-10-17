"""替换本次登记的探针进程，验证 PID 所属后再停止。"""
import json
import os
from pathlib import Path
import signal
import subprocess
import time

ROOT=Path('/tmp/rs-agent-e2e-20261010-llm-opt-20261011')
file=ROOT/'wire-probe-pid.json'; old=json.loads(file.read_text()); pid=old['pid']
command=Path(f'/proc/{pid}/cmdline')
assert command.exists() and command.read_bytes().decode().split('\0')[:-1]==old['command']
os.kill(pid, signal.SIGTERM)
for _ in range(20):
    if not command.exists() or not command.read_bytes(): break
    time.sleep(.1)
else: raise RuntimeError('probe did not stop')
with (ROOT/'wire-probe.log').open('ab') as output:
    process=subprocess.Popen(old['command'], stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
file.write_text(json.dumps({'pid':process.pid,'command':old['command']}))
print('自有模型探针已替换', flush=True)
