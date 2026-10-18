"""登录网关持续交易、备份恢复与计划内主从切换；仅操作本次随机 project。"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request

APPS = ('inventory', 'promotion', 'order', 'payment', 'seckill', 'user', 'recommend', 'gateway')
PORTS = (24492, 24495, 24491, 24493, 24494, 24401, 24403, 24488)


def main():
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='outputs/commerce-fullstack')
    parser.add_argument('--duration', type=int, default=60)
    parser.add_argument('--clients', type=int, default=4)
    parser.add_argument('--ha', action='store_true', help='额外验证单 broker 故障及计划内 MySQL/Redis 提升')
    args = parser.parse_args()
    if not 10 <= args.duration <= 3600 or not 4 <= args.clients <= 16: parser.error('duration=10..3600，clients=4..16')
    directory = Path(__file__).resolve().parent
    repo = directory.parents[3]
    output = Path(args.output).resolve()
    # 私密账号、备份只允许落入仓库忽略的 outputs，避免 CI/误提交泄露。
    if not output.is_relative_to(repo / 'outputs'): parser.error('output 必须位于仓库 outputs 目录')
    output.mkdir(parents=True, exist_ok=True)
    artifacts = output / 'artifacts'; artifacts.mkdir(exist_ok=True)
    project = 'rs-commerce-v2-it-' + secrets.token_hex(4)
    assert re.fullmatch(r'rs-commerce-v2-it-[0-9a-f]{8}', project)
    secret_keys = ('RS_IT_DB_PASSWORD', 'RS_COMMERCE_OPS_READ_TOKEN', 'RS_COMMERCE_OPS_WRITE_TOKEN', 'RS_COMMERCE_SERVICE_TOKEN', 'RS_PAYMENT_MOCK_CALLBACK_SECRET')
    env = dict(os.environ, **{key: secrets.token_urlsafe(32) for key in secret_keys}, RS_IT_JAR_DIR=str(artifacts),
               RS_IT_DURATION=str(args.duration), RS_IT_CLIENTS=str(args.clients), RS_IT_REPORT=str(output / 'load-report.json'),
               RS_IT_PRIVATE_STATE=str(output / 'private-accounts.json'), RS_IT_OUTPUT_DIR=str(output))
    compose = ['docker', 'compose', '-p', project, '-f', str(directory / 'fullstack.compose.yml')]
    status = {'project': project, 'artifactHashes': {}, 'deployed': False, 'fullstackPassed': False, 'haRequested': args.ha}

    def run(command, timeout=180, data=None, private=False):
        result = subprocess.run(command, env=env, input=data, capture_output=True, timeout=timeout)
        if not private or result.returncode:
            text = (result.stderr if private else result.stdout + result.stderr).decode('utf-8', 'replace')
            for key in secret_keys: text = text.replace(env[key], '[REDACTED]')
            with (output / 'commands.log').open('a', encoding='utf-8') as file: file.write(text)
        if result.returncode: raise RuntimeError('隔离联调命令失败；查看脱敏 commands.log（私密 SQL 不记录）')
        return result.stdout

    def sql(service, statement):
        return run(compose + ['exec', '-T', service, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -Drs_agent -N -B'], data=statement.encode(), private=True).decode().strip()

    def dump(service):
        return run(compose + ['exec', '-T', service, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -uroot --single-transaction --set-gtid-purged=ON --databases rs_agent'], private=True)

    def restore(service, backup):
        run(compose + ['exec', '-T', service, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot'], data=backup, private=True)

    def ready(ports=PORTS):
        deadline = time.monotonic() + 180
        for port in ports:
            while True:
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/actuator/health', timeout=3) as response:
                        if response.status == 200: break
                except Exception:
                    if time.monotonic() >= deadline: raise RuntimeError(f'服务 {port} 未就绪')
                    time.sleep(2)

    def node(phase): run(['node', str(directory / 'fullstack-acceptance.mjs'), phase], args.duration + 480)

    def counts(service):
        return {table: int(sql(service, f'SELECT COUNT(*) FROM {table}')) for table in ('orders', 'checkout_refund', 'payment_refund', 'commerce_order_event', 'recommendation_trade_event', 'promotion_coupon', 'inventory_adjustment')}

    def switch_alias(old, new, alias):
        network = project + '_default'
        ids = [run(compose + ['ps', '-a', '-q', name]).decode().strip() for name in (old, new)]
        for container in ids:
            label = run(['docker', 'inspect', '-f', '{{index .Config.Labels "com.docker.compose.project"}}', container]).decode().strip()
            if label != project: raise RuntimeError('拒绝操作非本次 project 容器')
        label = run(['docker', 'network', 'inspect', '-f', '{{index .Labels "com.docker.compose.project"}}', network]).decode().strip()
        if label != project: raise RuntimeError('拒绝操作非本次 project 网络')
        run(['docker', 'network', 'disconnect', network, ids[0]])
        run(['docker', 'network', 'disconnect', network, ids[1]])
        run(['docker', 'network', 'connect', '--alias', alias, '--alias', new, network, ids[1]])

    def database_invariants(service):
        assert sql(service, "SELECT COUNT(*) FROM sku_stock WHERE available_stock<>200 OR locked_stock<>0 OR sold_stock<>0") == '0', '库存未回到初始数量'
        assert sql(service, "SELECT COUNT(*) FROM checkout_refund WHERE status<>'REFUNDED'") == '0', '退款存在未结清任务'
        assert sql(service, "SELECT COUNT(*) FROM promotion_coupon WHERE status<>'AVAILABLE'") == '0', '券没有全部恢复'
        assert sql(service, 'SELECT COUNT(*) FROM recommendation_purchase_signal WHERE active=TRUE') == '0', 'Mock 污染真实偏好'
        assert sql(service, "SELECT COUNT(*) FROM commerce_event_delivery WHERE status<>'DONE'") == '0', '交易事件未全部交付'

    started = False
    try:
        run(['docker', 'info', '--format', '{{.ServerVersion}}'], 15)
        for service in APPS:
            name = 'rs-api-gateway' if service == 'gateway' else 'rs-service-' + service
            jar = name + ('-exec' if service == 'promotion' else '') + '.jar'
            target = artifacts / jar; shutil.copyfile(directory.parents[2] / name / 'target' / jar, target)
            status['artifactHashes'][jar] = hashlib.sha256(target.read_bytes()).hexdigest()
        print('启动独立中间件（容器上限约 5.8GB），准备 GTID 备份与副本', flush=True)
        started = True
        run(compose + ['up', '-d', '--wait', 'mysql', 'mysql-replica', 'redis', 'redis-replica', 'kafka', 'kafka-2', 'kafka-3'], 600)
        # 健康检查只保证 MySQL 可连接；初始化脚本全部执行完才可以取快照。
        deadline = time.monotonic() + 120
        while True:
            try:
                if sql('mysql', "SELECT version FROM rs_schema_version WHERE component='rs-service-commerce-completion'") == 'commerce_completion_v2' and sql('mysql', 'SELECT COUNT(*) FROM amazon_reviews_base') == '1': break
            except RuntimeError: pass
            if time.monotonic() >= deadline: raise RuntimeError('数据库迁移未完成')
            time.sleep(2)
        backup = dump('mysql'); restore('mysql-replica', backup)
        assert counts('mysql') == counts('mysql-replica')
        password = env['RS_IT_DB_PASSWORD']
        sql('mysql', f"CREATE USER 'replication'@'%' IDENTIFIED BY '{password}'; GRANT REPLICATION SLAVE ON *.* TO 'replication'@'%';")
        sql('mysql-replica', f"CHANGE REPLICATION SOURCE TO SOURCE_HOST='mysql',SOURCE_USER='replication',SOURCE_PASSWORD='{password}',SOURCE_AUTO_POSITION=1,GET_SOURCE_PUBLIC_KEY=1; START REPLICA;")
        status['initialRestorePassed'] = True
        run(compose + ['up', '-d', *APPS], 600); ready()
        before = sql('mysql', "SHOW GLOBAL STATUS WHERE Variable_name IN ('Innodb_row_lock_current_waits','Innodb_row_lock_time','Innodb_row_lock_waits')")
        print('开始登录网关→领券→下单→支付回调→退款持续闭环', flush=True)
        node('load')
        # 等后台 outbox 清空，随后采集池/队列/消费者指标。
        deadline = time.monotonic() + 120
        while sql('mysql', "SELECT COUNT(*) FROM commerce_event_delivery WHERE status<>'DONE'") != '0':
            if time.monotonic() >= deadline: raise RuntimeError('事件队列未清空')
            time.sleep(1)
        database_invariants('mysql')
        status['mysqlLockBefore'] = before
        status['mysqlLockAfter'] = sql('mysql', "SHOW GLOBAL STATUS WHERE Variable_name IN ('Innodb_row_lock_current_waits','Innodb_row_lock_time','Innodb_row_lock_waits')")
        status['metrics'] = {}
        for name, port in zip(APPS, PORTS):
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/actuator/prometheus', timeout=10) as response:
                lines = response.read().decode().splitlines()
            status['metrics'][name] = [line for line in lines if not line.startswith('#') and any(key in line for key in ('hikaricp_connections', 'commerce_tasks_', 'commerce_kafka_'))]
        status['fullstackPassed'] = True
        primary = 'mysql'
        if args.ha:
            print('验证单 broker 停机后继续异步秒杀', flush=True)
            run(compose + ['stop', '-t', '5', 'kafka'], 40); node('broker-down')
            run(compose + ['start', 'kafka'], 40)
            status['singleBrokerFailurePassed'] = True
            print('验证 MySQL 追平后计划内提升，重启应用切换连接', flush=True)
            run(compose + ['stop', '-t', '10', *APPS], 90)
            gtid = sql('mysql', 'SELECT @@GLOBAL.gtid_executed')
            assert sql('mysql-replica', f"SELECT WAIT_FOR_EXECUTED_GTID_SET('{gtid}',60)") == '0'
            assert counts('mysql') == counts('mysql-replica')
            run(compose + ['stop', '-t', '10', 'mysql'], 40)
            sql('mysql-replica', 'STOP REPLICA; SET GLOBAL super_read_only=OFF; SET GLOBAL read_only=OFF;')
            switch_alias('mysql', 'mysql-replica', 'mysql'); primary = 'mysql-replica'
            run(compose + ['start', *APPS], 90); ready(); node('mysql-promoted')
            status['mysqlPlannedPromotionPassed'] = True
            print('验证 Redis 复制确认后计划内提升，既有登录令牌继续有效', flush=True)
            run(compose + ['stop', '-t', '10', *APPS], 90)
            # 同一连接写入屏障并 WAIT；不能用独立连接的 WAIT 冒充复制确认。
            ack = run(compose + ['exec', '-T', 'redis', 'redis-cli'], data=b'SET it-promotion-barrier ready\nWAIT 1 10000\n').decode().strip().splitlines()
            assert ack[-1] == '1', 'Redis 副本未确认屏障'
            run(compose + ['stop', '-t', '5', 'redis'], 30)
            run(compose + ['exec', '-T', 'redis-replica', 'redis-cli', 'REPLICAOF', 'NO', 'ONE'])
            switch_alias('redis', 'redis-replica', 'redis')
            run(compose + ['start', *APPS], 90); ready(); node('redis-promoted')
            status['redisPlannedPromotionPassed'] = True
        # 停写快照→压缩→恢复到隔离 restore 容器，核对业务行数和财务守恒。
        run(compose + ['stop', '-t', '10', *APPS], 90)
        backup = dump(primary); path = output / 'private-backup.sql.gz'
        with gzip.open(path, 'wb') as file: file.write(backup)
        try: path.chmod(0o600)
        except OSError: pass
        run(compose + ['up', '-d', '--wait', 'mysql-restore'], 180)
        restore('mysql-restore', gzip.decompress(path.read_bytes()))
        assert counts(primary) == counts('mysql-restore'); database_invariants('mysql-restore')
        status['backupRestore'] = {'passed': True, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'counts': counts(primary)}
        print('验证 Alertmanager 到隔离 webhook 接收器的通知', flush=True)
        run(compose + ['--profile', 'notifications', 'up', '-d', 'webhook', 'alertmanager'], 180)
        deadline = time.monotonic() + 60
        while True:
            try:
                payload = json.dumps([{'labels': {'alertname': 'CommerceIntegrationNotification', 'severity': 'warning'}, 'annotations': {'summary': '隔离通知验收'}}]).encode()
                with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:24499/api/v2/alerts', data=payload, headers={'Content-Type': 'application/json'}), timeout=3): pass
                break
            except Exception:
                if time.monotonic() >= deadline: raise RuntimeError('Alertmanager 未就绪')
                time.sleep(1)
        while not (output / 'notification-receipt.json').exists():
            if time.monotonic() >= deadline: raise RuntimeError('隔离告警未收到通知')
            time.sleep(1)
        status['notificationPassed'] = json.loads((output / 'notification-receipt.json').read_text())['received']
    except Exception as error:
        status['error'] = str(error); print(str(error), flush=True)
    finally:
        if started:
            try: run(compose + ['logs', '--no-color'], 60)
            except Exception: pass
            try: run(compose + ['--profile', 'notifications', 'down', '--volumes', '--remove-orphans'], 90); status['cleanupPassed'] = True
            except Exception: status['cleanupPassed'] = False
        else: status['cleanupPassed'] = True
        (output / 'verification.json').write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
    passed = status['fullstackPassed'] and status.get('backupRestore', {}).get('passed') and status.get('notificationPassed') and status['cleanupPassed']
    if args.ha: passed = passed and all(status.get(key) for key in ('singleBrokerFailurePassed', 'mysqlPlannedPromotionPassed', 'redisPlannedPromotionPassed'))
    return 0 if passed else 1


if __name__ == '__main__': raise SystemExit(main())
