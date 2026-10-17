"""并发候选编排的真实复杂推荐、多轮功能验收；不输出身份、凭据或商品原始数据。"""
import hashlib
import argparse
import importlib.util
import json
import urllib.request
from pathlib import Path

import concurrency_probe as harness

ROOT = Path(__file__).resolve().parent
JAR = ROOT / 'rs-service-agent.jar'
EXPECTED_SHA = '4bc94fc6894a65fb933071ac91c2506c5964542c68d464f59155967c027c1c76'
REPORT = ROOT / 'functional.json'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--recommendation-slots', type=int, default=8)
    args = parser.parse_args()
    assert 1 <= args.recommendation_slots <= 32
    destination = REPORT if args.recommendation_slots == 8 else ROOT / f'functional-rec{args.recommendation_slots}.json'
    assert hashlib.file_digest(JAR.open('rb'), 'sha256').hexdigest() == EXPECTED_SHA
    report = {'agent_sha256': EXPECTED_SHA, 'model_before': harness.identity(), 'cases': [],
              'recommendation_slots': args.recommendation_slots,
              'scope': '真实复杂推荐及多轮工具、目录、历史、排序属性；不替代完整语义质量回归'}
    def save():
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    save()
    try:
        harness.configure(JAR, 16, 15000, args.recommendation_slots)
        spec = importlib.util.spec_from_file_location('business_probe',
            '/tmp/rs-agent-quantization-retry-20261011/business_probe.py')
        probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe)
        probe.BASE = f'http://127.0.0.1:{harness.PORT}'
        users = probe.accounts()
        queries = ('推荐鼠标', '推荐一款适合办公的鼠标，最好静音，说明理由',
                   '推荐适合编程使用的键盘，说明各自的区别', '请帮我推荐鼠标', '换一批鼠标，适合办公使用')
        session = None
        for index, query in enumerate(queries):
            case = {'index': index, 'query': query}
            try:
                row = probe.one(users[index >= 3], query, 'fast', 'concurrency-functional-' + str(index),
                                session if index >= 3 else None)
                if index >= 3:
                    session = row['session_id']
                final = row.get('response') or {}
                ids = [item['item_id'] for item in final.get('recommended_items', [])]
                trace = row.get('recommend_trace') or {}
                request = urllib.request.Request(probe.BASE + '/api/platform/agent/' + row['session_id'] + '/turns',
                                                headers={'X-User-Roles': 'OBSERVER'})
                with urllib.request.urlopen(request, timeout=15) as response:
                    turn = json.load(response)['turns'][-1]
                tools = turn.get('tool_calls', turn.get('toolCalls', []))
                case.update(complete_with_catalog_ms=row.get('complete_with_catalog_ms'),
                    item_count=len(ids), answer_chars=len(final.get('assistant_message', '')),
                    finish_reason=row['history']['turns'][-1]['finish_reason'],
                    tool_names=[tool.get('tool_name', tool.get('toolName')) for tool in tools],
                    failed_tools=sum(tool.get('status') in ('FAILED', 'ERROR', 'UNAVAILABLE') for tool in tools),
                    stage_counts=trace.get('stage_counts'), degradation_reasons=final.get('degradation_reasons'))
                checks = {'complete': bool(final) and not row.get('error'),
                    'five_real_unique_items': len(ids) == len(set(ids)) == len(row.get('catalog', [])) == 5,
                    'text_and_history': case['answer_chars'] > 0 and case['finish_reason'] == 'FINAL_ANSWER',
                    'tools_without_failure': case['failed_tools'] == 0,
                    'deepfm_bge': trace.get('stage_counts', {}).get('deepfm_scored', 0) > 0
                        and trace.get('stage_counts', {}).get('bge_reranked', 0) > 0,
                    'no_declared_degradation': final.get('degradation_reasons') == []
                        and trace.get('config', {}).get('ranking_degraded') == 0}
                case['checks'] = checks
                case['passed'] = all(checks.values())
            except Exception as error:
                case.update(passed=False, error_type=type(error).__name__)
            report['cases'].append(case)
            save()
            print('功能验收', index, '耗时', case.get('complete_with_catalog_ms'), 'ms；通过', case['passed'], flush=True)
        report['model_after'] = harness.identity()
        report['model_process_unchanged'] = report['model_before'] == report['model_after']
        save()
    finally:
        harness.cleanup()


if __name__ == '__main__':
    main()
