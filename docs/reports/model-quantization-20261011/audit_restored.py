"""核验最终 BF16 恢复状态，只导出允许公开的运行证据。"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import socket
import urllib.request

root = Path(__file__).resolve().parent
live = Path('/home/luo/RS_agent_java/model_deploy')
state = json.loads((root / 'deployment-state.json').read_text())
assert state['rollback'] and not state['promoted']
expected = json.loads((root / 'baseline-deployment.json').read_text())['sha256']
actual = {name: hashlib.sha256((live / name).read_bytes()).hexdigest() for name in expected}
assert actual == expected
spec = importlib.util.spec_from_file_location('runtime', '/tmp/rs-serving-tuning-20261011/deploy.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
runtime.canonical_process()
assert runtime.health()
with urllib.request.urlopen('http://127.0.0.1:18082/v1/models', timeout=5) as response:
    models = json.load(response)
assert models['data'][0]['root'] == '/mnt/data/luo/models/Qwen3.5-4B'
ready = Path('/tmp/rs_agent_latency/vllm_qwen35_4b.ready')
probe = json.loads(Path(str(ready) + '.structured-output.json').read_text())
assert ready.exists() and probe['status'] == 'PASS'
config = json.loads(Path('/mnt/data/luo/models/Qwen3.5-4B/config.json').read_text())
assert not config.get('quantization_config')
with socket.socket() as connection:
    isolated_port_closed = connection.connect_ex(('127.0.0.1', 18092)) != 0
assert isolated_port_closed
log = (live / 'quantization-20261011-rollback.log').read_text(errors='replace')
assert 'quantization=None' in log
loading = re.findall(r'Model loading took ([0-9.]+) GiB memory', log)
assert loading
report = {'health': 200, 'precision': 'BF16', 'quantization_retained': False,
          'model_root': models['data'][0]['root'], 'gpu': 1,
          'runtime_sha256': actual, 'original_runtime_restored': True,
          'ready_probe': probe, 'isolated_model_port_closed': isolated_port_closed,
          'model_loading_gib': float(loading[-1])}
(root / 'live-state.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print('正式 BF16 健康；原运行文件摘要一致，启动结构化探针通过，隔离模型端口关闭')
