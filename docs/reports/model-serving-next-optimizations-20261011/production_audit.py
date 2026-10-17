"""正式部署结束的只读白名单审计；不输出环境凭据或真实请求内容。"""
import importlib.util
import argparse
import json
from pathlib import Path
import re
import stat
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parent
LIVE = Path('/home/luo/RS_agent_java/model_deploy')
spec = importlib.util.spec_from_file_location('runtime', LIVE / 'partial_quantization_runtime_20261011.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def main(startup=False, idle=False, matched=False, original=False):
    assert not matched or idle
    state_name = 'model-serving-idle-guard-state-20261011.json' if idle else ('model-serving-warmup16-state-20261011.json' if startup else 'model-serving-next-state-20261011.json')
    if matched:
        state_name = 'model-serving-idle-guard-matched-state-20261011.json'
    state = json.loads((LIVE / state_name).read_text())
    if original:
        prior = json.loads((LIVE / 'partial-quantization-memory50-state.json').read_text())
        state = {**prior, 'model_path': prior['updates']['MODEL_PATH'],
            'deployed_file_sha256': {name: digest for name, digest in prior['baseline_sha256'].items() if name != '.env'},
            'log_file': 'model-serving-next-rollback50-20261011.log'}
    assert state['promoted'] and not state['rollback']
    api, launcher = runtime.identity(state['model_path'], .50, 128)
    assert (api, launcher) == (state['api_pid'], state['launcher_pid'])
    values = dict(entry.split('=', 1) for entry in Path(f'/proc/{api}/environ').read_bytes().decode().split('\0') if '=' in entry)
    allow = ['CUDA_VISIBLE_DEVICES', 'MODEL_PATH', 'VLLM_MAX_MODEL_LEN', 'VLLM_GPU_MEMORY_UTILIZATION',
        'VLLM_MAX_NUM_SEQS', 'VLLM_MAX_NUM_BATCHED_TOKENS', 'VLLM_SPECULATIVE_CONFIG',
        'VLLM_JSON_COMPACT_OUTPUT', 'VLLM_ENFORCE_STRICT_TOOL_CALLING', 'VLLM_LANGUAGE_MODEL_ONLY',
        'VLLM_CACHE_ROOT', 'VLLM_PREFIX_KEEPALIVE', 'VLLM_WARMUP_ONLY_WHEN_IDLE',
        'VLLM_EXTRA_WARMUP_CONCURRENCY', 'VLLM_WARMUP_PAYLOAD_FILE', 'VLLM_SERVER_DEV_MODE']
    public_env = {key: values.get(key, '') for key in allow}
    assert values.get('VLLM_EXTRA_WARMUP_CONCURRENCY', '0') == ('0' if idle or original else '16') and values['VLLM_PREFIX_KEEPALIVE'] == 'true'
    assert values.get('VLLM_WARMUP_ONLY_WHEN_IDLE', 'true') == 'true'
    assert values.get('VLLM_SERVER_DEV_MODE', '0') != '1'
    assert not values.get('VLLM_SPECULATIVE_CONFIG') and not values.get('VLLM_MAX_NUM_BATCHED_TOKENS')
    assert values.get('VLLM_LANGUAGE_MODEL_ONLY', 'false') == 'false'
    assert '--language-model-only' not in Path(f'/proc/{api}/cmdline').read_bytes().decode().split('\0')
    assert values['VLLM_JSON_COMPACT_OUTPUT'] == 'true' and values['VLLM_ENFORCE_STRICT_TOOL_CALLING'] == 'true'
    with urllib.request.urlopen('http://127.0.0.1:18082/v1/models', timeout=5) as response:
        models = json.load(response)['data']
    assert len(models) == 1 and models[0]['id'] == 'qwen35-4b'
    assert models[0]['root'] == state['model_path'] and models[0]['max_model_len'] == 16384
    source = json.loads(Path('/tmp/rs-agent-partial-quantization-20261011/mlp_only-source.json').read_text())
    assert source['path'] == state['model_path']
    config = json.loads((Path(source['path']) / 'config.json').read_text())
    assert config['quantization_config']['bits'] == 4
    assert config['quantization_config']['block_name_to_quantize'] == [f'model.language_model.layers.{i}.mlp' for i in range(32)]
    for name, digest in source['asset_sha256'].items():
        assert runtime.digest(Path(source['path']) / name) == digest
    for name, digest in state['deployed_file_sha256'].items():
        assert runtime.digest(LIVE / name) == digest
    assert runtime.digest(LIVE / '.env') == state['deployed_env_sha256']
    warmfile = Path(values['VLLM_WARMUP_PAYLOAD_FILE'])
    assert warmfile.resolve().parent == LIVE and stat.S_IMODE(warmfile.stat().st_mode) == 0o600
    records = len(json.loads(warmfile.read_text()))
    assert records == (2 if startup or idle or original else 8)
    log = (LIVE / state.get('log_file', 'model-serving-next-20261011.log')).read_text()
    cache_gib = float(re.findall(r'Available KV cache memory: ([\d.]+) GiB', log)[-1])
    cache_tokens = int(re.findall(r'GPU KV cache size: ([\d,]+) tokens', log)[-1].replace(',', ''))
    weights = float(re.findall(r'Model loading took ([\d.]+) GiB', log)[-1])
    assert cache_gib >= 3.8 and cache_tokens >= 106496 and weights < 5.6
    assert 'quantization=inc' in log and 'MarlinLinearKernel' in log and 'dtype=torch.bfloat16' in log
    keepalive = []
    for directory in Path('/proc').iterdir():
        if not directory.name.isdecimal():
            continue
        try:
            args = (directory / 'cmdline').read_bytes().decode().split('\0')
            if str(LIVE / 'vllm_prefix_warmup.py') in args and '--keepalive' in args:
                assert int((directory / 'stat').read_text().split()[3]) == launcher
                keepalive.append(int(directory.name))
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    assert len(keepalive) == 1 and runtime.health()
    assert all(runtime.closed(port) for port in [18092, 18314])
    assert not (ROOT / 'accounts.json').exists()
    assert not Path('/tmp/rs-agent-quantization-retry-20261011/agent-clone.private.env').exists()
    assert subprocess.run(['docker', 'inspect', 'rs-quantization-20261011-agent'], capture_output=True).returncode != 0
    shared = json.loads(subprocess.check_output(['docker', 'inspect', 'rs-e2e-857e8b14-agent-fast'], text=True))[0]
    assert shared['State']['Running']
    shared_env = dict(entry.split('=', 1) for entry in shared['Config']['Env'] if '=' in entry)
    assert shared_env['RS_AGENT_OPENAI_BASE_URL'].rstrip('/') == 'http://127.0.0.1:18082/v1'
    gpu = runtime.gpu()
    assert 3417056 in {row['pid'] for row in gpu['processes']}
    assert b'/tmp/rs-agent-e2e-20261010-llm-opt-20261011/bge_m3_embedding_server.py' in Path('/proc/3417056/cmdline').read_bytes().split(bytes([0]))
    removed_unused = False
    if idle or original:
        failed = json.loads((ROOT / 'production-deployment-state.json').read_text())
        assert failed['rollback'] and not failed['promoted']
        unused = Path(failed['updates']['VLLM_WARMUP_PAYLOAD_FILE'])
        assert unused.resolve().parent == LIVE and unused.name == 'warmup-prefixes-expanded-20261011.private.json'
        assert unused != warmfile
        if unused.exists():
            assert stat.S_IMODE(unused.stat().st_mode) == 0o600
            assert runtime.digest(unused) == runtime.digest(ROOT / 'expanded-prefixes.private.json')
            unused.unlink()
        removed_unused = True
    report = {'api_pid': api, 'launcher_pid': launcher, 'health': 200,
        'runtime_env_sha256': runtime.digest(LIVE / '.env'), 'settings': public_env,
        'kv_cache_gib': cache_gib, 'kv_cache_tokens': cache_tokens, 'model_loading_gib': weights,
        'gpu': gpu, 'keepalive_pid': keepalive[0], 'warmup_records': records, 'warmup_private_mode': '0600',
        'shared_agent_running': True, 'bge_pid_unchanged': 3417056, 'own_validation_cleaned': True,
        'source_sha256': state['deployed_file_sha256'], 'unused_failed_private_payload_removed': removed_unused,
        'original_configuration_restored': original, 'optimization_changes_promoted': not original,
        'promoted': not original}
    output = 'production-matched-live-state.json' if matched else ('production-final-live-state.json' if startup or idle else 'production-live-state.json')
    if original:
        output = 'production-original-live-state.json'
    (ROOT / output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    subprocess.run(['/mnt/data/luo/venvs/rsagent-vllm/bin/python', state['restore_script']], check=True)
    print('正式服务容量、配置、保温、BGE、业务服务及验证资源清理审计通过', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--startup16', action='store_true')
    group.add_argument('--idle-guard', action='store_true')
    group.add_argument('--original', action='store_true')
    parser.add_argument('--matched', action='store_true')
    args = parser.parse_args()
    main(args.startup16, args.idle_guard, args.matched, args.original)
