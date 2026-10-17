"""建立独立版本索引；固定商品塔允许与用户/查询训练同时准备，不覆盖现网集合。"""
import json,time,urllib.request
from pathlib import Path
import numpy as np
from pymilvus import MilvusClient,DataType

ROOT=Path('/mnt/data/luo/remote_runs/product_v8_training')
SOURCE=Path('/mnt/data/luo/remote_runs/product_v7_expansion/export_candidate_v6')
NAME='rs_agent_product_three_tower_v8_20261011'

def main():
    vectors=np.load(SOURCE/'item_vectors.npy',mmap_mode='r')
    ids=[json.loads(line)['item_id'] for line in (SOURCE/'item_ids.jsonl').open()]
    assert len(ids)==len(set(ids))==len(vectors)==763080
    client=MilvusClient(uri='http://127.0.0.1:19530')
    progress=ROOT/'index_progress.json'
    start=0
    if client.has_collection(NAME):
        state=json.loads(progress.read_text());assert state['collection']==NAME
        start=state['inserted']
    else:
        schema=client.create_schema(auto_id=False,enable_dynamic_field=False)
        schema.add_field('item_id',DataType.VARCHAR,is_primary=True,max_length=128)
        schema.add_field('vector',DataType.FLOAT_VECTOR,dim=1024)
        params=client.prepare_index_params();params.add_index(field_name='vector',index_type='AUTOINDEX',metric_type='COSINE')
        progress.write_text(json.dumps({'collection':NAME,'inserted':0,'state':'CREATING'}))
        client.create_collection(collection_name=NAME,schema=schema,index_params=params,consistency_level='Strong')
    began=time.time()
    for i in range(start,len(ids),500):
        end=min(i+500,len(ids))
        client.upsert(collection_name=NAME,data=[{'item_id':ids[j],'vector':vectors[j].tolist()} for j in range(i,end)])
        if i%10000==0 or end==len(ids):
            with urllib.request.urlopen('http://127.0.0.1:18213/actuator/health/readiness',timeout=5) as response:assert json.load(response)['status']=='UP'
            state={'collection':NAME,'inserted':end,'total':len(ids),'state':'INSERTING','seconds':time.time()-began}
            progress.write_text(json.dumps(state,indent=2));print(json.dumps(state),flush=True)
        time.sleep(.03)
    client.flush(collection_name=NAME);client.load_collection(collection_name=NAME)
    count=int(client.get_collection_stats(collection_name=NAME)['row_count']);assert count==len(ids)
    result={'state':'COMPLETE','collection':NAME,'count':count,'source':str(SOURCE),'item_vector_sha256':json.loads((SOURCE/'manifest.json').read_text())['output_hashes']['item_vectors.npy'],'seconds':time.time()-began}
    (ROOT/'index_manifest.json').write_text(json.dumps(result,indent=2));progress.write_text(json.dumps(result));print(json.dumps(result),flush=True)

if __name__=='__main__':main()
