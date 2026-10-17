"""独立 GPU2 模型直连定长对照；长度测试不当作完整业务成功。"""
import argparse
import datetime
import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, '/tmp/rs-agent-live-complex-concurrency-20261011')
from model_cache_metrics import read_cache_metrics

BASE = 'http://127.0.0.1:18096'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('name')
    args = parser.parse_args()
    assert args.name.replace('-', '').isalnum()
    destination = ROOT / (args.name + '.json')
    assert not destination.exists()
    state = json.loads((ROOT / 'temporary-model-state.json').read_text())
    report = {'checked_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'model': state['model'], 'model_path': state['model_path'], 'gpu': state['gpu'],
        'command': state['command'], 'cases': [],
        'scope': '同一GPU2顺序单请求；相同短提示词/seed/温度/强制128输出tokens，排除前三次预热；不代表完整推荐质量或高并发'}
    for index in range(13):
        before = read_cache_metrics(BASE)
        payload = {'model': 'qwen35-4b', 'messages': [
            {'role': 'system', 'content': '你是一个中文助手，请直接回答。'},
            {'role': 'user', 'content': '请连续列举选购办公鼠标时应检查的客观项目，逐条简短说明。'}],
            'temperature': 0, 'seed': 0, 'max_tokens': 128, 'min_tokens': 128, 'ignore_eos': True,
            'stream': True, 'stream_options': {'include_usage': True}}
        request = urllib.request.Request(BASE + '/v1/chat/completions',
            data=json.dumps(payload, ensure_ascii=False).encode(), headers={'Content-Type': 'application/json'})
        start = time.perf_counter(); first = None; usage = {}; finish = None
        with urllib.request.urlopen(request, timeout=90) as response:
            for raw in response:
                line = raw.decode().strip()
                if not line.startswith('data:') or line == 'data: [DONE]':
                    continue
                data = json.loads(line[5:].strip())
                if data.get('usage'):
                    usage = data['usage']
                for choice in data.get('choices', []):
                    delta = choice.get('delta') or {}
                    if first is None and any(delta.get(key) for key in ('content', 'reasoning_content', 'tool_calls')):
                        first = (time.perf_counter() - start) * 1000
                    if choice.get('finish_reason'):
                        finish = choice['finish_reason']
        total = (time.perf_counter() - start) * 1000
        after = read_cache_metrics(BASE)
        count = after['vllm:time_to_first_token_seconds_count'] - before['vllm:time_to_first_token_seconds_count']
        row = {'index': index, 'warmup': index < 3, 'complete_ms': round(total, 3),
            'http_first_nonempty_delta_ms': round(first, 3) if first is not None else None,
            'model_ttft_ms': round(1000 * (after['vllm:time_to_first_token_seconds_sum'] - before['vllm:time_to_first_token_seconds_sum']), 3) if count == 1 else None,
            'prompt_tokens': usage.get('prompt_tokens'), 'completion_tokens': usage.get('completion_tokens'),
            'finish_reason': finish, 'observed_model_calls': count}
        row['length_probe_passed'] = row['completion_tokens'] == 128 and count == 1 and first is not None
        report['cases'].append(row)
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(row, ensure_ascii=False), flush=True)
        if not row['length_probe_passed']:
            break
    rows = [row for row in report['cases'] if not row['warmup'] and row['length_probe_passed']]
    report['samples'] = len(rows)
    report['mean_ms'] = round(statistics.mean(row['complete_ms'] for row in rows), 3) if rows else None
    report['median_ms'] = round(statistics.median(row['complete_ms'] for row in rows), 3) if rows else None
    report['mean_model_ttft_ms'] = round(statistics.mean(row['model_ttft_ms'] for row in rows), 3) if rows else None
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
