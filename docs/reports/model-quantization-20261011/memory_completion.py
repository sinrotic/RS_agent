"""只导出实际最终回答和目录补全计数，不暴露请求、账号或商品 ID。"""
import json
from pathlib import Path
from business import item_ids

root = Path(__file__).resolve().parent
rows = json.loads((root / 'memory-business.private.json').read_text())
result = []
for row in rows:
    final = row.get('response')
    ids = item_ids(final) if final else []
    catalog = row.get('catalog', [])
    result.append({'query': row['query'], 'complete_final_answer': bool(final) and not row.get('error'),
                   'item_count': len(ids), 'catalog_complete': bool(ids) and
                   {item['item_id'] for item in catalog} == set(ids)})
(root / 'memory-answer-completion.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
assert len(result) == 5 and all(row['complete_final_answer'] and row['item_count'] == 5 and
                               row['catalog_complete'] for row in result)
print('五条实际请求均有最终回答、五件商品及完整目录补全；不等于内部工具全部成功')
