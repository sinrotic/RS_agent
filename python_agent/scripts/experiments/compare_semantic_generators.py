"""20 商品同提示词对照；凭据仅从服务器已有部署配置读取。"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import time
import urllib.request
import urllib.error


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--config', type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    config = {}
    for line in args.config.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            config[key] = value.strip().strip('"\'')
    # 提取历史生成脚本的表达式，保持逐字相同的提示词。
    tree = ast.parse((args.source / 'three_tower_smoke.py').read_text())
    generator = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'generate')
    assignment = next(n for n in ast.walk(generator) if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'prompt' for t in n.targets))
    prompt_code = compile(ast.Expression(assignment.value), '<historical-prompt>', 'eval')
    originals = [json.loads(s) for s in (args.source / 'generation_raw.jsonl').read_text().splitlines()]
    ids = list(dict.fromkeys(r['item_id'] for r in originals))
    assert len(ids) == 20 and len(originals) == 40
    by_id = {r['item_id']: r for r in map(json.loads, (args.source / 'generation_inputs.jsonl').read_text().splitlines())}
    results = []
    start = time.perf_counter()
    for item_id in ids:
        item = by_id[item_id]
        for language in ['zh', 'en']:
            prompt = eval(prompt_code, {'json': json, 'item': item, 'language': language})
            payload = {'model': 'gpt-6-luna', 'messages': [{'role': 'user', 'content': prompt}],
                       'temperature': 0, 'max_tokens': 200, 'stream': False}
            req = urllib.request.Request(config['RS_AGENT_OPENAI_BASE_URL'].rstrip('/') + '/chat/completions',
                data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0', 'Authorization': 'Bearer ' + config['RS_AGENT_API_KEY']})
            t = time.perf_counter()
            try:
                with urllib.request.urlopen(req, timeout=60) as response:
                    data = json.load(response)
            except urllib.error.HTTPError as exc:
                raise RuntimeError(f'HTTP {exc.code}; stopped without retry') from None
            if data.get('model') != 'gpt-6-luna':
                raise RuntimeError('Unexpected returned model; stopped')
            choice = data['choices'][0]
            results.append({'item_id': item_id, 'requested_language': language,
                'output': choice['message']['content'], 'returned_model': data['model'],
                'finish_reason': choice['finish_reason'], 'usage': data.get('usage'),
                'seconds': time.perf_counter()-t, 'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest()})
            (args.output / 'luna_raw.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in results))
        print('completed_products', len(results)//2, flush=True)
    summary = {'requested_model': 'gpt-6-luna', 'returned_model': 'gpt-6-luna',
        'model_identity_note': 'API response label only; backend identity not independently verified',
        'products': 20, 'queries': len(results), 'seconds': time.perf_counter()-start,
        'same_historical_prompt': True, 'temperature': 0, 'max_tokens': 200,
        'human_reviewed': False,
        'source_sha256': {n: hashlib.sha256((args.source/n).read_bytes()).hexdigest()
            for n in ['generation_inputs.jsonl','generation_raw.jsonl','three_tower_smoke.py']},
        'usage': {k: sum((r['usage'] or {}).get(k,0) for r in results)
            for k in ['prompt_tokens','completion_tokens','total_tokens']}}
    (args.output/'luna_metrics.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
