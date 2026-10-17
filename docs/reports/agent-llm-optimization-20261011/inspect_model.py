"""只读取模型和运行时能力；不加载权重，不输出环境凭证。"""
import importlib.metadata
import json
from pathlib import Path
import subprocess

ROOT=Path('/tmp/rs-agent-e2e-20261010-llm-opt-20261011')
model=Path('/mnt/data/luo/models/Qwen3.5-4B')
index=json.loads((model/'model.safetensors.index.json').read_text())
weights=[name for name in index['weight_map'] if 'mtp' in name.lower()]
package=Path('/mnt/data/luo/venvs/rsagent-vllm/lib/python3.12/site-packages/vllm')
lines=[]
for relative in ('config/speculative.py','config/cache.py','model_executor/models/qwen3_5_mtp.py'):
    file=package/relative
    if file.exists():
        matches=[line.strip() for line in file.read_text().splitlines() if 'prefix' in line.lower() or 'mtp' in line.lower() or 'mamba_cache_mode' in line]
        lines.append({'file':relative,'matches':matches[:30]})
result={'vllm_version':subprocess.check_output(['/mnt/data/luo/venvs/rsagent-vllm/bin/python','-c','import importlib.metadata;print(importlib.metadata.version("vllm"))'],text=True).strip(),
        'mtp_weight_count':len(weights),'mtp_weight_names':weights[:8],'runtime_capability':lines}
(ROOT/'model-capability.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False,indent=2))
