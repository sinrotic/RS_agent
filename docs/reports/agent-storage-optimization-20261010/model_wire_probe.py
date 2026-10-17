"""仅记录模型调用的长度、结束原因与工具名；不记录提示词或回答内容。"""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time

ROOT = Path('/tmp/rs-agent-e2e-20261010-storage-opt')
LOCK = threading.Lock()

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *args): pass
    def do_POST(self): self.forward()
    def do_GET(self): self.forward()
    def forward(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        request = json.loads(body) if body else {}
        begin = time.time()
        metadata = {'epoch_ms': begin * 1000, 'path': self.path,
                    'max_tokens': request.get('max_tokens', request.get('max_completion_tokens')),
                    'messages_chars': [len(str(m.get('content', ''))) for m in request.get('messages', [])],
                    'tool_choice': request.get('tool_choice'), 'finish_reasons': [], 'tool_names': [],
                    'tool_argument_chars': 0}
        upstream = http.client.HTTPConnection('127.0.0.1', 18082, timeout=180)
        try:
            upstream.request(self.command, self.path, body=body, headers={'Content-Type': 'application/json'})
            response = upstream.getresponse(); metadata['http_status'] = response.status
            self.send_response(response.status)
            self.send_header('Content-Type', response.getheader('Content-Type', 'application/json'))
            self.send_header('Connection', 'close'); self.end_headers()
            if request.get('stream'):
                while line := response.readline():
                    if line.startswith(b'data: ') and line.strip() != b'data: [DONE]':
                        chunk = json.loads(line[6:])
                        for choice in chunk.get('choices', []):
                            if choice.get('finish_reason'): metadata['finish_reasons'].append(choice['finish_reason'])
                            for call in choice.get('delta', {}).get('tool_calls', []):
                                function = call.get('function', {})
                                if function.get('name'): metadata['tool_names'].append(function['name'])
                                metadata['tool_argument_chars'] += len(function.get('arguments', ''))
                        if chunk.get('usage'): metadata['usage'] = chunk['usage']
                    self.wfile.write(line); self.wfile.flush()
            else:
                self.wfile.write(response.read())
        except (BrokenPipeError, ConnectionResetError):
            metadata['downstream_closed'] = True
        finally:
            upstream.close(); self.close_connection = True
            metadata['elapsed_ms'] = (time.time() - begin) * 1000
            with LOCK:
                with (ROOT / 'model-wire.jsonl').open('a') as output: output.write(json.dumps(metadata) + '\n')

if __name__ == '__main__': ThreadingHTTPServer(('127.0.0.1', 18217), Handler).serve_forever()
