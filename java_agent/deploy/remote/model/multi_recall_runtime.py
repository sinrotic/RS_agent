#!/usr/bin/env python3
"""按历史种子/用户/类目索引检索离线产物，不在请求中扫描 JSONL。"""
import argparse
import json
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SOURCES = ('itemcf_weak', 'itemcf_strong', 'swing_recall', 'usercf_recall', 'category', 'popular')


class Runtime:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.manifest = json.loads((self.directory / 'serving-manifest.json').read_text())
        assert self.manifest['status'] == 'PASS' and set(SOURCES) <= self.manifest['sources'].keys()
        with closing(sqlite3.connect(f'file:{self.directory / "candidates.sqlite"}?mode=ro', uri=True)) as db:
            db.execute('SELECT source FROM candidates LIMIT 1').fetchone()
        self.capacity = threading.BoundedSemaphore(8)

    def recall(self, request):
        user = request.get('profile_user_id', '')
        history = request.get('history_item_ids', [])
        sources = request.get('sources', list(SOURCES))
        limit = request.get('limit', 80)
        if not isinstance(user, str) or len(user) > 128 or not isinstance(history, list) or len(history) > 80:
            raise ValueError('invalid profile/history')
        if any(not isinstance(i, str) or not i or len(i) > 128 for i in history): raise ValueError('invalid item')
        if not isinstance(sources, list) or any(s not in SOURCES for s in sources): raise ValueError('invalid source')
        if not isinstance(limit, int) or not 1 <= limit <= 120: raise ValueError('invalid limit')
        history = list(dict.fromkeys(history))
        excluded = set(history)
        result = {}
        if not self.capacity.acquire(timeout=.1): raise RuntimeError('busy')
        try:
            with closing(sqlite3.connect(f'file:{self.directory / "candidates.sqlite"}?mode=ro&immutable=1', uri=True)) as db:
                db.execute('PRAGMA cache_size=-8192')
                def lookup(source, bucket, size):
                    return db.execute('SELECT item,score FROM candidates WHERE source=? AND bucket=? ORDER BY rank,item LIMIT ?',
                                      (source, bucket, size)).fetchall()
                def user_list(source):
                    row = db.execute('SELECT payload FROM user_lists WHERE source=? AND user=?', (source,user)).fetchone()
                    return json.loads(row[0]) if row else []
                for source in dict.fromkeys(sources):
                    hits = []
                    if source in ('itemcf_weak', 'itemcf_strong', 'swing_recall') and len(history) >= 2:
                        for rank, seed in enumerate(history[:10]):
                            decay = 1.0 if source == 'swing_recall' else .85**rank
                            hits.extend((item,score * decay) for item,score in lookup(source,seed,40))
                    elif source == 'usercf_recall' and len(history) >= 3:
                        hits = user_list(source)
                    elif source == 'category':
                        for rank,bucket in enumerate(user_list('category_profile')[:5]):
                            hits.extend((item,score/(rank+1)) for item,score in lookup(source,bucket,40))
                    elif source == 'popular':
                        hits = lookup(source,'global',120)
                    merged = {}
                    for item,score in hits:
                        if item not in excluded: merged[item] = max(score,merged.get(item,float('-inf')))
                    result[source] = [{'item_id': item, 'score': score} for item,score in
                                      sorted(merged.items(),key=lambda pair:(-pair[1],pair[0]))[:limit]]
            return {'version': self.manifest['version'], 'sources': result}
        finally:
            self.capacity.release()


class Handler(BaseHTTPRequestHandler):
    runtime = None
    def log_message(self, *_): pass
    def reply(self, code, value):
        body = json.dumps(value).encode()
        self.send_response(code); self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path != '/health': return self.reply(404,{'error':'not_found'})
        if not (self.runtime.directory / 'candidates.sqlite').is_file():
            return self.reply(503,{'status':'DOWN'})
        self.reply(200,{'status':'UP','version':self.runtime.manifest['version'],
                       'sources':{k:v['candidate_count'] for k,v in self.runtime.manifest['sources'].items()}})
    def do_POST(self):
        if self.path != '/internal/recall/multi': return self.reply(404,{'error':'not_found'})
        try:
            self.connection.settimeout(5)
            size = int(self.headers.get('Content-Length','0'))
            if self.headers.get('Transfer-Encoding') or not 0 < size <= 32768: raise ValueError('invalid body size')
            request = json.loads(self.rfile.read(size))
            if not isinstance(request,dict): raise ValueError('invalid body')
            self.reply(200,self.runtime.recall(request))
        except (ValueError,TypeError): self.reply(400,{'error':'invalid_request'})
        except (RuntimeError,sqlite3.Error): self.reply(503,{'error':'recall_unavailable'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory',required=True)
    parser.add_argument('--host',default='172.21.0.1')
    parser.add_argument('--port',type=int,default=18118)
    args = parser.parse_args()
    Handler.runtime = Runtime(args.directory)
    ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()
