"""真实推荐的配对复测；所有样本与失败保留，不择取单条最快值。"""
import argparse
import concurrent.futures
import datetime
import importlib.util
import json
import statistics
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PREVIOUS = Path('/tmp/rs-agent-before-after-20261011')
sys.path.insert(0, str(PREVIOUS))
import compare_live as probe
spec = importlib.util.spec_from_file_location('resume_model_control', ROOT / 'model_control.py')
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)

probe.ROOT = ROOT
probe.NAME = 'rs-agent-resume-ab-20261011'
probe.PORT = 18319
probe.BASE = 'http://127.0.0.1:18319'
probe.LABEL = 'rsagent.resume-ab-20261011'
model.ROOT = ROOT
model.STATE = ROOT / 'temporary-model-state.json'
QUESTIONS = ['推荐鼠标', '请帮我推荐鼠标',
             '推荐一款适合办公的鼠标，最好静音，说明理由', '推荐无线鼠标']


def fixture():
    spec = importlib.util.spec_from_file_location('business_probe', '/tmp/rs-agent-quantization-retry-20261011/business_probe.py')
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj, obj.accounts()


def ready():
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        state = json.loads(model.STATE.read_text())
        assert model.owned(state), '本任务临时模型已退出'
        try:
            with urllib.request.urlopen('http://127.0.0.1:18096/health', timeout=3) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        print(json.dumps({'waiting_for_model': state['model']}), flush=True)
        time.sleep(10)
    raise TimeoutError('临时模型未就绪')


def benchmark(version, name, screening=False, queries=None):
    destination = ROOT / (name + '.json')
    assert not destination.exists()
    probe.MODEL_PORT = 18096
    report = {'started_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'version': version, 'screening': screening, 'stages': [], 'warmups': [],
              'shared_model_before': probe.identity(), 'dependencies_before': probe.dependency_snapshot(),
              'target_model_before': probe.target_identity(), 'gpu_before': model.gpu_snapshot()}
    def save():
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    def stable():
        assert probe.identity() == report['shared_model_before']
        assert probe.dependency_snapshot() == report['dependencies_before']
        assert probe.target_identity() == report['target_model_before']
    save()
    try:
        report['configuration'] = probe.configure(version)
        obj, users = fixture()
        def sessions(count):
            return [obj.http('/api/sessions', {'entryScene': 'resume-paired-benchmark'},
                             users[index % len(users)]['accessToken'])['sessionId'] for index in range(count)]
        def batch(count, repeat, question):
            stable()
            session_ids = sessions(count)
            barrier = threading.Barrier(count)
            before = probe.read_cache_metrics()
            begin = time.perf_counter()
            def run(index):
                barrier.wait(timeout=20)
                row = probe.sample(users[index % len(users)], question, session_ids[index])
                row.update(index=index, pair_id=f'{count}-{repeat}-{index}', account_index=index % len(users))
                return row
            with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
                rows = list(pool.map(run, range(count)))
            elapsed = time.perf_counter() - begin
            stage = {'concurrency': count, 'repeat': repeat, 'question': question,
                     'distinct_accounts': min(count, len(users)), 'distinct_sessions': len(set(session_ids)),
                     'batch_wall_ms': round(1000 * elapsed, 2), 'cases': rows,
                     'model_metrics': probe.metric_window(before, probe.read_cache_metrics()),
                     **probe.distribution(rows)}
            stage['throughput'] = round(stage['passed'] / elapsed, 4)
            print(json.dumps({key: value for key, value in stage.items() if key not in ('cases', 'model_metrics')},
                             ensure_ascii=False), flush=True)
            stable()
            return stage
        report['warmups'].append(batch(1, -1, '推荐鼠标')); save()
        if screening:
            for index, question in enumerate(queries or QUESTIONS):
                report['stages'].append(batch(1, index, question)); save()
        else:
            assert report['warmups'][0]['passed'] == 1, '预热质量不合格，不进行并发压测'
            # 在数据产生前固定所有并发档位、重复数；不以最快单批决定结束。
            report['plan'] = {'1': 8, '4': 4, '8': 4, '16': 3}
            save()
            for count, repeats in ((1, 8), (4, 4), (8, 4), (16, 3)):
                for repeat in range(repeats):
                    report['stages'].append(batch(count, repeat, '推荐鼠标')); save()
        report['completed'] = True
    except Exception as error:
        report.update(completed=False, error_type=type(error).__name__)
        raise
    finally:
        probe.cleanup()
        report.update(shared_model_after=probe.identity(), dependencies_after=probe.dependency_snapshot(),
                      target_model_after=probe.target_identity(), gpu_after=model.gpu_snapshot(),
                      finished_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        report['shared_model_unchanged'] = report['shared_model_before'] == report['shared_model_after']
        report['dependencies_unchanged'] = report['dependencies_before'] == report['dependencies_after']
        report['target_model_unchanged'] = report['target_model_before'] == report['target_model_after']
        save()
    return report


def workflow():
    path = ROOT / 'workflow.json'
    if path.exists():
        previous = json.loads(path.read_text())
        assert previous.get('completed') is False and not previous['steps']
        archive = ROOT / 'workflow-resource-guard.json'
        if archive.exists():
            archive = ROOT / 'workflow-initialization-failure.json'
        assert not archive.exists()
        path.rename(archive)
    result = {'started_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'steps': []}
    def save():
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    save()
    try:
        model.start('bf16'); ready()
        original = benchmark('original', 'original-bf16-screen', True)
        successful = [stage['question'] for stage in original['stages'] if stage['passed'] == 1]
        result['original_screen_successful_queries'] = successful
        result['steps'].append('original-bf16-screen'); save()
        benchmark('pre-concurrency', 'before-bf16-capacity')
        result['steps'].append('before-bf16-capacity'); save()
        model.stop()
        # 释放结束后重新确认资源；不因其他任务繁忙而挤占它们。
        time.sleep(5)
        model.start('quant'); ready()
        if successful:
            benchmark('current', 'current-quant-screen', True, successful)
            result['steps'].append('current-quant-screen'); save()
        benchmark('current', 'after-quant-capacity')
        result['steps'].append('after-quant-capacity')
        result['completed'] = True
    except Exception as error:
        result.update(completed=False, error_type=type(error).__name__)
        print(json.dumps({'workflow_error_type': type(error).__name__}), flush=True)
    finally:
        probe.cleanup(); model.stop()
        result['finished_at_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        result['gpu_after'] = model.gpu_snapshot()
        save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['workflow', 'inventory'])
    args = parser.parse_args()
    if args.phase == 'inventory':
        print(json.dumps(model.gpu_snapshot(), ensure_ascii=False))
    else:
        workflow()
