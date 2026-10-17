"""核验部分量化缓存扩容，导出容量与实际运行证据。"""
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

import deployment_runtime as runtime

ROOT = Path('/tmp/rs-agent-partial-quantization-20261011')
STATE = runtime.LIVE / 'partial-quantization-memory50-state.json'
report = json.loads((ROOT / 'cache50-deployment-state.json').read_text())
assert report['promoted'] and not report['rollback'] and report['own_validation_cleanup_passed']
assert json.loads(STATE.read_text()) == report
assert runtime.digest(runtime.LIVE / '.env') == report['deployed_env_sha256']
for name, digest in report['baseline_sha256'].items():
    if name != '.env':
        assert runtime.digest(runtime.LIVE / name) == digest
api, launcher = runtime.identity(report['updates']['MODEL_PATH'], 0.50, 128)
assert (api, launcher) == (report['api_pid'], report['launcher_pid'])
with urllib.request.urlopen('http://127.0.0.1:18082/v1/models', timeout=5) as response:
    models = json.load(response)
assert models['data'][0]['root'] == report['updates']['MODEL_PATH']
assert models['data'][0]['id'] == 'qwen35-4b' and models['data'][0]['max_model_len'] == 16384
assert runtime.health()
probe = json.loads(Path(str(runtime.READY) + '.structured-output.json').read_text())
assert probe['status'] == 'PASS' and 'named_tool_concurrency_8' in probe['cases']
log = (runtime.LIVE / 'partial-quantization-memory50-20261011.log').read_text(errors='replace')
assert 'dtype=torch.bfloat16' in log and 'quantization=inc' in log and 'MarlinLinearKernel' in log
loading = float(re.findall(r'Model loading took ([0-9.]+) GiB memory', log)[-1])
kv_gib = float(re.findall(r'Available KV cache memory: ([0-9.]+) GiB', log)[-1])
kv_tokens = int(re.findall(r'GPU KV cache size: ([0-9,]+) tokens', log)[-1].replace(',', ''))
concurrency = float(re.findall(r'Maximum concurrency for 16,384 tokens per request: ([0-9.]+)x', log)[-1])
assert abs(loading - 5.52) < 0.1 and kv_gib >= 3.8 and kv_tokens >= 100000 and concurrency > 6
source = json.loads((ROOT / 'mlp_only-source.json').read_text())
config = json.loads((Path(source['path']) / 'config.json').read_text())
assert config['quantization_config']['bits'] == 4
assert config['quantization_config']['block_name_to_quantize'] == [f'model.language_model.layers.{i}.mlp' for i in range(32)]
for name, digest in source['asset_sha256'].items():
    assert runtime.digest(Path(source['path']) / name) == digest
env = dict(value.split('=', 1) for value in Path(f'/proc/{api}/environ').read_bytes().decode().split('\0') if '=' in value)
args = Path(f'/proc/{api}/cmdline').read_bytes().decode().split('\0')
assert '--enable-prefix-caching' in args and env['VLLM_PREFIX_KEEPALIVE'] == 'true'
assert env['VLLM_WARMUP_ONLY_WHEN_IDLE'] == 'true'
assert runtime.digest(ROOT / 'restore_cache50.py') == runtime.digest(Path(report['restore_script']))
assert not (ROOT / 'accounts.json').exists()
assert not Path('/tmp/rs-agent-quantization-retry-20261011/agent-clone.private.env').exists()
assert all(runtime.closed(port) for port in [18092, 18314, 18094])
agent = json.loads(subprocess.check_output(['docker', 'inspect', 'rs-e2e-857e8b14-agent-fast'], text=True))[0]
agent_env = dict(value.split('=', 1) for value in agent['Config']['Env'] if '=' in value)
assert agent['State']['Running'] and agent_env['RS_AGENT_OPENAI_BASE_URL'].rstrip('/') == 'http://127.0.0.1:18082/v1'
assert b'/tmp/rs-agent-e2e-20261010-llm-opt-20261011/bge_m3_embedding_server.py' in Path('/proc/3417056/cmdline').read_bytes().split(bytes([0]))
runtime.wait_idle()
state = {'health': 200, 'precision': report['precision'], 'model_root': models['data'][0]['root'],
    'served_model': 'qwen35-4b', 'gpu': 1, 'gpu_memory_utilization': 0.50, 'max_num_seqs': 128,
    'max_model_len': 16384, 'model_loading_gib': loading, 'kv_cache_gib': kv_gib,
    'kv_cache_tokens': kv_tokens, 'estimated_full_context_concurrency': concurrency,
    'api_pid': api, 'launcher_pid': launcher, 'gpu_memory': runtime.gpu(), 'structured_probe': probe,
    'runtime_env_sha256': report['deployed_env_sha256'], 'startup_scripts_unchanged': True,
    'prefix_caching_enabled': True, 'prefix_keepalive_enabled': True, 'warmup_only_when_idle': True,
    'shared_agent_running': True, 'bge_pid_unchanged': 3417056, 'own_validation_cleaned': True}
(ROOT / 'cache50-live-state.json').write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
subprocess.run([sys.executable, report['restore_script']], check=True)
print('50% / 128 / 16K、KV 容量、前缀缓存、保温、共享服务及恢复入口核验通过', flush=True)
