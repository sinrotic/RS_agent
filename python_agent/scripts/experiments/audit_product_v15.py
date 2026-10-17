"""校验冻结整轮产物、三塔权重、独立模型定义及部署服务包，无保护位。"""
import importlib.util,json,time
import torch
from package_product_v15 import ROOT,digest
from evaluate_product_v7_catalog import save

def main():
    output=ROOT/'export';m=json.loads((output/'manifest.json').read_text());selection=json.loads((ROOT/'selection.json').read_text())
    plan=json.loads((ROOT/'experiment_plan.json').read_text());result=json.loads((ROOT/'results.json').read_text())
    selected=torch.load(selection['checkpoint'],map_location='cpu',weights_only=True)
    exported=torch.load(output/'model.pt',map_location='cpu',weights_only=True)
    source=torch.load(plan['initial_checkpoint'],map_location='cpu',weights_only=True)
    checks={'hashes':all(digest(output/name)==value for name,value in m['output_hashes'].items()),
            'zero_old_head':m['protected_head_count']==exported['config']['old_head_protection']==0,
            'three_full_epochs':len(result['epochs'])==m['full_training_epochs_completed']==3,
            'selected_completed_epoch':selection['epoch'] in [1,2,3] and selected['step_in_epoch']==selected['rec_steps_per_epoch'],
            'selected_weights':all(torch.equal(v,selected['model'][k]) for k,v in exported['model'].items()),
            'three_towers_changed':all(any(not torch.equal(v,source['model'][k]) for k,v in exported['model'].items() if k.startswith(n+'.')) for n in ['item','user','query']),
            'index_matches_export':json.loads((ROOT/'index_manifest.json').read_text())['item_vector_sha256']==m['output_hashes']['item_vectors.npy'],
            'jar_matches_build':digest(ROOT/'rs-service-recommend.jar')==json.loads((ROOT/'deployment_build.json').read_text())['jar_sha256']}
    spec=importlib.util.spec_from_file_location('standalone_v15',output/'model_definition.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    model=module.create_model(exported['config'],763080);model.load_state_dict(exported['model'],strict=True)
    checks['independent_factory_strict_load']=True
    record={'state':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'selected_epoch':selection['epoch'],
            'model_sha256':m['output_hashes']['model.pt'],'jar_sha256':digest(ROOT/'rs-service-recommend.jar'),'timestamp':time.time()}
    save(ROOT/'final_artifact_audit.json',record);print('PURE_ARTIFACT_AUDIT',record['state'],checks,flush=True)

if __name__=='__main__':main()
