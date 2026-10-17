"""自有 QA 中部署最终已测构建，不覆盖正式业务服务。"""
import subprocess
from probe import ROOT

original=ROOT/'rs-service-agent.jar';backup=ROOT/'rs-service-agent-before-card-reference.jar'
assert not backup.exists()
original.rename(backup);(ROOT/'rs-service-agent-final.jar').rename(original)
subprocess.run(['python3',str(ROOT/'restart_services.py'),'control'],check=True)
