"""仅替换自有 QA Agent 构建并打开独立开关；保留基线。"""
from pathlib import Path
import subprocess
import json
import os

ROOT=Path('/tmp/rs-agent-e2e-20261010-llm-opt-20261011')
original=ROOT/'rs-service-agent.jar';backup=ROOT/'rs-service-agent-baseline.jar'
assert not backup.exists()
original.rename(backup);(ROOT/'rs-service-agent-compact.jar').rename(original)
file=ROOT/'environment.py';source=file.read_text()
assert '"RS_AGENT_COMPACT_TOOL_SCHEMAS_ENABLED"' not in source
source=source.replace('"RS_AGENT_DIRECT_RECOMMENDATION_ENABLED": "false",','"RS_AGENT_DIRECT_RECOMMENDATION_ENABLED": "false", "RS_AGENT_COMPACT_TOOL_SCHEMAS_ENABLED": "true",')
file.write_text(source)
subprocess.run(['python3',str(ROOT/'restart_services.py'),'control'],check=True)
subprocess.run(['python3',str(ROOT/'baseline.py'),'compact'],check=True)
