"""核验本轮仅改预热配置、现有服务健康且隔离模型退出，不输出环境值。"""
import datetime
import hashlib
import json
import os
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LIVE = Path('/home/luo/RS_agent_java/model_deploy')
sys.path.insert(0, '/tmp/rs-agent-before-after-20261011')
import compare_live as live
sys.path.insert(0, '/tmp/rs-agent-live-complex-concurrency-20261011')
from model_cache_metrics import read_cache_metrics


def main():
    deployment = json.loads((ROOT / 'deployment.json').read_text())
    keys = ('VLLM_KERNEL_WARMUP', 'VLLM_KERNEL_WARMUP_BATCH_SIZES')
    def unchanged_lines(path):
        return [line for line in path.read_text().splitlines() if line.split('=', 1)[0] not in keys]
    report = {'checked_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'model_unchanged': live.identity() == deployment['model_before'],
        'dependencies_unchanged': live.dependency_snapshot() == deployment['dependencies_before'],
        'model_and_business_env_lines_unchanged': unchanged_lines(LIVE / '.env') == unchanged_lines(ROOT / 'private-backup' / '.env'),
        'installed_file_sha256_match': all(hashlib.sha256((LIVE / name).read_bytes()).hexdigest() == expected
                                         for name, expected in deployment['after_sha256'].items()),
        'keepalive_alive': (Path('/proc') / str(deployment['keepalive_pid']) / 'cmdline').is_file(),
        'health': {}, 'model_metrics': read_cache_metrics()}
    for name, port, endpoint in (('agent',18214,'/actuator/health'),('gateway',18288,'/actuator/health'),
        ('recommend',18213,'/actuator/health'),('catalog',18202,'/actuator/health'),
        ('user',18201,'/actuator/health'),('model',18082,'/health')):
        with urllib.request.urlopen(f'http://127.0.0.1:{port}{endpoint}', timeout=5) as response:
            report['health'][name] = response.status
    with socket.socket() as sock:
        report['temporary_port_closed'] = sock.connect_ex(('127.0.0.1', 18096)) != 0
    state = json.loads((ROOT / 'cold-validation' / 'temporary-model-state.json').read_text())
    argv = Path('/proc') / str(state['pid']) / 'cmdline'
    report['temporary_model_stopped'] = state['stopped'] and (not argv.exists() or not argv.read_bytes())
    group_members = []
    for entry in Path('/proc').iterdir():
        if entry.name.isdecimal():
            try:
                if os.getpgid(int(entry.name)) == state['pid'] and (entry / 'cmdline').read_bytes():
                    group_members.append(int(entry.name))
            except (OSError, ProcessLookupError):
                pass
    report['temporary_group_remaining_pids'] = group_members
    report['gpu_snapshot'] = subprocess.check_output(['nvidia-smi', '--query-gpu=index,memory.used,utilization.gpu',
                                                     '--format=csv,noheader,nounits'], text=True).splitlines()
    report['compute_processes'] = subprocess.check_output(['nvidia-smi', '--query-compute-apps=gpu_uuid,pid,used_memory',
                                                          '--format=csv,noheader,nounits'], text=True).splitlines()
    report['passed'] = (all(report[key] for key in ('model_unchanged','dependencies_unchanged',
        'model_and_business_env_lines_unchanged','installed_file_sha256_match','keepalive_alive',
        'temporary_port_closed','temporary_model_stopped')) and not group_members
        and all(status == 200 for status in report['health'].values()))
    (ROOT / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    assert report['passed']


if __name__ == '__main__':
    main()
