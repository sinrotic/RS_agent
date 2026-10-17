import sys
from pathlib import Path
import numpy as np
import torch
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts/experiments'))
from evaluate_product_v7_catalog import exact_ranks,build_requests
from three_tower_residual import ResidualTowers


def test_streamed_exact_ranks_match_full_matrix_with_ties_and_history_masks():
    vectors=np.tile(np.eye(4,dtype='float32'),(5,1))
    requests=torch.tensor([[1.,0,0,0],[0,1.,0,0],[-1.,0,0,0]])
    targets=[0,1,4];histories=[[5,8],[6,9],[0,8]]
    scores=requests@torch.tensor(vectors).T
    expected=[]
    for i,(target,history) in enumerate(zip(targets,histories)):
        scores[i,history]=-torch.inf
        expected.append(int((scores[i]>=scores[i,target]).sum()))
    for block in [3,7,20]:
        actual,error=exact_ranks(requests,vectors,targets,histories,block)
        assert actual==expected and error==0
    excluded=[12]
    masked=scores.clone();masked[:,excluded]=-torch.inf
    actual,_=exact_ranks(requests,vectors,targets,histories,3,excluded)
    assert actual==[int((masked[i]>=masked[i,t]).sum()) for i,t in enumerate(targets)]


def test_expansion_keeps_missing_targets_and_cold_histories_in_denominator():
    torch.manual_seed(42);model=ResidualTowers(4,8,8,0).eval()
    vectors=np.tile(np.eye(4,dtype='float32'),(2,1))
    cohort={'dev':[{'old_target':-1,'target':5,'history_old':[],'history_full':[2]},
                   {'old_target':1,'target':1,'history_old':[0],'history_full':[0,4]}]}
    sem=[{'split':'valid','item_index':2}];q=np.array([[0,0,1,0]],dtype='float32')
    _,targets,_,positions,outputs=build_requests(model,vectors,cohort,sem,q,False)
    assert targets==[1,2] and outputs['dev/old_catalog']['ranks']==[0,0]
    _,targets,_,positions,outputs=build_requests(model,vectors,cohort,sem,q,True)
    assert targets==[1,5,1,2]
    assert ('dev/expanded_fixed_history',0) not in positions
    assert ('dev/expanded_full_history',0) in positions
