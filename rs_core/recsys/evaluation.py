from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from rs_core.recsys.ranking import rank_candidates
from rs_core.recsys.types import EvaluationSummary, MergedCandidate, RankingResult


def heldout_positives(records: list[dict[str, Any]]) -> dict[str, set[str]]:
    positives: dict[str, set[str]] = defaultdict(set)
    for row in records:
        if row.get("label_binary"):
            positives[row.get("user_id", "")].add(row.get("parent_asin", ""))
    return {user: {item for item in items if item} for user, items in positives.items() if user and items}


def evaluate(
    candidates_by_user: dict[str, list[MergedCandidate]],
    rankings_by_user: dict[str, RankingResult],
    holdout_records: list[dict[str, Any]],
    config: dict,
    fallback_users: set[str] | None = None,
) -> EvaluationSummary:
    fallback_users = fallback_users or set()
    positives = heldout_positives(holdout_records)
    users = sorted(set(candidates_by_user) | set(rankings_by_user))
    users_with_holdout = [user for user in users if positives.get(user)]
    eval_users = users_with_holdout or users
    eval_user_set = set(eval_users)
    k = int(config.get("top_k", 5))

    source_counter: Counter[str] = Counter()
    topk_source_counter: Counter[str] = Counter()
    candidate_hit_source_counter: Counter[str] = Counter()
    category_counts: list[int] = []
    candidate_counts: list[int] = []
    candidate_hit_ranks: list[int] = []
    candidate_hit_users = 0
    candidate_hit_missed_topk_users = 0
    ranked_hit_users = 0
    for user in users:
        candidates = candidates_by_user.get(user, [])
        candidate_counts.append(len(candidates))
        candidate_hits = [candidate for candidate in candidates if candidate.item_id in positives.get(user, set())]
        ranking = rankings_by_user.get(user, RankingResult(user, []))
        full_ranking = rank_candidates(user, candidates, config, top_k=len(candidates) or k)
        ranking_items = ranking.items[:k]
        ranked_hit = bool({item["parent_asin"] for item in ranking_items} & positives.get(user, set()))
        if user in eval_user_set and candidate_hits:
            candidate_hit_users += 1
            for candidate in candidate_hits:
                candidate_hit_source_counter.update(candidate.sources)
            rank = _best_hit_rank(full_ranking.items, positives.get(user, set()))
            if rank is not None:
                candidate_hit_ranks.append(rank)
            if not ranked_hit:
                candidate_hit_missed_topk_users += 1
        for candidate in candidates:
            source_counter.update(candidate.sources)
        if user in eval_user_set and ranked_hit:
            ranked_hit_users += 1
        for item in ranking_items:
            topk_source_counter.update(item.get("sources", []))
        categories = {item.get("category", "") for item in ranking_items if item.get("category")}
        category_counts.append(len(categories))

    sample_limitations: list[str] = []
    if not users_with_holdout:
        sample_limitations.append("No held-out positive valid/test rows were available; hit-rate metrics are reported as 0.0 placeholders.")
    if len(eval_users) < len(users):
        sample_limitations.append("Hit-rate metrics only include users with held-out positives.")
    if not users:
        sample_limitations.append("No users were available for evaluation.")

    return EvaluationSummary(
        evaluation_mode=str(config.get("evaluation_mode", "valid_test")),
        users_total=len(users),
        users_with_holdout=len(users_with_holdout),
        users_evaluated=len(eval_users),
        hit_rate_denominator="users_with_holdout" if users_with_holdout else "all_demo_users_placeholder",
        candidate_count_avg=_avg(candidate_counts),
        recall_source_coverage=dict(sorted(source_counter.items())),
        topk_source_coverage=dict(sorted(topk_source_counter.items())),
        source_diagnostics={},
        candidate_hit_rate_at_pool=round(candidate_hit_users / len(eval_users), 6) if eval_users and positives else 0.0,
        candidate_hit_users=candidate_hit_users,
        candidate_hit_source_coverage=dict(sorted(candidate_hit_source_counter.items())),
        candidate_hit_rank_min=min(candidate_hit_ranks) if candidate_hit_ranks else None,
        candidate_hit_rank_avg=_avg_float(candidate_hit_ranks) if candidate_hit_ranks else None,
        candidate_hit_rank_p50=_median(candidate_hit_ranks) if candidate_hit_ranks else None,
        candidate_hit_missed_topk_users=candidate_hit_missed_topk_users,
        ranked_hit_users=ranked_hit_users,
        fallback_rate=round(len(fallback_users) / len(users), 6) if users else 0.0,
        hit_rate_at_k=_hit_rate(rankings_by_user, positives, eval_users, k),
        popular_only_hit_rate_at_k=_source_hit_rate(candidates_by_user, positives, eval_users, config, k, {"popular"}),
        itemcf_only_hit_rate_at_k=_source_hit_rate(candidates_by_user, positives, eval_users, config, k, {"itemcf_weak", "itemcf_strong"}),
        hybrid_hit_rate_at_k=_hit_rate(rankings_by_user, positives, eval_users, k),
        hybrid_no_itemcf_hit_rate_at_k=_source_hit_rate(candidates_by_user, positives, eval_users, config, k, {"popular", "category", "semantic"}),
        category_diversity_avg=_avg(category_counts),
        sample_limitations=sample_limitations,
    )


def _hit_rate(rankings: dict[str, RankingResult], positives: dict[str, set[str]], users: list[str], k: int) -> float:
    if not users or not positives:
        return 0.0
    hits = 0
    counted = 0
    for user in users:
        targets = positives.get(user)
        if not targets:
            continue
        counted += 1
        recs = {item["parent_asin"] for item in rankings.get(user, RankingResult(user, [])).items[:k]}
        if recs & targets:
            hits += 1
    return round(hits / counted, 6) if counted else 0.0


def _source_hit_rate(
    candidates_by_user: dict[str, list[MergedCandidate]],
    positives: dict[str, set[str]],
    users: list[str],
    config: dict,
    k: int,
    sources: set[str],
) -> float:
    if not users or not positives:
        return 0.0
    rankings = {
        user: rank_candidates(user, candidates_by_user.get(user, []), config, top_k=k, allowed_sources=sources)
        for user in users
    }
    return _hit_rate(rankings, positives, users, k)


def _best_hit_rank(items: list[dict[str, Any]], targets: set[str]) -> int | None:
    for index, item in enumerate(items, start=1):
        if item.get("parent_asin") in targets:
            return index
    return None


def _median(values: list[int]) -> float:
    if not values:
        return 0.0
    rows = sorted(values)
    middle = len(rows) // 2
    if len(rows) % 2:
        return float(rows[middle])
    return round((rows[middle - 1] + rows[middle]) / 2, 6)


def _avg_float(values: list[int]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def _avg(values: list[int]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0
