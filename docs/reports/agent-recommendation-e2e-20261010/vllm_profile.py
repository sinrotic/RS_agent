"""保存原 GPU 1 模型进程参数，临时扩大上下文，结束后精确恢复参数。"""
import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path

ROOT = Path('/tmp/rs-agent-e2e-20261010-1247')
parser = argparse.ArgumentParser(); parser.add_argument('phase', choices=['temporary', 'restore'])
args = parser.parse_args()
manifest = ROOT / 'vllm-private.json'

def alive(pid):
    try: os.kill(pid, 0); return True
    except ProcessLookupError: return False

def stop(pid, expected):
    file=Path(f'/proc/{pid}/cmdline')
    if not file.exists(): return
    command=file.read_bytes().decode().split('\0')[:-1]
    if command != expected: raise RuntimeError('PID ownership mismatch')
    os.kill(pid, signal.SIGTERM)
    for _ in range(25):
        if not file.exists(): return
        time.sleep(1)
    if file.exists() and file.read_bytes().decode().split('\0')[:-1] == expected:
        os.kill(pid, signal.SIGKILL)

if args.phase == 'temporary':
    pid=447372; parent=447366
    command=Path(f'/proc/{pid}/cmdline').read_bytes().decode().split('\0')[:-1]
    assert command[2:4] == ['serve', '/mnt/data/luo/models/Qwen3.5-4B']
    env=dict(s.split('=',1) for s in Path(f'/proc/{pid}/environ').read_bytes().decode().split('\0') if '=' in s)
    assert env.get('CUDA_VISIBLE_DEVICES') == '1', 'never touch another GPU'
    parent_command=Path(f'/proc/{parent}/cmdline').read_bytes().decode().split('\0')[:-1]
    data={'original_pid':pid,'original_command':command,'original_env':env,'parent_command':parent_command}
    manifest.write_text(json.dumps(data)); manifest.chmod(0o600)
    stop(parent,parent_command)
    stop(pid,command)
    time.sleep(3)
    temporary=list(command); temporary[temporary.index('--max-model-len')+1]='16384'
    temporary[temporary.index('--gpu-memory-utilization')+1]='0.78'
    with (ROOT/'vllm-temporary.log').open('wb') as log:
        process=subprocess.Popen(temporary,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    data.update(temporary_pid=process.pid,temporary_command=temporary)
    manifest.write_text(json.dumps(data)); print('temporary vLLM PID',process.pid,flush=True)
else:
    data=json.loads(manifest.read_text())
    if data.get('temporary_pid'): stop(data['temporary_pid'],data['temporary_command'])
    if data.get('restored_pid'): stop(data['restored_pid'],data.get('restored_command',data['original_command']))
    time.sleep(3)
    env=dict(data['original_env'])
    env['VLLM_MAX_MODEL_LEN']=data['original_command'][data['original_command'].index('--max-model-len')+1]
    env['VLLM_GPU_MEMORY_UTILIZATION']=data['original_command'][data['original_command'].index('--gpu-memory-utilization')+1]
    command=data['parent_command']
    with (ROOT/'vllm-restored.log').open('wb') as log:
        process=subprocess.Popen(command,env=env,stdout=log,
                                 stderr=subprocess.STDOUT,start_new_session=True)
    data['restored_pid']=process.pid;data['restored_command']=command;manifest.write_text(json.dumps(data))
    print('restored original model parameters PID',process.pid,flush=True)
