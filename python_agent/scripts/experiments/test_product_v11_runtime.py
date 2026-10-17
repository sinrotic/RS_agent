"""实际NumPy CPU注意力与训练前向一致性，包括非零学习权重和最近优先。"""
import hashlib,json,tempfile
from pathlib import Path
import numpy as np
import torch
from product_v11_model import AttentionResidualTowers
from product_residual_runtime import Runtime
def main():
    torch.set_num_threads(1);torch.manual_seed(42)
    with tempfile.TemporaryDirectory(prefix='product-v11-runtime-') as tmp:
        root=Path(tmp);vectors=torch.nn.functional.normalize(torch.randn(50,16),dim=-1).numpy()
        np.save(root/'item_vectors.npy',vectors)
        (root/'item_ids.jsonl').write_text(''.join(json.dumps({'index':i,'item_id':str(i)})+'\n' for i in range(50)))
        model=AttentionResidualTowers(16,8,50,0).eval()
        with torch.no_grad():
            model.user.pool_score.weight.normal_(0,.1);model.user.pool_recency.fill_(.2)
            model.user.layers[2].weight.normal_(0,.05);model.user.layers[2].bias.normal_(0,.03)
        torch.save({'model':model.state_dict(),'config':{'hidden':8,'id_dim':0,'history_half_life_days':0,'pooling':'attention_cohesion'}},root/'model.pt')
        hashes={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in ['model.pt','item_vectors.npy','item_ids.jsonl']}
        (root/'manifest.json').write_text(json.dumps({'dimension':16,'output_hashes':hashes}))
        runtime=Runtime(root);errors=[]
        for length in [1,2,3,7,20,50]:
            history=[str(i) for i in reversed(range(length))]
            expected=model.encode_user(torch.tensor(vectors[:length])[None,:],torch.ones(1,length)).detach().numpy()[0]
            actual=np.asarray(runtime.infer(history)['embedding']);errors.append(float(np.max(np.abs(expected-actual))))
            np.testing.assert_allclose(actual,expected,atol=3e-6)
        np.testing.assert_allclose(runtime.infer(['2','2','unknown','1','0'])['embedding'],runtime.infer(['2','1','0'])['embedding'],atol=3e-6)
        assert runtime.infer(['unknown'])['embedding']==[]
    print('PASS_CPU_ATTENTION_RUNTIME',max(errors))
if __name__=='__main__':main()
