"""全量训练交互流式统计，抽取小画像快照；热度不在小快照上重新计算。"""

import hashlib
import json
import math
import random
import re
from collections import Counter
from pathlib import Path

from .dataset import fingerprint


def _scan(path, consume, progress=None):
    digest, count, first, last = hashlib.sha256(), 0, None, None
    with Path(path).open("rb") as stream:
        for raw in stream:
            digest.update(raw)
            row = json.loads(raw)
            if any(
                not isinstance(row.get(key), str) or not row[key]
                for key in ("user_id", "parent_asin")
            ):
                raise ValueError("交互标识无效")
            timestamp, rating = row.get("timestamp"), row.get("rating")
            if (
                type(timestamp) is not int
                or timestamp < 0
                or type(rating) not in {int, float}
                or not math.isfinite(rating)
            ):
                raise ValueError("交互时间/评分无效")
            consume({key: row[key] for key in ("user_id", "parent_asin", "timestamp", "rating")})
            first = timestamp if first is None else min(first, timestamp)
            last = timestamp if last is None else max(last, timestamp)
            count += 1
            if progress and count % 500000 == 0:
                progress({"phase": "scan", "file": Path(path).name, "rows": count})
    if not count:
        raise ValueError(f"交互文件为空：{path}")
    return {
        "path": str(Path(path).resolve()),
        "rows": count,
        "sha256": digest.hexdigest(),
        "complete": True,
        "min_timestamp": first,
        "max_timestamp": last,
    }


def _quantiles(counts, lower, upper):
    values = sorted(counts)
    if not values:
        raise ValueError("历史能力门槛筛选后总体为空")
    return [values[math.floor((len(values) - 1) * q)] for q in (lower, upper)]


def _write_rows(path, rows):
    digest, count = hashlib.sha256(), 0
    with Path(path).open("xb") as stream:
        for row in rows:
            encoded = (
                json.dumps(
                    row, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
                )
                + "\n"
            ).encode("utf-8")
            stream.write(encoded)
            digest.update(encoded)
            count += 1
    return {
        "path": str(Path(path).resolve()),
        "rows": count,
        "sha256": digest.hexdigest(),
        "complete": True,
    }


