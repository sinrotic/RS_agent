"""相同商品向量复用已验收物理集合，仅新增最终版本别名，不修改现网别名。"""
import json,time
from pymilvus import MilvusClient
from package_product_final import ROOT,BASE,COLLECTION,digest,write

def main():
    manifest=json.loads((ROOT/'export/manifest.json').read_text())
    reference=json.loads((BASE/'product_v14_training/index_manifest.json').read_text())
    assert manifest['output_hashes']['item_vectors.npy']==reference['item_vector_sha256']
    physical=reference['physical_collection'];client=MilvusClient(uri='http://127.0.0.1:19530')
    assert client.has_collection(physical)
    count=client.query(collection_name=physical,filter='',output_fields=['count(*)'])[0]['count(*)'];assert count==763080
    aliases=client.list_aliases(collection_name=physical)
    names=aliases.get('aliases',[]) if isinstance(aliases,dict) else aliases
    if COLLECTION not in names:client.create_alias(collection_name=physical,alias=COLLECTION)
    actual=client.describe_alias(alias=COLLECTION);assert actual['collection_name']==physical
    write('index_manifest.json',{'state':'COMPLETE','collection':COLLECTION,'physical_collection':physical,'count':count,
        'item_vector_sha256':manifest['output_hashes']['item_vectors.npy'],'new_vector_insertion':False,'timestamp':time.time()})
    print('FINAL_INDEX_ALIAS_READY',COLLECTION,count,flush=True)

if __name__=='__main__':main()
