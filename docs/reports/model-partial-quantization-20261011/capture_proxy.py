"""只为本次 Java 实例转发本地模型请求，私有捕获仅含 payload 与工具返回。"""
import itertools
import json
import os
from pathlib import Path
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.error
import urllib.request

ROOT = Path('/tmp/rs-agent-partial-quantization-20261011')
counter = itertools.count()
lock = threading.Lock()

def private_write(path, data):
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w') as handle:
        json.dump(data, handle, ensure_ascii=False)
        handle.write('\n')

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.forward(None)

    def do_POST(self):
        count = int(self.headers['Content-Length'])
        assert count <= 16 * 1024 * 1024
        self.forward(self.rfile.read(count))

    def forward(self, body):
        phase = json.loads((ROOT / 'proxy-phase.json').read_text())
        assert phase['port'] in [18082, 18092] and re.fullmatch('[a-z0-9_-]+', phase['label'])
        assert self.path.startswith('/v1/') or self.path == '/health'
        with lock:
            ordinal = next(counter)
        capture = {'phase': phase['label'], 'ordinal': ordinal}
        if body:
            capture['payload'] = json.loads(body)
        request = urllib.request.Request(f"http://127.0.0.1:{phase['port']}" + self.path, data=body,
                    headers={'Content-Type': 'application/json', 'Accept': self.headers.get('Accept', '*/*')})
        calls = {}
        pending = b''
        raw = bytearray()
        try:
            try:
                upstream = urllib.request.urlopen(request, timeout=180)
            except urllib.error.HTTPError as error:
                upstream = error
            with upstream:
                capture['upstream_status'] = upstream.status
                self.send_response(upstream.status)
                content_type = upstream.headers.get('Content-Type', 'application/json')
                self.send_header('Content-Type', content_type)
                self.send_header('Connection', 'close')
                self.end_headers()
                self.close_connection = True
                while True:
                    chunk = upstream.read1(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    if not body:
                        continue
                    if 'event-stream' not in content_type:
                        assert len(raw) + len(chunk) <= 8 * 1024 * 1024
                        raw.extend(chunk)
                        continue
                    pending += chunk
                    while b'\n' in pending:
                        line, pending = pending.split(b'\n', 1)
                        if not line.startswith(b'data:') or line[5:].strip() == b'[DONE]':
                            continue
                        event = json.loads(line[5:].strip())
                        if event.get('usage'):
                            capture['usage'] = event['usage']
                        for choice in event.get('choices', []):
                            if choice.get('finish_reason'):
                                capture['finish_reason'] = choice['finish_reason']
                            for call in choice.get('delta', {}).get('tool_calls', []):
                                value = calls.setdefault(call.get('index', 0), {'name': '', 'arguments': ''})
                                value['name'] += call.get('function', {}).get('name', '')
                                value['arguments'] += call.get('function', {}).get('arguments', '')
                if body and raw and upstream.status == 200:
                    event = json.loads(raw)
                    capture['usage'] = event.get('usage')
                    choices = event.get('choices', [])
                    if choices:
                        capture['finish_reason'] = choices[0].get('finish_reason')
                        for number, call in enumerate(choices[0].get('message', {}).get('tool_calls', [])):
                            calls[number] = call['function']
        except Exception as error:
            capture['capture_error_type'] = type(error).__name__
            self.close_connection = True
        finally:
            if body:
                capture['tool_calls'] = list(calls.values())
                directory = ROOT / 'capture'
                directory.mkdir(mode=0o700, exist_ok=True)
                private_write(directory / f'{phase["label"]}-{ordinal:06d}.private.json', capture)

if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 18094), Handler).serve_forever()
