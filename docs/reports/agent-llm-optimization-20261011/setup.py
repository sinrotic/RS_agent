"""创建新的真实依赖验收环境，强制关闭不经过 LLM 的直接回答。"""
import json
from pathlib import Path
import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SOURCE = HERE.parent / 'agent-storage-optimization-20261010'
ROOT = '/tmp/rs-agent-e2e-20261010-llm-opt-20261011'
OLD = '/tmp/rs-agent-e2e-20261010-storage-opt'
def run(args, **kwargs): return subprocess.run(args, check=True, text=True, encoding='utf-8', **kwargs)

bootstrap = f'''from pathlib import Path
import json,shutil
root=Path({ROOT!r});old=Path({OLD!r})
assert json.loads((old/'state.json').read_text())['cleaned']
assert not root.exists()
root.mkdir()
names=('rs-service-catalog.jar','rs-service-model.jar','rs-service-user.jar','rs-service-platform-trace.jar','rs-service-recommend.jar','rs-service-agent.jar','rs-api-gateway.jar','bge_m3_embedding_server.py','latency-agent-v2.jar')
for file in old.iterdir():
    if file.name in names or file.suffix in ('.sql','.cql'): shutil.copy2(file,root/file.name)
'''
run(['ssh','server','python3','-'], input=bootstrap)
for name in ('environment.py','probe.py','measure.py','start_bge.py','stop_bge.py','restart_services.py','model_wire_probe.py'):
    text = (SOURCE / name).read_text(encoding='utf-8').replace(OLD, ROOT)
    if name == 'environment.py':
        text = text.replace('"RS_AGENT_DIRECT_RECOMMENDATION_ENABLED": "true"', '"RS_AGENT_DIRECT_RECOMMENDATION_ENABLED": "false"')
        text = text.replace('"RS_AGENT_OPENAI_BASE_URL": os.environ.get("RS_OPT_MODEL_BASE_URL", "http://127.0.0.1:18082/v1")', '"RS_AGENT_OPENAI_BASE_URL": "http://127.0.0.1:18217/v1"')
    (HERE / name).write_text(text, encoding='utf-8')
    run(['scp',str(HERE / name),'server:'+ROOT+'/'+name])
run(['scp',str(HERE / 'baseline.py'),'server:'+ROOT+'/baseline.py'])
run(['scp',str(HERE / 'launch.py'),'server:'+ROOT+'/launch.py'])
print('已创建新的 LLM 验收目录', flush=True)
