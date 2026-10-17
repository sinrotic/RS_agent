"""仅导出计数与性能摘要，不导出请求正文、账号或生成内容。"""
import json
from pathlib import Path
import re
import statistics

ROOT = Path('/tmp/rs-agent-partial-quantization-20261011')

def collect():
    result = {}
    for label in ['control', 'mlp_only', 'gdn_bf16', 'winner_low_memory']:
        entry = {}
        path = ROOT / (label + '-business.json')
        if path.exists():
            rows = json.loads(path.read_text())['business_regression']
            entry['business'] = {'passed': sum(bool(row['passed']) for row in rows), 'samples': len(rows),
                'failed_tools': sum(row.get('failed_tools', 0) for row in rows),
                'median_ms': statistics.median(row['elapsed_ms'] for row in rows if row.get('elapsed_ms'))}
        path = ROOT / (label + '-planning.json')
        if path.exists():
            data = json.loads(path.read_text())
            entry['planning'] = {key: data[key] for key in ['samples', 'schema_errors', 'rag_missing_query', 'incomplete_generations']}
            entry['planning']['median_ms'] = statistics.median(row['elapsed_ms'] for row in data['results'])
            entry['planning']['completion_tokens'] = sum(row['completion_tokens'] for row in data['results'])
            entry['planning']['rag_support_or_delegate_calls'] = sum(
                name in ['rag_support', 'call_agent'] for row in data['results'] for name in row['tool_names'])
            entry['planning']['complete_with_missing_query'] = sum(
                row['complete'] and row['rag_missing_query'] > 0 for row in data['results'])
            private = json.loads((ROOT / (label + '-planning.private.json')).read_text())
            bad_cases = {(row['case'], row['repeat']): row for row in data['results'] if row['rag_missing_query']}
            shapes = []
            for row in private:
                key = (row['case'], row['repeat'])
                if key not in bad_cases:
                    continue
                for call in row['tool_calls']:
                    if call['function']['name'] not in ['call_agent', 'rag_support']:
                        continue
                    arguments = json.loads(call['function']['arguments'])
                    shapes.append({'case': key[0], 'repeat': key[1], 'tool_name': call['function']['name'],
                                   'argument_keys': sorted(arguments), 'complete': bad_cases[key]['complete']})
            entry['planning']['missing_query_argument_shapes'] = shapes
        path = ROOT / (label + '.log')
        if path.exists():
            log = path.read_text(errors='replace')
            for name, pattern in [('model_loading_gib', r'Model loading took ([0-9.]+) GiB memory'),
                                  ('kv_cache_gib', r'Available KV cache memory: ([0-9.]+) GiB'),
                                  ('max_context_concurrency', r'Maximum concurrency for 16,384 tokens per request: ([0-9.]+)x')]:
                values = re.findall(pattern, log)
                if values:
                    entry[name] = float(values[-1])
        captures = []
        for path in sorted((ROOT / 'capture').glob(label + '-*.private.json')):
            data = json.loads(path.read_text())
            captures.append(data)
        if captures:
            entry['actual_model_requests'] = len(captures)
            entry['actual_completion_tokens'] = sum((row.get('usage') or {}).get('completion_tokens', 0) for row in captures)
            entry['actual_length_stops'] = sum(row.get('finish_reason') == 'length' for row in captures)
            entry['capture_errors'] = sum(bool(row.get('capture_error_type')) for row in captures)
            entry['actual_temperatures'] = sorted({row['payload'].get('temperature', 0) for row in captures})
        if entry:
            result[label] = entry
    (ROOT / 'comparison-summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    collect()
