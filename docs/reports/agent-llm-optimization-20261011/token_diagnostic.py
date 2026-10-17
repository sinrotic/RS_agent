"""重复完整多轮请求，在探针中只统计 token 分类，不计入性能主结果。"""
import json
from measure import ready
from probe import ROOT,accounts,one

ready();user=accounts()[0]
(ROOT/'phase.txt').write_text('token-diagnostic')
rows=[];session=None
for i,query in enumerate(('请帮我推荐鼠标','换一批鼠标，适合办公使用','再推荐五款鼠标，说明理由')):
    row=one(user,query,'fast','diagnostic-'+str(i),session)
    session=row.get('session_id',session);rows.append(row)
    (ROOT/'token-diagnostic.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
