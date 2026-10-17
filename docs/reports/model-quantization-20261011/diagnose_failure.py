"""只导出本次失败的工具名和错误，不输出身份信息或完整请求。"""
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent
name = 'int4_autoround_restart2'
rows = json.loads((ROOT / (name + '-business.private.json')).read_text())
row = rows[-1]
request = urllib.request.Request('http://127.0.0.1:18314/api/platform/agent/' + row['session_id'] + '/turns',
                                 headers={'X-User-Roles': 'OBSERVER'})
with urllib.request.urlopen(request, timeout=10) as response:
    result = json.load(response)
turns = result['data'] if isinstance(result.get('data'), list) else result.get('data', {}).get('turns', result.get('turns', []))
if not turns and isinstance(result.get('data'), dict):
    turns = result['data'].get('items', [])
turn = turns[-1]
tools = turn.get('tool_calls', turn.get('toolCalls', []))
failed = []
for tool in tools:
    if str(tool.get('status', '')).upper() == 'FAILED':
        failed.append({key: value for key, value in tool.items()
                       if key in ['tool_name', 'toolName', 'status', 'error', 'error_message', 'errorMessage',
                                  'result', 'resultJson', 'failure_reason', 'failureReason']})
        failed[-1]['available_fields'] = sorted(tool)
        metadata = tool.get('metadata', {})
        failed[-1]['metadata_fields'] = sorted(metadata) if isinstance(metadata, dict) else type(metadata).__name__
        if isinstance(metadata, dict):
            failed[-1]['failure_details'] = {key: value for key, value in metadata.items()
                if any(term in key.lower() for term in ['error', 'fail', 'exception', 'message', 'code'])}
            payload = metadata.get('payload', {})
            if isinstance(payload, dict):
                failed[-1]['payload_fields'] = sorted(payload)
                failed[-1]['failure_payload'] = {key: value for key, value in payload.items()
                    if any(term in key.lower() for term in ['error', 'fail', 'exception', 'message', 'code'])}
report = {'candidate': name, 'case': row['query'], 'failed_tools': failed,
          'public_response_present': row.get('response') is not None}
(ROOT / 'int4-failure.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False, indent=2))
