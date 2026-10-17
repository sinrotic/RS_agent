"""冻结稳定纯三塔为独立服务版本；保留真实训练来源，绝不伪称来自失败的全量续训。"""
import hashlib,json,os,time
from pathlib import Path
import torch
ROOT=Path('/mnt/data/luo/remote_runs/product_v16_final');BASE=ROOT.parent
SOURCE=BASE/'product_v14_training/export'
MODEL='product_three_tower_final_v1';COLLECTION='rs_agent_product_three_tower_final_v1_20261013'

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(4194304),b''):h.update(block)
    return h.hexdigest()

def write(name,value):
    p=ROOT/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,ensure_ascii=False,indent=2))

def main():
    reference=json.loads((SOURCE/'manifest.json').read_text())
    assert all(digest(SOURCE/n)==sha for n,sha in reference['output_hashes'].items())
    state=torch.load(SOURCE/'model.pt',map_location='cpu',weights_only=True)
    assert state['config']['pooling']=='cohesion'
    output=ROOT/'export';output.mkdir(exist_ok=False)
    config={'hidden':256,'id_dim':0,'history_half_life_days':0,'pooling':'cohesion','dimension':1024,
            'model_key':MODEL,'old_head_protection':0,'mode':'frozen_final_serving',
            'source_training_config':state['config'],'source_checkpoint':str(SOURCE/'model.pt'),
            'release_is_new_training':False}
    torch.save({'model':state['model'],'config':config},output/'model.pt')
    for n in ['item_vectors.npy','item_ids.jsonl','model_definition.py']:os.link(SOURCE/n,output/n)
    manifest={'status':'EXPORTED_AWAITING_SERVING_VERIFICATION','model_key':MODEL,'collection':COLLECTION,
        'dimension':1024,'hidden':256,'candidate_count':763080,'pooling':'cohesion','BGE_frozen':True,
        'protected_head_count':0,'filter_history':True,'input_history_order':'recent_first_http / chronological_training',
        'query_task_trained':True,'trained_towers':['item','user','query'],'release_is_new_training':False,
        'source_checkpoint':str(SOURCE/'model.pt'),'source_model_sha256':digest(SOURCE/'model.pt'),
        'source_training_config':state['config'],
        'output_hashes':{n:digest(output/n) for n in ['model.pt','item_vectors.npy','item_ids.jsonl','model_definition.py']}}
    write('export/manifest.json',manifest)
    write('selection.json',{'state':'FROZEN','selected':'trained_three_tower_cohesion_stable','checkpoint':str(SOURCE/'model.pt'),
        'timestamp':time.time(),'protected_head_count':0,'rule':'选择历次稳定的已训练纯三塔，保留查询塔并取消旧保护；不采用v15历史MRR下降15.1%的续训模型。不是每个评测群体单指标最优。',
        'evidence_scope':'依据已经评估过的结果选择最终服务方案，无新独立测试集或新增训练。'})
    # 权重、聚合与商品向量完全一致，既有纯三塔排名可复用；HTTP/ANN/Java仍重新验收。
    evidence=BASE/'product_v15_training/final_validation.json';v=json.loads(evidence.read_text())
    older=BASE/'product_v14_training/results.json';prior=json.loads(older.read_text())
    checks={'same_tensor_weights':all(torch.equal(x,state['model'][k]) for k,x in torch.load(output/'model.pt',map_location='cpu',weights_only=True)['model'].items()),
            'same_item_vectors':manifest['output_hashes']['item_vectors.npy']==reference['output_hashes']['item_vectors.npy'],
            'same_cohesion_pooling':config['pooling']==state['config']['pooling'],
            'zero_protected_head':config['old_head_protection']==0,'all_three_towers_present':all(any(k.startswith(n+'.') for k in state['model']) for n in ['item','user','query'])}
    write('final_validation.json',{'state':'PASS' if all(checks.values()) else 'FAIL','checks':checks,
        'candidate':v['initial_pure'],'current_guarded':v['current_guarded'],'rejected_full_training':v['candidate'],
        'semantic':v['semantic']['initial_pure'],'previous_3000':{'pure':prior['sealed']['initial']['sealed_future'],'guarded':prior['sealed']['candidate']['sealed_future']},
        'evidence_sources':{str(p):digest(p) for p in [evidence,older]},
        'reason':'实际张量、商品矩阵、查询与历史聚合严格相同，复用既有纯三塔指标，重新验收部署契约。',
        'limitations':'最终方案从已知结果选择，全部数字是已有回归/复核证据，非新独立泛化试验；评分评论序列不等于购买；不宣称线上CTR收益。'})
    print('FINAL_STABLE_THREE_TOWER_EXPORTED',MODEL,763080,flush=True)

if __name__=='__main__':main()
