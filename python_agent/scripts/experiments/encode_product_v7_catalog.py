"""复用旧BGE特征，分块编码新增训练期商品；每块持久化，可断点续跑。"""
import argparse,gc,hashlib,json,os,time
from pathlib import Path
import numpy as np
import torch
from sentence_transformers import SentenceTransformer


def save(path,value):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)


def main(args):
    assert os.environ.get('CUDA_VISIBLE_DEVICES')=='2'
    torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.cuda.set_per_process_memory_fraction(.20)
    manifest=json.loads((args.data/'manifest.json').read_text());old_count=manifest['old_count'];total=manifest['total_count']
    progress_path=args.data/'encoding_progress.json';destination=args.data/'item_features.npy'
    old=np.load(args.old_data/'item_features.npy',mmap_mode='r');assert old.shape==(old_count,1024)
    model_path='/home/luo/RS_agent_java/data/models/BAAI/bge-m3'
    config={'catalog_sha256':manifest['catalog_sha256'],'model':model_path,'max_seq_length':256,'dtype':'fp16 inference, float32 normalized cache','old_count':old_count,'total_count':total}
    if progress_path.exists():
        progress=json.loads(progress_path.read_text());assert progress['config']==config
        if progress['state']=='COMPLETE':return
        features=np.load(destination,mmap_mode='r+');completed=progress['completed'];batch_size=progress['batch_size']
    else:
        if destination.exists():raise RuntimeError('feature file without progress; inspect before recovery')
        features=np.lib.format.open_memmap(destination,mode='w+',dtype='float32',shape=(total,1024))
        for start in range(0,old_count,8192):features[start:start+8192 if start+8192<old_count else old_count]=old[start:min(start+8192,old_count)]
        features.flush();completed=old_count;batch_size=32
        progress={'state':'ENCODING','completed':completed,'batch_size':batch_size,'config':config}
        save(progress_path,progress)
    assert features.shape==(total,1024)
    if args.batch_size is not None:batch_size=args.batch_size
    model=SentenceTransformer(model_path,device='cuda',local_files_only=True);model.half();model.max_seq_length=256
    # 检查当前编码环境与保留的旧缓存兼容，避免混入另一个向量空间。
    sample=[]
    with (args.old_data/'items.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            sample.append(json.loads(line)['text'])
            if len(sample)==32:break
    encoded=model.encode(sample,batch_size=32,normalize_embeddings=True,convert_to_numpy=True,show_progress_bar=False).astype('float32')
    cos=np.sum(encoded*old[:32],axis=1)/(np.linalg.norm(encoded,axis=1)*np.linalg.norm(old[:32],axis=1))
    assert float(cos.min())>.999, 'encoder differs from old cache'
    save(args.data/'encoder_compatibility.json',{'sample_count':32,'min_cosine_with_old_cache':float(cos.min()),'max_component_difference':float(np.max(np.abs(encoded-old[:32]))),'old_prefix_copied':True})
    if args.autotune:
        probe=[]
        with (args.data/'items.jsonl').open(encoding='utf-8') as stream:
            for line in stream:
                row=json.loads(line)
                if row['index']<completed:continue
                probe.append(row['text'])
                if len(probe)==512:break
        timings={}
        for size in [16,32,64]:
            elapsed=[]
            try:
                for repeat in range(2):
                    torch.cuda.synchronize();begin=time.time()
                    model.encode(probe,batch_size=size,normalize_embeddings=True,convert_to_numpy=True,show_progress_bar=False)
                    torch.cuda.synchronize();elapsed.append(time.time()-begin)
                timings[str(size)]=sum(elapsed)/len(elapsed)
            except torch.cuda.OutOfMemoryError:
                gc.collect();torch.cuda.empty_cache()
        batch_size=int(min(timings,key=timings.get))
        save(args.data/'encoding_batch_benchmark.json',{'same_probe_first_index':completed,'probe_items':len(probe),'mean_seconds_two_repeats':timings,'selected_batch_size':batch_size,'cuda_allocator_fraction':.20})
    started=time.time();initial_completed=completed;buffer=[]
    def flush():
        nonlocal completed,batch_size,buffer
        if not buffer:return
        while True:
            try:
                values=model.encode([r['text'] for r in buffer],batch_size=batch_size,normalize_embeddings=True,convert_to_numpy=True,show_progress_bar=False).astype('float32');break
            except torch.cuda.OutOfMemoryError:
                if batch_size<=4:raise
                batch_size//=2;gc.collect();torch.cuda.empty_cache()
        assert np.isfinite(values).all() and np.allclose(np.linalg.norm(values,axis=1),1,atol=.002)
        assert buffer[0]['index']==completed and buffer[-1]['index']==completed+len(buffer)-1
        features[completed:completed+len(buffer)]=values;features.flush();completed+=len(buffer);buffer=[]
        seconds=time.time()-started;rate=(completed-initial_completed)/max(seconds,.001)
        value={'state':'ENCODING','completed':completed,'total':total,'batch_size':batch_size,'seconds_this_session':seconds,'items_per_second':rate,'estimated_remaining_seconds':(total-completed)/max(rate,.001),'config':config}
        save(progress_path,value);print(json.dumps({k:v for k,v in value.items() if k!='config'}),flush=True)
    with (args.data/'items.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            r=json.loads(line)
            if r['index']<completed:continue
            buffer.append(r)
            if len(buffer)==512:flush()
    flush();assert completed==total
    for start in range(0,old_count,8192):assert np.array_equal(features[start:min(start+8192,old_count)],old[start:min(start+8192,old_count)])
    progress=json.loads(progress_path.read_text());progress.update(state='COMPLETE',peak_cuda_gib=torch.cuda.max_memory_allocated()/2**30,old_prefix_exact=True)
    save(progress_path,progress)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--old-data',type=Path,required=True);p.add_argument('--batch-size',type=int);p.add_argument('--autotune',action='store_true');main(p.parse_args())
