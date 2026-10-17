"""辅助人工检查复杂推荐的公开文字；不导出账号、会话或工具记录。"""
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parent
for name in sys.argv[1:]:
    assert name in ['bf16-production-business', 'int4_autoround', 'int4_autoround_restart2', 'production-after']
    rows = json.loads((root / (name + '-business.private.json')).read_text())
    print(name)
    for row in rows[1:3]:
        final = row['response']
        blocks = final.get('answer_blocks', final.get('answerBlocks', []))
        if not blocks:
            blocks = [e['data'] for e in row['events'] if e['event'] == 'answer_block']
        print(row['query'])
        print('\n'.join(str(b.get('content', '')) for b in blocks))
