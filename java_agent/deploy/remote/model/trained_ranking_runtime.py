#!/usr/bin/env python3
"""COLD/DeepFM 真参数推理与训练历史特征查询，标准库 CPU 运行时。"""
import argparse
from contextlib import closing
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import sqlite3
import threading

FEATURES=sorted(['has_item_train_history','has_user_train_history','score_item_train_positive_count_log1p',
    'score_item_train_positive_user_count_log1p','score_user_train_distinct_item_count_log1p','score_user_train_positive_count_log1p'])


def features(user_counts,item_counts):
    u,du=user_counts;i,di=item_counts
    return {'has_item_train_history':float(i>0),'has_user_train_history':float(u>0),
        'score_item_train_positive_count_log1p':round(math.log1p(i),10),
        'score_item_train_positive_user_count_log1p':round(math.log1p(di),10),
        'score_user_train_distinct_item_count_log1p':round(math.log1p(du),10),
        'score_user_train_positive_count_log1p':round(math.log1p(u),10)}


def cold_score(values,model):
    return model['bias']+sum(model['weights'].get(k,0)*v for k,v in values.items())


def deepfm_score(values,model):
    names=model['feature_names']
    x=[values[n] if abs(values[n])<=10 else math.copysign(math.log1p(abs(values[n])),values[n]) for n in names]
    linear=model['bias']+sum(model['linear_weights'].get(n,0)*v for n,v in zip(names,x))
    sums=[0.]*len(model['fm_factors'][names[0]]);squares=[0.]*len(sums)
    for name,value in zip(names,x):
        for k,factor in enumerate(model['fm_factors'][name]):
            product=factor*value;sums[k]+=product;squares[k]+=product*product
    fm=.5*sum(total*total-square for total,square in zip(sums,squares))
    hidden=[max(0.,sum(w*v for w,v in zip(weights,x))+bias) for weights,bias in zip(model['deep_weights'],model['deep_bias'])]
    return linear+fm+sum(w*v for w,v in zip(model['deep_output'],hidden))


def sigmoid(value):
    return 1. if value>=35 else 0. if value<=-35 else 1/(1+math.exp(-value))


def keep_with_protection(rows,limit,protected):
    selected=[r for r in rows if r['item_id'] in protected]
    if len(selected)>limit:raise ValueError('protected candidates exceed budget')
    selected+= [r for r in rows if r['item_id'] not in protected][:limit-len(selected)]
    ids={r['item_id'] for r in selected}
    return [r for r in rows if r['item_id'] in ids]


