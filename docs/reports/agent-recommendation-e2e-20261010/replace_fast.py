"""仅重新创建记录在验收 state 内的 Agent 快速路径容器。"""
import json
import subprocess
from pathlib import Path

root=Path('/tmp/rs-agent-e2e-20261010-1247')
state=json.loads((root/'state.json').read_text())
name=state['agent-fast']
assert name == 'rs-e2e-'+state['suffix']+'-agent-fast' and name in state['containers']
config=json.loads(subprocess.check_output(['docker','inspect',name]))[0]
env=root/'replace-fast.env'
env.write_text('\n'.join(config['Config']['Env']));env.chmod(0o600)
try:
    subprocess.run(['docker','rm','-f',name],check=True,capture_output=True)
    subprocess.run(['docker','run','-d','--name',name,'--network','host','--env-file',str(env),
          '-v',str(root/'rs-service-agent-updated.jar')+':/app/service.jar:ro',
          'eclipse-temurin:21-jre','sh','-c','exec java $JAVA_OPTS -jar /app/service.jar'],check=True,capture_output=True)
finally: env.unlink()
print('updated isolated Agent fast')
