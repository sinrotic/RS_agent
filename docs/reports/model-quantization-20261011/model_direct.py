"""模型侧 90 个直连请求及六个内容属性回归，不冒充实际业务验收。"""
import argparse
import json
from pathlib import Path

from benchmark_core import main
from replay import append_replay
from steady import append_steady
from quality import run as run_quality

if __name__ == '__main__':
    main()
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    append_replay(args.output, args.base_url)
    append_steady(args.output, args.base_url)
    data = json.loads(args.output.read_text())
    data['model_base'] = args.base_url
    data['scope'] = 'model_direct_only'
    data['fixed_quality'] = run_quality(args.base_url)
    assert len(data['fixed_quality']) == 6 and all(row['passed'] for row in data['fixed_quality'])
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print('模型直连、真实最终回答回放、并发工具及六项内容属性通过', flush=True)
