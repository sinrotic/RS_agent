"""从已有只读 trace 导出模型 token、工具计时及重复 skill 的脱敏证据。"""
import json
import hashlib
from pathlib import Path
import re
import urllib.request

root = Path(__file__).resolve().parent

def get(url):
    request = urllib.request.Request(url, headers={'X-User-Roles': 'OBSERVER'})
    with urllib.request.urlopen(request, timeout=10) as response:
        body = json.load(response)
    return body.get('data', body)

def safe(value):
    text = str(value)
    text = re.sub(r'(?i)bearer\s+\S+', 'Bearer <REDACTED>', text)
    text = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '<REDACTED>', text)
    return text[:300]

reports = []
cases = [('bf16-production-business', 'bf16-production-business-business.private.json', [1, 2]),
         ('middle16_formal', 'production-middle16-business.private.json', [1, 2]),
         ('middle16_warm', 'production-warm-business-business.private.json', [1, 2]),
         ('middle8_formal', 'production-after-business.private.json', [1, 2]),
         ('bf16_restart', 'bf16-restart-complex-business.private.json', [0, 1])]
for name, filename, numbers in cases:
    # 正式首次私有响应不被新实验复用：其证据已在上一次 trace-study 中留存。
    if name == 'middle16_formal' and (root / 'trace-study-middle16.json').exists():
        previous = json.loads((root / 'trace-study-middle16.json').read_text())
        reports.extend(report for report in previous if report['variant'] in ['production-after', 'middle16_formal'])
        continue
    if not (root / filename).exists():
        continue
    rows = json.loads((root / filename).read_text())
    for number in numbers:
        if number >= len(rows):
            continue
        row = rows[number]
        turns = get('http://127.0.0.1:18314/api/platform/agent/' + row['session_id'] + '/turns')['turns']
        request_id = turns[-1]['request_id']
        events = get('http://127.0.0.1:18208/api/platform/agent/requests/' + request_id + '/events')['events']
        selected = []
        for event in events:
            keys = ['event_type', 'tool_name', 'agent_name', 'latency_ms', 'prompt_tokens', 'completion_tokens',
                    'phase', 'status', 'error_code']
            record = {key: event.get(key) for key in keys}
            record['error_message'] = safe(event.get('error_message', ''))
            data = event.get('data', {})
            record['data_fields'] = sorted(data)
            if event.get('event_type') == 'model_usage':
                record['usage'] = {key: value for key, value in data.items()
                    if any(term in key.lower() for term in ['token', 'latency', 'duration', 'usage'])}
            if event.get('tool_name') == 'load_skill':
                record['skill_details'] = {key: safe(value) for key, value in data.items()
                                           if 'skill' in key.lower()}
                record['input_summary'] = safe(event.get('input_summary', ''))
                arguments = data.get('arguments')
                if arguments is not None:
                    if isinstance(arguments, str):
                        arguments = json.loads(arguments)
                    record['arguments_hash'] = hashlib.sha256(json.dumps(arguments, sort_keys=True).encode()).hexdigest()
                    record['skill_arguments'] = {key: safe(value) for key, value in arguments.items()
                                                if 'skill' in key.lower()}
            selected.append(record)
        reports.append({'variant': name, 'query': row['query'], 'elapsed_ms': row['agent_done_ms'],
                        'finish_reason': turns[-1].get('finish_reason'), 'events': selected})
(root / 'trace-study.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2) + '\n')
for report in reports:
    generations = [event for event in report['events'] if event['event_type'] == 'model_usage']
    skills = [event.get('skill_arguments', {}).get('skill_name') for event in report['events']
              if event['event_type'] == 'tool_use' and event['tool_name'] == 'load_skill']
    print(json.dumps({'variant': report['variant'], 'query': report['query'], 'elapsed_ms': report['elapsed_ms'],
                     'finish': report['finish_reason'], 'recorded_model_calls': len(generations),
                     'recorded_completion_tokens': sum(event.get('completion_tokens') or 0 for event in generations),
                     'generation_1200_calls': sum(event.get('completion_tokens') == 1200 for event in generations),
                     'skills': skills}, ensure_ascii=False))