class Runtime:
    def __init__(self,directory):
        self.root=Path(directory)
        self.manifest=json.loads((self.root/'serving-manifest.json').read_text())
        assert self.manifest['status']=='PASS'
        models=[]
        for name in ['cold_model.json','deepfm_model.json']:
            path=self.root/name
            assert hashlib.sha256(path.read_bytes()).hexdigest()==self.manifest['models'][name]['sha256']
            model=json.loads(path.read_text());assert sorted(model['feature_names'])==FEATURES
            assert model['training']['status']=='trained'
            models.append(model)
        self.cold,self.deepfm=models
        assert self.cold['model_type']=='cold_pointwise_logistic_ranker_v1'
        assert self.deepfm['model_type']=='deepfm_feature_cross_ranker_v1'
        assert len(self.deepfm['deep_weights'])==len(self.deepfm['deep_bias'])==len(self.deepfm['deep_output'])
        assert all(len(row)==len(FEATURES) for row in self.deepfm['deep_weights'])
        self.capacity=threading.BoundedSemaphore(8)

    def rank(self,request):
        user=request.get('profile_user_id','');ids=request.get('candidate_item_ids',[])
        protected=request.get('protected_item_ids',[]);stage=request.get('stage','chain')
        coarse_limit=request.get('coarse_limit',200);fine_limit=request.get('fine_limit',96)
        if not isinstance(user,str) or len(user)>128 or not isinstance(ids,list) or not 0<len(ids)<=500:raise ValueError('invalid ids')
        if any(not isinstance(i,str) or not i or len(i)>128 for i in ids):raise ValueError('invalid item')
        if stage not in ['chain','coarse','fine'] or not isinstance(protected,list) or len(protected)>96:raise ValueError('invalid stage/protection')
        if any(i not in ids for i in protected):raise ValueError('protected item outside candidates')
        if type(coarse_limit)!=int or type(fine_limit)!=int or not 1<=coarse_limit<=500 or not 1<=fine_limit<=500:raise ValueError('invalid limits')
        ids=list(dict.fromkeys(ids));protected=set(protected)
        if not self.capacity.acquire(timeout=.1):raise RuntimeError('busy')
        try:
            with closing(sqlite3.connect(f'file:{self.root}/features.sqlite?mode=ro&immutable=1',uri=True)) as db:
                db.execute('PRAGMA cache_size=-4096')
                user_counts=db.execute('SELECT n,distinct_n FROM user_stats WHERE id=?',(user,)).fetchone() or (0,0)
                stats=dict((row[0],row[1:]) for row in db.execute('SELECT id,n,distinct_n FROM item_stats WHERE id IN ('+','.join('?'*len(ids))+')',ids))
            rows=[]
            for item in ids:
                values=features(user_counts,stats.get(item,(0,0)))
                rows.append({'item_id':item,'cold_score':cold_score(values,self.cold),'features':values})
            rows.sort(key=lambda r:(-r['cold_score'],r['item_id']))
            coarse=rows if stage=='fine' else keep_with_protection(rows,min(coarse_limit,len(rows)),protected)
            if stage=='coarse':
                selected=[{**r,'score':sigmoid(r['cold_score'])} for r in coarse]
            else:
                for row in coarse:
                    row['deepfm_logit']=deepfm_score(row['features'],self.deepfm)
                    row['score']=sigmoid(row['deepfm_logit'])
                coarse.sort(key=lambda r:(-r['deepfm_logit'],r['item_id']))
                selected=keep_with_protection(coarse,min(fine_limit,len(coarse)),protected)
            assert all(math.isfinite(row['score']) and math.isfinite(row['cold_score']) for row in selected)
            if not request.get('include_features',False):
                selected=[{k:v for k,v in row.items() if k!='features'} for row in selected]
            return {'version':self.manifest['version'],'feature_version':self.manifest['feature_version'],
                'feature_cutoff_epoch_ms':self.manifest['feature_cutoff_epoch_ms'],
                'stage':stage,'coarse_input_count':len(rows),'coarse_output_count':len(coarse),
                'fine_output_count':0 if stage=='coarse' else len(selected),
                'known_item_count':len(stats),'known_user':bool(user_counts[0]),'items':selected}
        finally:self.capacity.release()


class Handler(BaseHTTPRequestHandler):
    runtime=None
    def log_message(self,*_):pass
    def reply(self,status,value):
        body=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if self.path!='/health':return self.reply(404,{'error':'not_found'})
        self.reply(200,{'status':'UP','version':self.runtime.manifest['version'],
            'models':self.runtime.manifest['models'],'feature_users':self.runtime.manifest['users'],'feature_items':self.runtime.manifest['items']})
    def do_POST(self):
        if self.path!='/internal/ranking/cold-deepfm':return self.reply(404,{'error':'not_found'})
        try:
            self.connection.settimeout(5);size=int(self.headers.get('Content-Length',0))
            if self.headers.get('Transfer-Encoding') or not 0<size<=131072:raise ValueError('invalid body')
            request=json.loads(self.rfile.read(size))
            if not isinstance(request,dict):raise ValueError('invalid body')
            self.reply(200,self.runtime.rank(request))
        except (ValueError,TypeError):self.reply(400,{'error':'invalid_request'})
        except (sqlite3.Error,RuntimeError):self.reply(503,{'error':'ranking_unavailable'})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--directory',required=True)
    parser.add_argument('--host',default='172.21.0.1');parser.add_argument('--port',type=int,default=18119)
    args=parser.parse_args();Handler.runtime=Runtime(args.directory)
    ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()
