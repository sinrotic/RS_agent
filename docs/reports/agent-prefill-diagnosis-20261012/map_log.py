"""只保存即时编译事件及其请求序号，不保存输入或正文。"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
logfile = Path('/tmp/rs-agent-resume-benchmark-20261011/temporary-quant.log')
ordinal = 0
events = []
for line in logfile.read_text().splitlines():
    if '"POST /v1/chat/completions HTTP/' in line:
        ordinal += 1
    if 'JIT compilation during inference:' in line:
        match = re.search(r'(\d\d-\d\d \d\d:\d\d:\d\d).*inference: ([\w]+)', line)
        if match:
            events.append({'request_ordinal': ordinal, 'time': match[1], 'kernel': match[2]})
report = {'http_model_calls': ordinal, 'jit_events': events,
          'interpretation': '该临时模型只接收本轮新版对照；第1次为预热、第2次为单并发正式样本0'}
(ROOT / 'historical-jit-map.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False))
assert ordinal == 105
assert any(event['request_ordinal'] == 2 and event['kernel'] == '_fused_post_conv_kernel' for event in events)
