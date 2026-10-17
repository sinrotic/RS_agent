"""顺序切换当前单活 Agent，保留旧容器/JAR/私有配置，失败时恢复原实例。"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

from inspect_live import NAME, ROOT, active_threads

BACKUP = NAME + '-rollback-20261011'
TARGET = Path('/tmp/rs-agent-e2e-20261010-llm-opt-20261011/rs-service-agent.jar')
CANDIDATE = Path('/tmp/rs-agent-concurrency-20261011/rs-service-agent.jar')
SHA = '4bc94fc6894a65fb933071ac91c2506c5964542c68d464f59155967c027c1c76'
PARAMETERS = {'RS_AGENT_MAX_ACTIVE_LOOPS': '32', 'RS_AGENT_ACTIVE_LOOP_ACQUIRE_TIMEOUT_MS': '300',
    'RS_AGENT_MAX_MODEL_STREAMS': '16', 'RS_AGENT_MODEL_STREAM_ACQUIRE_TIMEOUT_MS': '15000',
    'RS_AGENT_MAX_RECOMMENDATION_CALLS': '4', 'RS_AGENT_RECOMMENDATION_ACQUIRE_TIMEOUT_MS': '15000',
    'RS_AGENT_MAX_TOOL_CALLS': '64', 'RS_AGENT_TOOL_ACQUIRE_TIMEOUT_MS': '300',
    'RS_AGENT_MAX_SESSION_QUEUE_SIZE': '2', 'RS_AGENT_SESSION_QUEUE_TIMEOUT_MS': '500'}


def inspect(name):
    return json.loads(subprocess.check_output(['docker', 'inspect', name], text=True))[0]


def identity():
    output = subprocess.check_output(['pgrep', '-af', 'vllm serve'], text=True)
    return [line for line in output.splitlines() if '/bin/vllm serve ' in line and '--port 18082 ' in line]


def health():
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen('http://127.0.0.1:18214/actuator/health', timeout=3) as response:
                if json.load(response)['status'] == 'UP':
                    return
        except (OSError, AssertionError):
            pass
        time.sleep(2)
    raise TimeoutError('共享 Agent 未就绪')


def atomic_copy(source):
    assert TARGET.parent == Path('/tmp/rs-agent-e2e-20261010-llm-opt-20261011')
    staged = TARGET.with_name('rs-service-agent.jar.live-switch-staged')
    shutil.copy2(source, staged)
    os.replace(staged, TARGET)


def restore(report):
    current = subprocess.run(['docker', 'inspect', NAME], capture_output=True, text=True)
    if current.returncode == 0:
        container = json.loads(current.stdout)[0]
        assert container['Id'] == report.get('new_container_id') or (
            container['Config']['Labels'].get('rsagent.live-switch') == '20261011'
            and container['Id'] != report['old_container_id'])
        subprocess.run(['docker', 'stop', '--time', '150', NAME], check=True, capture_output=True)
        subprocess.run(['docker', 'rm', NAME], check=True, capture_output=True)
    assert inspect(BACKUP)['Id'] == report['old_container_id']
    atomic_copy(ROOT / 'rs-service-agent.previous.jar')
    subprocess.run(['docker', 'rename', BACKUP, NAME], check=True, capture_output=True)
    subprocess.run(['docker', 'start', NAME], check=True, capture_output=True)
    health()
    report.update(rolled_back=True, deployed=False)
    (ROOT / 'deployment.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    if args.rollback:
        restore(json.loads((ROOT / 'deployment.json').read_text()))
        print('原 Agent 已恢复', flush=True)
        return
    assert not (ROOT / 'deployment.json').exists(), '已有切换记录，拒绝重复切换'
    source = inspect(NAME)
    assert source['State']['Running'] and source['HostConfig']['NetworkMode'] == 'host'
    assert subprocess.run(['docker', 'inspect', BACKUP], capture_output=True).returncode != 0
    assert hashlib.file_digest(CANDIDATE.open('rb'), 'sha256').hexdigest() == SHA
    assert source['Mounts'][0]['Source'] == str(TARGET)
    assert all(not mount['RW'] for mount in source['Mounts'])
    assert not source['HostConfig']['Privileged']
    original_env = dict(item.split('=', 1) for item in source['Config']['Env'] if '=' in item)
    assert original_env['SERVER_PORT'] == '18214'
    assert original_env['RS_AGENT_OPENAI_BASE_URL'] == 'http://127.0.0.1:18082/v1'
    assert original_env['RS_AGENT_DIRECT_RECOMMENDATION_ENABLED'] == 'false'
    assert original_env['RS_AGENT_LLM_SYNTHESIS_ENABLED'] == 'true'
    private = ROOT / 'container.previous.private.json'
    private.write_text(json.dumps(source))
    private.chmod(0o600)
    shutil.copy2(TARGET, ROOT / 'rs-service-agent.previous.jar')
    deadline = time.monotonic() + 180
    while active_threads(source):
        if time.monotonic() >= deadline:
            raise TimeoutError('仍有正在执行的 Turn，本次未切换')
        print('等待现有 Turn 完成', flush=True)
        time.sleep(3)
    report = {'old_container_id': source['Id'], 'old_agent_sha256':
        hashlib.file_digest(TARGET.open('rb'), 'sha256').hexdigest(), 'new_agent_sha256': SHA,
        'parameters': PARAMETERS, 'model_before': identity(), 'active_turns_before_stop': 0,
        'backup_container': BACKUP, 'deployed': False, 'rolled_back': False}
    env = dict(original_env)
    env.update(PARAMETERS, SERVER_SHUTDOWN='graceful', SPRING_LIFECYCLE_TIMEOUT_PER_SHUTDOWN_PHASE='130s')
    envfile = ROOT / 'live.private.env'
    envfile.write_text('\n'.join(key + '=' + value for key, value in env.items()) + '\n')
    envfile.chmod(0o600)
    command = ['docker', 'run', '-d', '--name', NAME, '--network', 'host', '--env-file', str(envfile),
               '--label', 'rsagent.live-switch=20261011']
    for key, flag in (('Memory', '--memory'), ('MemorySwap', '--memory-swap'), ('NanoCpus', '--cpus')):
        value = source['HostConfig'].get(key, 0)
        if value:
            command += [flag, str(value / 1_000_000_000) if key == 'NanoCpus' else str(value)]
    restart = source['HostConfig']['RestartPolicy']['Name']
    if restart != 'no':
        assert restart in ('always', 'unless-stopped')
        command += ['--restart', restart]
    for key, value in (source['Config']['Labels'] or {}).items():
        command += ['--label', key + '=' + value]
    if source['Config'].get('User'):
        command += ['--user', source['Config']['User']]
    if source['Config'].get('WorkingDir'):
        command += ['--workdir', source['Config']['WorkingDir']]
    for mount in source['Mounts']:
        command += ['--mount', f"type=bind,src={mount['Source']},dst={mount['Destination']},readonly"]
    command += [source['Config']['Image']] + source['Config']['Cmd']
    stopped = False
    renamed = False
    try:
        print('当前无活跃 Turn，开始顺序切换单活 Agent', flush=True)
        subprocess.run(['docker', 'stop', '--time', '150', NAME], check=True, capture_output=True)
        stopped = True
        subprocess.run(['docker', 'rename', NAME, BACKUP], check=True, capture_output=True)
        renamed = True
        atomic_copy(CANDIDATE)
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        report['new_container_id'] = result.stdout.strip()
        (ROOT / 'deployment.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        health()
        live = inspect(NAME)
        running_env = dict(item.split('=', 1) for item in live['Config']['Env'] if '=' in item)
        assert all(running_env[key] == value for key, value in PARAMETERS.items())
        changed_keys = {key for key in set(original_env) | set(running_env)
            if original_env.get(key) != running_env.get(key)}
        assert changed_keys <= set(PARAMETERS) | {'SERVER_SHUTDOWN', 'SPRING_LIFECYCLE_TIMEOUT_PER_SHUTDOWN_PHASE'}
        assert not inspect(BACKUP)['State']['Running']
        assert report['model_before'] == identity()
        report.update(deployed=True, health_up=True, model_after=identity(), model_process_unchanged=True,
            changed_environment_keys=sorted(changed_keys), switched_at_epoch=time.time())
        (ROOT / 'deployment.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print('新版 Agent 已在原端口 18214 就绪；旧容器已停止并保留；模型未变', flush=True)
    except BaseException:
        if renamed:
            restore(report)
        elif stopped:
            subprocess.run(['docker', 'start', NAME], check=True, capture_output=True)
        raise
    finally:
        envfile.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
