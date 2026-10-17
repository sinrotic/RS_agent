"""保留关键调用树，折叠访问器等细小调用；互斥时长仍严格闭合。"""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

def keep(method):
    cls, name = method.rsplit('.', 1)
    if cls in ('ConnectionImpl', 'HikariDataSource', 'ClientPreparedStatement', 'ServerPreparedStatement', 'StatementImpl'):
        return True
    if cls.startswith('Scylla'): return name in ('latest', 'append', 'tailAfter', 'save')
    if cls == 'RedisAgentHotSessionStore': return name in ('append', 'events', 'replaceEvents', 'storeSnapshot', 'latestSnapshot')
    if cls.startswith('HttpAgent'): return name in ('admit', 'verifyOwner', 'recommendDelivery', 'report')
    if cls.startswith('MysqlAgent'): return name in ('recordTranscriptEntry', 'inTransaction', 'update', 'recordCheckpoint')
    if cls.startswith('JdbcRecommendationPersistenceStore'): return name in ('save', 'findByRequestId')
    if cls == 'HomeFeedDiversity': return name == 'select'
    if cls == 'RestHomeModelRanker': return name in ('score', 'compute')
    if cls == 'RecommendationInferenceCache': return name in ('embeddings', 'rankings')
    if cls == 'RestTrainedRankingClient': return name == 'rank'
    if cls in ('UserSessionService', 'AgentRecommendController', 'HttpModelGatewayService', 'AgentLoop'):
        return True
    if cls == 'InMemoryAgentOrchestrationService': return name in ('streamChat', 'chat', 'executeObservedTurn', 'claimSessionOwnership')
    if cls == 'JavaNetAgentModelProviderHttpClient': return name == 'postJson'
    if cls == 'DefaultRestClient$DefaultRequestBodyUriSpec': return name == 'exchangeInternal'
    if cls in ('DefaultSemanticItemRecallProvider', 'HttpRagQueryEmbeddingClient', 'SpringAiAgentModelStreamClient'):
        return name in ('recall', 'embedQuery', 'stream')
    return name in ('semanticRecall', 'rank') and '$' not in cls

if __name__ == '__main__':
    report = []
    for path in HERE.glob('*-spans.json'):
        raw = path.read_bytes(); data = json.loads(raw)
        before = sum(len(trace['nodes']) for traces in data.values() for trace in traces)
        for traces in data.values():
            for trace in traces:
                original = trace['nodes']; mapped = {}; selected = []
                for i, node in enumerate(original):
                    if i != 0 and not keep(node['method']):
                        mapped[i] = mapped[node['parent']]; continue
                    node = dict(node); node['parent'] = -1 if i == 0 else mapped[node['parent']]
                    node['exclusive_ns'] = node['duration_ns']; mapped[i] = len(selected); selected.append(node)
                for node in selected[1:]: selected[node['parent']]['exclusive_ns'] -= node['duration_ns']
                assert all(node['exclusive_ns'] >= 0 for node in selected)
                assert sum(node['exclusive_ns'] for node in selected) == selected[0]['duration_ns']
                trace['nodes'] = selected
        after = sum(len(trace['nodes']) for traces in data.values() for trace in traces)
        path.write_text(json.dumps(data, indent=2), encoding='utf-8')
        report.append({'file': path.name, 'original_sha256': hashlib.sha256(raw).hexdigest(),
                       'original_bytes': len(raw), 'original_nodes': before, 'retained_nodes': after,
                       'compacted_bytes': path.stat().st_size, 'all_duration_and_exclusive_sums_closed': True})
        print(path.name, before, '->', after, 'nodes')
    (HERE / 'profile-pruning.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
