"""纠正开发查询门槛的1ULP误判；只按开发集选型，保留纠错前冻结与验收档案。"""
import hashlib,json,os,time
from pathlib import Path
import numpy as np
import torch
from product_v10_model import SequenceResidualTowers
from train_product_v10 import evaluate_rec
from train_product_v15 import select_full_epoch
from three_tower_residual import rows
from evaluate_product_v7_catalog import save
ROOT=Path('/mnt/data/luo/remote_runs/product_v15_training');BASE=ROOT.parent

def main():
    assert os.environ.get('CUDA_VISIBLE_DEVICES')=='1'
    torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.cuda.set_per_process_memory_fraction(.2);torch.backends.cuda.matmul.allow_tf32=False
    assert not (ROOT/'selection_boundary_audit.json').exists()
    assert not (ROOT/'final_validation.json').exists() and not (ROOT/'export').exists()
    result=json.loads((ROOT/'results.json').read_text());before=json.loads((ROOT/'selection.json').read_text());assert result['state']=='COMPLETE'
    base=result['baseline_semantic']['metrics'];count_floor=round(base['hit@10']*base['count'])-2
    float_floor=base['hit@10']-2/base['count'];classification=[];candidates=[]
    for e in result['epochs']:
        m=e['semantic']['metrics'];count=round(m['hit@10']*m['count']);eligible=count>=count_floor
        classification.append({'epoch':e['epoch'],'hit10_count':count,'floating_gate':m['hit@10']>=float_floor,'integer_gate':eligible})
        if eligible:candidates.append(e)
    assert any(x['floating_gate']!=x['integer_gate'] for x in classification),'只能针对已证实数值边界修复'
    chosen=select_full_epoch(result)
    # 在读取/输出任一封存指标前完成选型；保留纠错前记录，不能把封存重放称为全新验收。
    audit={'state':'CORRECTED_DEVELOPMENT_ONLY','reason':'开发语义允许少2条，88/347-2/347比86/347高一个浮点单位；整数计数恢复预定规则。',
           'baseline_hit10':round(base['hit@10']*base['count']),'minimum_hit10':count_floor,'classification':classification,
           'before_epoch':before['epoch'],'corrected_epoch':chosen['epoch'],'selection_uses_sealed_metrics':False,
           'sealed_computed_before_correction':True,'timestamp':time.time(),
           'limitation':'原训练已为epoch3计算一次同一1890封存；纠错后按开发规则选型再重放，不宣称新第二封存或只打开一次。'}
    for name in ['selection.json','results.json','trained_tower_audit.json','progress.json']:
        data=(ROOT/name).read_bytes();(ROOT/(name.removesuffix('.json')+'_before_boundary_correction.json')).write_bytes(data)
    save(ROOT/'selection_boundary_audit.json',audit)
    plan=json.loads((ROOT/'experiment_plan.json').read_text())
    save(ROOT/'selection.json',{'state':'FROZEN','selected':'full_joint_epoch_'+str(chosen['epoch']),'checkpoint':chosen['checkpoint'],
        'vectors':chosen['vectors'],'epoch':chosen['epoch'],'development':chosen['evaluation'],'semantic_development':chosen['semantic'],
        'rule':plan,'timestamp':time.time(),'selection_correction':audit})
    state=torch.load(chosen['checkpoint'],map_location='cpu',weights_only=True)
    source=torch.load(plan['initial_checkpoint'],map_location='cpu',weights_only=True)
    changed={n:any(not torch.equal(v,source['model'][k]) for k,v in state['model'].items() if k.startswith(n+'.')) for n in ['item','user','query']}
    assert all(changed.values());save(ROOT/'trained_tower_audit.json',{'state':'PASS','changed_towers':changed,'full_epochs_completed':3,'source_sha256':plan['initial_sha256']})
    model=SequenceResidualTowers(1024,256,763086,0,pooling='cohesion').cuda().eval();model.load_state_dict(state['model'])
    vectors=np.load(chosen['vectors'],mmap_mode='r');excluded={x['index'] for x in json.loads((BASE/'product_v7_expansion/data/text_audit.json').read_text())['ineligible']}
    candidate=evaluate_rec(model,vectors,{'sealed_future':rows(ROOT/'data/sealed_future.jsonl')},excluded)
    result.update(selected='full_joint_epoch_'+str(chosen['epoch']),selection_correction=audit)
    result['sealed']['candidate']=candidate;save(ROOT/'results.json',result)
    save(ROOT/'progress.json',{'state':'COMPLETE','selected':result['selected'],'full_epochs_completed':3,'rec_steps':62271,'semantic_steps':6227,'selection_correction':True})
    print('DEVELOPMENT_BOUNDARY_CORRECTED',audit,flush=True)

if __name__=='__main__':main()
