"""只替换已通过本地检查的自有 QA Agent 构建。"""
import subprocess
from probe import ROOT

original=ROOT/'rs-service-agent.jar'; backup=ROOT/'rs-service-agent-before-grounding.jar'
assert not backup.exists()
original.rename(backup); (ROOT/'rs-service-agent-grounded.jar').rename(original)
subprocess.run(['python3',str(ROOT/'restart_services.py'),'control'],check=True)
