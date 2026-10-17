"""逐 tensor 重打包：复用已校准 INT4，敏感模块取原 BF16，源文件保持完整。"""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import struct

ROOT = Path('/tmp/rs-agent-partial-quantization-20261011')
BASE = Path('/mnt/data/luo/models/Qwen3.5-4B')
QUANT = Path('/mnt/data/luo/models/Qwen3.5-4B-INT4-AutoRound-0a857215-rs-runtime')
SUFFIXES = ('.qweight', '.qzeros', '.scales', '.g_idx')

def inventory(directory):
    index = json.loads((directory / 'model.safetensors.index.json').read_text())['weight_map']
    records = {}
    for filename in sorted(set(index.values())):
        with (directory / filename).open('rb') as handle:
            size = struct.unpack('<Q', handle.read(8))[0]
            assert size < 64 * 1024 * 1024
            header = json.loads(handle.read(size))
        for name, item in header.items():
            if name == '__metadata__':
                continue
            # 发布包含相同 tensor 的重复副本；采用 weight_map 指定的权威分片。
            if index.get(name) != filename:
                continue
            records[name] = {'file': directory / filename, 'header_bytes': 8 + size, **item}
    assert set(records) == set(index)
    return records

def bytes_count(item):
    return item['data_offsets'][1] - item['data_offsets'][0]

def write_shard(target, records):
    header = {'__metadata__': {'format': 'pt'}}
    offset = 0
    for name, item in records:
        count = bytes_count(item)
        header[name] = {'dtype': item['dtype'], 'shape': item['shape'], 'data_offsets': [offset, offset + count]}
        offset += count
    raw = json.dumps(header, separators=(',', ':')).encode()
    raw += b' ' * ((-len(raw)) % 8)
    next_path = target.with_name(target.name + '.next')
    fingerprints = {}
    with next_path.open('xb') as output:
        output.write(struct.pack('<Q', len(raw)))
        output.write(raw)
        for name, item in records:
            digest = hashlib.sha256()
            remaining = bytes_count(item)
            with item['file'].open('rb') as source:
                source.seek(item['header_bytes'] + item['data_offsets'][0])
                while remaining:
                    chunk = source.read(min(8 * 1024 * 1024, remaining))
                    assert chunk
                    output.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
            fingerprints[name] = digest.hexdigest()
    next_path.replace(target)
    # 读回实际写入的 payload，确认没有偏移或复制错误。
    with target.open('rb') as handle:
        size = struct.unpack('<Q', handle.read(8))[0]
        assert json.loads(handle.read(size)) == header
        for name, item in records:
            digest = hashlib.sha256()
            remaining = bytes_count(item)
            while remaining:
                chunk = handle.read(min(8 * 1024 * 1024, remaining))
                assert chunk
                digest.update(chunk)
                remaining -= len(chunk)
            assert digest.hexdigest() == fingerprints[name]
        assert not handle.read(1)
    return fingerprints

def export(mode, base, quant):
    leaf = ('Qwen3.5-4B-INT4-MLP-BF16-sensitive-20261011' if mode == 'mlp_only'
            else 'Qwen3.5-4B-INT4-attn-MLP-BF16-GDN-20261011')
    target = BASE.parent / leaf
    assert not target.exists(), '拒绝覆盖已有模型目录'
    target.mkdir()
    keep = lambda name: name.endswith(SUFFIXES) and ('.mlp.' in name if mode == 'mlp_only' else
                                                     ('.mlp.' in name or '.self_attn.' in name))
    quant_names = {name for name in quant if keep(name)}
    prefixes = {name.rsplit('.', 1)[0] for name in quant_names if name.endswith('.qweight')}
    assert len(prefixes) == (96 if mode == 'mlp_only' else 128)
    selected = {name: item for name, item in base.items() if name.rsplit('.', 1)[0] not in prefixes}
    selected.update({name: quant[name] for name in quant_names})
    assert not any('.linear_attn.' in name and name.endswith(SUFFIXES) for name in selected)
    if mode == 'mlp_only':
        assert not any('.self_attn.' in name and name.endswith(SUFFIXES) for name in selected)
    assert all(item['dtype'] in ['BF16', 'F32'] for name, item in selected.items() if name not in quant_names)
    partitions = []
    chunk = []
    total = 0
    for name, item in sorted(selected.items()):
        count = bytes_count(item)
        if chunk and total + count > 512 * 1024 * 1024:
            partitions.append(chunk)
            chunk, total = [], 0
        chunk.append((name, item))
        total += count
    if chunk:
        partitions.append(chunk)
    weight_map = {}
    fingerprints = {}
    for number, partition in enumerate(partitions, 1):
        filename = f'model-{number:05d}-of-{len(partitions):05d}.safetensors'
        fingerprints.update(write_shard(target / filename, partition))
        weight_map.update({name: filename for name, _ in partition})
    index = {'metadata': {'total_size': sum(bytes_count(item) for item in selected.values())},
             'weight_map': weight_map}
    (target / 'model.safetensors.index.json').write_text(json.dumps(index, indent=2) + '\n')
    config = json.loads((BASE / 'config.json').read_text())
    quant_config = copy.deepcopy(json.loads((QUANT / 'config.json').read_text())['quantization_config'])
    quant_config['block_name_to_quantize'] = [f'model.language_model.layers.{i}.{part}'
        for i in range(32) for part in (['mlp'] if mode == 'mlp_only' else ['mlp', 'self_attn'])]
    quant_config.pop('extra_config', None)
    config['quantization_config'] = quant_config
    (target / 'config.json').write_text(json.dumps(config, indent=2) + '\n')
    manifest = json.loads((Path('/tmp/rs-agent-quantization-retry-20261011') / 'int4-runtime-source.json').read_text())
    assets = {}
    for name in manifest['preserved_assets']:
        shutil.copyfile(BASE / name, target / name)
        assets[name] = hashlib.sha256((target / name).read_bytes()).hexdigest()
        assert assets[name] == manifest['preserved_assets'][name]['sha256']
    reread = inventory(target)
    assert set(reread) == set(selected)
    result = {'mode': mode, 'path': str(target), 'base_path': str(BASE), 'quant_path': str(QUANT),
              'quant_revision': '0a857215cab37e8caa857a053005a73cf98ff2c4',
              'method': '复用已校准 INT4 tensor，其他 tensor 原样取自原 BF16；无反量化恢复或重新校准',
              'int4_modules': len(prefixes), 'bf16_tensors': len(selected) - len(quant_names),
              'tensor_bytes': index['metadata']['total_size'], 'payload_roundtrip_verified': True,
              'asset_sha256': assets, 'tensor_sha256': fingerprints}
    (target / 'hybrid-source.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    (ROOT / (mode + '-source.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print('导出完成', mode, 'INT4 modules=', len(prefixes), 'tensor GiB=', round(index['metadata']['total_size']/2**30, 3), flush=True)

if __name__ == '__main__':
    ROOT.mkdir(exist_ok=True)
    base, quant = inventory(BASE), inventory(QUANT)
    for mode in ['mlp_only', 'gdn_bf16']:
        export(mode, base, quant)
