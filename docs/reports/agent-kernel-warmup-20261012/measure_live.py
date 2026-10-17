"""正式网关完整推荐的单请求及突发测试；只保存脱敏指标，独立测试 Session。"""
import argparse
import concurrent.futures
import datetime
import importlib.util
import json
import statistics
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, '/tmp/rs-agent-before-after-20261011')
import compare_live as live
sys.path.insert(0, '/tmp/rs-agent-live-complex-concurrency-20261011')
from model_cache_metrics import read_cache_metrics, single_observed_cache


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('before', 'after'))
    args = parser.parse_args()
    path = ROOT / ('live-' + args.phase + '.json')
    assert not path.exists()
    spec = importlib.util.spec_from_file_location('business_probe', '/tmp/rs-agent-quantization-retry-20261011/business_probe.py')
    probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
    users = probe.accounts()
    live.BASE = 'http://127.0.0.1:18288'
    # 网关只开放用户接口；平台验收读当前 Agent 的只读管理端点。
    original_json = live.request_json
    def request_json(url, *args, **kwargs):
        if '/api/platform/agent/' in url:
            url = url.replace('http://127.0.0.1:18288', 'http://127.0.0.1:18214')
        return original_json(url, *args, **kwargs)
    live.request_json = request_json
    report = {'phase': args.phase, 'started_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'model_before': live.identity(), 'dependencies_before': live.dependency_snapshot(),
        'scope': '正式网关，8 条单请求及 4/8 路各两批独立 Session；TTFT 为模型引擎首次生成，不是正文首字；不计登录和建会话',
        'serial': [], 'bursts': []}
    def save():
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    def session(index):
        return probe.http('/api/sessions', {'entryScene': 'kernel-warmup-validation'}, users[index % 8]['accessToken'])['sessionId']
    save()
    for index in range(8):
        assert read_cache_metrics()['vllm:num_requests_running'] == 0
        sid = session(0)
        before = read_cache_metrics()
        row = live.sample(users[0], '推荐鼠标', sid)
        after = read_cache_metrics()
        row.update(index=index, model_window=live.metric_window(before, after))
        row.update(single_observed_cache(before, after))
        report['serial'].append(row); save()
        print(json.dumps({k: row.get(k) for k in ('index', 'passed', 'complete_ms', 'first_text_block_ms',
            'model_ttft_cache_window_ms', 'model_prefill_observed_ms', 'model_cached_tokens')}, ensure_ascii=False), flush=True)
        assert not row.get('error_type') and not row.get('error_code'), '真实请求发生错误，中止压测'
        assert live.identity() == report['model_before']
    for size in (4, 8):
        for repeat in range(2):
            sids = [session(index) for index in range(size)]
            barrier = threading.Barrier(size)
            def worker(index):
                barrier.wait(timeout=15)
                return live.sample(users[index % 8], '推荐鼠标', sids[index])
            before = read_cache_metrics()
            with concurrent.futures.ThreadPoolExecutor(max_workers=size) as pool:
                rows = list(pool.map(worker, range(size)))
            after = read_cache_metrics()
            window = live.metric_window(before, after)
            delta = window['delta']; count = window['observed_model_calls']
            # 并发前缀统计可能重复查询；时间直方图单独核验，不据此否定时间计数。
            timing_valid = count == size and all(delta.get(name + '_count') == size for name in
                ('vllm:request_prompt_tokens', 'vllm:request_queue_time_seconds', 'vllm:request_prefill_time_seconds'))
            entry = {'concurrency': size, 'repeat': repeat, 'rows': rows, 'model_window': window,
                'timing_count_valid': timing_valid, 'summary': live.distribution(rows)}
            if timing_valid:
                entry['mean_model_ttft_ms'] = round(1000 * delta['vllm:time_to_first_token_seconds_sum'] / count, 3)
            report['bursts'].append(entry); save()
            print(json.dumps({k: entry[k] for k in ('concurrency', 'repeat', 'summary', 'timing_count_valid')} |
                {'mean_model_ttft_ms': entry.get('mean_model_ttft_ms')}, ensure_ascii=False), flush=True)
            assert live.identity() == report['model_before']
            assert not any(row.get('error_type') or row.get('error_code') for row in rows)
    valid = [row['model_ttft_cache_window_ms'] for row in report['serial'] if row.get('model_cache_single_window_valid')]
    report['serial_summary'] = live.distribution(report['serial']) | {
        'valid_ttft_samples': len(valid), 'mean_model_ttft_ms': statistics.mean(valid) if valid else None,
        'median_model_ttft_ms': statistics.median(valid) if valid else None,
        'min_model_ttft_ms': min(valid) if valid else None, 'max_model_ttft_ms': max(valid) if valid else None}
    report.update(model_after=live.identity(), dependencies_after=live.dependency_snapshot())
    report['model_unchanged'] = report['model_before'] == report['model_after']
    report['dependencies_unchanged'] = report['dependencies_before'] == report['dependencies_after']
    report['completed'] = True; save()
    print(json.dumps(report['serial_summary'], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
