"""在未参与调参的用户上确认既有推荐 checkpoint；固定候选库，不训练。"""
import argparse
import hashlib
import heapq
import json
import os
from pathlib import Path
import time

import numpy as np
import torch
import torch.nn.functional as F

from three_tower_residual import ResidualTowers, history_tensor, metrics, paired_interval, rows, save


def stream(path):
    with path.open() as source:
        for line in source:
            yield json.loads(line)


def user_hash(uid):
    return hashlib.sha256(uid.encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, nargs="+", required=True)
    parser.add_argument("--users", type=int, default=3000)
    parser.add_argument("--split", choices=["valid", "test"], default="valid")
    args = parser.parse_args()
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "2":
        raise RuntimeError("reserve GPU 2")
    torch.cuda.set_per_process_memory_fraction(.55)
    torch.set_num_threads(4)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "confirmation_source.py").write_bytes(Path(__file__).read_bytes())
    started = time.perf_counter()
    previous = {r["user_hash"] for r in rows(args.data / "rec_valid.jsonl")}
    targets = {}
    window = json.loads((args.source / "manifest.json").read_text())["window_policy"]["splits"]
    cutoff, end = window["train"]["end_ms"], window[args.split]["end_ms"]
    target_start = window[args.split]["start_ms"]
    for r in stream(args.source / f"canonical_interactions.{args.split}.jsonl"):
        if r["label_binary"] != 1 or user_hash(r["user_id"]) in previous:
            continue
        assert target_start <= r["timestamp"] < end
        value = (r["timestamp"], r["parent_asin"])
        uid = r["user_id"]
        if uid not in targets or value < targets[uid]:
            targets[uid] = value
    heap = []
    for r in stream(args.source / "user_sequences.train.jsonl"):
        uid = r["user_id"]
        if uid not in targets:
            continue
        ids, timestamps = r["recent_positive_item_sequence"], r["recent_positive_timestamp_sequence"]
        assert len(ids) == len(timestamps)
        if len(ids) < 3:
            continue
        assert all(t < cutoff for t in timestamps)
        ordering = int(hashlib.sha256(("product-pilot-v3:" + uid).encode()).hexdigest()[:16], 16)
        entry = (-ordering, uid, list(zip(ids, timestamps)))
        if len(heap) < args.users:
            heapq.heappush(heap, entry)
        elif entry[:2] > heap[0][:2]:
            heapq.heapreplace(heap, entry)
    base_items = rows(args.data / "items.jsonl")
    indices = {r["item_id"]: i for i, r in enumerate(base_items)}
    candidate_count = len(base_items)
    missing = {iid for _, _, hist in heap for iid, _ in hist} - indices.keys()
    extra = {}
    print("CONFIRMATION_USERS", len(heap), "extra_history_items", len(missing), flush=True)
    for r in stream(args.source / "canonical_items.jsonl"):
        if r["parent_asin"] in missing:
            parts = [r.get("title_clean", "").strip()[:400]]
            parts.extend(r.get(f, "").strip()[:700] for f in ["features_text", "description_text"] if r.get(f, "").strip())
            extra[r["parent_asin"]] = "\n".join(parts)
    if missing - extra.keys():
        raise ValueError("history metadata missing; do not silently drop users")
    extra_ids = sorted(extra)
    indices.update({iid: candidate_count + i for i, iid in enumerate(extra_ids)})
    from sentence_transformers import SentenceTransformer
    encoder = SentenceTransformer('/home/luo/RS_agent_java/data/models/BAAI/bge-m3', device='cuda', local_files_only=True)
    encoder.half(); encoder.max_seq_length = 256
    encoded = encoder.encode([extra[iid] for iid in extra_ids], batch_size=32, normalize_embeddings=True, show_progress_bar=False, convert_to_numpy=True).astype('float32')
    del encoder
    torch.cuda.empty_cache()
    features = F.normalize(torch.tensor(np.concatenate([np.load(args.data / "item_features.npy"), encoded]), device="cuda"), dim=-1)
    np.save(args.output / "extra_history_features.npy", encoded)
    save(args.output / "extra_history_ids.json", extra_ids)
    validation = []
    for _, uid, hist in sorted(heap, key=lambda v: v[1]):
        ts, target = targets[uid]
        history = sorted(hist, key=lambda x: (x[1], x[0]))[-50:]
        assert target not in {iid for iid, _ in history}
        target_index = indices.get(target, -1)
        validation.append({"user_hash": user_hash(uid), "history": [indices[iid] for iid, _ in history], "history_ts": [t for _, t in history], "target": target_index if 0 <= target_index < candidate_count else -1, "target_ts": ts})
    assert not previous & {r['user_hash'] for r in validation}
    with (args.output / "confirmation_rows.jsonl").open('w') as file:
        for row in validation:
            file.write(json.dumps(row) + '\n')

    @torch.inference_mode()
    def evaluate(model=None):
        item_vectors = features if model is None else torch.cat([model.encode_items(features[s:s + 1024]) for s in range(0, len(features), 1024)])
        ranks = []
        for start in range(0, len(validation), 64):
            batch = validation[start:start + 64]
            ids, mask = history_tensor(batch, 'cuda')
            history = item_vectors[ids]
            u = F.normalize((history * mask.unsqueeze(-1)).sum(1) / mask.sum(1, keepdim=True), dim=-1) if model is None else model.encode_user(history, mask)
            scores = u @ item_vectors[:candidate_count].T
            for j, r in enumerate(batch):
                if r['target'] < 0:
                    ranks.append(0); continue
                scores[j, [i for i in r['history'] if i < candidate_count]] = -torch.inf
                ranks.append(int((scores[j] >= scores[j, r['target']]).sum()))
        return ranks

    base = evaluate()
    result = {'scope': 'FROZEN_CHECKPOINT_OFFICIAL_TEST_TRAIN_ONLY_HISTORY' if args.split == 'test' else 'DISJOINT_USER_CONFIRMATION_SAME_VALID_MONTH_NOT_FINAL_TEST', 'candidate_count': candidate_count, 'previous_users': len(previous), 'confirmation_users': len(validation), 'user_overlap': 0, 'new_history_features_not_candidates': len(extra_ids), 'baseline': metrics(base), 'baseline_ranks': base, 'runs': []}
    for path in args.checkpoint:
        checkpoint = torch.load(path, map_location='cuda', weights_only=True)
        config = checkpoint['config']
        if config['id_dim'] or config.get('history_half_life_days', 0):
            raise ValueError('confirmation currently supports the frozen no-ID uniform-history candidate only')
        model = ResidualTowers(1024, config['hidden']).to('cuda')
        model.load_state_dict(checkpoint['model']); model.eval()
        actual = evaluate(model)
        result['runs'].append({'checkpoint': str(path), 'checkpoint_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'seed': config['seed'], 'step': checkpoint['step'], 'metrics': metrics(actual), 'ranks': actual, 'vs_baseline': paired_interval(base, actual)})
        print('CONFIRMED', config['seed'], metrics(actual), flush=True)
    a = np.array([r['ranks'] for r in result['runs']]); b = np.array(base)
    hit = (a > 0) & (a <= 100); base_hit = (b > 0) & (b <= 100)
    delta = hit.mean(0) - base_hit
    rng = np.random.default_rng(20261011)
    interval = np.quantile([rng.choice(delta, len(delta), replace=True).mean() for _ in range(2000)], [.025, .975])
    result['seed_mean'] = {'hit@100': float(hit.mean()), 'delta': float(delta.mean()), 'paired_user_95pct': interval.tolist(), 'note': 'fixed checkpoint runs averaged before user bootstrap; not seed-population uncertainty'}
    result['seconds'] = time.perf_counter() - started
    result['peak_cuda_gib'] = torch.cuda.max_memory_allocated() / 2**30
    result['script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    save(args.output / 'results.json', result)
    print('COMPLETE', result['seed_mean'], flush=True)


if __name__ == '__main__':
    main()
