"""核验本次 INT4 身份后恢复备份；仅显式 --apply 才执行。可长期保存在正式目录。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.request

live = Path('/home/luo/RS_agent_java/model_deploy')
state_file = live / 'quantization-memory50-state.json'

def health():
    try:
        with urllib.request.urlopen('http://127.0.0.1:18082/health', timeout=3) as response:
            return response.status == 200
    except Exception:
        return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    report = json.loads(state_file.read_text())
    assert report['promoted'] and not report.get('rollback')
    assert hashlib.sha256((live / '.env').read_bytes()).hexdigest() == report['deployed_env_sha256']
    backup = Path(report['backup'])
    assert backup.resolve().parent == live.resolve() and backup.name.startswith('backup-quantization-memory-')
    original = (backup / '.env').read_bytes()
    assert hashlib.sha256(original).hexdigest() == report['baseline_sha256']['.env']
    for name, digest in report['baseline_sha256'].items():
        if name != '.env':
            assert hashlib.sha256((live / name).read_bytes()).hexdigest() == digest
    launcher = report['launcher_pid']
    api = report['api_pid']
    assert Path(f'/proc/{launcher}/cwd').resolve() == live
    parent_args = Path(f'/proc/{launcher}/cmdline').read_bytes().decode().split('\0')
    assert parent_args[:2] == ['bash', str(live / 'start_qwen35_4b_vllm.sh')]
    api_args = Path(f'/proc/{api}/cmdline').read_bytes().decode().split('\0')
    assert report['updates']['MODEL_PATH'] in api_args and api_args[api_args.index('--port') + 1] == '18082'
    assert os.getpgid(launcher) == launcher and os.getpgid(api) == launcher
    print('本次 INT4 进程、配置和原 BF16 备份已核验', flush=True)
    if not args.apply:
        return
    os.killpg(launcher, signal.SIGTERM)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        cmdline = Path(f'/proc/{api}/cmdline')
        if not (cmdline.exists() and cmdline.read_bytes()) and not health():
            break
        time.sleep(1)
    else:
        raise TimeoutError('本次模型没有停止，未更改 .env')
    temporary = live / '.env.memory-restore-next'
    with temporary.open('xb') as handle:
        handle.write(original)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.chmod(0o600)
    temporary.replace(live / '.env')
    ready = Path('/tmp/rs_agent_latency/vllm_qwen35_4b.ready')
    ready.unlink(missing_ok=True)
    with (live / 'quantization-memory50-restore.log').open('ab', buffering=0) as log:
        restored = subprocess.Popen(['bash', str(live / 'run_qwen35_4b_vllm.sh')], cwd=live,
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + 660
    while time.monotonic() < deadline:
        assert restored.poll() is None, 'BF16 启动器退出'
        if ready.exists() and health():
            report.update(promoted=False, rollback=True, health=True, restored_launcher_pid=restored.pid)
            state_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
            print('BF16 已恢复且启动探针通过', flush=True)
            return
        time.sleep(2)
    raise TimeoutError('BF16 恢复等待超时，请检查独立恢复日志')

if __name__ == '__main__':
    main()
