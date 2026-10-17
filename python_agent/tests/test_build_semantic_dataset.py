import importlib.util
from pathlib import Path
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('semantic_builder', Path(__file__).parents[1]/'scripts/experiments/build_semantic_dataset.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_evidence_must_exist_in_declared_field():
    item={'item_id':'example','title':'Office Wheels', 'facts':[
        {'field':'title_clean','text':'Office Wheels for hardwood floors'},
        {'field':'features_text','text':'Other information'}]}
    query={'slot':'en_short','language':'en','query':'office wheels for hardwood floors',
           'claims':[{'claim':'hardwood floors','field':'features_text','quote':'hardwood floors'}]}
    assert 'invalid_evidence' in builder.local_checks(query,item,builder.SLOTS[2])
    query['claims'][0]['field']='title_clean'
    assert builder.local_checks(query,item,builder.SLOTS[2])==[]


def test_assembly_removes_cross_split_queries_and_isolates_test(tmp_path):
    data=tmp_path/'data';data.mkdir()
    items=[];records=[]
    for index,split in enumerate(['train','valid','test']):
        iid=str(index)
        items.append({'item_id':iid,'index':index,'split':split,'group':iid})
        qs=[{'slot':'en_short','language':'en','query':'same shared query'},
            {'slot':'en_need','language':'en','query':f'unique attribute demand {iid}'}]
        records.append({'item_id':iid,'status':'complete','queries':qs,
            'local_errors':{'en_short':[],'en_need':[]},
            'verdicts':[{'slot':q['slot'],'accept':True,'issues':[]} for q in qs]})
    builder.write_rows(tmp_path/'generation_inputs.jsonl',items)
    builder.write_rows(tmp_path/'generation_records.jsonl',records)
    builder.assemble(SimpleNamespace(root=tmp_path,data=data))
    train_input=list(builder.read(data/'semantic_clean.jsonl'))
    assert len(train_input)==2
    assert {r['split'] for r in train_input}=={'train','valid'}
    assert all(r['query']!='same shared query' for r in train_input)
    test=list(builder.read(data/'semantic_test.jsonl'))
    assert len(test)==1 and test[0]['item_id']=='2'


def test_truncated_response_cannot_be_accepted():
    import pytest
    with pytest.raises(ValueError,match='truncated'):
        builder.parse({'finish_reason':'length','output':'{"queries": []}'})