def prepare_population(
    history_source,
    target_sources,
    out_dir,
    *,
    seed=42,
    lower_quantile=0.6,
    upper_quantile=0.9,
    min_user_positive=5,
    min_item_interactions=5,
    candidate_user_limit=1500,
    max_target_rows=1000000,
    progress=None,
):
    """统计完整过去总体，条件分位数选用户/商品，保存有限候选用户的全部过去交互。"""
    if not 0 <= lower_quantile < upper_quantile <= 1 or type(seed) is not int:
        raise ValueError("分位数或种子无效")
    if any(
        type(value) is not int or value < 1
        for value in (
            min_user_positive,
            min_item_interactions,
            candidate_user_limit,
            max_target_rows,
        )
    ):
        raise ValueError("能力门槛和资源上限必须是正整数")
    destination = Path(out_dir)
    if destination.exists():
        raise ValueError("快照目录已经存在，拒绝覆盖")
    targets, target_evidence = [], []

    def target(row):
        if len(targets) >= max_target_rows:
            raise ValueError("目标交互超过内存保护上限；不允许静默截取")
        targets.append(row)

    for source in target_sources:
        target_evidence.append(_scan(source, target, progress))
    if not targets:
        raise ValueError("没有目标交互")
    cutoff = min(row["timestamp"] for row in targets)
    users, positives, items = Counter(), Counter(), Counter()

    def past(row):
        if row["timestamp"] >= cutoff:
            raise ValueError("训练期与目标时间重叠；不能使用未来计算热度")
        users[row["user_id"]] += 1
        items[row["parent_asin"]] += 1
        if row["rating"] >= 4:
            positives[row["user_id"]] += 1

    history_evidence = _scan(history_source, past, progress)
    active_users = {
        user: count for user, count in users.items() if positives[user] >= min_user_positive
    }
    supported_items = {
        item: count for item, count in items.items() if count >= min_item_interactions
    }
    user_bounds = _quantiles(active_users.values(), lower_quantile, upper_quantile)
    item_bounds = _quantiles(supported_items.values(), lower_quantile, upper_quantile)
    eligible_user_count, eligible_item_count = len(active_users), len(supported_items)
    popular_items = {
        item for item, count in supported_items.items() if item_bounds[0] <= count <= item_bounds[1]
    }
    candidate_rows = [
        row
        for row in targets
        if row["rating"] >= 4
        and row["parent_asin"] in popular_items
        and row["user_id"] in active_users
        and user_bounds[0] <= users[row["user_id"]] <= user_bounds[1]
    ]
    order = sorted({row["user_id"] for row in candidate_rows})
    random.Random(seed).shuffle(order)
    selected = set(order[:candidate_user_limit])
    if not selected:
        raise ValueError("条件热度范围内没有真实用户—商品目标交互")
    # 字典只保存标识/计数；不持有全部交互、评论正文或商品长文本。
    past_user_count, past_item_count = len(users), len(items)
    user_counts = {user: users[user] for user in sorted(selected)}
    positive_counts = {user: positives[user] for user in sorted(selected)}
    item_counts = {item: items[item] for item in sorted(popular_items)}
    users.clear()
    positives.clear()
    del active_users, supported_items
    destination.mkdir(parents=True)
    history_rows = []
    pattern = re.compile(rb'"user_id"\s*:\s*"([^"\\]+)"')
    second_hash = hashlib.sha256()
    with Path(history_source).open("rb") as stream:
        for raw in stream:
            second_hash.update(raw)
            match = pattern.search(raw)
            if match and match[1].decode("utf-8") in selected:
                row = json.loads(raw)
                projected = {
                    key: row[key] for key in ("user_id", "parent_asin", "timestamp", "rating")
                }
                history_rows.append(projected)
                if len(history_rows) > 250000:
                    raise ValueError(
                        "候选画像快照超过 25 万条资源上限，请减少 candidate_user_limit"
                    )
                item_counts[row["parent_asin"]] = items[row["parent_asin"]]
    if second_hash.hexdigest() != history_evidence["sha256"]:
        raise ValueError("两次扫描期间训练输入发生变化，拒绝发布快照")
    if dict(Counter(row["user_id"] for row in history_rows)) != user_counts:
        raise ValueError("候选用户过去交互回填不完整")
    items.clear()
    snapshots = {
        "history": _write_rows(destination / "history.jsonl", history_rows),
        "targets": _write_rows(
            destination / "targets.jsonl",
            (row for row in candidate_rows if row["user_id"] in selected),
        ),
    }
    result = {
        "schema_version": "rs-skill-population/1",
        "seed": seed,
        "lower_quantile": lower_quantile,
        "upper_quantile": upper_quantile,
        "min_user_positive": min_user_positive,
        "min_item_interactions": min_item_interactions,
        "candidate_user_limit": candidate_user_limit,
        "history_cutoff_exclusive": cutoff,
        "past_users": past_user_count,
        "past_items": past_item_count,
        "eligible_user_population": eligible_user_count,
        "eligible_item_population": eligible_item_count,
        "user_count_bounds": user_bounds,
        "item_count_bounds": item_bounds,
        "user_counts": user_counts,
        "user_positive_counts": positive_counts,
        "item_counts": dict(sorted(item_counts.items())),
        "population_item_ids": sorted(popular_items),
        "sources": {"history": history_evidence, "targets": target_evidence},
        "snapshots": snapshots,
        "sampling_policy": "full_past_counts; capability_conditioned_quantiles; seeded_future_pair_user_pool",
    }
    result["content_sha256"] = fingerprint(result)
    (destination / "population.json").write_text(
        json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8"
    )
    return result
