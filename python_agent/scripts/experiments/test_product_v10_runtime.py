"""真实CPU运行时与训练聚合一致性；验证最近优先、去重及未知商品处理。"""
import hashlib,json,tempfile
from pathlib import Path
import numpy as np
import torch
from product_v10_model import SequenceResidualTowers
from product_residual_runtime import Runtime
def main():
    torch.set_num_threads(1);torch.manual_seed(42)
    with tempfile.TemporaryDirectory(prefix='product-v10-runtime-') as tmp:
        root=Path(tmp);vectors=np.array([[1.,0.],[0.,1.],[.6,.8]],dtype='float32')
        np.save(root/'item_vectors.npy',vectors)
        (root/'item_ids.jsonl').write_text(''.join(json.dumps({'index':i,'item_id':str(i)})+'\n' for i in range(3)))
        for pooling in ['mean','decay08','blend_recent','cohesion']:
            model=SequenceResidualTowers(2,4,3,0,pooling=pooling).eval()
            torch.save({'model':model.state_dict(),'config':{'hidden':4,'id_dim':0,'history_half_life_days':0,'pooling':pooling}},root/'model.pt')
            hashes={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in ['model.pt','item_vectors.npy','item_ids.jsonl']}
            (root/'manifest.json').write_text(json.dumps({'dimension':2,'output_hashes':hashes}))
            runtime=Runtime(root)
            for history in [['0','1','2'],['2','1'],['1']]:
                actual=runtime.infer(history)['embedding']
                chronological=list(reversed([int(i) for i in history]))
                expected=model.encode_user(torch.tensor(vectors[chronological])[None,:],torch.ones(1,len(history))).detach().numpy()[0]
                np.testing.assert_allclose(actual,expected,atol=3e-6)
            np.testing.assert_allclose(runtime.infer(['2','2','unknown','1'])['embedding'],runtime.infer(['2','1'])['embedding'],atol=3e-6)
            assert runtime.infer(['unknown'])['embedding']==[]
    print('PASS: mean/decay/blend training and CPU runtime match, recent-first/dedup/unknown verified')
if __name__=='__main__':main()
