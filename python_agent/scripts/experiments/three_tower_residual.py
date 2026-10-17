"""商品三塔残差实验；冻结特征，先运行推荐单任务门禁。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import time

import numpy as np
import torch
from torch import nn
import torch.nn.functional as F


def rows(path):
    with Path(path).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def save(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class Adapter(nn.Module):
    def __init__(self, dimension=1024, hidden=256):
        super().__init__()
        self.layers = nn.Sequential(nn.Linear(dimension, hidden), nn.ReLU(), nn.Linear(hidden, dimension))
        nn.init.zeros_(self.layers[-1].weight)
        nn.init.zeros_(self.layers[-1].bias)

    def forward(self, x):
        return self.layers(x)


class ResidualTowers(nn.Module):
    def __init__(self, dimension=1024, hidden=256, item_count=0, id_dim=0):
        super().__init__()
        self.item = Adapter(dimension, hidden)
        self.user = Adapter(dimension, hidden)
        self.query = Adapter(dimension, hidden)
        self.id_embedding = nn.Embedding(item_count, id_dim) if id_dim else None
        self.id_projection = nn.Linear(id_dim, dimension, bias=False) if id_dim else None
        if id_dim:
            nn.init.normal_(self.id_embedding.weight, std=.01)
            nn.init.zeros_(self.id_projection.weight)

    def encode_items(self, features, ids=None):
        result = features + self.item(features)
        if self.id_embedding is not None:
            if ids is None:
                raise ValueError("ID branch requires IDs; use -1 for OOV")
            known = (ids >= 0) & (ids < self.id_embedding.num_embeddings)
            safe_ids = ids.clamp(0, self.id_embedding.num_embeddings - 1)
            result = result + self.id_projection(self.id_embedding(safe_ids)) * known.unsqueeze(-1)
        return F.normalize(result, dim=-1)

    def encode_user(self, history_vectors, mask):
        lengths = mask.sum(1, keepdim=True)
        if bool((lengths == 0).any()):
            raise ValueError("empty history must use cold-start fallback")
        mean = (history_vectors * mask.unsqueeze(-1)).sum(1) / lengths
        return F.normalize(mean + self.user(mean), dim=-1)

    def encode_query(self, features):
        return F.normalize(features + self.query(features), dim=-1)


def history_tensor(batch, device, half_life_days=0.):
    width = max(len(r["history"]) for r in batch)
    ids = torch.tensor([r["history"] + [0] * (width - len(r["history"])) for r in batch], device=device)
    mask = torch.tensor([[1.] * len(r["history"]) + [0.] * (width - len(r["history"])) for r in batch], device=device)
    if half_life_days:
        weights = []
        for r in batch:
            ts = r["history_ts"]
            if len(ts) != len(r["history"]):
                raise ValueError("history timestamps misaligned")
            latest = max(ts)
            weights.append([2 ** (-(latest - t) / (86400000 * half_life_days)) for t in ts] + [0.] * (width - len(ts)))
        mask = torch.tensor(weights, device=device)
    return ids, mask


def negatives(rng, target, blocked, count, n, explicit=()):
    blocked = set(blocked) | {target}
    result = []
    for i in explicit:
        if i not in blocked and len(result) < min(4, count):
            result.append(i); blocked.add(i)
    if n - len(blocked) < count - len(result):
        raise ValueError("not enough distinct negative candidates")
    while len(result) < count:
        i = rng.randrange(n)
        if i not in blocked:
            result.append(i); blocked.add(i)
    return [target] + result


def metrics(ranks):
    ranks = np.asarray(ranks)
    covered = ranks > 0
    ranks = np.where(covered, ranks, np.inf)
    return {"count": len(ranks), **{f"hit@{k}": float((ranks <= k).mean()) for k in [10, 50, 100]},
            "target_coverage": float(covered.mean()), "mrr": float((1 / ranks).mean()), "ndcg@100": float(np.where(ranks <= 100, 1 / np.log2(ranks + 1), 0).mean())}


def paired_interval(base, actual, seed=20261011):
    actual, base = np.asarray(actual), np.asarray(base)
    delta = ((actual > 0) & (actual <= 100)).astype(float) - ((base > 0) & (base <= 100))
    rng = np.random.default_rng(seed)
    boot = [rng.choice(delta, len(delta), replace=True).mean() for _ in range(2000)]
    return {"hit@100_delta": float(delta.mean()), "paired_95pct": np.quantile(boot, [.025, .975]).tolist(),
            "unit": "one target per user", "selection_adjusted": False}


def run(args):
    torch.set_num_threads(4)
    device = args.device
    if device == "cuda":
        if os.environ.get("CUDA_VISIBLE_DEVICES") != "2":
            raise RuntimeError("reserve physical GPU 2 only")
        torch.cuda.set_per_process_memory_fraction(.60)
    out = args.output
    out.mkdir(parents=True, exist_ok=False)
    (out / "training_source.py").write_bytes(Path(__file__).read_bytes())
    features = F.normalize(torch.tensor(np.load(args.data / "item_features.npy"), device=device), dim=-1)
    train = rows(args.data / "rec_train.jsonl")
    valid = rows(args.data / "rec_valid.jsonl")
    if len({r["user_hash"] for r in valid}) != len(valid):
        raise ValueError("evaluation expects one target per user")
    sem, queries, st, sv, known_sem = [], None, [], [], {}
    if args.mode != "rec" or args.semantic_eval:
        sem = rows(args.data / "semantic_clean.jsonl")
        queries = F.normalize(torch.tensor(np.load(args.data / "query_features.npy"), device=device), dim=-1)
        st = [i for i, r in enumerate(sem) if r["split"] == "train"]
        sv = [i for i, r in enumerate(sem) if r["split"] == "valid"]
        for i in st:
            known_sem.setdefault(sem[i]["query"].strip().lower(), set()).add(sem[i]["item_index"])
        if not st or not sv:
            raise ValueError("semantic train and holdout required")
    torch.manual_seed(args.seed)
    model = ResidualTowers(features.shape[1], args.hidden, len(features), args.id_dim).to(device)
    if args.freeze_item:
        for part in [model.item, model.id_embedding, model.id_projection]:
            if part is not None:
                part.requires_grad_(False)
    parameters = [{"params": [p for name, p in model.named_parameters() if name != "id_embedding.weight"
                              and not (args.query_lr is not None and name.startswith("query."))], "weight_decay": .01}]
    if args.query_lr is not None:
        parameters.append({"params": model.query.parameters(), "lr": args.query_lr, "weight_decay": .01})
    if model.id_embedding is not None:
        parameters.append({"params": model.id_embedding.parameters(), "weight_decay": 0.})
    optimizer = torch.optim.AdamW(parameters, lr=args.lr)
    rrng, srng = random.Random(args.seed + 1), random.Random(args.seed)

    @torch.inference_mode()
    def evaluate(base=False, check_initial=False):
        model.eval()
        item_v = features if base else torch.cat([model.encode_items(features[s:s + 1024], torch.arange(s, min(s + 1024, len(features)), device=device)) for s in range(0, len(features), 1024)])
        rec_ranks, sem_ranks, score_error = [], [], 0.
        for offset in range(0, len(valid), 64):
            batch = valid[offset:offset + 64]
            ids, mask = history_tensor(batch, device, args.history_half_life_days)
            if base:
                u = F.normalize((item_v[ids] * mask.unsqueeze(-1)).sum(1) / mask.sum(1, keepdim=True), dim=-1)
            else:
                u = model.encode_user(item_v[ids], mask)
            scores = u @ item_v.T
            if check_initial:
                reference_user = F.normalize((features[ids] * mask.unsqueeze(-1)).sum(1) / mask.sum(1, keepdim=True), dim=-1)
                score_error = max(score_error, float((scores - reference_user @ features.T).abs().max()))
            for j, r in enumerate(batch):
                if r["target"] < 0:
                    rec_ranks.append(0)  # 库外目标保留在分母，MRR/Hit/nDCG 均为零。
                    continue
                if r["target"] in r["history"]:
                    raise ValueError("held-out target in history")
                scores[j, r["history"]] = -torch.inf
                # 保守处理相同分数，不用任意候选排列让平局偏向目标。
                rec_ranks.append(int((scores[j] >= scores[j, r["target"]]).sum()))
        for offset in range(0, len(sv), 64):
            selected = sv[offset:offset + 64]
            q = queries[selected] if base else model.encode_query(queries[selected])
            scores = q @ item_v.T
            for j, i in enumerate(selected):
                sem_ranks.append(int((scores[j] >= scores[j, sem[i]["item_index"]]).sum()))
        result = {"rec": metrics(rec_ranks), "rec_ranks": rec_ranks}
        if check_initial:
            result["max_score_error_vs_bge"] = score_error
        if sem_ranks:
            result.update(semantic_source_proxy=metrics(sem_ranks), semantic_ranks=sem_ranks)
        return result

    def loss_for(task, batch, rng):
        if task == "rec":
            candidates = [negatives(rng, r["target"], r["known_train_positives"], args.negatives, len(features), r.get("explicit_negatives", []) if args.explicit_negatives else ()) for r in batch]
            history_ids, mask = history_tensor(batch, device, args.history_half_life_days)
        else:
            candidates = [negatives(rng, sem[i]["item_index"], known_sem[sem[i]["query"].strip().lower()], args.negatives, len(features)) for i in batch]
        candidates = torch.tensor(candidates, device=device)
        combined = torch.cat([candidates.flatten(), history_ids.flatten()]) if task == "rec" else candidates.flatten()
        unique, inverse = torch.unique(combined, return_inverse=True)
        encoded = model.encode_items(features[unique], unique)
        candidate_v = encoded[inverse[:candidates.numel()]].view(*candidates.shape, -1)
        if task == "rec":
            history_v = encoded[inverse[candidates.numel():]].view(*history_ids.shape, -1)
            request = model.encode_user(history_v, mask)
        else:
            request = model.encode_query(queries[batch])
        logits = torch.einsum("bd,bnd->bn", request, candidate_v) / .07
        return F.cross_entropy(logits, torch.zeros(len(batch), dtype=torch.long, device=device))

    baseline = evaluate(base=True)
    initial = evaluate(check_initial=True)
    with torch.no_grad():
        check = model.encode_items(features[:32], torch.arange(min(32, len(features)), device=device))
        assert torch.allclose(check, features[:32], atol=2e-6)
    # 浮点重新归一化会拆开极近分数或平局；以全候选分数误差判定数值等价，并保留排名差异。
    initial["rank_difference_count"] = sum(a != b for a, b in zip(initial["rec_ranks"], baseline["rec_ranks"]))
    if initial["max_score_error_vs_bge"] > 2e-6:
        raise AssertionError("initial scores differ materially from frozen BGE baseline")
    result = {"scope": "BOUNDED_REC_EXPERIMENT_NOT_PRODUCTION", "config": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
              "baseline": baseline, "initial": initial, "candidate_count": len(features), "rec_train_count": len(train),
              "semantic_train_count": len(st), "checkpoints": [], "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    result["input_sha256"] = {name: hashlib.sha256((args.data / name).read_bytes()).hexdigest()
                              for name in ["item_features.npy", "rec_train.jsonl", "rec_valid.jsonl"]}
    if sem:
        result["input_sha256"].update({name: hashlib.sha256((args.data / name).read_bytes()).hexdigest()
                                       for name in ["query_features.npy", "semantic_clean.jsonl"]})
    save(out / "results.json", result)
    print("INITIAL", baseline["rec"], flush=True)
    start = time.perf_counter()
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    semantic_updates = 0
    for step in range(1, args.steps + 1):
        model.train(); optimizer.zero_grad(set_to_none=True)
        losses = {}
        if args.mode in ("rec", "joint"):
            loss = loss_for("rec", rrng.choices(train, k=args.batch_size), rrng)
            loss.backward(); losses["rec"] = float(loss.detach())
            assert all(p.grad is None for p in model.query.parameters())
        if args.mode == "semantic" or (args.mode == "joint" and step % args.semantic_every == 0):
            loss = loss_for("semantic", srng.choices(st, k=args.batch_size), srng)
            (args.semantic_weight * loss).backward(); losses["semantic"] = float(loss.detach())
            semantic_updates += 1
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5)
        optimizer.step()
        if step % args.eval_every == 0 or step == args.steps:
            evaluation = evaluate()
            comparison = paired_interval(baseline["rec_ranks"], evaluation["rec_ranks"])
            record = {"step": step, "loss": losses, "evaluation": evaluation, "vs_baseline": comparison,
                      "elapsed_seconds": time.perf_counter() - start, "semantic_updates": semantic_updates}
            result["checkpoints"].append(record)
            save(out / "results.json", result)
            torch.save({"model": model.state_dict(), "config": result["config"], "step": step}, out / f"step_{step}.pt")
            print("EVAL", step, losses, evaluation["rec"], comparison, flush=True)
    result["peak_cuda_allocated_gib"] = torch.cuda.max_memory_allocated() / 2**30 if device == "cuda" else None
    result["seconds"] = time.perf_counter() - start
    save(out / "results.json", result)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--mode", choices=["rec", "semantic", "joint"], default="rec")
    p.add_argument("--steps", type=int, default=200)
    p.add_argument("--eval-every", type=int, default=50)
    p.add_argument("--lr", type=float, default=2e-5)
    p.add_argument("--query-lr", type=float, default=None)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--hidden", type=int, default=256)
    p.add_argument("--id-dim", type=int, default=0)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--negatives", type=int, default=32)
    p.add_argument("--semantic-weight", type=float, default=1.)
    p.add_argument("--semantic-every", type=int, default=1, help="joint only: one semantic batch per N recommendation steps")
    p.add_argument("--semantic-eval", action="store_true", help="evaluate fixed semantic proxy during rec-only control")
    p.add_argument("--explicit-negatives", action="store_true")
    p.add_argument("--freeze-item", action="store_true")
    p.add_argument("--history-half-life-days", type=float, default=0.)
    p.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    args = p.parse_args()
    if args.semantic_every < 1:
        p.error("--semantic-every must be positive")
    run(args)


if __name__ == "__main__":
    main()
