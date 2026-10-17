"""紧凑样本必须还原严格时间前缀，并将目标与全序列已知正例用于负例屏蔽。"""
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts/experiments'))
from train_product_v9 import compact_batch

def test_compact_rows_keep_strict_prefix_and_known_future_training_positives():
    items=np.array([10,11,12,13,20,21,22],dtype='int32')
    offsets=np.array([0,4,7],dtype='int64')
    # 11与12同一时间，目标12的严格过去只有10。
    examples=np.array([[0,2,1],[1,2,2]],dtype='int32')
    batch=compact_batch(examples,[1,0],items,offsets)
    assert batch==[{'target':22,'history':[20,21],'known_train_positives':[20,21,22]},
                   {'target':12,'history':[10],'known_train_positives':[10,11,12,13]}]
    assert all(r['target'] not in r['history'] for r in batch)

if __name__=='__main__':
    test_compact_rows_keep_strict_prefix_and_known_future_training_positives()
    print('PASS: compact samples preserve strict historical prefixes')
