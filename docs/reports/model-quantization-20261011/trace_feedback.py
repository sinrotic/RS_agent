"""回放实际业务验收摘要，快速检出静音鼠标的轮次与完成时间退化。"""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--candidate', type=Path, required=True)
parser.add_argument('--baseline', type=Path, default=Path(__file__).with_name('bf16-production-business.json'))
parser.add_argument('--query', default='推荐一款适合办公的鼠标，最好静音，说明理由')
args = parser.parse_args()
baseline = next(row for row in json.loads(args.baseline.read_text(encoding='utf-8'))['business_regression'] if row['query'] == args.query)
candidate = next(row for row in json.loads(args.candidate.read_text(encoding='utf-8'))['business_regression'] if row['query'] == args.query)
assert baseline['query'] == candidate['query']
result = {'baseline_ms': baseline['elapsed_ms'], 'candidate_ms': candidate['elapsed_ms'],
          'baseline_tools': baseline['tool_names'], 'candidate_tools': candidate['tool_names'],
          'slowdown_ratio': round(candidate['elapsed_ms'] / baseline['elapsed_ms'], 3)}
result['passed'] = candidate['elapsed_ms'] <= baseline['elapsed_ms'] * 1.25 and candidate['failed_tools'] == 0
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(0 if result['passed'] else 1)
