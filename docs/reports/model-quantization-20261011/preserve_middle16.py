"""在下一次正式验收写入前，保存上一候选的私有完整业务证据。"""
import json
from pathlib import Path
import shutil

root = Path(__file__).resolve().parent
source = root / 'production-after-business.private.json'
target = root / 'production-middle16-business.private.json'
assert not target.exists()
rows = json.loads(source.read_text())
assert abs(rows[0]['agent_done_ms'] - 4815.21) < 0.01
shutil.copyfile(source, target); target.chmod(0o600)
print('上一候选私有证据已另存，未导出请求正文', flush=True)
