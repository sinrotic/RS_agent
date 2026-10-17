"""检查最终模型来源、三塔完整性、独立前向、索引和Java包的实际哈希。"""
import importlib.util,json,time,zipfile
import torch
from package_product_final import ROOT,BASE,SOURCE,digest,write

def main():
    p=ROOT/'export';m=json.loads((p/'manifest.json').read_text());state=torch.load(p/'model.pt',map_location='cpu',weights_only=True)
    source=torch.load(SOURCE/'model.pt',map_location='cpu',weights_only=True)
    checks={'hashes':all(digest(p/name)==sha for name,sha in m['output_hashes'].items()),
        'all_weights_match_selected':all(torch.equal(v,source['model'][k]) for k,v in state['model'].items()),
        'three_towers_present':all(any(k.startswith(n+'.') for k in state['model']) for n in ['item','user','query']),
        'zero_old_head':m['protected_head_count']==state['config']['old_head_protection']==0,
        'index_matches':json.loads((ROOT/'index_manifest.json').read_text())['item_vector_sha256']==m['output_hashes']['item_vectors.npy'],
        'jar_matches_tested_build':digest(ROOT/'rs-service-recommend.jar')==json.loads((ROOT/'deployment_build.json').read_text())['jar_sha256']}
    spec=importlib.util.spec_from_file_location('final_model_definition',p/'model_definition.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    model=module.create_model(state['config'],763080);model.load_state_dict(state['model'],strict=True);checks['standalone_strict_load']=True
    with zipfile.ZipFile(ROOT/'rs-service-recommend.jar') as z:
        checks['tested_java_classes']=all(z.read(entry)==(BASE/'product_v15_training/classes'/name).read_bytes() for entry,name in {
            'BOOT-INF/classes/com/sinrotic/rs/recommend/config/TwoTowerRecallConfiguration.class':'TwoTowerRecallConfiguration.class',
            'BOOT-INF/classes/com/sinrotic/rs/recommend/service/impl/HistoryFilteredTwoTowerRecallProvider.class':'HistoryFilteredTwoTowerRecallProvider.class'}.items())
    record={'state':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'model_sha256':m['output_hashes']['model.pt'],
            'jar_sha256':digest(ROOT/'rs-service-recommend.jar'),'timestamp':time.time()};write('final_artifact_audit.json',record)
    print('FINAL_ARTIFACT_AUDIT',record['state'],checks,flush=True)

if __name__=='__main__':main()
