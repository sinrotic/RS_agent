"""核验正式部署与回退入口，仅导出公开配置和显存证据。"""
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

import deployment_runtime as runtime

ROOT = Path('/tmp/rs-agent-partial-quantization-20261011')
report = json.loads((ROOT / 'deployment-state.json').read_text())
assert report['promoted'] and not report['rollback'] and report['own_validation_cleanup_passed']
assert json.loads(runtime.STATE.read_text()) == report
assert runtime.digest(runtime.LIVE / '.env') == report['deployed_env_sha256']
for name, digest in report['baseline_sha256'].items():
    if name != '.env':
        assert runtime.digest(runtime.LIVE / name) == digest
api, launcher = runtime.identity(report['updates']['MODEL_PATH'], 0.40, 64)
assert (api, launcher) == (report['api_pid'], report['launcher_pid'])
with urllib.request.urlopen('http://127.0.0.1:18082/v1/models', timeout=5) as response:
    models = json.load(response)
assert models['data'][0]['root'] == report['updates']['MODEL_PATH']
assert models['data'][0]['id'] == 'qwen35-4b' and models['data'][0]['max_model_len'] == 16384
assert runtime.health()
probe = json.loads(Path(str(runtime.READY) + '.structured-output.json').read_text())
assert probe['status'] == 'PASS' and 'named_tool_concurrency_8' in probe['cases']
log = (runtime.LIVE / 'partial-quantization-memory40-20261011.log').read_text(errors='replace')
assert 'quantization=inc' in log and 'dtype=torch.bfloat16' in log and 'MarlinLinearKernel' in log
loading = re.findall(r'Model loading took ([0-9.]+) GiB memory', log)
assert loading and abs(float(loading[-1]) - 5.52) < 0.1
source = json.loads((ROOT / 'mlp_only-source.json').read_text())
config = json.loads((Path(source['path']) / 'config.json').read_text())
assert config['quantization_config']['block_name_to_quantize'] == [f'model.language_model.layers.{i}.mlp' for i in range(32)]
assert config['quantization_config']['bits'] == 4 and source['int4_modules'] == 96
for name, digest in source['asset_sha256'].items():
    assert runtime.digest(Path(source['path']) / name) == digest
for local, remote in [('deployment_runtime.py', 'partial_quantization_runtime_20261011.py'),
                      ('restore.py', 'restore_qwen35_4b_partial_memory40.py')]:
    assert runtime.digest(ROOT / local) == runtime.digest(runtime.LIVE / remote)
assert not (ROOT / 'accounts.json').exists()
assert not Path('/tmp/rs-agent-quantization-retry-20261011/agent-clone.private.env').exists()
assert all(runtime.closed(port) for port in [18092, 18314, 18094])
source_agent = json.loads(subprocess.check_output(['docker', 'inspect', 'rs-e2e-857e8b14-agent-fast'], text=True))[0]
assert source_agent['State']['Running']
source_env = dict(value.split('=', 1) for value in source_agent['Config']['Env'] if '=' in value)
source_url = source_env['RS_AGENT_OPENAI_BASE_URL'].rstrip('/')
assert source_url in ['http://127.0.0.1:18082/v1', 'http://localhost:18082/v1']
assert source_agent['HostConfig']['NetworkMode'] == 'host'
before_pids = {row['pid'] for row in report['gpu_before']['processes']}
assert 3417056 in before_pids
bge_args = Path('/proc/3417056/cmdline').read_bytes().split(bytes([0]))
assert b'/tmp/rs-agent-e2e-20261010-llm-opt-20261011/bge_m3_embedding_server.py' in bge_args
runtime.wait_idle()
state = {'health': 200, 'model_root': models['data'][0]['root'], 'served_model': 'qwen35-4b',
    'precision': 'MLP INT4 / attention and GDN BF16', 'int4_modules': 96, 'model_loading_gib': float(loading[-1]),
    'gpu': 1, 'gpu_memory_utilization': 0.40, 'max_num_seqs': 64, 'max_model_len': 16384,
    'api_pid': api, 'launcher_pid': launcher, 'gpu_memory': runtime.gpu(), 'structured_probe': probe,
    'startup_scripts_unchanged': True, 'runtime_env_sha256': report['deployed_env_sha256'],
    'shared_agent_running': True, 'shared_agent_model_url': source_url,
    'bge_pid_unchanged': 3417056, 'own_validation_cleaned': True,
    'kernel_evidence': [line for line in log.splitlines() if 'MarlinLinearKernel' in line],
    'cache_capacity_evidence': [line for line in log.splitlines() if any(term in line for term in
        ['Available KV cache memory', 'GPU KV cache size', 'Maximum concurrency'])]}
(ROOT / 'deployment-live-state.json').write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
subprocess.run([sys.executable, report['restore_script']], check=True)
print('正式部分量化、40% / 64 / 16K、BF16 激活、Marlin、原分词器、清理及回退入口核验通过', flush=True)

