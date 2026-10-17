"""只读核验共享服务仍可用、本次容器与私有环境副本已清理。"""
import hashlib
import json
import subprocess
import urllib.request

import concurrency_probe as harness


def main():
    clone = subprocess.run(['docker', 'inspect', harness.NAME], capture_output=True)
    assert clone.returncode != 0
    assert not (harness.ROOT / 'clone.private.env').exists()
    source = json.loads(subprocess.check_output(['docker', 'inspect', harness.SOURCE], text=True))[0]
    assert source['State']['Running']
    env = dict(item.split('=', 1) for item in source['Config']['Env'] if '=' in item)
    assert env['RS_AGENT_OPENAI_BASE_URL'] == 'http://127.0.0.1:18082/v1'
    jar = next(mount['Source'] for mount in source['Mounts'] if mount['Source'].endswith('/rs-service-agent.jar'))
    with open(jar, 'rb') as stream:
        shared_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    for address in ('http://127.0.0.1:18214/actuator/health', 'http://127.0.0.1:18082/health'):
        with urllib.request.urlopen(address, timeout=10) as response:
            assert response.status == 200
    model = harness.identity()
    candidate = json.loads((harness.ROOT / 'guarded4-repeat.json').read_text())
    assert model == candidate['model_after']
    report = {'clone_absent': True, 'private_env_absent': True, 'shared_agent_running': True,
              'shared_agent_health_200': True, 'model_health_200': True, 'model_identity_unchanged': True,
              'shared_agent_mounted_jar_sha256': shared_sha, 'shared_agent_rollout': False}
    (harness.ROOT / 'runtime-check.json').write_text(json.dumps(report, indent=2))
    print('共享 Agent 和模型健康；本次容器及私有环境副本已清理', flush=True)


if __name__ == '__main__':
    main()
