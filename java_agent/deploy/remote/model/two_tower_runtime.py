#!/usr/bin/env python3
"""从已训练 epoch5 产物提供查询投影；不读取验证标签，也不执行训练。"""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import numpy as np

MODEL_KEY = 'two_tower_sparse_aware_epoch5_queryv2'
DIMENSION = 64


class Runtime:
    def __init__(self, directory):
        directory = Path(directory)
        self.manifest = json.loads((directory / 'serving-manifest.json').read_text())
        model_file = directory / 'two_tower_model.json'
        assert hashlib.sha256(model_file.read_bytes()).hexdigest() == self.manifest['model_sha256']
        model = json.loads(model_file.read_text())
        assert model['variant'] == 'youtube_dnn' and model['embedding_dim'] == DIMENSION
        params = model['model_parameters']
        self.w1 = np.asarray(params['user_tower.0.weight'], dtype=np.float32)
        self.b1 = np.asarray(params['user_tower.0.bias'], dtype=np.float32)
        self.w2 = np.asarray(params['user_tower.2.weight'], dtype=np.float32)
        self.b2 = np.asarray(params['user_tower.2.bias'], dtype=np.float32)
        assert self.w1.shape == (128, 64) and self.w2.shape == (64, 128)
        assert all(np.isfinite(x).all() for x in [self.w1, self.b1, self.w2, self.b2])
        ids = json.loads((directory / 'item_ids.json').read_text())
        self.index = {item_id: i for i, item_id in enumerate(ids)}
        self.vectors = np.load(directory / 'item_vectors.npy', mmap_mode='r')
        assert self.vectors.shape == (len(ids), DIMENSION) and len(self.index) == len(ids)
        self.lock = threading.Lock()

    def infer(self, history):
        # 输入约定：最近优先。与既有 queryv2 的种子均值归一化、MLP 残差投影一致。
        ids = list(dict.fromkeys(history))[:80]
        matched = [item for item in ids if item in self.index]
        if not matched:
            return {'embedding': [], 'matched_history_count': 0, 'query_source': 'no_in_vocabulary_history'}
        with self.lock:
            vectors = self.vectors[[self.index[item] for item in matched]]
            weights = np.power(.85, np.arange(len(matched), dtype=np.float64))
            mean = np.average(vectors.astype(np.float64), axis=0, weights=weights)
            norm = np.linalg.norm(mean)
            if norm <= 1e-9:
                return {'embedding': [], 'matched_history_count': len(matched), 'query_source': 'zero_seed_vector'}
            seed = (mean / norm).astype(np.float32)
            hidden = np.maximum(self.w1 @ seed + self.b1, 0)
            output = self.w2 @ hidden + self.b2 + seed
            norm = np.linalg.norm(output)
            if norm <= 1e-9 or not np.isfinite(output).all():
                raise ValueError('invalid_user_projection')
            return {'embedding': (output / norm).tolist(), 'matched_history_count': len(matched),
                    'query_source': 'trained_epoch5_seed_projection'}


class Handler(BaseHTTPRequestHandler):
    runtime = None

    def log_message(self, *_):
        pass

    def reply(self, code, body):
        encoded = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if self.path != '/health':
            return self.reply(404, {'error': 'not_found'})
        self.reply(200, {'status': 'UP', 'model_key': MODEL_KEY, 'dimension': DIMENSION,
                         'item_count': len(self.runtime.index), 'model_sha256': self.runtime.manifest['model_sha256']})

    def do_POST(self):
        if self.path != '/internal/model/two-tower/user-embedding':
            return self.reply(404, {'error': 'not_found'})
        try:
            data = json.loads(self.read_body())
            if not isinstance(data, dict):
                return self.reply(400, {'error': 'expected_json_object'})
            history = data.get('history_item_ids')
            if data.get('model_key') != MODEL_KEY or not isinstance(history, list) or len(history) > 100:
                return self.reply(400, {'error': 'invalid_model_or_history'})
            if any(not isinstance(item, str) or not item or len(item) > 128 for item in history):
                return self.reply(400, {'error': 'invalid_item_id'})
            result = self.runtime.infer(history)
            self.reply(200, {'model_key': MODEL_KEY, 'dimension': DIMENSION, **result})
        except (ValueError, TypeError, KeyError):
            self.reply(400, {'error': 'invalid_request'})

    def read_body(self):
        self.connection.settimeout(5)
        if self.headers.get('Transfer-Encoding', '').lower() != 'chunked':
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 32768:
                raise ValueError('invalid_body_size')
            return self.rfile.read(size)
        body = bytearray()
        for _ in range(1024):
            line = self.rfile.readline(128)
            size = int(line.split(b';', 1)[0].strip(), 16)
            if size == 0:
                for _ in range(32):
                    if self.rfile.readline(1024) == b'\r\n': return bytes(body)
                raise ValueError('invalid_trailers')
            if size < 0 or len(body) + size > 32768: raise ValueError('invalid_body_size')
            body.extend(self.rfile.read(size))
            if self.rfile.read(2) != b'\r\n': raise ValueError('invalid_chunk')
        raise ValueError('too_many_chunks')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', required=True)
    parser.add_argument('--host', default='172.21.0.1')
    parser.add_argument('--port', type=int, default=18117)
    args = parser.parse_args()
    Handler.runtime = Runtime(args.directory)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
