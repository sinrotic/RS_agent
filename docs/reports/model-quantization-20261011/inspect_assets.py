"""只记录量化模型与原模型的分词及结构兼容性，不输出私有请求。"""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path('/tmp/rs-agent-quantization-retry-20261011')
original = Path('/mnt/data/luo/models/Qwen3.5-4B')
source = json.loads((ROOT / 'int4-source.json').read_text())
quantized = Path(source['path'])

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

old = json.loads((original / 'tokenizer.json').read_text())
new = json.loads((quantized / 'tokenizer.json').read_text())
differences = [key for key in set(old) | set(new) if old.get(key) != new.get(key)]
report = {
    'chat_template_identical': digest(original / 'chat_template.jinja') == digest(quantized / 'chat_template.jinja'),
    'tokenizer_byte_identical': digest(original / 'tokenizer.json') == digest(quantized / 'tokenizer.json'),
    'tokenizer_different_sections': sorted(differences),
    'tokenizer_section_equal': {key: old.get(key) == new.get(key) for key in sorted(set(old) | set(new))},
    'tokenizer_model_different_keys': [key for key in sorted(set(old['model']) | set(new['model']))
                                      if old['model'].get(key) != new['model'].get(key)],
}
old_config = json.loads((original / 'tokenizer_config.json').read_text())
new_config = json.loads((quantized / 'tokenizer_config.json').read_text())
report['tokenizer_config_differences'] = {key: {'old': old_config.get(key), 'new': new_config.get(key)}
    for key in sorted(set(old_config) | set(new_config))
    if old_config.get(key) != new_config.get(key) and key not in ['chat_template', 'added_tokens_decoder']}
from transformers import AutoTokenizer
a = AutoTokenizer.from_pretrained(original, trust_remote_code=False)
b = AutoTokenizer.from_pretrained(quantized, trust_remote_code=False)
samples = ['推荐办公鼠标，预算300元。', '129×2+20=278', '<|im_start|>assistant\n',
           '<tool_call>\n{"name":"report_result","arguments":{"advice":"选择轻便背包"}}\n</tool_call>',
           '你好，hello world! 😀\n\t12.50元', '<think></think><|im_end|>']
report['effective_vocab_identical'] = a.get_vocab() == b.get_vocab()
report['special_tokens_identical'] = a.special_tokens_map == b.special_tokens_map
effective_old = json.loads(a.backend_tokenizer.to_str())
effective_new = json.loads(b.backend_tokenizer.to_str())
report['effective_tokenizer_identical'] = effective_old == effective_new
report['effective_different_sections'] = [key for key in effective_old if effective_old.get(key) != effective_new.get(key)]
report['effective_section_differences'] = {key: {'old': effective_old.get(key), 'new': effective_new.get(key)}
    for key in report['effective_different_sections'] if key not in ['model', 'added_tokens']}
old_tokens = {t['id']: t for t in effective_old['added_tokens']}
new_tokens = {t['id']: t for t in effective_new['added_tokens']}
report['effective_added_token_differences'] = [{'old': old_tokens.get(i), 'new': new_tokens.get(i)}
    for i in sorted(set(old_tokens) | set(new_tokens)) if old_tokens.get(i) != new_tokens.get(i)]
old_merges = effective_old['model']['merges']
new_merges = effective_new['model']['merges']
report['merge_lengths'] = [len(old_merges), len(new_merges)]
report['effective_model_different_keys'] = [key for key in effective_old['model']
    if effective_old['model'].get(key) != effective_new['model'].get(key)]
report['first_merge_differences'] = [{'index': i, 'old': x, 'new': y}
    for i, (x, y) in enumerate(zip(old_merges, new_merges)) if x != y][:6]
report['sample_ids_identical'] = [a.encode(s) == b.encode(s) for s in samples]
state = json.loads((ROOT / 'w8a16_middle_restart2-state.json').read_text())
config = json.loads(state['configuration']['VLLM_QUANTIZATION_CONFIG'])
edge = config['ignore'][-1].removeprefix('re:')
report['w8_edge_exclusion'] = {str(i): bool(re.match(edge, f'model.layers.{i}.mlp.gate_up_proj')) for i in [0, 7, 8, 23, 24, 31]}
report['compatible'] = all([report['chat_template_identical'], report['effective_tokenizer_identical'], report['effective_vocab_identical'],
                            report['special_tokens_identical'], all(report['sample_ids_identical'])])
(ROOT / 'asset-compatibility.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False, indent=2))
assert report['compatible'], '分词协议不一致，停止推广 INT4'
