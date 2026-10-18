"""只接收本次隔离网络内的合成告警，报告不保存告警负载或身份。"""
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import json


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        if self.path != '/alerts' or not 0 < length <= 65536:
            self.send_error(400); return
        payload = json.loads(self.rfile.read(length))
        alerts = payload.get('alerts', [])
        if any(alert.get('labels', {}).get('alertname') == 'CommerceIntegrationNotification' for alert in alerts):
            Path('/output/notification-receipt.json').write_text(json.dumps({'received': True, 'synthetic': True}))
        self.send_response(200); self.end_headers()

    def log_message(self, *args): pass


if __name__ == '__main__': HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
