"""顺序运行剩余模型/编排对照，异常时清理本任务资源。"""
import datetime
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import compare_live
import temporary_model

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / 'workflow.json'
result = {'started_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'steps': []}
resume_quant = '--resume-quant' in sys.argv
if resume_quant:
    result = json.loads(REPORT.read_text())
    (ROOT / 'workflow-first-attempt.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    result['resumed_at_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    result.pop('error_type', None)


def save():
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2))


def ready():
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        state = json.loads(temporary_model.STATE.read_text())
        assert temporary_model.owned(state), '临时模型进程已退出'
        try:
            with urllib.request.urlopen('http://127.0.0.1:18096/health', timeout=3) as response:
                if response.status == 200:
                    temporary_model.status()
                    return
        except OSError:
            pass
        print(json.dumps({'waiting_for_temporary_model': state['model']}), flush=True)
        time.sleep(15)
    raise TimeoutError('临时模型在10分钟内未就绪')


def run(script, arguments, name):
    print(json.dumps({'starting_step': name}), flush=True)
    begin = time.perf_counter()
    subprocess.run(['python3', str(ROOT / script)] + arguments, check=True)
    data = json.loads((ROOT / (name + '.json')).read_text())
    step = {'name': name, 'wall_seconds': round(time.perf_counter() - begin, 2),
            'completed': data.get('completed', data.get('samples') == 10)}
    result['steps'].append(step); save()
    print(json.dumps(step), flush=True)
    assert step['completed'], '对照阶段未完整执行：' + name


try:
    if not resume_quant:
        ready()
        run('model_probe.py', ['bf16-length-probe'], 'bf16-length-probe')
        run('compare_live.py', ['latency', '--version', 'original', '--name', 'original-bf16-gpu2',
            '--model-port', '18096', '--ordinary-only', '--ordinary-samples', '3'], 'original-bf16-gpu2')
        run('compare_live.py', ['latency', '--version', 'current', '--name', 'current-bf16-gpu2',
            '--model-port', '18096', '--ordinary-only', '--ordinary-samples', '3'], 'current-bf16-gpu2')
        temporary_model.stop()
    temporary_model.start('quant')
    ready()
    run('model_probe.py', ['quant-length-probe'], 'quant-length-probe')
    run('compare_live.py', ['latency', '--version', 'current', '--name', 'current-quant-gpu2',
        '--model-port', '18096', '--ordinary-only', '--ordinary-samples', '3'], 'current-quant-gpu2')
    temporary_model.stop()
    run('compare_live.py', ['capacity', '--version', 'pre-concurrency', '--name', 'pre-concurrency-capacity',
        '--levels', '8,16', '--repeats', '2'], 'pre-concurrency-capacity')
    run('compare_live.py', ['capacity', '--version', 'current', '--name', 'current-capacity',
        '--levels', '8,16', '--repeats', '2'], 'current-capacity')
    result['completed'] = True
except Exception as error:
    result.update(completed=False, error_type=type(error).__name__)
    print(json.dumps({'workflow_failed': type(error).__name__}), flush=True)
finally:
    compare_live.cleanup()
    temporary_model.stop()
    result['audit_returncode'] = subprocess.run(['python3', str(ROOT / 'audit.py')]).returncode
    result['finished_at_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save()
