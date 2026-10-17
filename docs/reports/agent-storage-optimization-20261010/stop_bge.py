"""只停止本次记录的独立 BGE 进程。"""
import json
import os
import signal
import time
from pathlib import Path

root=Path('/tmp/rs-agent-e2e-20261010-storage-opt')
data=json.loads((root/'bge-pid.json').read_text());pid=data['pid']
file=Path(f'/proc/{pid}/cmdline')
if file.exists():
    assert file.read_bytes().decode().split('\0')[:-1]==data['command'],'PID owner mismatch'
    os.kill(pid,signal.SIGTERM)
    for _ in range(30):
        if not file.exists(): break
        time.sleep(1)
    else: raise RuntimeError('BGE did not stop; inspect before restoring model')
print('owned BGE stopped')
