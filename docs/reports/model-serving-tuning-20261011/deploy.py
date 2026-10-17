"""本次服务器的原子部署与回退；只操作核验后的 18082 模型实例。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import time
import urllib.request


ROOT = Path('/home/luo/RS_agent_java/model_deploy')
STAGE = Path('/tmp/rs-serving-tuning-20261011')
PYTHON = '/mnt/data/luo/venvs/rsagent-vllm/bin/python'
READY = Path('/tmp/rs_agent_latency/vllm_qwen35_4b.ready')
FILES = ['start_qwen35_4b_vllm.sh', 'vllm_prefix_warmup.py', 'vllm_structured_output_probe.py']
EXPECTED = {
    '.env': 'b728be18ddd34e23a07a6687e01c09994f3f849f2fcff51a380019fe1ad9dc73',
    'start_qwen35_4b_vllm.sh': '2b0171472af7a7f6a418431be26acca7907745056131c4c84682eab12e3ba73f',
    'run_qwen35_4b_vllm.sh': 'a0e401fae45e0fb2fe3af50e34229e4fec2400556ff9099d1a4de9e4f82f7921',
    'vllm_prefix_warmup.py': 'bdf3a8ff800f91c5ac61257abcb74af45c88cdb28c2ace508ac1d76148603d1a',
    'vllm_structured_output_probe.py': '88d89cd88d53bfdebf2a7149125c86ed54a1d81b178b3122b2592501298cacd7',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write(path, contents, mode):
    temporary = path.with_name(path.name + '.serving-tuning-next')
    with temporary.open('xb') as handle:
        handle.write(contents)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.chmod(mode)
    temporary.replace(path)


def health():
    try:
        return urllib.request.urlopen('http://127.0.0.1:18082/health', timeout=2).status == 200
    except Exception:
        return False


def idle():
    with urllib.request.urlopen('http://127.0.0.1:18082/metrics', timeout=5) as response:
        metrics = response.read().decode()
    counts = []
    for name in ('running', 'waiting'):
        samples = re.findall(r'^vllm:num_requests_' + name + r'(?:\{[^}]*\})?\s+([0-9.eE+-]+)', metrics, re.M)
        if not samples:
            raise RuntimeError('模型负载指标缺失，拒绝切换')
        counts.extend(float(sample) for sample in samples)
    return all(count == 0 for count in counts)


def wait_idle():
    # ready 后的保温进程可能正在完成首轮；等待安静窗口再开始计时，
    # 不能把验收与正常保温的短暂重叠当作模型质量失败。
    deadline = time.monotonic() + 60
    consecutive = 0
    while time.monotonic() < deadline:
        consecutive = consecutive + 1 if idle() else 0
        if consecutive >= 2:
            return
        time.sleep(1)
    raise RuntimeError('正式服务持续有请求，无法执行空闲基准')


def wait_external_validation():
    directory = '/tmp/rs-agent-e2e-20261010-llm-opt-20261011/'
    scripts = {(directory + name).encode() for name in
               ('serving_refresh.py', 'baseline.py', 'concurrent_matrix.py', 'timeout_probe.py')}
    deadline = time.monotonic() + 600
    last_notice = 0
    while time.monotonic() < deadline:
        running = []
        for process in Path('/proc').iterdir():
            if not process.name.isdecimal():
                continue
            try:
                if scripts.intersection((process / 'cmdline').read_bytes().split(b'\0')):
                    running.append(process.name)
            except FileNotFoundError:
                pass
        if not running:
            return
        if time.monotonic() - last_notice > 30:
            print('等待另一组实际 Agent 验收结束，不切换使用中的模型', running, flush=True)
            last_notice = time.monotonic()
        time.sleep(2)
    raise TimeoutError('另一组模型验收持续运行，本次未切换配置')


def canonical_process():
    found = []
    for directory in Path('/proc').iterdir():
        if not directory.name.isdecimal():
            continue
        try:
            args = (directory / 'cmdline').read_bytes().split(b'\0')
            if b'serve' in args and b'18082' in args and any(b'/bin/vllm' in arg for arg in args):
                pid = int(directory.name)
                parent = int((directory / 'stat').read_text().split()[3])
                parent_args = Path(f'/proc/{parent}/cmdline').read_bytes().split(b'\0')
                env = dict(entry.split(b'=', 1) for entry in (directory / 'environ').read_bytes().split(b'\0') if b'=' in entry)
                parent_cwd = Path(os.readlink(f'/proc/{parent}/cwd'))
                launcher_paths = [(parent_cwd / arg.decode()).resolve() for arg in parent_args
                                  if arg.endswith(FILES[0].encode())]
                assert ROOT / FILES[0] in launcher_paths, '父进程不是正式启动器'
                assert env.get(b'CUDA_VISIBLE_DEVICES') == b'1', '正式 GPU 发生变化'
                assert args[args.index(b'--max-model-len')+1] == b'16384'
                assert args[args.index(b'--gpu-memory-utilization')+1] == b'0.78'
                assert b'--quantization' not in args and b'--speculative-config' not in args
                found.append((pid, parent))
        except (FileNotFoundError, ProcessLookupError):
            continue
    if len(found) != 1:
        raise RuntimeError(f'正式模型进程数异常：{len(found)}')
    return found[0]


def stop_existing(pid, parent):
    assert canonical_process() == (pid, parent), '切换前进程身份变化'
    os.kill(parent, signal.SIGTERM)  # 启动器的 trap 负责清理其模型与保温子进程。
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if not Path(f'/proc/{pid}').exists() and not health():
            return
        time.sleep(1)
    raise RuntimeError('原模型未及时停止，拒绝创建第二个实例')


def launch(log_name):
    READY.unlink(missing_ok=True)
    with (ROOT / log_name).open('ab', buffering=0) as log:
        process = subprocess.Popen(['bash', str(ROOT / 'run_qwen35_4b_vllm.sh')], cwd=ROOT,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
    deadline = time.monotonic() + 660
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'正式启动失败：{log_name}，exit={process.returncode}')
        if READY.exists() and health():
            return process
        time.sleep(2)
    # 超时实例仍归本脚本所有，先关闭再回退。
    os.killpg(process.pid, signal.SIGTERM)
    process.wait(timeout=60)
    raise TimeoutError('正式模型 ready 等待超时')


def stop_owned(process):
    if process is None or process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    process.wait(timeout=60)
    deadline = time.monotonic() + 30
    while health() and time.monotonic() < deadline:
        time.sleep(1)
    if health():
        raise RuntimeError('本次模型尚未释放端口，拒绝回退双实例')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    wait_external_validation()
    for filename, expected in EXPECTED.items():
        assert digest(ROOT / filename) == expected, f'{filename} 在准备期间被修改，请重新核对'
    pid, parent = canonical_process()
    assert health(), '正式服务不健康'
    wait_idle()
    source = STAGE / 'production-candidate'
    for filename in FILES:
        assert (source / filename).is_file()
    subprocess.run(['bash', '-n', str(source / FILES[0])], check=True)
    compact = json.loads((STAGE / 'json_compact.json').read_text())
    assert compact.get('real_request_replay') and compact.get('steady_tool_rounds')
    private = STAGE / 'replay-payloads.private.json'
    assert len(json.loads(private.read_text())) == 2
    updates = {
        'VLLM_JSON_COMPACT_OUTPUT': 'true',
        'VLLM_WARMUP_CONCURRENCY': '8',
        'VLLM_WARMUP_ONLY_WHEN_IDLE': 'true',
        'VLLM_WARMUP_PAYLOAD_FILE': str(ROOT / 'model_warmup_payloads.private.json'),
        'VLLM_WARMUP_MAX_TOKENS': '1',
        'VLLM_READY_TIMEOUT_SEC': '600',
    }
    lines = (ROOT / '.env').read_text().splitlines()
    for key in updates:
        assert sum(line.startswith(key+'=') for line in lines) <= 1, f'{key} 重复定义'
    env = '\n'.join(line for line in lines if line.split('=',1)[0] not in updates) + '\n'
    env += '\n'.join(key+'='+shlex.quote(value) for key,value in updates.items()) + '\n'
    print('部署核验通过', {'pid': pid, 'parent': parent, 'gpu': 1, 'updates': updates}, flush=True)
    if not args.apply:
        return
    backup = ROOT / ('backup-serving-tuning-' + time.strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(mode=0o700)
    originals = FILES + ['.env']
    private_target = ROOT / 'model_warmup_payloads.private.json'
    if private_target.exists():
        originals.append(private_target.name)
    for filename in originals:
        atomic_write(backup / filename, (ROOT / filename).read_bytes(), (ROOT / filename).stat().st_mode & 0o777)
    state = {'backup': str(backup), 'previous_api_pid': pid, 'previous_launcher_pid': parent,
             'configuration': updates, 'original_sha256': EXPECTED, 'promoted': False}
    process = None
    stopped = False
    try:
        stop_existing(pid, parent)
        stopped = True
        for filename in FILES:
            atomic_write(ROOT / filename, (source / filename).read_bytes(), (backup / filename).stat().st_mode & 0o777)
        atomic_write(private_target, private.read_bytes(), 0o600)
        atomic_write(ROOT / '.env', env.encode(), 0o600)
        process = launch('serving-tuning-20261011.log')
        probe = json.loads(Path(str(READY)+'.structured-output.json').read_text())
        assert probe['status'] == 'PASS' and 'named_tool_concurrency_8' in probe['cases']
        state['structured_output_report'] = probe
        wait_idle()
        subprocess.run([PYTHON, str(STAGE / 'benchmark.py'), '--base-url', 'http://127.0.0.1:18082/v1',
                        '--output', str(STAGE / 'production-after.json')], check=True, timeout=300)
        state.update(promoted=True, launcher_pid=process.pid, api_pid=canonical_process()[0],
                     deployed_sha256={filename:digest(ROOT / filename) for filename in originals},
                     private_payload_sha256=digest(private_target), health=health())
        print('正式部署与重启后验证通过', flush=True)
    except Exception as error:
        state['failure'] = str(error)
        if stopped:
            stop_owned(process)
            for filename in originals:
                atomic_write(ROOT / filename, (backup / filename).read_bytes(), (backup / filename).stat().st_mode & 0o777)
            if private_target.name not in originals:
                private_target.unlink(missing_ok=True)
            restored = launch('serving-tuning-20261011-rollback.log')
            state.update(rollback=True, restored_launcher_pid=restored.pid, health=health())
        raise
    finally:
        (STAGE / 'deployment-state.json').write_text(json.dumps(state, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
