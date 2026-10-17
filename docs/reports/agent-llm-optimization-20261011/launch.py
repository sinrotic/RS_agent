"""只启动本次辅助服务；GPU 0/2 不做任何变更。"""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path('/tmp/rs-agent-e2e-20261010-llm-opt-20261011')
subprocess.run(['python3',str(ROOT/'environment.py'),'prepare','--root',str(ROOT)],check=True)
subprocess.run(['python3',str(ROOT/'start_bge.py')],check=True)
command = ['python3',str(ROOT/'model_wire_probe.py')]
with (ROOT/'wire-probe.log').open('wb') as output:
    process=subprocess.Popen(command,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
(ROOT/'wire-probe-pid.json').write_text(json.dumps({'pid':process.pid,'command':command}))
environment=dict(os.environ,RS_PROFILE_ENABLED='false')
subprocess.run(['python3',str(ROOT/'environment.py'),'services','--root',str(ROOT)],check=True,env=environment)
subprocess.run(['python3',str(ROOT/'baseline.py'),'baseline'],check=True)
