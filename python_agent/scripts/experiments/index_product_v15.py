"""为新商品塔建立独立Milvus集合；慢速写入并检查现网健康，不改旧集合。"""
import json,time,urllib.request
from pathlib import Path
import numpy as np
from pymilvus import MilvusClient,DataType
from package_product_v15 import ROOT,COLLECTION,digest
from evaluate_product_v7_catalog import save

def main():
    source=ROOT/'export';manifest=json.loads((source/'manifest.json').read_text())
    vectors=np.load(source/'item_vectors.npy',mmap_mode='r');ids=[json.loads(l)['item_id'] for l in (source/'item_ids.jsonl').open()]
    assert len(ids)==len(set(ids))==len(vectors)==763080
    sha=digest(source/'item_vectors.npy');assert sha==manifest['output_hashes']['item_vectors.npy']
    client=MilvusClient(uri='http://127.0.0.1:19530');progress=ROOT/'index_progress.json';start=0
    if client.has_collection(COLLECTION):
        state=json.loads(progress.read_text());assert state['collection']==COLLECTION and state['item_vector_sha256']==sha
        start=state['inserted']
    else:
        schema=client.create_schema(auto_id=False,enable_dynamic_field=False)
        schema.add_field('item_id',DataType.VARCHAR,is_primary=True,max_length=128)
        schema.add_field('vector',DataType.FLOAT_VECTOR,dim=1024)
        params=client.prepare_index_params();params.add_index(field_name='vector',index_type='AUTOINDEX',metric_type='COSINE')
        save(progress,{'state':'CREATING','collection':COLLECTION,'inserted':0,'item_vector_sha256':sha})
        client.create_collection(collection_name=COLLECTION,schema=schema,index_params=params,consistency_level='Strong')
    began=time.time()
    for start in range(start,len(ids),500):
        end=min(start+500,len(ids))
        client.upsert(collection_name=COLLECTION,data=[{'item_id':ids[j],'vector':vectors[j].tolist()} for j in range(start,end)])
        if start%10000==0 or end==len(ids):
            with urllib.request.urlopen('http://127.0.0.1:18213/actuator/health/readiness',timeout=5) as r:assert json.load(r)['status']=='UP'
            state={'state':'INSERTING','collection':COLLECTION,'inserted':end,'total':len(ids),'item_vector_sha256':sha,'seconds':time.time()-began}
            save(progress,state);print(json.dumps(state),flush=True)
        time.sleep(.03)
    client.flush(collection_name=COLLECTION);client.load_collection(collection_name=COLLECTION)
    count=client.query(collection_name=COLLECTION,filter='',output_fields=['count(*)'])[0]['count(*)'];assert count==len(ids)
    record={'state':'COMPLETE','collection':COLLECTION,'count':count,'source':str(source),'item_vector_sha256':sha,'inserted':len(ids),'seconds':time.time()-began}
    save(ROOT/'index_manifest.json',record);save(progress,record);print('NEW_INDEX_COMPLETE',count,flush=True)

if __name__=='__main__':main()
