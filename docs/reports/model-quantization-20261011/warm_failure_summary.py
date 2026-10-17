"""保存热复测失败的公开错误与完成状态，不导出 Session 身份。"""
import json
from pathlib import Path
import re

root = Path(__file__).resolve().parent
rows = json.loads((root / 'production-warm-business-business.private.json').read_text())
row = rows[-1]
errors = []
for event in row.get('events', []):
    if event['event'] not in ['error', 'failed']:
        continue
    data = event['data']
    fields = {key: value for key, value in data.items() if key in ['code', 'message', 'error_code', 'error_message', 'error']}
    for key, value in fields.items():
        text = str(value)
        text = re.sub(r'(?i)bearer\s+\S+', 'Bearer <REDACTED>', text)
        text = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '<REDACTED>', text)
        fields[key] = text[:1000]
    errors.append(fields)
result = {'candidate': 'w8a16_middle_restart2', 'query': row['query'], 'elapsed_ms': row['agent_done_ms'],
          'complete_final_answer': row.get('response') is not None, 'public_errors': errors}
(root / 'warm-failure.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(result, ensure_ascii=False, indent=2))
