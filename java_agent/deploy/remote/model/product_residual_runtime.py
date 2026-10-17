"""已导出商品残差召回的 CPU 用户塔；与训练前向一致。"""
import argparse
import hashlib
import json
from pathlib import Path
import threading
from http.server import ThreadingHTTPServer
import numpy as np
import torch
import two_tower_runtime as http_contract


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(4*1024*1024),b''):h.update(chunk)
    return h.hexdigest()


class Runtime:
    def __init__(self,directory):
        directory=Path(directory)
        self.manifest=json.loads((directory/'manifest.json').read_text())
        for name in ['model.pt','item_vectors.npy','item_ids.jsonl']:
            if digest(directory/name)!=self.manifest['output_hashes'][name]:raise ValueError('artifact checksum mismatch')
        checkpoint=torch.load(directory/'model.pt',map_location='cpu',weights_only=True)
        config=checkpoint['config']
        if config['id_dim'] or config['history_half_life_days']:
            raise ValueError('unsupported user forward')
        state=checkpoint['model']
        self.w1=state['user.layers.0.weight'].numpy();self.b1=state['user.layers.0.bias'].numpy()
        self.w2=state['user.layers.2.weight'].numpy();self.b2=state['user.layers.2.bias'].numpy()
        self.query_weights=[state['query.layers.'+name].numpy() for name in ['0.weight','0.bias','2.weight','2.bias']]
        dimension=self.manifest['dimension']
        if self.w1.shape!=(config['hidden'],dimension) or self.w2.shape!=(dimension,config['hidden']):raise ValueError('invalid weight shape')
        if not all(np.isfinite(v).all() for v in [self.w1,self.b1,self.w2,self.b2]):raise ValueError('nonfinite weights')
        items=[json.loads(line) for line in (directory/'item_ids.jsonl').open()]
        if [r['index'] for r in items]!=list(range(len(items))):raise ValueError('item index mismatch')
        self.index={r['item_id']:r['index'] for r in items}
        self.vectors=np.load(directory/'item_vectors.npy',mmap_mode='r')
        if self.vectors.shape!=(len(self.index),dimension):raise ValueError('vector shape mismatch')
        self.manifest['model_sha256']=self.manifest['output_hashes']['model.pt']
        self.lock=threading.Lock()

    def infer(self,history):
        # 接口约定最近优先；均匀聚合，没有旧queryv2的时间衰减和均值预归一化。
        selected=list(dict.fromkeys(history))[:50]
        matched=[self.index[i] for i in selected if i in self.index]
        if not matched:return {'embedding':[],'matched_history_count':0,'query_source':'no_in_vocabulary_history'}
        with self.lock:
            mean=np.asarray(self.vectors[matched],dtype=np.float32).mean(axis=0)
            output=mean+self.w2@np.maximum(self.w1@mean+self.b1,0)+self.b2
            norm=np.linalg.norm(output)
            if not np.isfinite(output).all() or norm<=1e-9:raise ValueError('invalid user projection')
            return {'embedding':(output/norm).tolist(),'matched_history_count':len(matched),
                    'query_source':'product_residual_uniform_history_v4'}

    def project_query(self,embedding):
        vector=np.asarray(embedding,dtype=np.float32)
        if vector.shape!=(self.manifest['dimension'],) or not np.isfinite(vector).all():raise ValueError('invalid query vector')
        norm=np.linalg.norm(vector)
        if norm<=1e-9:raise ValueError('zero query vector')
        vector=vector/norm
        w1,b1,w2,b2=self.query_weights
        with self.lock:output=vector+w2@np.maximum(w1@vector+b1,0)+b2
        norm=np.linalg.norm(output)
        if not np.isfinite(output).all() or norm<=1e-9:raise ValueError('invalid query projection')
        return (output/norm).tolist()


class Handler(http_contract.Handler):
    def do_POST(self):
        if self.path!='/internal/model/product/query-embedding':return super().do_POST()
        try:
            data=json.loads(self.read_body())
            if not isinstance(data,dict) or data.get('model_key')!=http_contract.MODEL_KEY:raise ValueError('invalid model')
            vector=self.runtime.project_query(data['embedding'])
            self.reply(200,{'model_key':http_contract.MODEL_KEY,'embedding':vector,'dimension':len(vector)})
        except (ValueError,TypeError,KeyError):self.reply(400,{'error':'invalid_request'})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',required=True)
    p.add_argument('--model-key',required=True);p.add_argument('--host',default='172.21.0.1')
    p.add_argument('--port',type=int,default=18120);args=p.parse_args()
    torch.set_num_threads(1)
    runtime=Runtime(args.directory)
    http_contract.MODEL_KEY=args.model_key
    http_contract.DIMENSION=runtime.manifest['dimension']
    Handler.runtime=runtime
    ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()
