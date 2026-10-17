"""从v10受控训练框架派生三个仅学习注意力的对照，保留冻结/恢复/负例契约。"""
from pathlib import Path
ROOT=Path('/mnt/data/luo/remote_runs/product_v11_training');V10=ROOT.parent/'product_v10_training'
def once(s,a,b):
    assert s.count(a)==1,(a,s.count(a));return s.replace(a,b,1)
def main():
    s=(V10/'scripts/train_product_v10.py').read_text().replace("ROOT=Path('/mnt/data/luo/remote_runs/product_v10_training')","ROOT=Path('/mnt/data/luo/remote_runs/product_v11_training')")
    s=once(s,'from product_v10_model import SequenceResidualTowers,sample_hard_ids,head_loss','from product_v10_model import sample_hard_ids,head_loss\nfrom product_v11_model import AttentionResidualTowers as SequenceResidualTowers')
    s=once(s,"while not (ROOT/'data/manifest.json').exists():time.sleep(5)","while not (ROOT/'data/manifest.json').exists() or not (ROOT/'initial.pt').exists():time.sleep(5)")
    s=once(s,"source=torch.load(V9/'initial.pt',map_location='cpu',weights_only=True)","source=torch.load(ROOT/'initial.pt',map_location='cpu',weights_only=True)")
    s=once(s,"order=np.random.default_rng(42).permutation(len(examples));", "examples=np.asarray(examples)[np.asarray(examples[:,2])>=3]\n    assert len(examples)>=512000\n    order=np.random.default_rng(42).permutation(len(examples));")
    s=once(s,"add_initial('mean');add_initial('decay08');add_initial('blend_recent');add_initial('cohesion');", "add_initial('attention_cohesion');")
    s=once(s,"model.load_state_dict(source['model']);model.requires_grad_(False);model.user.requires_grad_(True)","model.load_state_dict(source['model']);model.requires_grad_(False)\n        for key,param in model.user.named_parameters():param.requires_grad_(key.startswith('pool_'))")
    s=once(s,"optimizer=torch.optim.AdamW(model.user.parameters(),lr=5e-7,weight_decay=.01);", "learning_rate=2e-4 if name=='pool_high_random' else 5e-5\n        optimizer=torch.optim.AdamW([p for p in model.user.parameters() if p.requires_grad],lr=learning_rate,weight_decay=.01);")
    s=once(s,"'learning_rate':5e-7,'full_steps':total", "'learning_rate':learning_rate,'full_steps':total")
    start=s.index("    specs=[('mean_random'");end=s.index('    for spec in specs:',start)
    s=s[:start]+"    specs=[('pool_low_random','attention_cohesion',False,False),('pool_high_random','attention_cohesion',False,False),('pool_low_soft_hard','attention_cohesion',True,False)]\n"+s[end:]
    s=once(s,"model.load_state_dict(old['model'])","model.load_state_dict(old['model'],strict=False)")
    s=s.replace('五组负样本/位置衰减/头部损失对照','三组仅注意力对照').replace('固定商品/BGE/查询塔','固定商品/BGE/查询及用户MLP')
    compile(s,str(ROOT/'scripts/train_product_v11.py'),'exec');(ROOT/'scripts/train_product_v11.py').write_text(s)
    print('V11_THREE_ATTENTION_RUNS_READY')
if __name__=='__main__':main()
