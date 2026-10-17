"""部署已通过回归的最终 QA 构建，保留配置绑定修复前的失败样本。"""
import subprocess
from probe import ROOT

original=ROOT/'rs-service-agent.jar';backup=ROOT/'rs-service-agent-before-delegate-fix.jar'
assert not backup.exists()
original.rename(backup);(ROOT/'rs-service-agent-fixed.jar').rename(original)
subprocess.run(['python3',str(ROOT/'restart_services.py'),'control'],check=True)
subprocess.run(['python3',str(ROOT/'baseline.py'),'optimized-final'],check=True)
subprocess.run(['python3',str(ROOT/'concurrent_matrix.py'),'optimized-final-concurrent'],check=True)
