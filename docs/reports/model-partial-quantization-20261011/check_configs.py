"""只读取 HF 配置，核对位置编码及模型尺寸；不加载任何模型权重。"""
import json
from pathlib import Path
from transformers import AutoConfig

ROOT = Path('/tmp/rs-agent-partial-quantization-20261011')
paths = {'control': '/mnt/data/luo/models/Qwen3.5-4B-INT4-AutoRound-0a857215-rs-runtime',
         'mlp_only': json.loads((ROOT / 'mlp_only-source.json').read_text())['path'],
         'gdn_bf16': json.loads((ROOT / 'gdn_bf16-source.json').read_text())['path']}
keys = ['hidden_size', 'intermediate_size', 'num_hidden_layers', 'num_attention_heads', 'num_key_value_heads',
        'head_dim', 'layer_types', 'rope_parameters', 'max_position_embeddings', 'vocab_size',
        'linear_conv_kernel_dim', 'linear_key_head_dim', 'linear_value_head_dim',
        'linear_num_key_heads', 'linear_num_value_heads', 'rms_norm_eps']
result = {}
for label, path in paths.items():
    config = AutoConfig.from_pretrained(path, local_files_only=True, trust_remote_code=True).text_config
    result[label] = {key: getattr(config, key, None) for key in keys}
assert result['control'] == result['mlp_only'] == result['gdn_bf16']
(ROOT / 'resolved-config-check.json').write_text(json.dumps({'matched': True, 'effective_text_config': result}, indent=2) + '\n')
print('三个候选的位置编码、模型尺寸及 GDN 配置一致；未加载权重', flush=True)
