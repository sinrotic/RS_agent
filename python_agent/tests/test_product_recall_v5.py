import sys,random
from pathlib import Path
import torch
import torch.nn.functional as F
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts/experiments'))
from product_recall_v5 import AttentionTowers,candidate_ids,epoch_indices
from three_tower_residual import ResidualTowers

def test_shuffle_visits_every_row_once_and_changes_epoch():
    a=epoch_indices(103,42,1,'shuffle');b=epoch_indices(103,42,2,'shuffle')
    assert sorted(a)==list(range(103)) and len(set(a))==103 and a!=b
    assert a==epoch_indices(103,42,1,'shuffle')

def test_mixed_negatives_mask_all_known_positives_and_deduplicate():
    batch=[{'target':1,'known_train_positives':[1,2,3]},{'target':2,'known_train_positives':[2,4]}]
    cats=['a']*40;pools={'a':list(range(40))}
    for mode in ['random','mixed']:
        result=candidate_ids(batch,random.Random(42),40,15,mode,cats,pools)
        for row,ids in zip(batch,result):
            assert ids[0]==row['target'] and len(ids)==len(set(ids))==16
            assert not set(ids[1:]) & set(row['known_train_positives'])

def test_attention_starts_as_mean_ignores_padding_and_learns():
    torch.manual_seed(42);m=AttentionTowers(16,8,10)
    vectors=F.normalize(torch.randn(2,4,16),dim=-1);mask=torch.tensor([[1.,1.,0.,0.],[1.,1.,1.,1.]])
    expected=F.normalize((vectors*mask.unsqueeze(-1)).sum(1)/mask.sum(1,keepdim=True),dim=-1)
    actual=m.encode_user(vectors,mask);assert torch.allclose(actual,expected,atol=1e-6)
    changed=vectors.clone();changed[0,2:]=1000;assert torch.allclose(actual,m.encode_user(changed,mask))
    (-actual[:,0].sum()).backward();assert m.attention[-1].weight.grad.abs().sum()>0
    optimizer=torch.optim.SGD(m.parameters(),lr=.1);optimizer.step()
    assert not torch.allclose(m.encode_user(vectors,mask),expected)

def test_attention_initialization_preserves_shared_tower_seed():
    torch.manual_seed(42);a=ResidualTowers(16,8,10)
    torch.manual_seed(42);b=AttentionTowers(16,8,10)
    for k,v in a.state_dict().items():assert torch.equal(v,b.state_dict()[k])

def test_paired_report_counts_missing_targets_as_misses_and_direction_is_treatment_minus_control():
    from finish_product_v5_comparison import paired
    assert paired([0,200,1,20],[1,2,0,30])['hit100_delta']==.25
    result=paired([1,0,200],[1,0,200])
    assert result['hit100_delta']==0 and result['paired_user_95pct']==[0,0]

def test_completed_epoch_resume_restores_optimizer_and_next_shuffle_order():
    import json,os,subprocess,tempfile,numpy as np
    script=Path(__file__).parents[1]/'scripts/experiments/product_recall_v5.py'
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);data=root/'data';data.mkdir()
        np.save(data/'item_features.npy',np.random.default_rng(42).normal(size=(10,16)).astype('float32'))
        samples=[{'user_hash':str(i),'history':[0,1],'target':i,'known_train_positives':[0,1,i]} for i in range(2,10)]
        for name,values in [('rec_train.jsonl',samples),('rec_valid.jsonl',samples[:2]),('items.jsonl',[{'index':i,'category':'x'} for i in range(10)])]:
            (data/name).write_text(''.join(json.dumps(row)+'\n' for row in values))
        def run(name,epochs,extra=()):
            subprocess.run([sys.executable,str(script),'--data',str(data),'--output',str(root/name),'--epochs',str(epochs),'--batch-size','3','--negatives','3',*extra],check=True,capture_output=True,env={**os.environ,'CUDA_VISIBLE_DEVICES':'','OMP_NUM_THREADS':'2','OPENBLAS_NUM_THREADS':'2'})
        run('full',2);run('first',1);run('resumed',2,['--resume-checkpoint',str(root/'first/last.pt')])
        a=torch.load(root/'full/last.pt',weights_only=True);b=torch.load(root/'resumed/last.pt',weights_only=True)
        assert a['steps']==b['steps']==6
        for key in a['model']:assert torch.equal(a['model'][key],b['model'][key])
        assert len(json.loads((root/'resumed/results.json').read_text())['epochs'])==2
