"""只输出部署相关的非私密状态；不会打印容器环境或业务日志。"""
import json
import subprocess
import urllib.request
from pathlib import Path

NAME = 'rs-e2e-857e8b14-agent-fast'
ROOT = Path(__file__).resolve().parent


def active_threads(container):
    target = '/tmp/rs-live-switch-20261011-threads.json'
    dump = ROOT / 'threads.private.json'
    command = ['docker', 'run', '--rm', '--pid', 'container:' + NAME, '--network', 'none',
        '--mount', 'type=bind,src=/usr/lib/jvm/java-21-openjdk-amd64,dst=/jdk,readonly',
        container['Config']['Image'], '/jdk/bin/jcmd', '1', 'Thread.dump_to_file', '-overwrite', '-format=json', target]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError('JVM 活跃 Turn 检查失败，未继续切换')
        subprocess.run(['docker', 'cp', NAME + ':' + target, str(dump)], check=True, capture_output=True)
        dump.chmod(0o600)
        threads = json.loads(dump.read_text())['threadDump']['threadContainers']
        active = []
        for group in threads:
            for thread in group.get('threads', []):
                stack = '\n'.join(thread.get('stack', []))
                if any(value in stack for value in ('InMemoryAgentOrchestrationService.chat',
                    'InMemoryAgentOrchestrationService.streamChat', 'AgentChatController.lambda$streamChat')):
                    active.append(thread)
        return len(active)
    finally:
        dump.unlink(missing_ok=True)
        subprocess.run(['docker', 'exec', NAME, 'rm', '-f', target], capture_output=True)


def main():
    container = json.loads(subprocess.check_output(['docker', 'inspect', NAME], text=True))[0]
    env = dict(item.split('=', 1) for item in container['Config']['Env'] if '=' in item)
    report = {'running': container['State']['Running'], 'pid': container['State']['Pid'],
        'memory_limit': container['HostConfig']['Memory'], 'network': container['HostConfig']['NetworkMode'],
        'mounts': container['Mounts'], 'command': container['Config']['Cmd'],
        'selected_env': {key: value for key, value in env.items() if key.startswith('RS_AGENT_MAX_')
            or key.endswith('_ACQUIRE_TIMEOUT_MS') or key in ('SERVER_PORT', 'SERVER_SHUTDOWN',
            'SPRING_LIFECYCLE_TIMEOUT_PER_SHUTDOWN_PHASE', 'RS_AGENT_PERFORMANCE_OBSERVATION_ENABLED',
            'RS_AGENT_LLM_SYNTHESIS_ENABLED', 'RS_AGENT_DIRECT_RECOMMENDATION_ENABLED')},
        'qa_env_files': [file.name for file in Path('/tmp/rs-agent-e2e-20261010-llm-opt-20261011').glob('*env*')]}
    try:
        with urllib.request.urlopen('http://127.0.0.1:18214/actuator/metrics', timeout=5) as response:
            report['metric_names'] = json.load(response).get('names', [])
    except Exception as error:
        report['metrics_available'] = False
        report['metrics_error_type'] = type(error).__name__
    # 一次性 JDK 诊断进程与目标 JVM 共享 PID 空间，可观察虚拟线程；不运行第二个 Agent。
    report['active_turn_threads'] = active_threads(container)
    (ROOT / 'preflight.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
