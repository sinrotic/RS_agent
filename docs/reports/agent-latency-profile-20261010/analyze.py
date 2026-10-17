"""互斥计时与跨服务子阶段分别统计，避免把 HTTP 和内部 SQL 重复相加。"""
import json
import statistics
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent

def stats(values):
    return {'n': len(values), 'min': round(min(values), 3), 'median': round(statistics.median(values), 3),
            'mean': round(statistics.mean(values), 3), 'max': round(max(values), 3)} if values else None

def methods(trace):
    inclusive = Counter(); exclusive = Counter(); counts = Counter()
    for node in trace['nodes']:
        method = node['method']; inclusive[method] += node['duration_ns'] / 1e6
        exclusive[method] += node['exclusive_ns'] / 1e6; counts[method] += 1
    return inclusive, exclusive, counts

def jdbc(trace):
    inclusive, exclusive, counts = methods(trace)
    return {'commit_ms': exclusive['ConnectionImpl.commit'],
            'sql_ms': sum(ms for name, ms in exclusive.items() if name.startswith(('ClientPreparedStatement.', 'ServerPreparedStatement.', 'StatementImpl.'))),
            'pool_ms': inclusive['HikariDataSource.getConnection'],
            'transaction_setup_ms': exclusive['ConnectionImpl.setAutoCommit'],
            'commit_count': counts['ConnectionImpl.commit'],
            'sql_execute_count': counts['ClientPreparedStatement.executeInternal'],
            'pool_borrow_count': counts['HikariDataSource.getConnection']}

def agent_categories(trace):
    names = []
    for node in trace['nodes']:
        method = node['method']; parent = None if node['parent'] < 0 else names[node['parent']]
        if parent in ('session_http', 'recommend_http', 'scylla', 'redis'): category = parent
        elif method == 'HttpAgentSessionAdmissionClient.admit': category = 'session_http'
        elif method == 'HttpAgentRecommendationService.recommendDelivery': category = 'recommend_http'
        elif method.startswith('Scylla'): category = 'scylla'
        elif method.startswith('RedisAgentHotSessionStore'): category = 'redis'
        elif method == 'ConnectionImpl.commit': category = 'agent_mysql_commit'
        elif method.startswith(('ClientPreparedStatement.', 'ServerPreparedStatement.', 'StatementImpl.')): category = 'agent_mysql_sql'
        elif method == 'HikariDataSource.getConnection': category = 'agent_mysql_pool'
        elif method == 'ConnectionImpl.setAutoCommit': category = 'agent_mysql_setup'
        else: category = 'remaining_agent'
        names.append(category)
    result = Counter()
    for category, node in zip(names, trace['nodes']): result[category] += node['exclusive_ns'] / 1e6
    assert abs(sum(result.values()) - trace['nodes'][0]['duration_ns'] / 1e6) < 1e-6
    return dict(result)

def ranges(rows):
    return min(row['start_epoch_ms'] for row in rows), max(row['start_epoch_ms'] + row['agent_done_ms'] for row in rows)

