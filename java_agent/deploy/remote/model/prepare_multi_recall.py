#!/usr/bin/env python3
"""流式制作版本化只读候选库；不修改原实验产物或线上 MySQL。"""
import argparse
import hashlib
import json
import math
import sqlite3
from pathlib import Path


def rows(path):
    with path.open() as handle:
        for line in handle:
            yield json.loads(line)


def build(config, output):
    output.mkdir(parents=True, exist_ok=False)
    db = sqlite3.connect(output / 'candidates.sqlite')
    db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-65536;'
                     'CREATE TABLE candidates(source TEXT, bucket TEXT, item TEXT, score REAL, rank INTEGER);'
                     'CREATE TABLE user_lists(source TEXT, user TEXT, payload TEXT, PRIMARY KEY(source,user)) WITHOUT ROWID;')
    report = {'scope': '用户授权的 Java 首页多路召回接入；原离线实验门禁状态保留',
              'version': config['version'], 'sources': {}, 'ranking_input_replacement_allowed': False,
              'offline_pool500_promotion_claimed': False}
    for source, spec in config['sources'].items():
        manifest_path = Path(spec['manifest'])
        manifest = json.loads(manifest_path.read_text())
        assert manifest.get('train_only') is True and manifest.get('source') == source
        assert manifest.get('status') == 'PASS', (source, manifest.get('status'))
        paths = sorted(manifest_path.parent.glob(spec['files']))
        assert paths, source
        count = 0
        signatures = []
        batch = []
        for path in paths:
            digest = hashlib.sha256()
            with path.open('rb') as handle:
                for line in handle:
                    digest.update(line)
                    row = json.loads(line)
                    kind = spec['kind']
                    if kind == 'user':
                        candidates = [[r['item_id'], float(r['score'])] for r in row['candidates']]
                        assert all(math.isfinite(r[1]) for r in candidates)
                        batch.append((source, row['user_id'], json.dumps(candidates, separators=(',', ':'))))
                        count += len(candidates)
                    elif kind == 'category':
                        for rank, r in enumerate(row['top_items'], 1):
                            batch.append((source, row['bucket'], r['parent_asin'], float(r['score']), rank))
                            count += 1
                    else:
                        item = row['dst_item'] if kind == 'edges' else row['item_id']
                        bucket = row['src_item'] if kind == 'edges' else 'global'
                        score = float(row['score'])
                        assert item and bucket and math.isfinite(score)
                        batch.append((source, bucket, item, score, int(row['rank'])))
                        count += 1
                    if len(batch) >= 5000:
                        db.executemany('INSERT INTO user_lists VALUES (?,?,?)' if kind == 'user' else 'INSERT INTO candidates VALUES (?,?,?,?,?)', batch)
                        db.commit(); batch.clear()
            signatures.append({'file': str(path), 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size})
            print(source, path.name, count, flush=True)
        if batch:
            db.executemany('INSERT INTO user_lists VALUES (?,?,?)' if spec['kind'] == 'user' else 'INSERT INTO candidates VALUES (?,?,?,?,?)', batch)
            db.commit()
        report['sources'][source] = {'candidate_count': count, 'manifest': str(manifest_path),
            'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            'original_status': manifest.get('source_status', manifest['status']), 'files': signatures}
    # 类目画像按用户存储；线上不加载百万用户进内存。
    profile_path = Path(config['category_profiles'])
    profile_digest = hashlib.sha256()
    profile_count = 0
    with profile_path.open('rb') as handle:
        for line in handle:
            profile_digest.update(line)
            row = json.loads(line)
            buckets = [r['bucket'] for r in row['top_profile_buckets'][:5]]
            db.execute('INSERT INTO user_lists VALUES (?,?,?)', ('category_profile', row['user_id'], json.dumps(buckets)))
            profile_count += 1
    report['category_profiles'] = {'file': str(profile_path), 'sha256': profile_digest.hexdigest(),
                                   'bytes': profile_path.stat().st_size, 'users': profile_count}
    db.commit()
    db.execute('CREATE INDEX candidate_lookup ON candidates(source,bucket,rank,item)')
    db.commit()
    assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
    db.close()
    report['status'] = 'PASS'
    (output / 'serving-manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('PASS index ready', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    build(json.loads(Path(args.config).read_text()), Path(args.output))
