"""临时 GPU2 模型：重复相同长度、相同缓存命中路径，关联即时编译与延迟。"""
import datetime
import json
import os
import shutil
import statistics
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
import model_control as model
sys.path.insert(0, '/tmp/rs-agent-before-after-20261011')
import compare_live as live
sys.path.insert(0, '/tmp/rs-agent-live-complex-concurrency-20261011')
from model_cache_metrics import read_cache_metrics

model.ROOT = ROOT
model.STATE = ROOT / 'temporary-model-state.json'
BASE = 'http://127.0.0.1:18096'
REPORT = ROOT / 'reproduction.json'


def http(path, payload=None):
    request = urllib.request.Request(BASE + path, data=None if payload is None else json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=180) as response:
        body = response.read()
        return json.loads(body) if body else {}


def request(prompt, label, cycle):
    before = read_cache_metrics(BASE)
    assert before['vllm:num_requests_running'] == before['vllm:num_requests_waiting'] == 0
    logfile = ROOT / 'temporary-quant.log'
    offset = logfile.stat().st_size
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    begin = time.perf_counter()
    data = http('/v1/completions', {'model': 'qwen35-4b', 'prompt': prompt, 'max_tokens': 1,
                                  'min_tokens': 1, 'ignore_eos': True, 'temperature': 0, 'seed': 0})
    elapsed = (time.perf_counter() - begin) * 1000
    # 完整非流式响应后再读统计，只有一个生成 token，不保存任何输出正文。
    after = read_cache_metrics(BASE)
    delta = {key: after[key] - value for key, value in before.items() if key in after}
    for name in ('vllm:time_to_first_token_seconds', 'vllm:request_prefill_time_seconds',
                 'vllm:request_queue_time_seconds', 'vllm:request_prompt_tokens'):
        assert delta[name + '_count'] == 1
    with logfile.open('rb') as stream:
        stream.seek(offset)
        loglines = stream.read().decode(errors='replace').splitlines()
    row = {'cycle': cycle, 'label': label, 'started_at_utc': started,
           'finished_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
           'input_tokens': delta['vllm:request_prompt_tokens_sum'],
           'cache_queries': delta['vllm:prefix_cache_queries_total'], 'cached_tokens': delta['vllm:prefix_cache_hits_total'],
           'ttft_ms': round(1000 * delta['vllm:time_to_first_token_seconds_sum'], 3),
           'prefill_ms': round(1000 * delta['vllm:request_prefill_time_seconds_sum'], 3),
           'queue_ms': round(1000 * delta['vllm:request_queue_time_seconds_sum'], 3),
           'client_complete_ms': round(elapsed, 3), 'completion_tokens': data['usage']['completion_tokens'],
           'jit_events': [line for line in loglines if 'JIT compilation during inference' in line],
           'gpu_snapshot': model.gpu_snapshot()}
    assert row['cache_queries'] == row['input_tokens'] and row['completion_tokens'] == 1
    return row


def main():
    if REPORT.exists():
        previous = json.loads(REPORT.read_text())
        assert previous.get('completed') is False and not previous['cases']
        archive = ROOT / 'reproduction-first-attempt.json'
        if archive.exists():
            archive = ROOT / 'reproduction-reset-endpoint-unavailable.json'
        assert not archive.exists()
        REPORT.rename(archive)
    report = {'started_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'cases': [],
              'shared_model_before': live.identity(), 'dependencies_before': live.dependency_snapshot(),
              'scope': '合成 token 输入；长输入无缓存、首次部分命中、再次部分命中；同长度同缓存命中数量三轮，首token标记区分前缀，非业务质量评测'}
    def save():
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    save()
    try:
        source_cache = Path('/tmp/rs-agent-resume-benchmark-20261011/model-cache-quant')
        target_cache = ROOT / 'model-cache-quant'
        assert source_cache.is_dir()
        assert sum(p.stat().st_size for p in source_cache.rglob('*') if p.is_file()) < 512 * 1024 * 1024
        if not target_cache.exists():
            shutil.copytree(source_cache, target_cache)
        model.start('quant')
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            assert model.owned(json.loads(model.STATE.read_text()))
            try:
                if http('/health') == {}:
                    break
            except OSError:
                pass
            print(json.dumps({'waiting_for_temporary_model': True}), flush=True)
            time.sleep(10)
        else:
            raise TimeoutError('临时模型未就绪')
        for cycle in range(3):
            state = json.loads(model.STATE.read_text())
            assert model.owned(state) and live.identity() == report['shared_model_before']
            # 前缀第一个 token 每轮不同，避免依赖未开放的 reset 开发接口。
            first = [1000] * 6608
            first[0] = 1010 + cycle
            partial = first[:5000] + [1001] * 1610
            longer = partial[:5300] + [1002] * 1308
            for label, prompt in (('uncached', first), ('first-prefix-hit', partial), ('second-prefix-hit', longer)):
                row = request(prompt, label, cycle)
                report['cases'].append(row); save()
                print(json.dumps({key: value for key, value in row.items() if key != 'gpu_snapshot'}, ensure_ascii=False), flush=True)
        partial_rows = [row for row in report['cases'] if row['label'] == 'first-prefix-hit']
        report['same_workload_valid'] = len({(row['input_tokens'], row['cached_tokens']) for row in partial_rows}) == 1
        report['cold_prefix_prefill_ms'] = partial_rows[0]['prefill_ms']
        report['hot_same_prefix_prefill_mean_ms'] = statistics.mean(row['prefill_ms'] for row in partial_rows[1:])
        report['cold_prefix_jit_kernels'] = partial_rows[0]['jit_events']
        report['hot_prefix_jit_events'] = [event for row in partial_rows[1:] for event in row['jit_events']]
        report['completed'] = True
    except Exception as error:
        report.update(completed=False, error_type=type(error).__name__)
        print(json.dumps({'error_type': type(error).__name__}), flush=True)
    finally:
        model.stop()
        report.update(shared_model_after=live.identity(), dependencies_after=live.dependency_snapshot(),
                      gpu_after=model.gpu_snapshot(), finished_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        report['shared_model_unchanged'] = report['shared_model_before'] == report['shared_model_after']
        report['dependencies_unchanged'] = report['dependencies_before'] == report['dependencies_after']
        state = json.loads(model.STATE.read_text()) if model.STATE.exists() else None
        report['temporary_model_stopped'] = state is None or (state['stopped'] and not model.owned(state))
        save()


if __name__ == '__main__':
    main()
