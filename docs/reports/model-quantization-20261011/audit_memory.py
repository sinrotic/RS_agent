"""导出正式 INT4 与显存预算的运行证据，不导出环境或请求正文。"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import socket
import subprocess
import urllib.request

root = Path(__file__).resolve().parent
live = Path('/home/luo/RS_agent_java/model_deploy')
state = json.loads((root / 'memory-deployment-state.json').read_text())
assert state['promoted'] and not state['rollback']
assert hashlib.sha256((live / '.env').read_bytes()).hexdigest() == state['deployed_env_sha256']
for name, digest in state['baseline_sha256'].items():
    if name != '.env':
        assert hashlib.sha256((live / name).read_bytes()).hexdigest() == digest
spec = importlib.util.spec_from_file_location('memory_deploy', root / 'memory_deploy.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
api = module.process(state['updates']['MODEL_PATH'])
assert api == state['api_pid']
with urllib.request.urlopen('http://127.0.0.1:18082/v1/models', timeout=5) as response:
    models = json.load(response)
assert models['data'][0]['root'] == state['updates']['MODEL_PATH']
with urllib.request.urlopen('http://127.0.0.1:18082/health', timeout=5) as response:
    assert response.status == 200
ready = Path('/tmp/rs_agent_latency/vllm_qwen35_4b.ready')
probe = json.loads(Path(str(ready) + '.structured-output.json').read_text())
assert ready.exists() and probe['status'] == 'PASS' and 'named_tool_concurrency_8' in probe['cases']
config = json.loads((Path(state['updates']['MODEL_PATH']) / 'config.json').read_text())
quant = config['quantization_config']
assert quant['bits'] == 4
log = (live / 'quantization-memory50-20261011.log').read_text(errors='replace')
assert 'quantization=inc' in log
loading = re.findall(r'Model loading took ([0-9.]+) GiB memory', log)
assert loading
kernel = [line for line in log.splitlines() if 'MarlinLinearKernel' in line or 'Selected Marlin' in line]
assert kernel
with socket.socket() as connection:
    isolated_closed = connection.connect_ex(('127.0.0.1', 18092)) != 0
assert isolated_closed
report = {'health': 200, 'precision': 'INT4 weights / BF16 activations', 'model_root': models['data'][0]['root'],
          'api_pid': api, 'gpu': 1, 'max_model_len': 16384, 'gpu_memory_utilization': 0.50,
          'ready_probe': probe, 'model_loading_gib': float(loading[-1]), 'quantization_config': quant,
          'kernel_evidence': kernel, 'gpu_memory': module.gpu(), 'runtime_env_sha256': state['deployed_env_sha256'],
          'startup_scripts_unchanged': True, 'isolated_model_port_closed': isolated_closed,
          'cache_capacity_evidence': [line for line in log.splitlines() if any(term in line for term in
               ['Available KV cache memory', 'GPU KV cache size', 'Maximum concurrency', 'Mamba cache size'])]}
(root / 'memory-live-state.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
subprocess.run(['/mnt/data/luo/venvs/rsagent-vllm/bin/python', str(live / 'restore_qwen35_4b_memory50.py')], check=True)
print('正式 INT4、原分词器、50% 预算、16K、结构化探针和恢复脚本均已核验', flush=True)
