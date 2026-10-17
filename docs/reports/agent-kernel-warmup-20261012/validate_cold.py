"""GPU2 隔离实例，以空 Triton 缓存验证新版预热；不重启正式模型。"""
import datetime
import importlib.util
import json
import re
import shutil
import statistics
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, '/tmp/rs-agent-before-after-20261011')
import compare_live as live
sys.path.insert(0, '/tmp/rs-agent-live-complex-concurrency-20261011')
from model_cache_metrics import read_cache_metrics


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def main():
    model = load('cold_control', '/tmp/rs-agent-prefill-diagnosis-20261012/model_control.py')
    model.ROOT = ROOT / 'cold-validation'
    model.ROOT.mkdir(exist_ok=False)
    model.STATE = model.ROOT / 'temporary-model-state.json'
    warmup = load('updated_warmup', ROOT / 'vllm_prefix_warmup.py')
    path = ROOT / 'cold-validation.json'
    assert not path.exists()
    base = 'http://127.0.0.1:18096'
    report = {'started_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'model_before': live.identity(), 'dependencies_before': live.dependency_snapshot(),
        'scope': 'GPU2 相同 INT4 权重/.50 显存/16K，32 sequences，空 Triton 缓存；合成输入，不代表业务延迟',
        'warmup': [], 'formal': [], 'completed': False}
    def save():
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    save()
    def observed_post(url, payload, timeout, destination, label):
        before = read_cache_metrics(base)
        assert before['vllm:num_requests_running'] == before['vllm:num_requests_waiting'] == 0
        logfile = model.ROOT / 'temporary-quant.log'
        offset = logfile.stat().st_size
        begin = time.perf_counter()
        result = warmup.post_json(url, payload, timeout)
        after = read_cache_metrics(base)
        delta = {key: after[key] - value for key, value in before.items() if key in after}
        with logfile.open('rb') as stream:
            stream.seek(offset)
            lines = stream.read().decode(errors='replace').splitlines()
        events = [line for line in lines if 'JIT compilation during inference' in line]
        count = delta['vllm:time_to_first_token_seconds_count']
        row = {'label': label, 'model_calls': count, 'input_tokens': delta['vllm:request_prompt_tokens_sum'],
            'cache_queries': delta['vllm:prefix_cache_queries_total'], 'cached_tokens': delta['vllm:prefix_cache_hits_total'],
            'mean_ttft_ms': round(1000 * delta['vllm:time_to_first_token_seconds_sum'] / count, 3),
            'mean_prefill_ms': round(1000 * delta['vllm:request_prefill_time_seconds_sum'] / count, 3),
            'mean_queue_ms': round(1000 * delta['vllm:request_queue_time_seconds_sum'] / count, 3),
            'client_complete_ms': round((time.perf_counter() - begin) * 1000, 3),
            'completion_tokens': result['usage']['completion_tokens'], 'jit_events': events}
        destination.append(row); save()
        print(json.dumps(row, ensure_ascii=False), flush=True)
        assert live.identity() == report['model_before']
        return result
    try:
        source_cache = Path('/tmp/rs-agent-resume-benchmark-20261011/model-cache-quant')
        assert source_cache.is_dir() and sum(p.stat().st_size for p in source_cache.rglob('*') if p.is_file()) < 512 * 1024 * 1024
        shutil.copytree(source_cache, model.ROOT / 'model-cache-quant')
        model.start('quant')
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            assert model.owned(json.loads(model.STATE.read_text()))
            try:
                with urllib.request.urlopen(base + '/health', timeout=3) as response:
                    if response.status == 200:
                        break
            except OSError:
                pass
            print('等待隔离模型就绪', flush=True); time.sleep(10)
        else:
            raise TimeoutError('隔离模型未就绪')
        planned = iter(warmup.build_kernel_warmup_batches('qwen35-4b', [1, 4, 8, 16]))
        def warm_post(url, payload, timeout):
            item = next(planned)
            assert payload == item['payload']
            return observed_post(url, payload, timeout, report['warmup'], item['label'])
        warmup.run_kernel_warmup(base + '/v1', 'qwen35-4b', [1, 4, 8, 16], 180, post_json=warm_post,
            idle_check=lambda: warmup.server_is_idle(base + '/v1', 3))
        for cycle in range(3):
            full = [1010 + cycle] + [1000] * 6607
            partial = full[:5000] + [1001] * 1610
            for label, prompt in (('uncached', full), ('first-prefix-hit', partial)):
                payload = {'model': 'qwen35-4b', 'prompt': prompt, 'max_tokens': 1,
                           'ignore_eos': True, 'temperature': 0, 'seed': 0}
                observed_post(base + '/v1/completions', payload, 180, report['formal'], f'{cycle}-{label}')
        for size in (4, 8, 16):
            payload = {'model': 'qwen35-4b', 'prompt': [[1200 + i] + [1000] * 255 for i in range(size)],
                       'max_tokens': 2, 'ignore_eos': True, 'temperature': 0, 'seed': 0}
            observed_post(base + '/v1/completions', payload, 180, report['formal'], f'batch-decode-{size}')
        partials = [row for row in report['formal'] if row['label'].endswith('first-prefix-hit')]
        report['same_partial_workload'] = {(row['input_tokens'], row['cached_tokens']) for row in partials} == {(6610, 4752)}
        report['formal_jit_events'] = [event for row in report['formal'] for event in row['jit_events']]
        report['first_partial_ttft_ms'] = partials[0]['mean_ttft_ms']
        report['partial_mean_ttft_ms'] = statistics.mean(row['mean_ttft_ms'] for row in partials)
        report['passed'] = (report['same_partial_workload'] and not report['formal_jit_events']
                            and all(row['mean_prefill_ms'] < 300 for row in partials))
        report['completed'] = True
    except Exception as error:
        report.update(error_type=type(error).__name__, passed=False)
        print(json.dumps({'error_type': type(error).__name__}), flush=True)
    finally:
        model.stop()
        report.update(model_after=live.identity(), dependencies_after=live.dependency_snapshot(), gpu_after=model.gpu_snapshot())
        report['model_unchanged'] = report['model_before'] == report['model_after']
        report['dependencies_unchanged'] = report['dependencies_before'] == report['dependencies_after']
        report['temporary_stopped'] = not model.STATE.exists() or (
            json.loads(model.STATE.read_text())['stopped'] and not model.owned(json.loads(model.STATE.read_text())))
        save()
    print(json.dumps({k: report.get(k) for k in ('passed', 'first_partial_ttft_ms', 'partial_mean_ttft_ms',
        'formal_jit_events', 'model_unchanged', 'dependencies_unchanged', 'temporary_stopped')}, ensure_ascii=False), flush=True)
    assert report.get('passed') and report['model_unchanged'] and report['dependencies_unchanged'] and report['temporary_stopped']


if __name__ == '__main__':
    main()
