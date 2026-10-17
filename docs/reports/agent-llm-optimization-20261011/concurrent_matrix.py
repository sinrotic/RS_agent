"""八个真实用户同时请求；按商品交付 ID 核验独立模型调用。"""
import concurrent.futures
import json
import sys
from probe import ROOT,accounts,one
from measure import ready

ready();users=accounts();phase=sys.argv[1]
(ROOT/'phase.txt').write_text(phase)
result={'concurrent_8':[], 'failures':[]}
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    futures=[pool.submit(one,user,'推荐鼠标','fast','concurrent-'+str(i)) for i,user in enumerate(users)]
    for i,future in enumerate(futures):
        try: row=future.result()
        except Exception as error: row={'label':'concurrent-'+str(i),'query':'推荐鼠标','error':str(error)}
        result['concurrent_8' if row.get('response') else 'failures'].append(row)
        (ROOT/(phase+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
print('真实 LLM 八用户并发完成，失败数',len(result['failures']),flush=True)
