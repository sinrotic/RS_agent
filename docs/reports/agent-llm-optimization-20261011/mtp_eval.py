"""MTP 必须先过启动验收，再依次进行固定输入、全流程、并发对照。"""
import json
from pathlib import Path
import subprocess
import time
from probe import ROOT

for _ in range(120):
    state=json.loads((ROOT/'model-switch.json').read_text())
    assert state['mode']=='mtp'
    assert Path(f"/proc/{state['pid']}/cmdline").exists(),'实验模型已停止'
    if Path(state['ready_file']).exists(): break
    time.sleep(2)
else: raise RuntimeError('实验模型未通过启动验收')
print('MTP 已通过模型启动验收',flush=True)
subprocess.run(['python3',str(ROOT/'start_bge.py')],check=True)
subprocess.run(['python3',str(ROOT/'model_floor.py'),'model-floor-mtp'],check=False)
subprocess.run(['python3',str(ROOT/'model_bench.py'),'model-bench-mtp'],check=True)
subprocess.run(['python3',str(ROOT/'baseline.py'),'mtp'],check=True)
subprocess.run(['python3',str(ROOT/'concurrent_matrix.py'),'mtp-concurrent'],check=True)
