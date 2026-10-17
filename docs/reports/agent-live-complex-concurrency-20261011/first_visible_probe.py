"""补测当前网关首事件、正文 token、回答区块和完整回答；不保存身份或回答正文。"""
import argparse
import datetime
import importlib.util
import json
import time
import urllib.request
from collections import Counter

from deploy_live import ROOT, NAME, SHA, identity, inspect
from complex_probe import dependency_snapshot
from model_ttft_metrics import read_ttft_metrics, single_observed_ttft
from model_cache_metrics import read_cache_metrics, single_observed_cache


class TimedResponse:
    def __init__(self, response, metrics, start):
        self.response, self.metrics, self.start = response, metrics, start
        self.event = ''
        self.counts = Counter()

    def __enter__(self):
        self.response.__enter__()
        return self

    def __exit__(self, *args):
        return self.response.__exit__(*args)

    def __iter__(self):
        for raw in self.response:
            line = raw.decode().strip()
            if line.startswith('event:'):
                self.event = line[6:].strip()
            if line.startswith('data:'):
                elapsed = round((time.perf_counter() - self.start) * 1000, 2)
                payload = json.loads(line[5:].strip())
                self.counts[self.event] += 1
                self.metrics.setdefault('first_sse_event_ms', elapsed)
                if self.event == 'token' and isinstance(payload.get('delta'), str) and payload['delta'].strip():
                    if self.metrics.get('first_public_token_ms') is None:
                        self.metrics['first_public_token_ms'] = elapsed
                if self.event == 'answer_block':
                    if self.metrics.get('first_answer_block_ms') is None:
                        self.metrics['first_answer_block_ms'] = elapsed
                    content = payload.get('content')
                    if payload.get('type') == 'text' and isinstance(content, str) and content.strip():
                        if self.metrics.get('first_text_block_ms') is None:
                            self.metrics['first_text_block_ms'] = elapsed
                if self.event == 'done':
                    self.metrics.setdefault('done_event_ms', elapsed)
            self.metrics['sse_event_counts'] = dict(self.counts)
            yield raw


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--samples', type=int, choices=(1, 2, 4), default=4)
    parser.add_argument('--name', default='first-visible-current')
    args = parser.parse_args()
    assert args.name.replace('-', '').isalnum()
    spec = importlib.util.spec_from_file_location('business_probe',
        '/tmp/rs-agent-quantization-retry-20261011/business_probe.py')
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    users = probe.accounts()
    row = inspect(NAME)
    deployment = json.loads((ROOT / 'deployment.json').read_text())
    assert row['State']['Running'] and row['Id'] == deployment['new_container_id']
    report = {'checked_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'agent_sha256': SHA, 'model_before': identity(), 'dependencies_before': dependency_snapshot(),
        'scope': '当前网关与真实完整推荐，独立新 Session，顺序单请求，不计登录和建会话，非浏览器绘制时间',
        'first_event_note': 'started 等控制事件不算 token；前端当前只展示 answer_block，模型内部增量不在此测量',
        'cases': []}
    destination = ROOT / (args.name + '.json')
    def save():
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    save()
    queries = ('推荐鼠标', '推荐鼠标', '推荐一款适合办公的鼠标，最好静音，说明理由',
               '推荐适合编程使用的键盘，说明各自的区别')
    original_open = urllib.request.urlopen
    for index, query in enumerate(queries[:args.samples]):
        entry = {'index': index, 'query': query, 'concurrent_requests': 1, 'passed': False,
                 'first_public_token_ms': None, 'first_answer_block_ms': None, 'first_text_block_ms': None}
        try:
            with original_open('http://127.0.0.1:18082/health', timeout=3) as response:
                assert response.status == 200
            account = users[0]
            session = probe.http('/api/sessions', {'entryScene': 'first-visible-current'}, account['accessToken'])['sessionId']
            metrics_before = read_ttft_metrics()
            cache_before = read_cache_metrics()
            start = time.perf_counter()
            def observed_open(request, *args, **kwargs):
                response = original_open(request, *args, **kwargs)
                url = request.full_url if isinstance(request, urllib.request.Request) else request
                return TimedResponse(response, entry, start) if url.endswith('/api/agent/chat/stream') else response
            urllib.request.urlopen = observed_open
            try:
                result = probe.one(account, query, 'fast', 'first-visible-' + str(index), session)
            finally:
                urllib.request.urlopen = original_open
            final = result.get('response') or {}
            metrics_after = read_ttft_metrics()
            cache_after = read_cache_metrics()
            entry.update(model_metrics_before=metrics_before, model_metrics_after=metrics_after)
            entry.update(single_observed_ttft(metrics_before, metrics_after))
            entry.update(single_observed_cache(cache_before, cache_after))
            entry.update(complete_ms=result.get('complete_with_catalog_ms'), agent_done_ms=result['agent_done_ms'],
                         error_code=(result.get('error') or {}).get('error_code'))
            history = result.get('history', {}).get('turns', [])
            trace = result.get('recommend_trace') or {}
            ids = [item['item_id'] for item in final.get('recommended_items', [])]
            request = urllib.request.Request('http://127.0.0.1:18214/api/platform/agent/' + session + '/turns',
                                            headers={'X-User-Roles': 'OBSERVER'})
            with original_open(request, timeout=15) as response:
                turns = json.load(response)['turns']
            tools = turns[-1].get('tool_calls', []) if turns else []
            failures = sum(tool.get('status') in ('FAILED', 'ERROR', 'UNAVAILABLE') for tool in tools)
            counts = trace.get('stage_counts') or {}
            checks = {'complete': bool(final) and not result.get('error'),
                'five_real_unique_items': len(ids) == len(set(ids)) == len(result.get('catalog', [])) == 5,
                'answer_and_history': bool(final.get('assistant_message', '').strip())
                    and bool(history) and history[-1].get('finish_reason') == 'FINAL_ANSWER',
                'tools_without_failure': failures == 0,
                'deepfm_bge': counts.get('deepfm_scored', 0) > 0 and counts.get('bge_reranked', 0) > 0,
                'no_degradation': final.get('degradation_reasons') == []
                    and trace.get('config', {}).get('ranking_degraded') == 0}
            entry.update(complete_ms=result.get('complete_with_catalog_ms'), agent_done_ms=result['agent_done_ms'],
                checks=checks, passed=all(checks.values()), items=len(ids), answer_chars=len(final.get('assistant_message', '')),
                failed_tools=failures, tool_names=[tool.get('tool_name') for tool in tools], stage_counts=counts,
                degradation_reasons=final.get('degradation_reasons'),
                error_code=(result.get('error') or {}).get('error_code'))
        except Exception as error:
            entry.update(error_type=type(error).__name__)
        report['cases'].append(entry)
        save()
        print(json.dumps(entry, ensure_ascii=False), flush=True)
        if entry.get('error_type') or entry.get('error_code') or identity() != report['model_before']:
            report['stopped_on_error_or_model_change'] = True
            break
    report.update(model_after=identity(), dependencies_after=dependency_snapshot())
    report['model_process_unchanged'] = report['model_before'] == report['model_after']
    report['dependencies_stable'] = report['dependencies_before'] == report['dependencies_after']
    save()


if __name__ == '__main__':
    main()
