"""缩小复测到此前退化的两条复杂推荐，保留实际工具和目录检查。"""
import json
import argparse
from pathlib import Path
import subprocess
from business import probe, summarize, item_ids

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--label', choices=['production-narrow-warm', 'bf16-restart-complex'], default='production-narrow-warm')
args = parser.parse_args()
container = json.loads(subprocess.check_output(['docker', 'inspect', 'rs-quantization-20261011-agent'], text=True))[0]
env = dict(row.split('=', 1) for row in container['Config']['Env'] if '=' in row)
assert env['RS_AGENT_OPENAI_BASE_URL'] == 'http://127.0.0.1:18082/v1'
users = probe.accounts()
rows = []; summaries = []
private = root / (args.label + '-business.private.json')
for number, query in enumerate(['推荐一款适合办公的鼠标，最好静音，说明理由',
                                '推荐适合编程使用的键盘，说明各自的区别']):
    row = probe.one(users[0], query, 'fast', 'narrow-warm-' + str(number))
    rows.append(row)
    private.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n'); private.chmod(0o600)
    summary, text = summarize(row)
    assert summary['item_count'] == 5 and len(set(item_ids(row['response']))) == 5 and text.strip()
    summaries.append(summary)
(root / (args.label + '.json')).write_text(json.dumps({'business_regression': summaries}, ensure_ascii=False, indent=2) + '\n')
print('两条曾退化的复杂推荐热运行验收通过', flush=True)
