"""只给既有服务包增加保护召回装配；不把工作区其他改动部署到线上。"""
import hashlib,json,zipfile
from pathlib import Path
ROOT=Path('/mnt/data/luo/remote_runs/product_v14_training')

def main():
    source=ROOT.parent/'product_v9_training/rs-service-recommend.jar';target=ROOT/'rs-service-recommend.jar'
    entries={'BOOT-INF/classes/com/sinrotic/rs/recommend/config/TwoTowerRecallConfiguration.class':'TwoTowerRecallConfiguration.class',
             'BOOT-INF/classes/com/sinrotic/rs/recommend/service/impl/ProtectedHeadTwoTowerRecallProvider.class':'ProtectedHeadTwoTowerRecallProvider.class'}
    assert not target.exists()
    with zipfile.ZipFile(source) as old,zipfile.ZipFile(target,'w') as new:
        for info in old.infolist():
            data=(ROOT/'classes'/entries[info.filename]).read_bytes() if info.filename in entries else old.read(info.filename)
            new.writestr(info,data)
        for name,file in entries.items():
            if name not in old.namelist():new.writestr(name,(ROOT/'classes'/file).read_bytes(),compress_type=zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(source) as old,zipfile.ZipFile(target) as new:
        changed=[n for n in old.namelist() if old.read(n)!=new.read(n)]
        added=sorted(set(new.namelist())-set(old.namelist()))
        assert changed==['BOOT-INF/classes/com/sinrotic/rs/recommend/config/TwoTowerRecallConfiguration.class']
        assert added==['BOOT-INF/classes/com/sinrotic/rs/recommend/service/impl/ProtectedHeadTwoTowerRecallProvider.class']
        assert not set(old.namelist())-set(new.namelist())
    original=json.loads((ROOT.parent/'product_v9_training/deployment_build.json').read_text())
    report={'state':'BUILT','source_existing_patch':str(source),'source_existing_patch_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'jar_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'changed_from_v9':changed,'added_from_v9':added,
            'original_live_build_evidence':original,'scope':'相对原现网：保留已验证Milvus EF配置补丁，替换双塔装配配置，新增固定头部保护类。其余jar条目原样保留。'}
    (ROOT/'deployment_build.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('ISOLATED_JAR_BUILT',report['jar_sha256'])

if __name__=='__main__':main()
