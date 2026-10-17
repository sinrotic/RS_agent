"""仅同步白名单公开报告；私有提示词、凭据和原始日志留在远端。"""
import json
from pathlib import Path
import shlex
import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent
REMOTE = '/tmp/rs-serving-next-optimization-20261011'
SUFFIXES = ('-state.json', '-performance.json', '-model.json', '-functional.json',
            '-planning.json', '-business.json', '-business-cleanup.json', '-prefix.json', '-selection.json')
EXACT = {'selection.json', 'warmup-selection.json'}
code = (
    "import json; from pathlib import Path; root=Path(" + repr(REMOTE) + "); "
    "suffixes=" + repr(SUFFIXES) + "; exact=" + repr(EXACT) + "; "
    "files={p.name:p.read_text() for p in root.glob('*.json') "
    "if (p.name.endswith(suffixes) or p.name in exact) and '.private.' not in p.name}; "
    "print(json.dumps(files,ensure_ascii=False))"
)
result = subprocess.run(['ssh', 'server', 'python3 -c ' + shlex.quote(code)], check=True,
                        capture_output=True, encoding='utf-8', timeout=90)
assert len(result.stdout.encode()) < 8 * 1024 * 1024
files = json.loads(result.stdout)
for name, contents in files.items():
    assert Path(name).name == name and '.private.' not in name
    assert name.endswith(SUFFIXES) or name in EXACT
    json.loads(contents)
    (ROOT / name).write_text(contents, encoding='utf-8')
assert not list(ROOT.glob('*.private.*'))
print('公开报告同步', len(files), '个；未同步凭据、原始请求或日志')
