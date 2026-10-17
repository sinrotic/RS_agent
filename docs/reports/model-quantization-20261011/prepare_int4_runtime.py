"""保留原服务分词/处理器资产，量化权重保持固定下载版本不变。"""
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path('/tmp/rs-agent-quantization-retry-20261011')
source = json.loads((ROOT / 'int4-source.json').read_text())
checkpoint = Path(source['path'])
original = Path('/mnt/data/luo/models/Qwen3.5-4B')
target = checkpoint.with_name(checkpoint.name + '-rs-runtime')
if target.exists():
    # 允许续写本脚本已复制的目录，但逐项确认来源，拒绝改动未知内容。
    for existing in target.iterdir():
        assert existing.is_file()
        if existing.is_symlink():
            assert existing.resolve() == checkpoint / existing.name
        else:
            candidates = [p for p in [original / existing.name, checkpoint / existing.name] if p.is_file()]
            digest = hashlib.sha256(existing.read_bytes()).hexdigest()
            assert any(hashlib.sha256(p.read_bytes()).hexdigest() == digest for p in candidates)
else:
    target.mkdir()
files = {}
for path in checkpoint.iterdir():
    if path.is_file() and path.suffix in ['.json', '.safetensors', '.jinja', '.txt']:
        if path.suffix == '.safetensors':
            if not (target / path.name).exists():
                (target / path.name).symlink_to(path)
        else:
            shutil.copyfile(path, target / path.name)
for name in ['tokenizer.json', 'tokenizer_config.json', 'chat_template.jinja',
             'preprocessor_config.json', 'processor_config.json', 'video_preprocessor_config.json',
             'generation_config.json', 'merges.txt', 'vocab.json']:
    path = original / name
    if path.is_file():
        shutil.copyfile(path, target / name)
        files[name] = {'source': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
from transformers import AutoTokenizer
a = AutoTokenizer.from_pretrained(original, trust_remote_code=False)
b = AutoTokenizer.from_pretrained(target, trust_remote_code=False)
assert a.get_vocab() == b.get_vocab()
assert a.chat_template == b.chat_template
assert json.loads(a.backend_tokenizer.to_str()) == json.loads(b.backend_tokenizer.to_str())
result = {'repo_id': source['repo_id'], 'revision': source['revision'], 'path': str(target),
          'checkpoint_path': str(checkpoint), 'preserved_assets': files,
          'effective_tokenizer_identical': True, 'chat_template_identical': True,
          'weights_changed': False}
(ROOT / 'int4-runtime-source.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(result, ensure_ascii=False, indent=2))
