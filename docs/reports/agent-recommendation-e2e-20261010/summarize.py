"""从真实请求证据统计完整完成耗时；未收到最终回答的请求单独计失败。"""
import json
import statistics
from pathlib import Path

root=Path(__file__).resolve().parent
report={}
def describe(rows,key):
    values=[row[key] for row in rows if row.get(key) is not None]
    return {'requests':len(rows),'completed':len(values),'failed':len(rows)-len(values),
            'minimum_ms':round(min(values),2) if values else None,
            'median_ms':round(statistics.median(values),2) if values else None,
            'maximum_ms':round(max(values),2) if values else None}
for name in ['optimized-mouse','optimized-cold-warm','optimized-cold-concurrent','baseline-concurrent']:
    data=json.loads((root/(name+'.json')).read_text(encoding='utf8'))
    for group,rows in data.items():
        if rows: report[name+'/'+group]=describe(rows,'complete_with_catalog_ms')
data=json.loads((root/'optimized-mouse.json').read_text(encoding='utf8'))
report['optimized-mouse/steady-single']=describe(data['single'][1:],'complete_with_catalog_ms')
report['baseline/single']=describe([json.loads((root/(name+'.json')).read_text(encoding='utf8')) for name in
                                  ['baseline-five-1','baseline-five-2']],'complete_with_catalog_ms')
for name in ['browser-fast','browser-baseline']:
    data=json.loads((root/(name+'.json')).read_text(encoding='utf8'))
    report[name]=describe(data['samples'],'complete_render_ms')
(root/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(report,ensure_ascii=False,indent=2))
