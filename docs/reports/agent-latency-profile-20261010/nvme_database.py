"""复制 QA 自有表到独立 NVMe MySQL；不迁移或修改正式数据库。"""
import json
import re
import secrets
import subprocess
import time
from probe import ROOT

def run(args, data=None):
    return subprocess.run(args, input=data, check=True, capture_output=True, text=True, timeout=120).stdout.strip()

def sql(container, text):
    return run(['docker', 'exec', '-i', container, 'sh', '-c',
                'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -B'], text)

state_path = ROOT / 'state.json'; state = json.loads(state_path.read_text())
assert not state.get('cleaned') and not state.get('mysql_nvme')
database = state['database']; assert re.fullmatch(r'rs_e2e_[a-f0-9]{8}', database)
data_dir = (ROOT / 'mysql-nvme').resolve(); assert data_dir.parent == ROOT.resolve() and not data_dir.exists()
assert '/dev/nvme' in run(['findmnt', '--target', str(ROOT), '--noheadings', '--output', 'SOURCE'])
data_dir.mkdir()
image = json.loads(run(['docker', 'inspect', 'rs-agent-java-mysql']))[0]['Config']['Image']
name = 'rs-e2e-' + state['suffix'] + '-mysql-nvme'
env_file = ROOT / 'mysql-nvme.env'
env_file.write_text('MYSQL_ROOT_PASSWORD=' + secrets.token_urlsafe(32) + '\n'); env_file.chmod(0o600)
state['containers'].append(name); state['mysql_nvme'] = name; state['mysql_nvme_directory'] = str(data_dir)
state['mysql_nvme_image'] = image; state_path.write_text(json.dumps(state, indent=2))
try:
    run(['docker', 'run', '-d', '--name', name, '--network', 'host', '--memory', '1g', '--cpus', '4',
         '--env-file', str(env_file), '-v', str(data_dir) + ':/var/lib/mysql', image,
         '--bind-address=127.0.0.1', '--port=18306', '--server-id=98261010', '--log-bin=mysql-bin',
         '--sync-binlog=1', '--innodb-flush-log-at-trx-commit=1', '--innodb-flush-method=fsync',
         '--innodb-buffer-pool-size=268435456', '--innodb-redo-log-capacity=104857600'])
finally: env_file.unlink(missing_ok=True)
for _ in range(60):
    try: sql(name, 'SELECT 1;'); break
    except Exception: time.sleep(1)
else: raise RuntimeError('NVMe MySQL 未就绪')
tables = sql('rs-agent-java-mysql', f"SELECT TABLE_NAME FROM information_schema.tables WHERE TABLE_SCHEMA='{database}' AND TABLE_TYPE='BASE TABLE';").splitlines()
assert tables and all(re.fullmatch(r'\w+', table) for table in tables)
dump_file = ROOT / 'qa-private-dump.sql'
# 参数来自已验证标识符，不输出 dump 或凭据。
dump = run(['docker', 'exec', 'rs-agent-java-mysql', 'sh', '-c',
            'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -uroot --no-tablespaces --single-transaction '
            '--skip-lock-tables --set-gtid-purged=OFF ' + database + ' ' + ' '.join(tables)])
dump_file.write_text(dump); dump_file.chmod(0o600)
creds = json.loads((ROOT / 'credentials.json').read_text())
sql(name, f"CREATE DATABASE `{database}`; CREATE USER '{database}'@'%' IDENTIFIED BY '{creds['password']}'; GRANT ALL ON `{database}`.* TO '{database}'@'%';")
sql(name, f'USE `{database}`;\n' + dump); dump_file.unlink()
evidence = {'owned_qa_tables_copied': len(tables), 'data_directory': str(data_dir),
            'filesystem': run(['findmnt', '--target', str(data_dir), '--noheadings', '--output', 'SOURCE,FSTYPE,TARGET']),
            'durability': sql(name, 'SELECT @@version,@@innodb_flush_log_at_trx_commit,@@sync_binlog,@@log_bin,@@innodb_flush_method,@@innodb_doublewrite;'),
            'original_durability': sql('rs-agent-java-mysql', 'SELECT @@version,@@innodb_flush_log_at_trx_commit,@@sync_binlog,@@log_bin,@@innodb_flush_method,@@innodb_doublewrite;'),
            'max_container_memory_bytes': 1073741824,
            'moved_services': ['agent-fast', 'recommend-fast', 'user'], 'original_database_unchanged': True}
(ROOT / 'nvme-environment.json').write_text(json.dumps(evidence, indent=2))
print('独立 NVMe QA 数据库就绪', len(tables), 'tables; durability', evidence['durability'], flush=True)
