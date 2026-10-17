"""仅替换当前服务包的双塔装配并新增历史过滤器，保留所有其他现网字节。"""
import hashlib,json,zipfile
from pathlib import Path
ROOT=Path('/mnt/data/luo/remote_runs/product_v15_training')

def main():
    source=ROOT.parent/'product_v14_training/rs-service-recommend.jar';target=ROOT/'rs-service-recommend.jar'
    entries={'BOOT-INF/classes/com/sinrotic/rs/recommend/config/TwoTowerRecallConfiguration.class':'TwoTowerRecallConfiguration.class',
             'BOOT-INF/classes/com/sinrotic/rs/recommend/service/impl/HistoryFilteredTwoTowerRecallProvider.class':'HistoryFilteredTwoTowerRecallProvider.class'}
    assert not target.exists()
    with zipfile.ZipFile(source) as old,zipfile.ZipFile(target,'w') as new:
        for info in old.infolist():new.writestr(info,(ROOT/'classes'/entries[info.filename]).read_bytes() if info.filename in entries else old.read(info.filename))
        for name,file in entries.items():
            if name not in old.namelist():new.writestr(name,(ROOT/'classes'/file).read_bytes(),compress_type=zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(source) as old,zipfile.ZipFile(target) as new:
        changed=[n for n in old.namelist() if old.read(n)!=new.read(n)];added=sorted(set(new.namelist())-set(old.namelist()))
        assert changed==['BOOT-INF/classes/com/sinrotic/rs/recommend/config/TwoTowerRecallConfiguration.class']
        assert added==['BOOT-INF/classes/com/sinrotic/rs/recommend/service/impl/HistoryFilteredTwoTowerRecallProvider.class']
        assert not set(old.namelist())-set(new.namelist())
    evidence={'state':'BUILT','source_current_v14_jar':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
              'jar_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'changed_entries':changed,'added_entries':added,
              'scope':'新单模型路线保留历史排除和去重，不调用旧模型；其余包条目全部保留。'}
    (ROOT/'deployment_build.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2));print('PURE_MODEL_JAR_READY',evidence['jar_sha256'])

if __name__=='__main__':main()
