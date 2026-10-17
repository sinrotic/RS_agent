"""冻结路线的历史回归；查询分支和商品向量严格未变时复用其既有查询回归。"""
import hashlib,json,os
from pathlib import Path
import torch
from prepare_product_v12 import stream,SOURCE
from evaluate_product_v14 import BASE,ROOT,V7,V4,evaluate,checks
from evaluate_product_v7_catalog import save

def main():
    assert os.environ.get('CUDA_VISIBLE_DEVICES')=='2'
    torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.cuda.set_per_process_memory_fraction(.2);torch.backends.cuda.matmul.allow_tf32=False
    selection=json.loads((ROOT/'selection.json').read_text());assert selection['state']=='FROZEN'
    assert not (ROOT/'final_validation.json').exists(),'冻结后只做一次验收，不重新选择'
    item_ids=[r['item_id'] for r in stream(V7/'data/items.jsonl')];mapping={s:i for i,s in enumerate(item_ids)}
    original_ids=item_ids[:203887]+json.loads((V4/'final_test/extra_history_ids.json').read_text())
    original=list(stream(V4/'final_test/confirmation_rows.jsonl'));users={r['user_hash'] for r in original};targets={}
    for r in stream(SOURCE/'canonical_interactions.test.jsonl'):
        if r['label_binary']!=1:continue
        uid=hashlib.sha256(r['user_id'].encode()).hexdigest()
        if uid not in users:continue
        v=(r['timestamp'],r['parent_asin'])
        if uid not in targets or v<targets[uid]:targets[uid]=v
    cohort=[]
    for r in original:
        t,iid=targets[r['user_hash']];assert t==r['target_ts']
        cohort.append({'user_hash':r['user_hash'],'old_target':r['target'],'target':mapping.get(iid,-1),
                      'history_old':[i for i in r['history'] if i<203887],
                      'history_full':[mapping[original_ids[i]] for i in r['history']]})
    ev=evaluate({'test':cohort});g=checks(ev)['test']
    # 固定商品、query权重、查询路由完全一致。保护规则只用于用户召回。
    reference=BASE/'product_v10_training';old=torch.load(reference/'initial_cohesion.pt',map_location='cpu',weights_only=True)
    selected=torch.load(selection['checkpoint'],map_location='cpu',weights_only=True)
    assert old['config']['pooling']==selected['config']['pooling']=='cohesion'
    assert all(torch.equal(v,old['model'][k]) for k,v in selected['model'].items())
    cached=json.loads((reference/'final_validation.json').read_text());models={}
    for name,key in [('online_actual','test/old_catalog'),('online_expanded','test/expanded_full_history'),('candidate','test/expanded_full_history')]:
        models[name]={key:ev[name]['test'],'semantic':cached['models'][name]['semantic']}
    g['semantic_vs_same_catalog']=models['candidate']['semantic']['metrics']['hit@10']>=models['online_expanded']['semantic']['metrics']['hit@10']
    out={'state':'PASS' if all(g.values()) else 'FAIL','models':models,'gate_checks':g,
         'numerical_proof':ev['numerical_proof'],'policy':selection['rule'],
         'query_regression_reuse':{'reason':'原模型全部张量bitwise相同，商品文件后续包验证SHA相同；查询路线未启用头部保护。',
                                   'source':str(reference/'final_validation.json'),'source_sha256':hashlib.sha256((reference/'final_validation.json').read_bytes()).hexdigest()}}
    save(ROOT/'final_validation.json',out)
    print('GUARDED_HISTORICAL',out['state'],g,flush=True)
    for n,v in models.items():print(n,next(iter(v.values()))['metrics'],flush=True)

if __name__=='__main__':main()
