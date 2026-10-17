"""头部保护路线预留独立滚动验收；不读取其他轮的效果选参数。"""
from pathlib import Path
import prepare_product_v13 as preparation

if __name__=='__main__':
    preparation.ROOT=Path('/mnt/data/luo/remote_runs/product_v14_training')
    preparation.main(extra_previous=['product_v13_training/data/future_dev.jsonl','product_v13_training/data/sealed_future.jsonl'])
