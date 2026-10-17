"""自有 QA 中替换 Agent，保留失败实验构建；每轮仍调用模型。"""
from pathlib import Path
import subprocess

ROOT = Path('/tmp/rs-agent-e2e-20261010-llm-opt-20261011')
original = ROOT / 'rs-service-agent.jar'
backup = ROOT / 'rs-service-agent-compact-regression.jar'
assert not backup.exists()
original.rename(backup)
(ROOT / 'rs-service-agent-synthesis.jar').rename(original)
file = ROOT / 'environment.py'
source = file.read_text()
assert '"RS_AGENT_LLM_SYNTHESIS_ENABLED"' not in source
assert '"RS_AGENT_COMPACT_TOOL_SCHEMAS_ENABLED": "true"' in source
source = source.replace('"RS_AGENT_DIRECT_RECOMMENDATION_ENABLED": "false",',
    '"RS_AGENT_DIRECT_RECOMMENDATION_ENABLED": "false", "RS_AGENT_LLM_SYNTHESIS_ENABLED": "true",')
file.write_text(source)
subprocess.run(['python3', str(ROOT / 'restart_services.py'), 'control'], check=True)
subprocess.run(['python3', str(ROOT / 'baseline.py'), 'synthesis'], check=True)
