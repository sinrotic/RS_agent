"""发布前端到指定的现有 QA，拒绝覆盖容器、恢复正式服务或改变模型。"""
import argparse
import hashlib
import json
import re
import socket
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--qa-root', required=True)
    parser.add_argument('--release-dir', required=True)
    args = parser.parse_args()
    root = Path(args.qa_root).resolve()
    release = Path(args.release_dir).resolve()
    assert root == Path('/tmp/rs-agent-e2e-20261010-llm-opt-20261011')
    assert release.parent == root and re.fullmatch(r'frontend-a2ui-20261011-[0-9TZ]+', release.name)
    state_file = root / 'state.json'
    original_state = state_file.read_bytes()
    state = json.loads(original_state)
    assert not state.get('cleaned')
    assert re.fullmatch(r'[0-9a-f]{8}', state['suffix'])
    for label in ('agent-fast', 'gateway', 'catalog', 'recommend-fast', 'user', 'model'):
        obj = json.loads(command('docker', 'inspect', state[label]))[0]
        assert obj['State']['Running'], f'QA service not running: {label}'
    name = 'rs-e2e-' + state['suffix'] + '-a2ui-frontend'
    assert not command('docker', 'ps', '-a', '--filter', 'name=^/' + name + '$', '--format', '{{.Names}}')
    with socket.socket() as check:
        check.bind(('127.0.0.1', 18289))
    expected = json.loads((release / 'manifest.json').read_text())
    for relative, digest in expected['files'].items():
        source = (release / relative).resolve()
        assert source.is_relative_to(release)
        assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    assert (release / 'dist/index.html').is_file()
    image = command('docker', 'image', 'inspect', 'nginx:alpine', '--format', '{{.Id}}')
    command('docker', 'run', '--rm', '--network', 'host', '-v', str(release / 'nginx.conf') + ':/etc/nginx/conf.d/default.conf:ro',
            image, 'nginx', '-t')
    command('docker', 'run', '-d', '--name', name, '--network', 'host', '--restart', 'unless-stopped',
            '--health-cmd', 'wget -q -O /dev/null http://127.0.0.1:18289/healthz',
            '--health-interval', '10s', '--health-timeout', '3s', '--health-retries', '3',
            '-v', str(release / 'dist') + ':/usr/share/nginx/html:ro',
            '-v', str(release / 'nginx.conf') + ':/etc/nginx/conf.d/default.conf:ro', image)
    try:
        for _ in range(20):
            try:
                with urllib.request.urlopen('http://127.0.0.1:18289/healthz', timeout=2) as response:
                    assert response.read().strip() == b'ok'
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError('QA frontend health check failed')
        with urllib.request.urlopen('http://127.0.0.1:18289/', timeout=5) as response:
            assert hashlib.sha256(response.read()).hexdigest() == expected['files']['dist/index.html']
        assert state_file.read_bytes() == original_state, 'QA state changed during deployment'
        state['containers'].append(name)
        state['a2ui-frontend'] = name
        temporary = state_file.with_name('state.a2ui-deploy.tmp')
        temporary.write_text(json.dumps(state, indent=2))
        temporary.replace(state_file)
    except Exception:
        # 仅停止本次新建的前端，保留容器和产物便于排查。
        command('docker', 'stop', name)
        raise
    result = {'deployed_at_utc': datetime.now(timezone.utc).isoformat(), 'qa_root': str(root),
              'release_dir': str(release), 'container': name, 'image_id': image,
              'frontend_url': 'http://127.0.0.1:18289', 'gateway_url': 'http://127.0.0.1:18288',
              'backend_or_model_restarted': False, 'index_sha256': expected['files']['dist/index.html'],
              'rollback': ['docker', 'stop', name]}
    (release / 'deployment.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
