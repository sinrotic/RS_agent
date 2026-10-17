"""GPU2 临时模型管理；不修改任何现有模型入口，只终止本任务创建的进程组。"""
import argparse
import datetime
import json
import os
import signal
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = 18096
GPU = 2
VLLM = '/mnt/data/luo/venvs/rsagent-vllm/bin/vllm'
MODELS = {'bf16': '/mnt/data/luo/models/Qwen3.5-4B',
          'quant': '/mnt/data/luo/models/Qwen3.5-4B-INT4-MLP-BF16-sensitive-20261011'}
STATE = ROOT / 'temporary-model-state.json'


def gpu_snapshot():
    output = subprocess.check_output(['nvidia-smi', '--query-gpu=index,uuid,name,memory.total,memory.used,utilization.gpu',
        '--format=csv,noheader,nounits'], text=True)
    result = []
    for line in output.splitlines():
        index, uuid, name, total, used, utilization = [part.strip() for part in line.split(',')]
        result.append({'index': int(index), 'uuid': uuid, 'name': name, 'total_mib': int(total),
                       'used_mib': int(used), 'utilization': int(utilization)})
    processes = []
    output = subprocess.check_output(['nvidia-smi', '--query-compute-apps=gpu_uuid,pid,used_memory',
        '--format=csv,noheader,nounits'], text=True)
    for line in output.splitlines():
        uuid, pid, used = [part.strip() for part in line.split(',')]
        cmdline = Path('/proc/' + pid + '/cmdline')
        argv = cmdline.read_bytes().split(b'\0') if cmdline.exists() else []
        script = Path(argv[1].decode()).name if len(argv) > 1 and argv[1].endswith(b'.py') else '(非脚本入口)'
        processes.append({'gpu_uuid': uuid, 'pid': int(pid), 'used_mib': int(used), 'script': script})
    return {'gpus': result, 'processes': processes}


def owned(state):
    path = Path('/proc') / str(state['pid']) / 'cmdline'
    if not path.exists():
        return False
    argv = path.read_bytes().split(b'\0')
    return (VLLM.encode() in argv and state['model_path'].encode() in argv
            and b'--port' in argv and argv[argv.index(b'--port') + 1] == str(PORT).encode()
            and os.getpgid(state['pid']) == state['pid'])


def stop():
    if not STATE.exists():
        return
    state = json.loads(STATE.read_text())
    if state.get('stopped'):
        return
    if owned(state):
        os.killpg(state['pid'], signal.SIGTERM)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and owned(state):
            time.sleep(.2)
        if owned(state):
            os.killpg(state['pid'], signal.SIGKILL)
    # 已退出或成为僵尸的任务不匹配 cmdline，不会向其他 PID 发信号。
    state['stopped'] = True
    state['stopped_at_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    (ROOT / ('temporary-' + state['model'] + '-state.json')).write_text(json.dumps(state, ensure_ascii=False, indent=2))
    print(json.dumps({'stopped': True, 'task_pid': state['pid']}), flush=True)


def start(model):
    assert not STATE.exists() or json.loads(STATE.read_text()).get('stopped'), '已有临时实例，先清理'
    with socket.socket() as sock:
        assert sock.connect_ex(('127.0.0.1', PORT)) != 0, '临时端口已被占用'
    snapshot = gpu_snapshot()
    gpu = next(row for row in snapshot['gpus'] if row['index'] == GPU)
    fraction = .50
    headroom = 1200
    assert gpu['used_mib'] + gpu['total_mib'] * fraction + headroom < gpu['total_mib'], '空闲显存不足，拒绝挤占既有任务'
    assert gpu['utilization'] < 20, 'GPU2 存在活跃计算，不启动模型'
    command = [VLLM, 'serve', MODELS[model], '--host', '127.0.0.1', '--port', str(PORT),
        '--served-model-name', 'qwen35-4b', '--trust-remote-code', '--enable-prefix-caching',
        '--max-model-len', '16384', '--gpu-memory-utilization', str(fraction),
        '--max-num-seqs', '32',
        '--structured-outputs-config', json.dumps({'backend': 'xgrammar', 'disable_any_whitespace': True}, separators=(',', ':')),
        '--enable-auto-tool-choice', '--tool-call-parser', 'qwen3_xml', '--jit-monitor-verbose']
    env = dict(os.environ, CUDA_VISIBLE_DEVICES=str(GPU), VLLM_CACHE_ROOT=str(ROOT / ('model-cache-' + model)),
               VLLM_USE_FLASHINFER_SAMPLER='0', TRITON_CACHE_DIR=str(ROOT / 'triton-cold-cache'))
    env['PATH'] = str(Path(VLLM).parent) + os.pathsep + env.get('PATH', '')
    cache_seed = None
    cache = ROOT / ('model-cache-' + model)
    if model == 'quant' and not cache.exists():
        source_cache = Path('/home/luo/RS_agent_java/model_deploy/quantization-cache/20261011-mlp-int4-bf16-memory50')
        if source_cache.is_dir() and sum(path.stat().st_size for path in source_cache.rglob('*') if path.is_file()) < 512 * 1024 * 1024:
            shutil.copytree(source_cache, cache)
            cache_seed = str(source_cache)
    log = ROOT / ('temporary-' + model + '.log')
    if log.exists():
        shutil.copy2(log, ROOT / ('temporary-' + model + '-previous-start.log'))
    with log.open('w') as output:
        process = subprocess.Popen(command, env=env, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
    state = {'model': model, 'model_path': MODELS[model], 'pid': process.pid, 'gpu': GPU, 'port': PORT,
        'command': command, 'sampler_environment': {'VLLM_USE_FLASHINFER_SAMPLER': '0'},
        'cache_seed_source': cache_seed,
        'snapshot_before': snapshot, 'stopped': False,
        'started_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    print(json.dumps({'started': True, 'model': model, 'pid': process.pid, 'gpu': GPU, 'port': PORT}), flush=True)


def status():
    state = json.loads(STATE.read_text())
    healthy = False
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/health', timeout=3) as response:
            healthy = response.status == 200
    except OSError:
        pass
    state.update(healthy=healthy, owned_process=owned(state), snapshot_current=gpu_snapshot())
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    print(json.dumps({'model': state['model'], 'healthy': healthy, 'owned_process': state['owned_process'],
        'gpus': state['snapshot_current']['gpus']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('inventory', 'start', 'status', 'stop'))
    parser.add_argument('--model', choices=tuple(MODELS), default='bf16')
    args = parser.parse_args()
    if args.action == 'inventory':
        print(json.dumps(gpu_snapshot(), ensure_ascii=False, indent=2))
    elif args.action == 'start':
        start(args.model)
    elif args.action == 'status':
        status()
    else:
        stop()



