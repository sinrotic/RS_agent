"""通过隔离与语义验收后切换正式 .env，实际重启失败时恢复 BF16。"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
import urllib.request


def wait_clone_ready():
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen('http://127.0.0.1:18314/actuator/health', timeout=3) as response:
                if response.status == 200 and json.load(response).get('status') == 'UP':
                    return
        except Exception:
            pass
        time.sleep(1)
    raise TimeoutError('本次独立业务验收实例未就绪')

ROOT=Path(__file__).resolve().parent
LIVE=Path('/home/luo/RS_agent_java/model_deploy')
helper=Path('/tmp/rs-serving-tuning-20261011/deploy.py')
spec=importlib.util.spec_from_file_location('serving_runtime',helper)
runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)


def gate(candidate):
    baseline=json.loads((ROOT/'bf16.json').read_text())
    expected=json.loads((ROOT/'bf16-production-business.json').read_text())
    quality=json.loads((ROOT/'quality-bf16.json').read_text())
    state=json.loads((ROOT/(candidate+'-state.json')).read_text())
    data=json.loads((ROOT/(candidate+'.json')).read_text())
    assert state['passed'], '隔离候选未通过'
    if state['variant'] == 'int4_autoround':
        compatible = json.loads((ROOT / 'int4-runtime-source.json').read_text())
        assert compatible['effective_tokenizer_identical'] and not compatible['weights_changed']
        assert state.get('model_path') == compatible['path'], '只推广保持原分词协议的 INT4 候选'
    assert quality['passed'] and len(quality['results'])==6
    assert len(data['fixed_quality'])==6 and all(r['passed'] for r in data['fixed_quality'])
    assert len(data['real_request_replay'])==6
    assert len(data['business_regression'])==5 and all(r['passed'] and r['failed_tools']==0 for r in data['business_regression'])
    assert len(data['advice_diagnostic'])==3
    for key in ['passed','advice_complete','advice_respects_no_products']:
        assert sum(r[key] for r in data['advice_diagnostic'])>=sum(r[key] for r in expected['advice_diagnostic']), '一般建议诊断出现新增回归'
    before=baseline['summaries']['decode_128']['e2e_median_ms']
    after=data['summaries']['decode_128']['e2e_median_ms']
    assert after<before*0.95, '固定长度生成未获得至少5%的速度优势'
    return state,data,{'fixed_decode_before_ms':before,'fixed_decode_after_ms':after,
                        'latency_reduction_percent':round((1-after/before)*100,2)}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--candidate',required=True,choices=['w8a16_middle_restart2','w8a16_middle8','int4_autoround','int4_autoround_restart2'])
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    state,data,speed=gate(args.candidate)
    runtime.wait_external_validation()
    saved=json.loads((ROOT/'baseline-deployment.json').read_text())
    for name,digest in saved['sha256'].items():
        assert hashlib.sha256((LIVE/name).read_bytes()).hexdigest()==digest, f'{name} 在实验期间发生变化'
    pid,parent=runtime.canonical_process()
    runtime.wait_idle()
    selected=state['variant']
    model='/mnt/data/luo/models/Qwen3.5-4B'
    if selected=='int4_autoround':
        source=json.loads((ROOT/'int4-runtime-source.json').read_text())
        assert source['revision']=='0a857215cab37e8caa857a053005a73cf98ff2c4'
        model=source['path']
    updates={'MODEL_PATH':model,'VLLM_QUANTIZATION':state['configuration']['VLLM_QUANTIZATION'],
             'VLLM_QUANTIZATION_CONFIG':state['configuration']['VLLM_QUANTIZATION_CONFIG'],
             'VLLM_TEST_FORCE_FP8_MARLIN':state['configuration']['VLLM_TEST_FORCE_FP8_MARLIN'],
             'VLLM_CACHE_ROOT':str(LIVE/'quantization-cache'/('20261011-'+selected))}
    print('量化推广前验收通过',selected,speed,flush=True)
    if not args.apply:return
    # 同型号 GPU 的同一候选已验收编译产物，先复制到持久目录以减少停服编译。
    # 此处运行于候选进程退出后；精度家族和 config hash 由 vLLM 再次核验。
    cache_source=Path(state['configuration']['VLLM_CACHE_ROOT']).resolve()
    assert cache_source.is_relative_to((ROOT/'cache').resolve())
    cache_target=Path(updates['VLLM_CACHE_ROOT'])
    assert not cache_target.exists(), '拒绝覆盖已有正式精度缓存目录'
    shutil.copytree(cache_source,cache_target)
    runtime.wait_idle()
    original=(LIVE/'.env').read_bytes()
    backup=LIVE/('backup-quantization-'+time.strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(mode=0o700)
    runtime.atomic_write(backup/'.env',original,0o600)
    lines=original.decode().splitlines()
    for key in updates: assert sum(line.startswith(key+'=') for line in lines)<=1
    new='\n'.join(line for line in lines if line.split('=',1)[0] not in updates)+'\n'
    new+='\n'.join(key+'='+shlex.quote(value) for key,value in updates.items())+'\n'
    report={'candidate':args.candidate,'quantization':selected,'backup':str(backup),'speed_screen':speed,
            'updates':updates,'promoted':False,'baseline_sha256':saved['sha256']}
    report['compile_cache_source']=str(cache_source)
    formal_before=json.loads((ROOT/'bf16-production-latency.json').read_text())['summaries']['decode_128']['e2e_median_ms']
    report['formal_fixed_decode_before_ms']=formal_before
    process=None;stopped=False
    try:
        runtime.stop_existing(pid,parent);stopped=True
        runtime.atomic_write(LIVE/'.env',new.encode(),0o600)
        process=runtime.launch('quantization-20261011.log')
        runtime.wait_idle()
        # 只将本次独立验收实例连到正式模型，其他业务容器不修改。
        subprocess.run([sys.executable,str(ROOT/'clone.py'),'--model-port','18082'],check=True)
        wait_clone_ready()
        runtime.wait_idle()
        subprocess.run([sys.executable,str(ROOT/'benchmark.py'),'--base-url','http://127.0.0.1:18082/v1',
                        '--output',str(ROOT/'production-after.json')],check=True,timeout=360)
        actual=json.loads((ROOT/'production-after.json').read_text())
        assert len(actual['fixed_quality'])==6 and len(actual['business_regression'])==5
        assert all(row['passed'] for row in actual['fixed_quality'])
        assert all(row['passed'] and row['failed_tools']==0 for row in actual['business_regression'])
        baseline=json.loads((ROOT/'bf16-production-business.json').read_text())
        for key in ['passed','advice_complete','advice_respects_no_products']:
            assert sum(r[key] for r in actual['advice_diagnostic'])>=sum(r[key] for r in baseline['advice_diagnostic'])
        # 正式配置的同长度生成也须变快，不能只推广隔离数字。
        formal_after=actual['summaries']['decode_128']['e2e_median_ms']
        assert formal_after < formal_before*0.97
        # 量化改变工具决策时，单次生成加速不能抵消完整业务的明显退化。
        import statistics
        before_business=statistics.median(row['elapsed_ms'] for row in baseline['business_regression'])
        after_business=statistics.median(row['elapsed_ms'] for row in actual['business_regression'])
        report.update(formal_business_before_median_ms=before_business,formal_business_after_median_ms=after_business)
        assert after_business <= before_business*1.25, '完整推荐小样本中位耗时显著退化'
        report.update(promoted=True,launcher_pid=process.pid,health=runtime.health(),
                      deployed_env_sha256=hashlib.sha256((LIVE/'.env').read_bytes()).hexdigest(),
                      formal_fixed_decode_ms=formal_after,
                      formal_latency_reduction_percent=round((1-formal_after/formal_before)*100,2))
        print('正式量化重启与完整工具回归通过',flush=True)
    except Exception as error:
        report['failure']=str(error)
        if stopped:
            runtime.stop_owned(process)
            runtime.atomic_write(LIVE/'.env',original,0o600)
            restored=runtime.launch('quantization-20261011-rollback.log')
            report.update(rollback=True,health=runtime.health(),restored_launcher_pid=restored.pid)
        raise
    finally:
        (ROOT/'deployment-state.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
