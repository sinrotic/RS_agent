"""观察并保留其他任务的正式模型部署，待其完成后重新评测，不操作模型进程。"""
import json
from pathlib import Path
import subprocess
import time
from probe import ROOT

deployment=Path('/tmp/rs-serving-tuning-20261011/deployment-state.json')
ready=Path('/tmp/rs_agent_latency/vllm_qwen35_4b.ready')
deadline=time.monotonic()+360
while time.monotonic()<deadline:
    if deployment.exists() and ready.exists():
        state=json.loads(deployment.read_text())
        if state.get('promoted') or state.get('rollback'):
            (ROOT/'external-model-deployment.json').write_text(json.dumps(state,ensure_ascii=False,indent=2))
            break
    time.sleep(2)
else: raise RuntimeError('另一项模型部署尚未完成，不能据此评测或恢复旧模型')
print('另一项模型部署已结束；开始新配置下的完整流程评测',flush=True)
for phase,script in (('serving-refresh','baseline.py'),('serving-refresh-concurrent','concurrent_matrix.py')):
    subprocess.run(['python3',str(ROOT/script),phase],check=True)
audit=ROOT/'audit.json'
if audit.exists(): audit.rename(ROOT/'audit-original-model.json')
subprocess.run(['python3',str(ROOT/'audit.py'),'serving-refresh','serving-refresh-concurrent'],check=True)
timeout=ROOT/'timeout-probe.json'
if timeout.exists():timeout.rename(ROOT/'timeout-probe-failed.json')
subprocess.run(['python3',str(ROOT/'timeout_probe.py')],check=True)
