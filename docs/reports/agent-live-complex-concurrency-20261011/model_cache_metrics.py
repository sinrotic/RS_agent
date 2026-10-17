"""采集真实模型窗口的缓存和时间指标，不保存模型输入或响应正文。"""
import re
import urllib.request
from collections import defaultdict


METRICS = {
    'vllm:prefix_cache_queries_total', 'vllm:prefix_cache_hits_total',
    'vllm:num_requests_running', 'vllm:num_requests_waiting',
}
HISTOGRAMS = (
    'vllm:request_prompt_tokens', 'vllm:request_queue_time_seconds',
    'vllm:request_prefill_time_seconds', 'vllm:time_to_first_token_seconds',
)
METRICS.update(name + suffix for name in HISTOGRAMS for suffix in ('_count', '_sum'))


def read_cache_metrics(base_url='http://127.0.0.1:18082'):
    with urllib.request.urlopen(base_url + '/metrics', timeout=5) as response:
        raw = response.read().decode()
    values = defaultdict(float)
    for line in raw.splitlines():
        match = re.match(r'^([A-Za-z_:][A-Za-z_0-9:]*)(?:\{[^}]*\})?\s+([0-9.eE+-]+)$', line)
        if match and match.group(1) in METRICS:
            values[match.group(1)] += float(match.group(2))
    return dict(values)


def single_observed_cache(before, after):
    delta = {key: after[key] - value for key, value in before.items()
             if key in after and key not in ('vllm:num_requests_running', 'vllm:num_requests_waiting')}
    result = {'model_cache_metrics_before': before, 'model_cache_metrics_after': after,
              'model_cache_metric_deltas': delta,
              'model_cache_attribution': '共享指标窗口；未按 request_id 关联，不等于固定提示词独立命中率'}
    counts = [delta.get(name + '_count') for name in HISTOGRAMS]
    queries = delta.get('vllm:prefix_cache_queries_total')
    hits = delta.get('vllm:prefix_cache_hits_total')
    prompt = delta.get('vllm:request_prompt_tokens_sum')
    valid = all(count == 1 for count in counts) and all(value >= 0 for value in delta.values())
    valid = valid and queries is not None and hits is not None and queries > 0 and 0 <= hits <= queries
    valid = valid and prompt == queries
    result['model_cache_single_window_valid'] = valid
    if not valid:
        result['model_cache_attribution'] = '指标缺失、重置或窗口不止一条请求，拒绝推导单请求命中率'
        return result
    result.update(model_prompt_tokens=int(prompt), model_cached_tokens=int(hits),
                  model_uncached_tokens=int(queries - hits),
                  model_prefix_cache_hit_percent=round(100 * hits / queries, 2),
                  model_queue_observed_ms=round(delta['vllm:request_queue_time_seconds_sum'] * 1000, 3),
                  model_prefill_observed_ms=round(delta['vllm:request_prefill_time_seconds_sum'] * 1000, 3),
                  model_ttft_cache_window_ms=round(delta['vllm:time_to_first_token_seconds_sum'] * 1000, 3))
    return result
