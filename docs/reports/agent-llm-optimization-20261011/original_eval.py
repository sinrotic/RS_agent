"""同一业务构建下对照原 BF16 解码，等待原启动校验后再测。"""
import json
from pathlib import Path
import subprocess
import time
from probe import ROOT

for _ in range(180):
    state=json.loads((ROOT/'model-switch.json').read_text())
    assert state['mode']=='restore'
    assert Path(f"/proc/{state['pid']}/cmdline").exists()
    if Path(state['ready_file']).exists(): break
    time.sleep(2)
else: raise RuntimeError('原模型未通过启动验收')
print('原 BF16 配置通过启动验收',flush=True)
subprocess.run(['python3',str(ROOT/'start_bge.py')],check=True)
subprocess.run(['python3',str(ROOT/'model_bench.py'),'model-bench-original'],check=True)
subprocess.run(['python3',str(ROOT/'baseline.py'),'original-control'],check=True)
subprocess.run(['python3',str(ROOT/'concurrent_matrix.py'),'original-control-concurrent'],check=True)
