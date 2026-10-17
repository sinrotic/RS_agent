"""空闲热应用预热并原子安装启动脚本；不重启/停止模型及现有保温进程。"""
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LIVE = Path('/home/luo/RS_agent_java/model_deploy')
sys.path.insert(0, '/tmp/rs-agent-before-after-20261011')
import compare_live as live
sys.path.insert(0, '/tmp/rs-agent-live-complex-concurrency-20261011')
from model_cache_metrics import read_cache_metrics


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def process(pid):
    return (Path('/proc') / str(pid) / 'cmdline').read_bytes().split(b'\0')


def main():
    path = ROOT / 'deployment.json'
    assert not path.exists()
    validation = json.loads((ROOT / 'cold-validation.json').read_text())
    assert validation['passed'] and validation['temporary_stopped']
    api, launcher, keepalive = 1614322, 1614314, 1622545
    assert b'--port' in process(api) and process(api)[process(api).index(b'--port') + 1] == b'18082'
    assert str(LIVE / 'start_qwen35_4b_vllm.sh').encode() in process(launcher)
    assert str(LIVE / 'vllm_prefix_warmup.py').encode() in process(keepalive) and b'--keepalive' in process(keepalive)
    keepalive_before = process(keepalive)
    env = dict(entry.decode().split('=', 1) for entry in (Path('/proc') / str(keepalive) / 'environ').read_bytes().split(b'\0') if b'=' in entry)
    assert env['VLLM_BASE_URL'] == 'http://127.0.0.1:18082/v1'
    payload = Path(env['VLLM_WARMUP_PAYLOAD_FILE'])
    assert payload.is_file() and payload.stat().st_mode & 0o077 == 0
    report = {'started_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'model_before': live.identity(), 'dependencies_before': live.dependency_snapshot(),
        'api_pid': api, 'launcher_pid': launcher, 'keepalive_pid': keepalive,
        'payload_sha256': digest(payload), 'ready_before': Path(env['VLLM_READY_FILE']).exists(),
        'installed': False, 'hot_warmup_completed': False}
    def save():
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    # 防止运行中 Bash 被原地覆盖。暂存规范 LF，保留原文件权限后原子替换。
    for name in ('vllm_prefix_warmup.py', 'start_qwen35_4b_vllm.sh', 'test_vllm_launcher.py'):
        source = ROOT / name
        source.write_bytes(source.read_bytes().replace(b'\r\n', b'\n'))
    subprocess.run(['bash', '-n', str(ROOT / 'start_qwen35_4b_vllm.sh')], check=True)
    test_env = dict(os.environ, TEST_LAUNCHER=str(ROOT / 'start_qwen35_4b_vllm.sh'))
    subprocess.run([sys.executable, str(ROOT / 'test_vllm_launcher.py')], env=test_env, check=True, timeout=30)
    report['launcher_checks_passed'] = True
    names = ('vllm_prefix_warmup.py', 'start_qwen35_4b_vllm.sh', '.env')
    report['before_sha256'] = {name: digest(LIVE / name) for name in names}
    backup = ROOT / 'private-backup'
    backup.mkdir(mode=0o700)
    for name in names:
        shutil.copy2(LIVE / name, backup / name)
        (backup / name).chmod(0o600)
    save()
    metrics = read_cache_metrics()
    assert metrics['vllm:num_requests_running'] == metrics['vllm:num_requests_waiting'] == 0
    assert live.identity() == report['model_before']
    with (ROOT / 'hot-warmup.log').open('w') as output:
        result = subprocess.run([sys.executable, str(ROOT / 'vllm_prefix_warmup.py'),
            '--kernel-warmup', '--kernel-batch-sizes', '1', '4', '8', '16', '--only-when-idle',
            '--skip-ready-wait', '--delay-after-warmup-sec', '0'],
            env=env, stdout=output, stderr=subprocess.STDOUT, timeout=180)
    report['hot_warmup_exit_code'] = result.returncode
    report['hot_warmup_completed'] = result.returncode == 0
    save()
    assert result.returncode == 0, '热应用未完成，未安装文件；查看脱敏预热日志'
    assert live.identity() == report['model_before'] and live.dependency_snapshot() == report['dependencies_before']
    assert {name: digest(LIVE / name) for name in names} == report['before_sha256']
    updates = {'VLLM_KERNEL_WARMUP': 'true', 'VLLM_KERNEL_WARMUP_BATCH_SIZES': '"1 4 8 16"'}
    lines = (LIVE / '.env').read_text().splitlines()
    kept = [line for line in lines if line.split('=', 1)[0] not in updates]
    new_env = '\n'.join(kept + [key + '=' + value for key, value in updates.items()]) + '\n'
    replaced = []
    try:
        for name in names:
            destination = LIVE / name
            stage = LIVE / (name + '.kernel-warmup-20261012.stage')
            assert not stage.exists()
            stage.write_bytes(new_env.encode() if name == '.env' else (ROOT / name).read_bytes())
            stage.chmod(destination.stat().st_mode & 0o777)
            os.replace(stage, destination)
            replaced.append(name)
        report['installed'] = True
    except Exception:
        for name in reversed(replaced):
            restore = LIVE / (name + '.kernel-warmup-20261012.restore')
            shutil.copy2(backup / name, restore)
            restore.chmod(0o600 if name == '.env' else 0o755)
            os.replace(restore, LIVE / name)
        report['rolled_back_files'] = True
        save(); raise
    report.update(after_sha256={name: digest(LIVE / name) for name in names},
        model_after=live.identity(), dependencies_after=live.dependency_snapshot(),
        ready_after=Path(env['VLLM_READY_FILE']).exists(), payload_unchanged=digest(payload) == report['payload_sha256'])
    report['existing_keepalive_unchanged'] = process(keepalive) == keepalive_before
    report['model_unchanged'] = report['model_before'] == report['model_after']
    report['dependencies_unchanged'] = report['dependencies_before'] == report['dependencies_after']
    report['keepalive_note'] = '现有保温进程保留原轻量逻辑；模型已用新脚本补热，下一次正常启动加载新预热流程'
    save()
    assert report['model_unchanged'] and report['dependencies_unchanged'] and report['payload_unchanged'] and report['ready_after']
    print(json.dumps({k: report[k] for k in ('installed', 'hot_warmup_completed', 'model_unchanged',
        'dependencies_unchanged', 'payload_unchanged', 'existing_keepalive_unchanged')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