def summarize(name):
    data = json.loads((HERE / f'{name}.json').read_text(encoding='utf-8'))
    output = {'failed_requests': len(data['failures']), 'failures': [
        {'query': row['query'], 'label': row['label'], 'elapsed_ms': row.get('agent_done_ms'), 'error': row['error']}
        for row in data['failures']], 'groups': {}}
    spans_file = HERE / f'{name}-spans.json'
    spans = json.loads(spans_file.read_text()) if spans_file.exists() else {}
    for group in ('first', 'warmups', 'single', 'concurrent_8', 'cold_variants_8'):
        rows = data[group]
        if not rows: continue
        result = {'complete_ms': stats([r['complete_with_catalog_ms'] for r in rows]),
                  'sse_done_ms': stats([r['agent_done_ms'] for r in rows]),
                  'catalog_ms': stats([r['catalog_ms'] for r in rows])}
        output['groups'][group] = result
        if not spans.get('agent-fast'): continue
        lo, hi = ranges(rows)
        # 冷 query 的失败请求也在阶段窗口内；失败不混入成功完成时延。
        failures = [r for r in data['failures'] if r.get('label') == 'cold-variants-8'] if group == 'cold_variants_8' else []
        if failures and all(r.get('start_epoch_ms') for r in failures):
            lo, hi = ranges(rows + failures)
        traces = {service: [trace for trace in values if lo - 3 <= trace['epoch_ms'] <= hi]
                  for service, values in spans.items()}
        agents = traces['agent-fast']
        if group != 'cold_variants_8': assert len(agents) == len(rows), (name, group, len(agents), len(rows))
        categories = [agent_categories(trace) for trace in agents]
        result['agent_disjoint_ms'] = {key: stats([row.get(key, 0) for row in categories])
                                      for key in sorted(set().union(*categories))}
        result['agent_total_ms'] = stats([trace['nodes'][0]['duration_ns'] / 1e6 for trace in agents])
        result['jdbc'] = {}
        for service, values in traces.items():
            if service == 'user': values = [trace for trace in values if trace['nodes'][0]['method'] == 'UserSessionService.admit']
            if service == 'model' or not values: continue
            if group != 'cold_variants_8': assert len(values) == len(rows), (name, group, service, len(values))
            metrics = [jdbc(trace) for trace in values]
            result['jdbc'][service] = {key: stats([row[key] for row in metrics]) for key in metrics[0]}
        recommend = traces.get('recommend-fast', [])
        result['recommend_substages_ms'] = {label: stats([methods(trace)[0][method] for trace in recommend])
            for label, method in {'delivery_persist': 'JdbcRecommendationPersistenceStore.save',
                                 'bge_score': 'RestHomeModelRanker.score',
                                 'deepfm_http': 'RestTrainedRankingClient.rank',
                                 'diversity_select': 'HomeFeedDiversity.select'}.items()}
        if group == 'single':
            # 单请求按 HTTP 时间窗口一一对应，可拆内部与服务间剩余时间。
            expanded = []
            for trace in agents:
                inc, _, _ = methods(trace); total = trace['nodes'][0]['duration_ns'] / 1e6
                begin = trace['epoch_ms']; end = begin + total
                rec = [t for t in recommend if begin <= t['epoch_ms'] <= end]
                user = [t for t in traces['user'] if begin <= t['epoch_ms'] <= end and t['nodes'][0]['method'].endswith('.admit')]
                assert len(rec) == len(user) == 1
                rec_jdbc = jdbc(rec[0]); user_jdbc = jdbc(user[0]); agent_jdbc = jdbc(trace)
                categories = agent_categories(trace)
                rec_inc, _, _ = methods(rec[0]); delivery = rec_inc['JdbcRecommendationPersistenceStore.save']
                expanded.append({'agent_commit': agent_jdbc['commit_ms'], 'user_sql_autocommit': user_jdbc['sql_ms'],
                    'user_http_other': categories['session_http'] - user_jdbc['sql_ms'],
                    'delivery_persist': delivery, 'recommend_other_and_http': categories['recommend_http'] - delivery,
                    'scylla': categories['scylla'], 'redis': categories['redis'],
                    'other_agent': total - categories['session_http'] - categories['recommend_http']
                        - categories['scylla'] - categories['redis'] - agent_jdbc['commit_ms'],
                    'mysql_explicit_commits_and_user_sql_fraction':
                        (agent_jdbc['commit_ms'] + rec_jdbc['commit_ms'] + user_jdbc['sql_ms']) / total})
            result['expanded_disjoint_ms'] = {key: stats([row[key] for row in expanded]) for key in expanded[0]}
    return output

if __name__ == '__main__':
    result = {name: summarize(name) for name in ('profiled', 'control', 'detailed', 'nvme', 'nvme-control')}
    (HERE / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    for name, result in result.items():
        print(name, {g: v['complete_ms'] for g, v in result['groups'].items() if g not in ('warmups', 'first')})
        if 'expanded_disjoint_ms' in result['groups']['single']:
            print('single mean components', {k: v['mean'] for k, v in result['groups']['single']['expanded_disjoint_ms'].items()})
