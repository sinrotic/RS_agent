"""用全新 Compose project 验证真实中间件；不连接既有数据库，退出时清理本次容器与卷。"""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import hashlib
import subprocess
import sys
import time
import urllib.request

def main():
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='outputs/commerce-allocation-integration')
    parser.add_argument('--faults', action='store_true', help='追加消费者停机、服务重启和 Kafka 停机恢复验收')
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent
    output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=True)
    artifacts = output / 'artifacts'; artifacts.mkdir(exist_ok=True)
    artifact_hashes = {}
    for service in ('inventory', 'promotion', 'order', 'seckill'):
        name = f'rs-service-{service}'
        jar = name + ('-exec' if service == 'promotion' else '') + '.jar'
        source = directory.parents[2] / name / 'target' / jar
        target = artifacts / jar
        shutil.copyfile(source, target)
        with target.open('rb') as file: artifact_hashes[jar] = hashlib.file_digest(file, 'sha256').hexdigest()
    project = 'rs-commerce-it-' + secrets.token_hex(4)
    assert re.fullmatch(r'rs-commerce-it-[0-9a-f]{8}', project)
    environment = dict(os.environ, RS_IT_DB_PASSWORD=secrets.token_urlsafe(32), RS_COMMERCE_OPS_READ_TOKEN=secrets.token_urlsafe(32),
                       RS_COMMERCE_OPS_WRITE_TOKEN=secrets.token_urlsafe(32), RS_IT_REPORT=str(output / 'report.json'), RS_IT_JAR_DIR=str(artifacts),
                       RS_IT_FAULT_ACTIVITY_ID='it-fault-'+secrets.token_hex(8), RS_IT_FAULT_REPORT=str(output / 'fault-report.json'))
    compose = ['docker', 'compose', '-p', project, '-f', str(directory / 'compose.yml')]
    private = [environment[key] for key in ('RS_IT_DB_PASSWORD', 'RS_COMMERCE_OPS_READ_TOKEN', 'RS_COMMERCE_OPS_WRITE_TOKEN')]
    def run(command, timeout=600):
        result = subprocess.run(command, env=environment, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
        text = result.stdout + result.stderr
        for token in private: text = text.replace(token, '[REDACTED]')
        with (output / 'commands.log').open('a', encoding='utf-8') as log: log.write(text)
        if result.returncode: raise RuntimeError('隔离联调命令失败，请查看脱敏 commands.log')
        return text
    status = {'project': project, 'artifactHashes': artifact_hashes, 'realIntegrationPassed': False, 'deployed': False}
    try:
        run(['docker', 'info', '--format', '{{.ServerVersion}}'], 15)
        print('正在启动约 4.3GB 上限的隔离容器环境', flush=True)
        run(compose + ['up', '-d'], 600)
        for port in (24291, 24391, 24292, 24294, 24394, 24295):
            deadline = time.monotonic() + 120
            while True:
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/actuator/health', timeout=3) as response:
                        if response.status == 200: break
                except Exception:
                    if time.monotonic() >= deadline: raise RuntimeError(f'隔离服务 {port} 未就绪')
                    time.sleep(2)
        print('真实 MySQL/Redis/Kafka 和双实例服务已就绪，开始库存竞争与终态验收', flush=True)
        run(['node', str(directory / 'acceptance.mjs')], 240)
        status['realIntegrationPassed'] = True
        if args.faults:
            phase = lambda name: run(['node', str(directory / 'faults.mjs'), name], 150)
            print('库存验收通过，开始消费者停机与服务重启验证', flush=True)
            phase('prepare')
            run(compose + ['stop', '-t', '5', 'order', 'order-b'], 30)
            phase('consumer-down')
            run(compose + ['restart', '-t', '5', 'seckill', 'seckill-b'], 30)
            run(compose + ['start', 'order', 'order-b'], 30)
            phase('consumer-recovered')
            print('消费者与服务重启恢复通过，开始 Kafka 停机恢复验证', flush=True)
            run(compose + ['stop', '-t', '5', 'kafka'], 30)
            phase('broker-down')
            run(compose + ['start', 'kafka'], 30)
            phase('broker-recovered')
            status['realFaultTestsPassed'] = True
        print('真实联合验收通过，正在清理本次环境', flush=True)
    except Exception as error:
        status['error'] = str(error)
        print(str(error), flush=True)
    finally:
        try: run(compose + ['logs', '--no-color'], 30)
        except Exception: pass
        try: run(compose + ['down', '--volumes', '--remove-orphans'], 60); status['cleanupPassed'] = True
        except Exception: status['cleanupPassed'] = False
        (output / 'verification.json').write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if status['realIntegrationPassed'] and status.get('cleanupPassed') and (not args.faults or status.get('realFaultTestsPassed')) else 1

if __name__ == '__main__':
    raise SystemExit(main())
