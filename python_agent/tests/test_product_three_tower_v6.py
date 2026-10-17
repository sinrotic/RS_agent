import random,sys
from pathlib import Path
import torch
import torch.nn.functional as F
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts/experiments'))
from product_three_tower_v6 import parameter_groups,contrastive
from three_tower_residual import ResidualTowers


def test_query_calibration_keeps_recommendation_parameters_exactly_fixed():
    torch.manual_seed(42)
    m=ResidualTowers(16,8,160,0)
    initial={k:v.clone() for k,v in m.state_dict().items()}
    features=F.normalize(torch.randn(160,16),dim=-1);queries=F.normalize(torch.randn(2,16),dim=-1)
    optimizer=torch.optim.AdamW(parameter_groups(m,'query',1e-3,1e-3))
    loss=contrastive(m,features,[{'target':3,'known_train_positives':[3,4],'query_index':0}],random.Random(42),'semantic',queries)
    loss.backward();optimizer.step()
    assert all(torch.equal(v,initial[k]) for k,v in m.state_dict().items() if not k.startswith('query.'))
    assert any(not torch.equal(v,initial[k]) for k,v in m.state_dict().items() if k.startswith('query.'))


def test_joint_tasks_only_share_item_gradients():
    torch.manual_seed(42);m=ResidualTowers(16,8,160,0)
    parameter_groups(m,'joint',1e-3,1e-3)
    features=F.normalize(torch.randn(160,16),dim=-1);queries=F.normalize(torch.randn(2,16),dim=-1)
    contrastive(m,features,[{'target':3,'known_train_positives':[0,1,3],'history':[0,1]}],random.Random(42),'rec').backward()
    assert all(p.grad is None for p in m.query.parameters())
    assert m.user.layers[-1].weight.grad.abs().sum()>0 and m.item.layers[-1].weight.grad.abs().sum()>0
    m.zero_grad(set_to_none=True)
    contrastive(m,features,[{'target':3,'known_train_positives':[3],'query_index':0}],random.Random(42),'semantic',queries).backward()
    assert all(p.grad is None for p in m.user.parameters())
    assert m.query.layers[-1].weight.grad.abs().sum()>0 and m.item.layers[-1].weight.grad.abs().sum()>0
