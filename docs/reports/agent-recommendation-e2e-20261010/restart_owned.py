"""重启验收 Recommend 清空计算缓存；只作用于 state 登记的容器。"""
import json
import subprocess
import time
import urllib.request
from pathlib import Path

root=Path('/tmp/rs-agent-e2e-20261010-1247')
state=json.loads((root/'state.json').read_text()); name=state['recommend-fast']
assert name == 'rs-e2e-'+state['suffix']+'-recommend-fast' and name in state['containers']
config=json.loads(subprocess.check_output(['docker','inspect',name]))[0]
env=root/'restart-owned.env'; env.write_text('\n'.join(config['Config']['Env']));env.chmod(0o600)
try:
    subprocess.run(['docker','rm','-f',name],check=True,capture_output=True)
    subprocess.run(['docker','run','-d','--name',name,'--network','host','--env-file',str(env),
          '-v',str(root/'rs-service-recommend.jar')+':/app/service.jar:ro',
          'eclipse-temurin:21-jre','sh','-c','exec java $JAVA_OPTS -jar /app/service.jar'],check=True,capture_output=True)
finally: env.unlink()
for _ in range(60):
    try:
        with urllib.request.urlopen('http://127.0.0.1:18213/actuator/health',timeout=2) as response:
            if json.load(response)['status']=='UP': break
    except Exception: pass
    time.sleep(1)
else: raise RuntimeError('readiness failed')
print('owned Recommend ready; inference caches empty',flush=True)
