"""相同账号和输入的工具回归，完整响应仅保存远端私有文件。"""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path('/tmp/rs-agent-partial-quantization-20261011')
OLD = Path('/tmp/rs-agent-quantization-retry-20261011')
sys.path.insert(0, str(OLD))
from business import probe, summarize, trace, item_ids
probe.ROOT = ROOT

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True, choices=['control', 'mlp_only', 'gdn_bf16', 'winner_low_memory', 'production', 'production_cache50'])
    args = parser.parse_args()
    users = probe.accounts()
    rows, summaries = [], []
    queries = ['推荐鼠标', '推荐一款适合办公的鼠标，最好静音，说明理由', '推荐适合编程使用的键盘，说明各自的区别']
    inputs = [(query, 0, None) for _ in range(2) for query in queries]
    inputs += [('请帮我推荐鼠标', 1, None), ('换一批鼠标，适合办公使用', 1, 'previous')]
    session = None
    for number, (query, user, previous) in enumerate(inputs):
        row = None
        try:
            row = probe.one(users[user], query, 'fast', args.label + '-' + str(number), session if previous else None)
            rows.append(row)
            descriptor = os.open(ROOT / (args.label + '-business.private.json'), os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, 'w') as handle:
                json.dump(rows, handle, ensure_ascii=False, indent=2)
            session = row['session_id']
            summary, text = summarize(row)
            assert len(set(item_ids(row['response']))) == 5
            if '说明' in query:
                assert text.strip()
        except Exception as error:
            summary = {'query': query, 'passed': False, 'failure_type': type(error).__name__,
                       'elapsed_ms': row.get('agent_done_ms') if row else None,
                       'complete_final_answer': bool(row and row.get('response'))}
            if row:
                turns = trace(row['session_id']).get('turns', [])
                if turns:
                    tools = turns[-1].get('tool_calls', [])
                    summary.update(finish_reason=turns[-1].get('finish_reason'),
                        failed_tools=sum(str(tool.get('status', '')).upper() == 'FAILED' for tool in tools),
                        failed_tool_names=[tool.get('tool_name') for tool in tools if str(tool.get('status', '')).upper() == 'FAILED'])
        summaries.append(summary)
        (ROOT / (args.label + '-business.json')).write_text(json.dumps({'label': args.label,
            'business_regression': summaries}, ensure_ascii=False, indent=2) + '\n')
        print(args.label, 'case', number + 1, '通过' if summary['passed'] else '未通过', flush=True)
    print(args.label, '业务通过', sum(bool(row['passed']) for row in summaries), '/', len(summaries), flush=True)
    if args.label in ['mlp_only', 'gdn_bf16', 'winner_low_memory']:
        from tool_replay import run
        if not (ROOT / 'control-planning.json').exists():
            run('control', 18082)
        run(args.label, 18092)

if __name__ == '__main__':
    main()
