"""按用户显存优先的新要求部署 INT4；模型侧失效回退，业务变慢单独记录。"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
import urllib.request

from promote import wait_clone_ready

root = Path(__file__).resolve().parent
live = Path('/home/luo/RS_agent_java/model_deploy')
spec = importlib.util.spec_from_file_location('runtime', '/tmp/rs-serving-tuning-20261011/deploy.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)

def gpu():
    output = subprocess.check_output(['nvidia-smi', '-i', '1', '--query-gpu=memory.total,memory.used,memory.free',
                                     '--format=csv,noheader,nounits'], text=True)
    values = [int(value.strip()) for value in output.strip().split(',')]
    return dict(zip(['total_mib', 'used_mib', 'free_mib'], values))

def process(model):
    found = []
    for directory in Path('/proc').iterdir():
        if not directory.name.isdecimal():
            continue
        try:
            args = (directory / 'cmdline').read_bytes().decode().split('\0')
            if 'serve' not in args or model not in args or '--port' not in args:
                continue
            if args[args.index('--port') + 1] != '18082':
                continue
            env = dict(item.split('=', 1) for item in (directory / 'environ').read_bytes().decode().split('\0') if '=' in item)
            assert env.get('CUDA_VISIBLE_DEVICES') == '1'
            assert args[args.index('--gpu-memory-utilization') + 1] == '0.50'
            assert args[args.index('--max-model-len') + 1] == '16384'
            found.append(int(directory.name))
        except (FileNotFoundError, ProcessLookupError):
            continue
    assert len(found) == 1
    return found[0]

def main():
    candidate = json.loads((root / 'int4_autoround_restart2_memory50-state.json').read_text())
    assert candidate['passed'] and candidate['scope'] == 'model_only'
    assert candidate['configuration']['VLLM_GPU_MEMORY_UTILIZATION'] == '0.50'
    source = json.loads((root / 'int4-runtime-source.json').read_text())
    assert source['effective_tokenizer_identical'] and not source['weights_changed']
    assert source['revision'] == '0a857215cab37e8caa857a053005a73cf98ff2c4'
    assert source['path'] == candidate['model_path']
    for name, asset in source['preserved_assets'].items():
        assert hashlib.sha256((Path(source['path']) / name).read_bytes()).hexdigest() == asset['sha256']
    expected = json.loads((root / 'baseline-deployment.json').read_text())['sha256']
    for name, digest in expected.items():
        assert hashlib.sha256((live / name).read_bytes()).hexdigest() == digest
    runtime.wait_external_validation()
    api, parent = runtime.canonical_process()
    runtime.wait_idle()
    cache_source = Path(candidate['configuration']['VLLM_CACHE_ROOT']).resolve()
    assert cache_source.is_relative_to((root / 'cache').resolve())
    cache_target = live / 'quantization-cache' / '20261011-int4-memory50'
    assert not cache_target.exists(), '不覆盖未知正式缓存目录'
    shutil.copytree(cache_source, cache_target)
    updates = {'MODEL_PATH': source['path'], 'VLLM_QUANTIZATION': 'auto',
               'VLLM_QUANTIZATION_CONFIG': '', 'VLLM_TEST_FORCE_FP8_MARLIN': '0',
               'VLLM_GPU_MEMORY_UTILIZATION': '0.50', 'VLLM_CACHE_ROOT': str(cache_target)}
    original = (live / '.env').read_bytes()
    backup = live / ('backup-quantization-memory-' + time.strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(mode=0o700)
    runtime.atomic_write(backup / '.env', original, 0o600)
    lines = original.decode().splitlines()
    for key in updates:
        assert sum(line.startswith(key + '=') for line in lines) <= 1
    contents = '\n'.join(line for line in lines if line.split('=', 1)[0] not in updates) + '\n'
    contents += '\n'.join(key + '=' + shlex.quote(value) for key, value in updates.items()) + '\n'
    restore_target = live / 'restore_qwen35_4b_memory50.py'
    assert not restore_target.exists(), '不覆盖未知恢复脚本'
    runtime.atomic_write(restore_target, (root / 'memory_restore.py').read_bytes(), 0o700)
    report = {'priority': 'free_gpu_memory', 'authorization': '用户明确要求部署量化，以腾出显存供其他任务使用',
              'candidate': 'int4_autoround_original_tokenizer_memory50', 'updates': updates,
              'known_limitations': ['先前同一 INT4 资产出现一次 rag_support 工具失败',
                                    'BF16 和量化都观察到更多规划轮次，不保证业务更快'],
              'backup': str(backup), 'baseline_sha256': expected, 'gpu_before': gpu(),
              'promoted': False, 'rollback': False, 'restore_script': str(restore_target)}
    state_file = root / 'memory-deployment-state.json'
    persistent_state = live / 'quantization-memory50-state.json'
    def save():
        contents = (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode()
        runtime.atomic_write(state_file, contents, 0o600)
        runtime.atomic_write(persistent_state, contents, 0o600)
    save()
    owned = None
    stopped = False
    try:
        runtime.wait_idle()
        print('隔离 INT4/50% 模型检查通过，开始正式切换', flush=True)
        runtime.stop_existing(api, parent)
        stopped = True
        runtime.atomic_write(live / '.env', contents.encode(), 0o600)
        owned = runtime.launch('quantization-memory50-20261011.log')
        runtime.wait_idle()
        report.update(launcher_pid=owned.pid, api_pid=process(source['path']),
                      deployed_env_sha256=hashlib.sha256((live / '.env').read_bytes()).hexdigest())
        save()
        subprocess.run([sys.executable, str(root / 'model_direct.py'), '--base-url', 'http://127.0.0.1:18082/v1',
                        '--output', str(root / 'memory-production-model.json')], check=True, timeout=360)
        report['model_regression_passed'] = True
        print('正式模型侧回归通过，检查实际业务', flush=True)
        accounts = root / 'accounts.json'
        assert not accounts.exists()
        source_accounts = Path('/tmp/rs-agent-e2e-20261010-llm-opt-20261011/accounts.json')
        runtime.atomic_write(accounts, source_accounts.read_bytes(), 0o600)
        subprocess.run([sys.executable, str(root / 'clone.py'), '--model-port', '18082'], check=True)
        wait_clone_ready()
        subprocess.run([sys.executable, str(root / 'memory_business.py')], check=True, timeout=360)
        business = json.loads((root / 'memory-business.json').read_text())['business_regression']
        report.update(business_passed=sum(bool(row['passed']) for row in business), business_total=len(business))
        runtime.wait_idle()
        report.update(promoted=True, health=runtime.health(), gpu_after=gpu())
        report['released_gpu_memory_mib'] = report['gpu_before']['used_mib'] - report['gpu_after']['used_mib']
        assert report['health'] and report['released_gpu_memory_mib'] >= 5000, '未释放预期显存或服务不健康'
        print('INT4 显存优先部署完成，GPU 1 释放 MiB=', report['released_gpu_memory_mib'], flush=True)
    except Exception as error:
        report.update(promoted=False, failure_type=type(error).__name__, failure=str(error))
        if stopped:
            runtime.stop_owned(owned)
            runtime.atomic_write(live / '.env', original, 0o600)
            restored = runtime.launch('quantization-memory50-failed-rollback.log')
            report.update(rollback=True, health=runtime.health(), restored_launcher_pid=restored.pid)
        raise
    finally:
        save()

if __name__ == '__main__':
    main()
