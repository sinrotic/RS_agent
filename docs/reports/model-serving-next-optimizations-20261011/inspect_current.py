"""只读核验正式模型配置；不生成请求、不读取提示词或私有环境文件。"""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
REMOTE = r'''
import json
from pathlib import Path
import re
import subprocess
import urllib.request
from datetime import datetime, timezone
live = Path('/home/luo/RS_agent_java/model_deploy')
state = json.loads((live / 'partial-quantization-memory50-state.json').read_text())
assert state['promoted'] and not state['rollback']
pid = state['api_pid']
args = Path(f'/proc/{pid}/cmdline').read_bytes().decode().split('\0')
assert args[args.index('--port') + 1] == '18082'
model = state['updates']['MODEL_PATH']
assert model in args
env = dict(row.split('=', 1) for row in Path(f'/proc/{pid}/environ').read_bytes().decode().split('\0') if '=' in row)
assert env['CUDA_VISIBLE_DEVICES'] == '1'
keys = ['CUDA_VISIBLE_DEVICES', 'VLLM_MAX_NUM_BATCHED_TOKENS', 'VLLM_MAX_NUM_SEQS',
        'VLLM_GPU_MEMORY_UTILIZATION', 'VLLM_CACHE_ROOT', 'VLLM_SPECULATIVE_CONFIG',
        'VLLM_PREFIX_KEEPALIVE', 'VLLM_WARMUP_ONLY_WHEN_IDLE', 'VLLM_USE_FLASHINFER_SAMPLER']
log = (live / 'partial-quantization-memory50-20261011.log').read_text(errors='replace')
config_line = next(row for row in log.splitlines() if 'Initializing a V1 LLM engine' in row)
patterns = {'version': r'\(v([0-9.]+)\)', 'chunked_prefill': r'enable_chunked_prefill=(\w+)',
            'prefix_caching': r'enable_prefix_caching=(\w+)', 'kv_cache_dtype': r'kv_cache_dtype=(\w+)',
            'speculative_config': r'speculative_config=([^,]+)', 'enforce_eager': r'enforce_eager=(\w+)',
            'compilation_mode': r"'mode': <CompilationMode\.([A-Z_]+)",
            'cudagraph_mode': r"'cudagraph_mode': <CUDAGraphMode\.([A-Z_]+)",
            'compile_ranges_endpoints': r"'compile_ranges_endpoints': (\[[^\]]+\])",
            'max_cudagraph_capture_size': r"'max_cudagraph_capture_size': ([0-9]+)"}
resolved = {}
for key, pattern in patterns.items():
    match = re.search(pattern, config_line)
    assert match, key
    resolved[key] = match.group(1)
resolved['ordinary_attention_backend'] = re.search(r'Using ([A-Z_]+) attention backend out', log).group(1)
resolved['quantized_linear_kernel'] = re.search(r'Using (\w+) for AutoGPTQLinearMethod', log).group(1)
resolved['mamba_cache_mode'] = re.search(r"Mamba cache mode is set to '([^']+)'", log).group(1)
# The log may omit the resolved scheduler budget; a source default is not reported as live evidence.
batch_match = re.search(r'Chunked prefill is enabled with max_num_batched_tokens=([0-9]+)', log)
resolved['max_num_batched_tokens_from_log'] = int(batch_match.group(1)) if batch_match else None
resolved['async_scheduling_from_log'] = None
resolved['async_scheduling_note'] = 'Startup log does not expose this field; do not count its default as a newly enabled optimization.'
try:
    with urllib.request.urlopen('http://127.0.0.1:18082/server_info?config_format=json', timeout=5) as response:
        server_info = json.load(response)
    engine_config = server_info.get('vllm_config', {})
    if isinstance(engine_config, str):
        engine_config = json.loads(engine_config)
    scheduler = engine_config.get('scheduler_config', {})
    resolved['scheduler_config_from_server_info'] = {key: scheduler.get(key) for key in
        ['max_num_batched_tokens', 'max_num_seqs', 'enable_chunked_prefill', 'async_scheduling',
         'max_num_partial_prefills', 'max_long_partial_prefills', 'long_prefill_token_threshold']}
except Exception as error:
    resolved['server_info_unavailable'] = type(error).__name__
config = json.loads((Path(model) / 'config.json').read_text())
index = json.loads((Path(model) / 'model.safetensors.index.json').read_text())
mtp_keys = [key for key in index['weight_map'] if 'mtp' in key.lower()]
with urllib.request.urlopen('http://127.0.0.1:18082/health', timeout=5) as response:
    health = response.status
with urllib.request.urlopen('http://127.0.0.1:18082/metrics', timeout=5) as response:
    metrics = response.read().decode()
allowed_metrics = ['vllm:num_requests_running', 'vllm:num_requests_waiting', 'vllm:num_preemptions_total',
                   'vllm:prefix_cache_queries_total', 'vllm:prefix_cache_hits_total',
                   'vllm:kv_cache_usage_perc', 'vllm:request_queue_time_seconds_count',
                   'vllm:request_queue_time_seconds_sum']
metric_values = {}
for row in metrics.splitlines():
    if row.startswith('#'):
        continue
    family = re.split(r'[ {]', row, maxsplit=1)[0]
    if family in allowed_metrics:
        metric_values[family] = metric_values.get(family, 0) + float(row.split()[-1])
gpu = subprocess.check_output(['nvidia-smi', '-i', '1', '--query-gpu=memory.used,memory.free,utilization.gpu',
                               '--format=csv,noheader,nounits'], text=True).strip()
result = {'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'read_only': True, 'health': health,
          'api_pid': pid, 'model_path': model, 'gpu': 1, 'precision': state['precision'],
          'max_model_len': int(args[args.index('--max-model-len') + 1]),
          'max_num_seqs': int(args[args.index('--max-num-seqs') + 1]),
          'gpu_memory_utilization': float(args[args.index('--gpu-memory-utilization') + 1]),
          'selected_env': {key: env.get(key) for key in keys}, 'resolved_startup': resolved,
          'mtp_num_hidden_layers': config.get('text_config', {}).get('mtp_num_hidden_layers'),
          'mtp_tensor_count': len(mtp_keys), 'mtp_tensor_first_keys': mtp_keys[:3],
          'metrics_snapshot': metric_values, 'metrics_scope': 'Instance lifetime includes benchmarks and keepalive; not a production-only sample.',
          'gpu_used_free_utilization': gpu}
print(json.dumps(result, ensure_ascii=False, indent=2))
'''
result = subprocess.run(['ssh', 'server', 'python3 -c ' + "'exec(bytes(" + str(list(REMOTE.encode('utf-8'))) + "))'"],
                        check=True, capture_output=True, text=True, encoding='utf-8', timeout=45)
evidence = json.loads(result.stdout)
assert evidence['health'] == 200 and evidence['read_only']
(ROOT / 'current-runtime.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(evidence, ensure_ascii=False, indent=2))
