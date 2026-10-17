"""完整训练产物导出为连续商品索引；全部三塔权重来自完成整轮的选中检查点。"""
import hashlib,json,os
from pathlib import Path
import numpy as np
import torch
from evaluate_product_v7_catalog import save
ROOT=Path('/mnt/data/luo/remote_runs/product_v15_training');BASE=ROOT.parent;V7=BASE/'product_v7_expansion'
MODEL='product_three_tower_v15_full';COLLECTION='rs_agent_product_three_tower_v15_20261013'

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for part in iter(lambda:f.read(4194304),b''):h.update(part)
    return h.hexdigest()

def main():
    result=json.loads((ROOT/'results.json').read_text());selection=json.loads((ROOT/'selection.json').read_text())
    assert result['state']=='COMPLETE' and selection['state']=='FROZEN' and len(result['epochs'])==3
    assert json.loads((ROOT/'trained_tower_audit.json').read_text())['state']=='PASS'
    output=ROOT/'export';output.mkdir(exist_ok=False)
    state=torch.load(selection['checkpoint'],map_location='cpu',weights_only=True);plan=json.loads((ROOT/'experiment_plan.json').read_text())
    config={**state['config'],'data':str(BASE/'product_v9_training/data'),'semantic_data':str(BASE/'three_tower_dataset_v4/data'),
            'evaluation':str(ROOT/'data'),'output':str(output),'checkpoint':plan['initial_checkpoint'],
            'steps':state['rec_steps'],'semantic_steps':state['semantic_steps'],'learning_rates':plan['learning_rates'],
            'selected_epoch':selection['epoch'],'full_training_epochs_completed':3,'old_head_protection':0,'trained_towers':['item','user','query']}
    for stale in ['lr','query_lr','eval_every']:config.pop(stale,None)
    torch.save({'model':state['model'],'config':config},output/'model.pt')
    raw=np.load(selection['vectors'],mmap_mode='r');excluded={r['index'] for r in json.loads((V7/'data/text_audit.json').read_text())['ineligible']}
    target=np.lib.format.open_memmap(output/'item_vectors.npy',mode='w+',dtype='float32',shape=(len(raw)-len(excluded),1024));cursor=0
    for start in range(0,len(raw),8192):
        block=raw[start:start+8192];keep=np.asarray([start+i not in excluded for i in range(len(block))])
        chosen=np.asarray(block[keep]);assert np.isfinite(chosen).all() and np.max(abs(np.linalg.norm(chosen,axis=1)-1))<1e-4
        target[cursor:cursor+len(chosen)]=chosen;cursor+=len(chosen)
    assert cursor==763080;target.flush()
    os.link(V7/'export_candidate_v6/item_ids.jsonl',output/'item_ids.jsonl')
    # 原始词表含6个空商品，导出连续索引必须逐项与过滤后的原始ID对应。
    with (V7/'data/items.jsonl').open() as raw_ids,(output/'item_ids.jsonl').open() as compact_ids:
        checked=0
        for index,line in enumerate(raw_ids):
            if index in excluded:continue
            row=json.loads(next(compact_ids));raw_row=json.loads(line)
            assert row['index']==checked and row['item_id']==raw_row['item_id']
            checked+=1
        assert checked==cursor and next(compact_ids,None) is None
    base=(ROOT/'scripts/three_tower_residual.py').read_text();definitions=base[base.index('class Adapter'):base.index('def history_tensor')]
    seq=(ROOT/'scripts/product_v10_model.py').read_text();seq=seq[seq.index('class SequenceResidualTowers'):seq.index('def sample_hard_ids')]
    factory="\ndef create_model(config,item_count):\n    return SequenceResidualTowers(1024,config['hidden'],item_count,config['id_dim'],pooling=config.get('pooling','cohesion'))\n"
    (output/'model_definition.py').write_text('import torch\nfrom torch import nn\nimport torch.nn.functional as F\n\n'+definitions+seq+factory)
    manifest={'status':'EXPORTED_AWAITING_SERVING_VERIFICATION','dimension':1024,'candidate_count':cursor,'model_key':MODEL,
              'collection':COLLECTION,'pooling':'cohesion','input_history_order':'recent_first_http / chronological_training',
              'selected_epoch':selection['epoch'],'full_training_epochs_completed':3,'source_checkpoint':selection['checkpoint'],
              'trained_towers':['item','user','query'],'BGE_frozen':True,'protected_head_count':0,
              'output_hashes':{n:digest(output/n) for n in ['model.pt','item_vectors.npy','item_ids.jsonl','model_definition.py']}}
    save(output/'manifest.json',manifest);print('FULL_THREE_TOWER_EXPORTED',selection['epoch'],cursor,flush=True)

if __name__=='__main__':main()
