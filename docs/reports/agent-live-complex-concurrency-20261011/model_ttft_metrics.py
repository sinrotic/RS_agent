"""读取模型引擎首次 token 计时累计值，不记录请求正文或私有身份。"""
import json
import re
import urllib.request
from collections import defaultdict


def read_ttft_metrics():
    with urllib.request.urlopen('http://127.0.0.1:18082/metrics', timeout=5) as response:
        raw = response.read().decode()
    values = defaultdict(float)
    for line in raw.splitlines():
        match = re.match(r'^([A-Za-z_:][A-Za-z_0-9:]*time_to_first_token_seconds_(?:sum|count))'
                         r'(?:\{[^}]*\})?\s+([0-9.eE+-]+)$', line)
        if match:
            values[match.group(1)] += float(match.group(2))
    return dict(values)


def single_observed_ttft(before, after):
    sum_keys = [key for key in before if key.endswith('_sum')]
    for sum_key in sum_keys:
        count_key = sum_key[:-4] + '_count'
        if count_key not in before or sum_key not in after or count_key not in after:
            continue
        count = after[count_key] - before[count_key]
        elapsed = after[sum_key] - before[sum_key]
        if count == 1 and elapsed >= 0:
            return {'model_ttft_observed_ms': round(elapsed * 1000, 3), 'model_ttft_observed_count': 1,
                    'model_ttft_metric': sum_key[:-4],
                    'model_ttft_attribution': '共享窗口仅新增一条模型首次 token 计时；与本次普通推荐一致，未按 request_id 关联'}
        return {'model_ttft_observed_ms': None, 'model_ttft_observed_count': count,
                'model_ttft_attribution': '计数不是 1，不能当作本条请求 TTFT'}
    return {'model_ttft_observed_ms': None, 'model_ttft_attribution': '模型未提供所需 TTFT 指标'}


if __name__ == '__main__':
    print(json.dumps(read_ttft_metrics(), indent=2))
