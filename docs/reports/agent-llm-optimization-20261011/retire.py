"""等待其他任务的模型部署结束，再撤除本次诊断代理；不终止其他任务。"""
import subprocess
import time
import urllib.request
from probe import ROOT

deadline=time.monotonic()+360
while time.monotonic()<deadline:
    deployment=subprocess.run(['pgrep','-f','^/mnt/data/luo/venvs/rsagent-vllm/bin/python /tmp/rs-serving-tuning-20261011/deploy.py --apply$'],capture_output=True)
    if deployment.returncode==1:
        try:
            with urllib.request.urlopen('http://127.0.0.1:18082/health',timeout=2) as response:
                if response.status==200:break
        except Exception:pass
    time.sleep(2)
else:raise RuntimeError('其他模型部署仍在进行，不对其进程或配置执行清理')
subprocess.run(['python3',str(ROOT/'cleanup_verify.py')],check=True)
