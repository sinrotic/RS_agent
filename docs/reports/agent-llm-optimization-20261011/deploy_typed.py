"""只替换自有 QA Agent 构建，验证类型约束与完整模型流程。"""
from pathlib import Path
import subprocess

ROOT=Path('/tmp/rs-agent-e2e-20261010-llm-opt-20261011')
original=ROOT/'rs-service-agent.jar'; backup=ROOT/'rs-service-agent-synthesis-before-typed.jar'
assert not backup.exists()
original.rename(backup); (ROOT/'rs-service-agent-typed.jar').rename(original)
subprocess.run(['python3',str(ROOT/'restart_services.py'),'control'],check=True)
subprocess.run(['python3',str(ROOT/'baseline.py'),'typed'],check=True)
