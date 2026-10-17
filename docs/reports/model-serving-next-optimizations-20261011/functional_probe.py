"""保留视觉能力和响应协议的真实模型补充验收。"""
import argparse
import base64
import io
import json
from pathlib import Path
import time
import urllib.request
from PIL import Image

ROOT = Path(__file__).resolve().parent

def run(base, label):
    buffer = io.BytesIO()
    Image.new('RGB', (64, 64), (255, 0, 0)).save(buffer, format='PNG')
    request_body = {'model': 'qwen35-4b', 'temperature': 0, 'seed': 0, 'max_tokens': 64,
        'chat_template_kwargs': {'enable_thinking': False}, 'messages': [{'role': 'user', 'content': [
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()}},
            {'type': 'text', 'text': '这张图片主要是什么颜色？只回答中文颜色名称。'}]}]}
    started = time.perf_counter()
    request = urllib.request.Request(base + '/chat/completions', data=json.dumps(request_body).encode(),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=60) as response:
        body = json.load(response)
    choice = body['choices'][0]
    text = choice['message'].get('content') or ''
    assert choice['finish_reason'] == 'stop' and '红' in text, '视觉识别或正常结束回归'
    report = {'label': label, 'vision_passed': True, 'finish_reason': choice['finish_reason'],
        'elapsed_ms': (time.perf_counter() - started) * 1000, 'usage': body['usage'],
        'scope': '真实视觉编码器单一颜色 smoke，不能替代全部视觉任务质量'}
    (ROOT / (label + '-functional.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(label, '视觉烟测通过', flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    run(args.base_url, args.label)
