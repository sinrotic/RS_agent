#!/usr/bin/env python3
"""真实双塔、Milvus、BGE/Catalog 联调；仅临时实例中的交付与偏好发生变化。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
from feedback_acceptance import sql, literal
from personalized_home_acceptance import http


def run(args):
    return subprocess.run(args, capture_output=True, text=True, check=True, timeout=60).stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--jar', required=True)
    parser.add_argument('--output', default='two-tower-home-acceptance.json')
    parser.add_argument('--source-request-id')
    args = parser.parse_args()
    profiles = sql('''SELECT user_id FROM (SELECT user_id FROM amazon_reviews_base WHERE rating >= 4 LIMIT 10000) s
                      GROUP BY user_id HAVING COUNT(*) >= 2 LIMIT 4''').splitlines()
    assert len(profiles) >= 2
    if args.source_request_id:
        source_profile = sql('SELECT profile_user_id FROM rs_recommendation_delivery WHERE request_id=' + literal(args.source_request_id))
        assert source_profile
        if source_profile not in profiles: profiles.append(source_profile)
    config = json.loads(run(['docker', 'inspect', 'rs-agent-java-service-recommend']))[0]
    original_env = dict(entry.split('=', 1) for entry in config['Config']['Env'])
    suffix = secrets.token_hex(5)
    service = 'rs-tower-acceptance-' + suffix
    report = {'profiles': [], 'checks': []}
    env_path = None

    def start(runtime_url):
        nonlocal env_path
        env = {**original_env, 'SPRING_APPLICATION_NAME': service, 'SPRING_CLOUD_NACOS_DISCOVERY_ENABLED': 'false',
               'SPRING_CLOUD_DISCOVERY_ENABLED': 'false', 'RS_RECOMMEND_FEEDBACK_PERSISTENCE': 'memory',
               'RS_RECOMMEND_FEEDBACK_PROJECTION': 'memory', 'RS_RECOMMEND_TWO_TOWER_ENABLED': 'true',
               'RS_RECOMMEND_TWO_TOWER_BASE_URL': runtime_url,
               'RS_RECOMMEND_TWO_TOWER_MODEL_KEY': 'two_tower_sparse_aware_epoch5_queryv2',
               'RS_RECOMMEND_TWO_TOWER_COLLECTION': 'rs_agent_two_tower_epoch5_20260913', 'JAVA_OPTS': '-Xms128m -Xmx384m'}
        with tempfile.NamedTemporaryFile(mode='w', prefix='rs-tower-', delete=False) as handle:
            env_path = Path(handle.name)
            os.chmod(env_path, 0o600)
            handle.write('\n'.join(k + '=' + v for k, v in env.items()) + '\n')
        run(['docker', 'run', '-d', '--name', service, '--network', 'rs-agent-java_default', '--env-file', str(env_path),
             '-p', '127.0.0.1:18133:18103', '-v', str(Path(args.jar).resolve()) + ':/app/rs-service-recommend.jar:ro',
             config['Config']['Image'], 'sh', '-c', 'java $JAVA_OPTS -jar /app/rs-service-recommend.jar'])
        env_path.unlink(); env_path = None
        for _ in range(40):
            try:
                if http('http://127.0.0.1:18133', '/actuator/health/readiness', timeout=2)['status'] == 'UP': return
            except Exception: pass
            time.sleep(1)
        raise AssertionError('隔离服务未就绪')

    def page(profile, cursor=''):
        started = time.monotonic()
        value = http('http://127.0.0.1:18133', '/api/recommend/home',
                     {'session_id': service, 'scene': 'home', 'page_size': 6, 'cursor': cursor},
                     headers={'X-Account-Id': service, 'X-Profile-User-Id': profile})
        elapsed = round((time.monotonic() - started) * 1000, 1)
        trace = http('http://127.0.0.1:18133', '/api/platform/recommend/' + value['request_id'] + '/trace')
        return value, trace, elapsed

    try:
        start('http://172.21.0.1:18117')
        tower_candidates = tower_displayed = 0
        for profile in profiles:
            http('http://127.0.0.1:18133', '/internal/recommend/pipeline/recall',
                 {'profile_user_id': profile, 'sources': ['two_tower'], 'limit': 120})
            first, trace, elapsed = page(profile)
            assert len(first['items']) == 6 and not first['degradation_reasons'], first
            count = trace['source_distribution'].get('two_tower', 0)
            displayed = sum('two_tower' in item['source_tags'] for item in first['items'])
            tower_candidates += count; tower_displayed += displayed
            next_page, _, _ = page(profile, first['next_cursor'])
            assert {i['item_id'] for i in first['items']}.isdisjoint(i['item_id'] for i in next_page['items'])
            # 属性来自 Catalog；核验全部展示 ID 均能回填。
            cards = http('http://127.0.0.1:18102', '/api/catalog/items/batch', {'item_ids': [i['item_id'] for i in first['items']]})
            assert {c['item_id'] for c in cards} == {i['item_id'] for i in first['items']}
            report['profiles'].append({'profile_hash': hashlib.sha256(profile.encode()).hexdigest(), 'latency_ms': elapsed,
                                       'two_tower_candidates': count, 'two_tower_displayed': displayed,
                                       'sources': trace['source_distribution'], 'items': first['items']})
            print(f'PASS profile candidates={count} displayed={displayed} latency_ms={elapsed}', flush=True)
        assert tower_candidates > 0 and tower_displayed > 0, '双塔必须真实参与召回和最终展示'
        cold, trace, _ = page('unseen-tower-profile-' + suffix)
        assert len(cold['items']) == 6 and trace['source_distribution'].get('two_tower') == 0
        report['checks'].append('多画像真实双塔召回、BGE排序、Catalog回填、换批去重、无历史降级通过')
        run(['docker', 'rm', '-f', service])
        start('http://127.0.0.1:9')
        fallback, _, _ = page(profiles[0])
        assert len(fallback['items']) == 6 and 'two_tower_unavailable' in fallback['degradation_reasons']
        report['checks'].append('双塔连接故障时保留现有推荐且明确标记降级')
        report['status'] = 'PASS'
    finally:
        logs = subprocess.run(['docker', 'logs', '--tail', '100', service], capture_output=True, text=True, timeout=15)
        Path(args.output + '.service.log').write_text(logs.stdout + logs.stderr)
        subprocess.run(['docker', 'rm', '-f', service], capture_output=True, timeout=45)
        if env_path: env_path.unlink(missing_ok=True)
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
