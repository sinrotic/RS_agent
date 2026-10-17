#!/usr/bin/env python3
"""隔离交付与偏好状态，使用指定交付的真实历史画像及线上 Catalog/BGE 回放换批。"""
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
    return subprocess.run(args, capture_output=True, text=True, check=True, timeout=45).stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--jar', required=True)
    parser.add_argument('--source-request-id', required=True)
    parser.add_argument('--output', default='home-refresh-content-acceptance.json')
    args = parser.parse_args()
    profile = sql('SELECT profile_user_id FROM rs_recommendation_delivery WHERE request_id=' + literal(args.source_request_id))
    assert profile, '源交付不存在'
    before_count = sql('SELECT COUNT(*) FROM rs_recommendation_delivery WHERE profile_user_id=' + literal(profile))
    config = json.loads(run(['docker', 'inspect', 'rs-agent-java-service-recommend']))[0]
    env = dict(entry.split('=', 1) for entry in config['Config']['Env'])
    env.update({'SPRING_APPLICATION_NAME': 'rs-content-acceptance', 'SPRING_CLOUD_NACOS_DISCOVERY_ENABLED': 'false',
                'SPRING_CLOUD_DISCOVERY_ENABLED': 'false', 'RS_RECOMMEND_FEEDBACK_PERSISTENCE': 'memory',
                'RS_RECOMMEND_FEEDBACK_PROJECTION': 'memory', 'JAVA_OPTS': '-Xms128m -Xmx384m'})
    name = 'rs-home-content-' + secrets.token_hex(5)
    report = {'profile_hash': hashlib.sha256(profile.encode()).hexdigest(), 'batches': []}
    env_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', prefix='rs-content-', delete=False) as handle:
            env_path = Path(handle.name)
            os.chmod(env_path, 0o600)
            handle.write('\n'.join(key + '=' + value for key, value in env.items()) + '\n')
        run(['docker', 'run', '-d', '--name', name, '--network', 'rs-agent-java_default', '--env-file', str(env_path),
             '-p', '127.0.0.1:18133:18103', '-v', str(Path(args.jar).resolve()) + ':/app/rs-service-recommend.jar:ro',
             config['Config']['Image'], 'sh', '-c', 'java $JAVA_OPTS -jar /app/rs-service-recommend.jar'])
        env_path.unlink()
        env_path = None
        base = 'http://127.0.0.1:18133'
        for _ in range(35):
            try:
                if http(base, '/actuator/health/readiness', timeout=2)['status'] == 'UP':
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            raise AssertionError('隔离 Recommend 未就绪')
        seen_ids, seen_images = set(), set()
        cursor = ''
        for batch in range(3):
            started = time.monotonic()
            page = http(base, '/api/recommend/home', {'session_id': name, 'scene': 'home', 'page_size': 6, 'cursor': cursor},
                        headers={'X-Account-Id': name, 'X-Profile-User-Id': profile})
            ids = {item['item_id'] for item in page['items']}
            cards = http('http://127.0.0.1:18102', '/api/catalog/items/batch', {'item_ids': list(ids)})
            images = {card['image_url'] for card in cards if card.get('image_url')}
            exploration = sum('catalog_exploration' in item['source_tags'] for item in page['items'])
            backpacks = sum('backpack' in item['display']['title'].lower() for item in page['items'])
            report['batches'].append({'request_id': page['request_id'], 'latency_ms': round((time.monotonic() - started) * 1000, 1),
                                     'exploration_count': exploration, 'backpack_count': backpacks, 'items': page['items'], 'cards': cards})
            assert len(ids) == 6 and ids.isdisjoint(seen_ids), '换批 ID 重复或未补满'
            assert not page['degradation_reasons'], page['degradation_reasons']
            assert images.isdisjoint(seen_images), '换批出现相同商品主图'
            assert exploration >= (3 if batch else 2), '最终页面缺少真正的探索候选'
            if batch:
                assert backpacks <= 3, '换批仍被同类背包占满'
            seen_ids.update(ids)
            seen_images.update(images)
            cursor = page['next_cursor']
            print(f'PASS batch={batch + 1} items=6 exploration={exploration} backpacks={backpacks}', flush=True)
        assert before_count == sql('SELECT COUNT(*) FROM rs_recommendation_delivery WHERE profile_user_id=' + literal(profile)), '回放不应写入真实交付'
        report['status'] = 'PASS'
        report['production_delivery_unchanged'] = True
    finally:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=45)
        if env_path:
            env_path.unlink(missing_ok=True)
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
