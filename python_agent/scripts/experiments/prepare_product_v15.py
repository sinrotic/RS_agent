"""为完整三塔训练预留未打开的滚动未来目标，排除全部既有评测用户。"""
from pathlib import Path
import prepare_product_v13 as preparation

if __name__=='__main__':
    preparation.ROOT=Path('/mnt/data/luo/remote_runs/product_v15_training')
    preparation.main(extra_previous=['product_v13_training/data/future_dev.jsonl','product_v13_training/data/sealed_future.jsonl',
                                     'product_v14_training/data/future_dev.jsonl','product_v14_training/data/sealed_future.jsonl'])
