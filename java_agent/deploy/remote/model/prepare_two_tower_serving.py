#!/usr/bin/env python3
"""流式转换训练产物并建立独立的 64 维 Milvus 索引，保留原离线 manifest。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import numpy as np
from pymilvus import MilvusClient, DataType


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--checkpoint', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--collection', required=True)
    parser.add_argument('--milvus', default='http://127.0.0.1:19530')
    args = parser.parse_args()
    checkpoint, output = Path(args.checkpoint), Path(args.output)
    model = json.loads((checkpoint / 'two_tower_model.json').read_text())
    config = json.loads((checkpoint / 'train_config.json').read_text())
    assert model['embedding_dim'] == 64 and model['variant'] == 'youtube_dnn' and config['epochs'] == 5
    ids = json.loads((checkpoint / 'item_id_map.json').read_text())['ids']
    assert len(ids) == model['item_count'] and len(set(ids)) == len(ids)
    client = MilvusClient(uri=args.milvus)
    if client.has_collection(args.collection):
        raise RuntimeError('目标集合已存在，请使用新版本名称，避免覆盖已部署索引')
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'serving-manifest.json').exists():
        raise RuntimeError('目标产物已存在，请使用新版本目录')
    vectors = np.lib.format.open_memmap(output / 'item_vectors.npy', mode='w+', dtype='float32', shape=(len(ids), 64))
    digest = hashlib.sha256()
    count = 0
    with (checkpoint / 'item_embeddings.jsonl').open('rb') as handle:
        for i, line in enumerate(handle):
            digest.update(line)
            row = json.loads(line)
            assert i < len(ids) and row['item_id'] == ids[i]
            vector = np.asarray(row['embedding'], dtype=np.float32)
            assert vector.shape == (64,) and np.isfinite(vector).all() and np.linalg.norm(vector) > 1e-9
            vectors[i] = vector / np.linalg.norm(vector)
            count += 1
    assert count == len(ids)
    vectors.flush()
    (output / 'item_ids.json').write_text(json.dumps(ids))
    shutil.copy2(checkpoint / 'two_tower_model.json', output / 'two_tower_model.json')
    schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field(field_name='item_id', datatype=DataType.VARCHAR, is_primary=True, max_length=128)
    schema.add_field(field_name='vector', datatype=DataType.FLOAT_VECTOR, dim=64)
    index = client.prepare_index_params()
    index.add_index(field_name='vector', index_type='AUTOINDEX', metric_type='COSINE')
    client.create_collection(collection_name=args.collection, schema=schema, index_params=index)
    for start in range(0, len(ids), 4000):
        end = min(start + 4000, len(ids))
        client.insert(collection_name=args.collection, data=[{'item_id': ids[i], 'vector': vectors[i].tolist()} for i in range(start, end)])
        if start % 40000 == 0:
            print(f'indexed {end}/{len(ids)}', flush=True)
    client.flush(collection_name=args.collection)
    client.load_collection(collection_name=args.collection)
    actual = int(client.get_collection_stats(collection_name=args.collection)['row_count'])
    assert actual == len(ids), (actual, len(ids))
    manifest = {'model_key': 'two_tower_sparse_aware_epoch5_queryv2', 'model_sha256': hashlib.sha256((output / 'two_tower_model.json').read_bytes()).hexdigest(),
                'item_embeddings_sha256': digest.hexdigest(), 'source_checkpoint': str(checkpoint), 'item_count': count,
                'collection': args.collection, 'dimension': 64, 'metric': 'COSINE', 'query_history_order': 'newest_first',
                'query_window': 80, 'query_recency_decay': .85, 'query_projection': 'normalized_seed_mean_mlp_residual_queryv2',
                'scope': '用户授权的 Java 首页新增双塔召回；原 pool500 离线诊断状态保留',
                'candidate_generation_allowed': True, 'ranking_input_replacement_allowed': False,
                'offline_pool500_promotion_claimed': False, 'index_verified': True}
    (output / 'serving-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': 'PASS', 'items': count, 'collection': args.collection}), flush=True)


if __name__ == '__main__':
    main()
