"""只导出模型运行状态；不输出完整环境、密钥或真实请求。"""
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parent
LIVE = Path('/home/luo/RS_agent_java/model_deploy')
expected = json.loads((ROOT / 'deployment-state.json').read_text())
assert expected['promoted']
with urllib.request.urlopen('http://127.0.0.1:18082/v1/models', timeout=5) as response:
    models = json.load(response)
assert models['data'][0]['root'] == expected['updates']['MODEL_PATH']
with urllib.request.urlopen('http://127.0.0.1:18082/health', timeout=5) as response:
    health = response.status
ready = Path('/tmp/rs_agent_latency/vllm_qwen35_4b.ready')
probe = json.loads(Path(str(ready) + '.structured-output.json').read_text())
assert health == 200 and ready.exists() and probe['status'] == 'PASS'
processes = []
for directory in Path('/proc').iterdir():
    if not directory.name.isdigit():
        continue
    try:
        args = (directory / 'cmdline').read_bytes().decode().split('\0')
        if 'serve' not in args or expected['updates']['MODEL_PATH'] not in args:
            continue
        env = dict(x.split('=', 1) for x in (directory / 'environ').read_bytes().decode().split('\0') if '=' in x)
        assert env.get('CUDA_VISIBLE_DEVICES') == '1'
        assert args[args.index('--port') + 1] == '18082'
        processes.append({'pid': int(directory.name), 'gpu': env['CUDA_VISIBLE_DEVICES'], 'arguments': args[:-1],
                          'force_fp8_marlin': env.get('VLLM_TEST_FORCE_FP8_MARLIN')})
    except (FileNotFoundError, ProcessLookupError):
        pass
assert len(processes) == 1
log = (LIVE / 'quantization-20261011.log').read_text(errors='replace')
loading = re.findall(r'Model loading took ([0-9.]+) GiB memory', log)
assert loading
config = json.loads((Path(expected['updates']['MODEL_PATH']) / 'config.json').read_text())
with socket.socket() as connection:
    isolated_port_closed = connection.connect_ex(('127.0.0.1', 18092)) != 0
assert isolated_port_closed
report = {'health': health, 'ready_probe': probe, 'models': models, 'processes': processes,
          'model_loading_gib': float(loading[-1]), 'quantization_config': config.get('quantization_config'),
          'env_sha256': hashlib.sha256((LIVE / '.env').read_bytes()).hexdigest(),
          'isolated_port_closed': isolated_port_closed,
          'gpu_memory': subprocess.check_output(['nvidia-smi', '--query-gpu=index,memory.used,utilization.gpu',
                       '--format=csv,noheader'], text=True)}
report['kernel_evidence'] = [line for line in log.splitlines() if 'MarlinLinearKernel' in line or 'Selected Marlin' in line]
assert report['env_sha256'] == expected['deployed_env_sha256']
if expected['quantization'] == 'int4_autoround':
    assert report['quantization_config']['bits'] == 4
    assert 'quantization=inc' in log
    assert report['kernel_evidence']
else:
    assert expected['quantization'] in ['w8a16_middle', 'w8a16_middle8']
    assert processes[0]['force_fp8_marlin'] == '1'
    args = processes[0]['arguments']
    assert args[args.index('--quantization') + 1] == 'fp8_per_block'
    assert any('MarlinFP8ScaledMMLinearKernel' in line for line in report['kernel_evidence'])
    report['online_quantization_config'] = json.loads(args[args.index('--quantization-config') + 1])
(ROOT / 'live-state.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print('正式服务健康，量化配置、GPU、ready 与隔离进程清理核验通过', flush=True)
