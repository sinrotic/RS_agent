"""仅重新创建记录在验收 state 内的 Agent 快速路径容器。"""
import json
import subprocess
import time
import urllib.request
from pathlib import Path

root=Path('/tmp/rs-agent-e2e-20261010-pool-1400')
state=json.loads((root/'state.json').read_text())
assert not state.get('cleaned'), 'QA workspace has already been cleaned'
name=state['agent-fast']
assert name == 'rs-e2e-'+state['suffix']+'-agent-fast' and name in state['containers']
config=json.loads(subprocess.check_output(['docker','inspect',name]))[0]
env=root/'replace-fast.env'
env.write_text('\n'.join(config['Config']['Env']));env.chmod(0o600)
try:
    subprocess.run(['docker','rm','-f',name],check=True,capture_output=True)
    subprocess.run(['docker','run','-d','--name',name,'--network','host','--env-file',str(env),
          '-v',str(root/'rs-service-agent-final.jar')+':/app/service.jar:ro',
          'eclipse-temurin:21-jre','sh','-c','exec java $JAVA_OPTS -jar /app/service.jar'],check=True,capture_output=True)
finally: env.unlink()
print('updated isolated Agent fast')
for _ in range(60):
    try:
        with urllib.request.urlopen('http://127.0.0.1:18214/actuator/health', timeout=1) as response:
            if json.load(response).get('status') == 'UP':
                break
    except Exception:
        pass
    time.sleep(1)
else:
    raise RuntimeError('replaced Agent readiness failed')
print('replaced isolated Agent ready', flush=True)
