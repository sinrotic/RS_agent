#!/usr/bin/env python3
"""对照仓库原 queryv2 函数验证真实 epoch5 推理，并对照精确搜索验证 ANN。"""
import argparse
import ast
import json
from pathlib import Path
import types
import urllib.request
import numpy as np
from pymilvus import MilvusClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', required=True)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root, reference = Path(args.directory), Path(args.reference)
    functions = []
    for filename, names in [('vector_index.py', ['normalize_vector', 'average_vectors']),
                            ('two_tower_query.py', ['apply_user_tower_projection'])]:
        tree = ast.parse((reference / filename).read_text(encoding='utf-8-sig'))
        functions.extend(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names)
    scope = {}
    exec('from __future__ import annotations\nimport math\n' + '\n'.join(ast.unparse(node) for node in functions), scope)
    model = json.loads((root / 'two_tower_model.json').read_text())
    manifest = json.loads((root / 'serving-manifest.json').read_text())
    ids = json.loads((root / 'item_ids.json').read_text())
    vectors = np.load(root / 'item_vectors.npy', mmap_mode='r')
    client = MilvusClient(uri='http://127.0.0.1:19530')
    rng = np.random.default_rng(20260913)
    report = {'checks': [], 'parity_max_absolute_error': 0, 'ann_recall_at_20': []}
    for _ in range(10):
        indices = rng.choice(len(ids), size=8, replace=False)
        history = [ids[i] for i in indices]
        request = urllib.request.Request('http://172.21.0.1:18117/internal/model/two-tower/user-embedding',
                    data=json.dumps({'model_key': manifest['model_key'], 'history_item_ids': history}).encode(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=5) as response:
            actual = np.asarray(json.load(response)['embedding'], dtype=np.float32)
        mean = scope['average_vectors']([vectors[i].tolist() for i in reversed(indices)], recency_decay=.85)
        expected = np.asarray(scope['apply_user_tower_projection'](mean, types.SimpleNamespace(model_metadata=model)))
        error = float(np.max(np.abs(actual - expected)))
        report['parity_max_absolute_error'] = max(report['parity_max_absolute_error'], error)
        assert error < 1e-5 and abs(np.linalg.norm(actual) - 1) < 1e-5
        scores = vectors @ actual
        exact = {ids[i] for i in np.argpartition(scores, -20)[-20:]}
        hits = client.search(collection_name=manifest['collection'], data=[actual.tolist()], anns_field='vector', limit=20,
                             output_fields=['item_id'])[0]
        recall = len(exact & {hit['entity']['item_id'] for hit in hits}) / 20
        report['ann_recall_at_20'].append(recall)
    report['mean_ann_recall_at_20'] = float(np.mean(report['ann_recall_at_20']))
    assert report['mean_ann_recall_at_20'] >= .9, report
    report['checks'] = ['真实 epoch5 用户投影与原 queryv2 数值一致', '64维ANN与精确检索对照通过']
    report['status'] = 'PASS'
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
