"""记录显存优先部署的实际业务表现，保留失败，不用旧时延门槛撤回。"""
import json
import os
from pathlib import Path
import stat

from business import probe, summarize, item_ids, trace

root = Path(__file__).resolve().parent
users = probe.accounts()
private = root / 'memory-business.private.json'
artifact = root / 'memory-business.json'
rows = []
summaries = []

def capture():
    descriptor = os.open(private, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    assert stat.S_IMODE(os.fstat(descriptor).st_mode) == 0o600
    with os.fdopen(descriptor, 'w') as handle:
        json.dump(rows, handle, ensure_ascii=False, indent=2)
        handle.write('\n')

session = None
queries = ['推荐鼠标', '推荐一款适合办公的鼠标，最好静音，说明理由',
           '推荐适合编程使用的键盘，说明各自的区别', '请帮我推荐鼠标', '换一批鼠标，适合办公使用']
for number, query in enumerate(queries):
    row = None
    try:
        row = probe.one(users[0 if number < 3 else 1], query, 'fast', 'memory-' + str(number),
                        session if number == 4 else None)
        rows.append(row)
        capture()
        if number == 3:
            session = row['session_id']
        summary, text = summarize(row)
        assert summary['item_count'] == 5 and len(set(item_ids(row['response']))) == 5
        if number in [1, 2]:
            assert text.strip(), '复杂推荐没有说明文字'
    except Exception as error:
        summary = {'query': query, 'passed': False, 'elapsed_ms': row.get('agent_done_ms') if row else None,
                   'complete_answer': bool(row and row.get('response')), 'failure_type': type(error).__name__}
        if row:
            turns = trace(row['session_id']).get('turns', [])
            if turns:
                summary['finish_reason'] = turns[-1].get('finish_reason')
                tools = turns[-1].get('tool_calls', turns[-1].get('toolCalls', []))
                summary['failed_tools'] = sum(str(tool.get('status', '')).upper() == 'FAILED' for tool in tools)
                summary['failed_tool_names'] = [tool.get('tool_name', tool.get('toolName')) for tool in tools
                                                if str(tool.get('status', '')).upper() == 'FAILED']
    summaries.append(summary)
    artifact.write_text(json.dumps({'scope': 'actual_business_diagnostic',
                                    'business_regression': summaries}, ensure_ascii=False, indent=2) + '\n')
    print('实际业务', number + 1, '通过' if summary['passed'] else '未通过',
          'elapsed_ms=', summary['elapsed_ms'], flush=True)
assert sum(bool(row['passed']) for row in summaries) > 0, '实际业务全部失败，拒绝保留不可用部署'
print('实际业务通过', sum(bool(row['passed']) for row in summaries), '/5；完整保留诊断结果', flush=True)
