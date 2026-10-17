"""过去交互定热度、未来正向交互绑定画像用户；固定种子抽样，不截取文件前缀。"""

import copy
import hashlib
import json
import math
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from .dataset import fingerprint, validate_benchmark


def _interactions(path, max_rows):
    digest, rows = hashlib.sha256(), []
    with Path(path).open("rb") as stream:
        for raw in stream:
            digest.update(raw)
            if len(rows) >= max_rows:
                raise ValueError("交互行数超出资源上限；禁止静默截取后声称总体抽样")
            row = json.loads(raw)
            if not isinstance(row.get("user_id"), str) or not isinstance(
                row.get("parent_asin"), str
            ):
                raise ValueError("交互缺少用户或商品标识")
            if type(row.get("timestamp")) is not int or row["timestamp"] < 0:
                raise ValueError("交互必须有非负整数毫秒时间戳")
            rating = row.get("rating")
            if type(rating) not in {int, float} or not math.isfinite(rating):
                raise ValueError("交互必须有有限评分")
            rows.append(
                {key: row[key] for key in ("user_id", "parent_asin", "timestamp", "rating")}
            )
    return rows, {
        "path": str(Path(path).resolve()),
        "rows": len(rows),
        "sha256": digest.hexdigest(),
        "complete": True,
    }


def _bounds(counts, lower, upper):
    values = sorted(counts.values())
    return [values[math.floor((len(values) - 1) * quantile)] for quantile in (lower, upper)]


def _preferences(known, items):
    categories = Counter(items[row["parent_asin"]]["category"] for row in known)
    stores = Counter(
        items[row["parent_asin"]]["store"]
        for row in known
        if items[row["parent_asin"]].get("store")
    )
    return {
        "category_counts": dict(sorted(categories.items())),
        "store_counts": dict(sorted(stores.items())),
        "category_scores": {
            key: value / max(categories.values()) for key, value in sorted(categories.items())
        },
        "store_scores": {
            key: value / max(stores.values()) for key, value in sorted(stores.items())
        },
        "preferred_store": sorted(stores, key=lambda value: (-stores[value], value))[0]
        if stores
        else None,
    }


def _affinity(item, preferences):
    return preferences["category_scores"].get(item["category"], 0) + preferences[
        "store_scores"
    ].get(item.get("store"), 0)


def _catalog(sources, wanted, currency):
    items, evidence = {}, []
    pattern = re.compile(rb'"parent_asin"\s*:\s*"([^"\\]+)"')
    for source in sources:
        digest, scanned = hashlib.sha256(), 0
        with Path(source).open("rb") as stream:
            for raw in stream:
                scanned += 1
                digest.update(raw)
                match = pattern.search(raw)
                if not match or match[1].decode("utf-8") not in wanted:
                    continue
                row = json.loads(raw)
                item_id = row["parent_asin"]
                if item_id in items:
                    continue
                categories = row.get("categories") or []
                price = row.get("price")
                try:
                    price = float(price) if not isinstance(price, bool) else float("nan")
                except (TypeError, ValueError):
                    price = float("nan")
                if not row.get("title") or not categories or row.get("main_category") == "Books":
                    continue
                # 缺价历史仍能建立兴趣；缺价商品不能进入带预算的评测目录。
                items[item_id] = {
                    "item_id": item_id,
                    "title": row["title"],
                    "category": categories[-1],
                    "category_path": categories,
                    "store": row.get("store"),
                    "price": price if math.isfinite(price) and price > 0 else None,
                    "currency": currency,
                    "source": {
                        "file": str(Path(source).resolve()),
                        "row": scanned,
                        "parent_asin": item_id,
                    },
                }
        evidence.append(
            {
                "path": str(Path(source).resolve()),
                "rows": scanned,
                "sha256": digest.hexdigest(),
                "complete": True,
            }
        )
    return items, evidence


def build_personalized_benchmark(
    metadata_sources,
    history_source,
    target_sources,
    *,
    seed=42,
    lower_quantile=0.6,
    upper_quantile=0.9,
    family_limit=20,
    catalog_limit=300,
    currency="SOURCE_UNIT",
    max_interaction_rows=250000,
    population_snapshot=None,
):
    """每个真实 Profile User 一个 family；同用户不跨 split，目标交互不进入画像。"""
    if not 0 <= lower_quantile < upper_quantile <= 1:
        raise ValueError("热度百分位必须满足 0 <= lower < upper <= 1")
    if type(seed) is not int or type(family_limit) is not int or family_limit < 2:
        raise ValueError("seed 必须是整数，family_limit 至少为 2")
    if type(catalog_limit) is not int or catalog_limit < family_limit * 3:
        raise ValueError("catalog_limit 至少为 family_limit 的三倍")
    history, history_evidence = _interactions(history_source, max_interaction_rows)
    targets, target_evidence = [], []
    for source in target_sources:
        rows, evidence = _interactions(source, max_interaction_rows - len(targets))
        targets.extend(rows)
        target_evidence.append(evidence)
    if (
        not history
        or not targets
        or max(row["timestamp"] for row in history) >= min(row["timestamp"] for row in targets)
    ):
        raise ValueError("历史与目标必须非空且按全局时间严格隔离")
    cutoff = min(row["timestamp"] for row in targets)
    users = Counter(row["user_id"] for row in history)
    item_counts = Counter(row["parent_asin"] for row in history)
    user_bounds, item_bounds = (
        _bounds(users, lower_quantile, upper_quantile),
        _bounds(item_counts, lower_quantile, upper_quantile),
    )
    population = None
    if population_snapshot is not None:
        population = copy.deepcopy(population_snapshot)
        expected_hash = population.pop("content_sha256", None)
        if (
            population.get("schema_version") != "rs-skill-population/1"
            or fingerprint(population) != expected_hash
        ):
            raise ValueError("全量统计快照版本/哈希无效")
        if (
            population["snapshots"]["history"]["sha256"] != history_evidence["sha256"]
            or [population["snapshots"]["targets"]["sha256"]]
            != [entry["sha256"] for entry in target_evidence]
            or dict(users) != population["user_counts"]
            or population["lower_quantile"] != lower_quantile
            or population["upper_quantile"] != upper_quantile
        ):
            raise ValueError("画像/目标快照与全量统计来源不一致")
        for item, count in item_counts.items():
            if population["item_counts"].get(item, 0) < count:
                raise ValueError("全量商品频次不能少于画像快照中的频次")
        users, item_counts = Counter(population["user_counts"]), Counter(population["item_counts"])
        user_bounds, item_bounds = population["user_count_bounds"], population["item_count_bounds"]
        cutoff = population["history_cutoff_exclusive"]
        if (
            max(row["timestamp"] for row in history) >= cutoff
            or min(row["timestamp"] for row in targets) < cutoff
        ):
            raise ValueError("画像快照不满足原始全局时间截止")
        population["content_sha256"] = expected_hash
    popular = {
        item for item, count in item_counts.items() if item_bounds[0] <= count <= item_bounds[1]
    }
    seen, past_positive = defaultdict(set), defaultdict(list)
    for row in history:
        seen[row["user_id"]].add(row["parent_asin"])
        if row["rating"] >= 4:
            past_positive[row["user_id"]].append(row)
    pairs = [
        row
        for row in targets
        if row["rating"] >= 4
        and user_bounds[0] <= users[row["user_id"]] <= user_bounds[1]
        and row["parent_asin"] in popular
        and row["parent_asin"] not in seen[row["user_id"]]
        and len(past_positive[row["user_id"]]) >= 2
    ]
    if not pairs:
        raise ValueError("选定热度范围内没有具备过去画像的真实用户—商品正向交互")
    wanted = set(item_counts) | {row["parent_asin"] for row in pairs}
    items, metadata_evidence = _catalog(metadata_sources, wanted, currency)
    candidate_pool = {
        item: facts
        for item, facts in items.items()
        if item in popular and facts["price"] is not None
    }
    known_history = {
        user: [row for row in rows if row["parent_asin"] in items]
        for user, rows in past_positive.items()
    }
    preferences = {
        user: _preferences(rows, items) for user, rows in known_history.items() if len(rows) >= 2
    }
    pool_by_category = defaultdict(list)
    for item in candidate_pool.values():
        pool_by_category[item["category"]].append(item)
    by_user = defaultdict(list)
    flat_pairs = 0
    for row in pairs:
        if row["parent_asin"] in candidate_pool and row["user_id"] in preferences:
            user = row["user_id"]
            prefs = preferences[user]
            preferred_category = sorted(
                prefs["category_counts"],
                key=lambda value: (-prefs["category_counts"][value], value),
            )[0]
            categories = {items[row["parent_asin"]]["category"], preferred_category}
            affinities = [
                _affinity(item, prefs)
                for category in categories
                for item in pool_by_category[category]
                if item["item_id"] not in seen[user]
            ]
            if max(affinities) > min(affinities):
                by_user[user].append(row)
            else:
                flat_pairs += 1
    rng = random.Random(seed)
    user_order = sorted(by_user)
    rng.shuffle(user_order)
    selected, anchor_ids = [], set()
    for user in user_order:
        options = sorted(by_user[user], key=lambda row: (row["timestamp"], row["parent_asin"]))
        rng.shuffle(options)
        anchor = next((row for row in options if row["parent_asin"] not in anchor_ids), None)
        if anchor is not None:
            selected.append(anchor)
            anchor_ids.add(anchor["parent_asin"])
        if len(selected) == family_limit:
            break
    if len(selected) < family_limit:
        raise ValueError(
            f"筛选后仅 {len(selected)} 个可绑定且目标不重复的画像用户，不能生成 {family_limit} 个 family"
        )
    pool_order = sorted(candidate_pool)
    rng.shuffle(pool_order)
    # 留出偏好与非偏好对照，余下席位从整个合格商品池抽样；不按文件顺序选商品。
    catalog_ids = set(anchor_ids)
    for anchor in selected:
        user = anchor["user_id"]
        prefs = preferences[user]
        preferred_category = sorted(
            prefs["category_counts"], key=lambda value: (-prefs["category_counts"][value], value)
        )[0]
        categories = {items[anchor["parent_asin"]]["category"], preferred_category}
        alternatives = [
            item
            for item in pool_order
            if items[item]["category"] in categories and item not in seen[user]
        ]
        alternatives.sort(key=lambda item: -_affinity(items[item], prefs))
        catalog_ids.update([alternatives[0], alternatives[-1]])
    for item in pool_order:
        if len(catalog_ids) >= catalog_limit:
            break
        catalog_ids.add(item)
    catalog = [
        dict(items[item], historical_interaction_count=item_counts[item])
        for item in sorted(catalog_ids)
    ]
    profiles, tasks, diagnostics = {}, [], []
    for index, anchor_row in enumerate(selected):
        user, anchor_id = anchor_row["user_id"], anchor_row["parent_asin"]
        known = known_history[user]
        known.sort(key=lambda row: (row["timestamp"], row["parent_asin"]))
        prefs = preferences[user]
        profiles[user] = {
            "profile_user_id": user,
            "activity_count": users[user],
            "history_cutoff_exclusive": cutoff,
            "seen_item_ids": sorted(seen[user]),
            "history": [dict(row, item=items[row["parent_asin"]]) for row in known[-50:]],
            "history_total_positive_count": len(past_positive[user]),
            "history_metadata_count": len(known),
            "profile_preferences": prefs,
        }
        anchor = items[anchor_id]
        preferred_category = sorted(
            prefs["category_counts"], key=lambda value: (-prefs["category_counts"][value], value)
        )[0]
        categories = sorted({anchor["category"], preferred_category})
        category_items = [
            item
            for item in catalog
            if item["category"] in categories and item["item_id"] not in seen[user]
        ]
        affinities = [_affinity(item, prefs) for item in category_items]
        diagnostics.append(
            {
                "profile_user_id": user,
                "family_id": f"profile-family-{index:03d}",
                "candidate_count": len(category_items),
                "profile_affinity_min": min(affinities),
                "profile_affinity_max": max(affinities),
                "observable": max(affinities) > min(affinities),
            }
        )
        budget = max(item["price"] for item in category_items)
        hard = [
            {"field": "category", "op": "in", "value": categories},
            {"field": "currency", "op": "eq", "value": currency},
            {"field": "price", "op": "lte", "value": budget},
            {"field": "item_id", "op": "not_in", "value": sorted(seen[user])},
        ]
        price = {"field": "price", "op": "minimize", "best": 0, "worst": budget, "weight": 0.3}
        soft = [
            price,
            {
                "field": "category",
                "op": "lookup",
                "scores": prefs["category_scores"],
                "weight": 0.35 if prefs["store_scores"] else 0.7,
            },
        ]
        if prefs["store_scores"]:
            soft.append(
                {"field": "store", "op": "lookup", "scores": prefs["store_scores"], "weight": 0.35}
            )
        gold = {"k": 2, "hard": hard, "soft": soft}
        category_text = "、".join(f"“{category}”" for category in categories)
        message = f"请结合我的历史画像，从{category_text}中推荐2件没评价过的不同商品，每件不超过{budget:g} {currency}，不换算货币。历史类目与店铺偏好各占35%，便宜程度占30%；无店铺历史时类目占70%。偏好分按正向历史频次除以对应维度最大频次计算，未知偏好记0。请读取画像，不猜测。若不足2件，明确说明，不要凑数。"
        family = f"profile-family-{index:03d}"
        split = (
            "train"
            if index < int(family_limit * 0.6)
            else "dev"
            if index < int(family_limit * 0.8)
            else "test"
        )

        def turn(text, current_gold):
            return {"user_message": text, "limit": 2, "gold": copy.deepcopy(current_gold)}

        def add(kind, turns, config=None):
            tasks.append(
                {
                    "task_id": f"{family}-{kind}",
                    "family_id": family,
                    "split": split,
                    "kind": kind,
                    "review_status": "pending",
                    "profile_user_id": user,
                    "anchor_item_id": anchor_id,
                    "anchor_evidence": dict(anchor_row),
                    "environment": config or {},
                    "turns": turns,
                }
            )

        add(
            "personalized",
            [turn(message, gold)],
            {"unavailable_tools": ["rag_support", "rag_evidence_search"]} if index == 0 else None,
        )
        explicit = copy.deepcopy(gold)
        explicit["soft"] = [dict(price, weight=1)]
        add(
            "explicit_overrides_profile",
            [turn(message + "但这次忽略我的历史类目和店铺偏好，只按便宜程度排序。", explicit)],
        )
        revised = copy.deepcopy(gold)
        new_budget = sorted(item["price"] for item in category_items)[
            (len(category_items) - 1) // 2
        ]
        revised["hard"][2]["value"] = new_budget
        revised["soft"][0]["worst"] = new_budget
        add(
            "personalized_budget_change",
            [
                turn(message, gold),
                turn(f"预算收紧到{new_budget:g} {currency}，其他要求保持不变。", revised),
            ],
        )
        add(
            "personalized_exclude_previous",
            [
                turn(message, gold),
                dict(
                    turn("再推荐2件，之前推荐的不要，其他要求不变。若不足2件，请明确说明。", gold),
                    exclude_previous=True,
                ),
            ],
        )
    benchmark = {
        "schema_version": "rs-skill-benchmark/1",
        "catalog": catalog,
        "profiles": profiles,
        "tasks": tasks,
        "environment": {
            "tool_call_budget": 16,
            "session_preferences": {},
            "catalog_scope": "frozen_fixture_only",
            "retrieval": "profile_lexical_price_v2",
            "network_policy": "fixture_tools_local_only; model_endpoint_explicit",
            "task_timeout_seconds": 180,
        },
        "manifest": {
            "builder_version": "personalized-grounded-seeds/3"
            if population
            else "personalized-grounded-seeds/2",
            "human_reviewed": False,
            "builder_parameters": {
                "seed": seed,
                "lower_quantile": lower_quantile,
                "upper_quantile": upper_quantile,
                "family_limit": family_limit,
                "catalog_limit": catalog_limit,
                "currency": currency,
                "max_interaction_rows": max_interaction_rows,
            },
            "catalog_sha256": fingerprint(catalog),
            "profiles_sha256": fingerprint(profiles),
            "currency": currency,
            "currency_interpretation": "explicit_source_unit; no_fx_conversion",
            "sampling": {
                "policy": "seeded_user_shuffle_then_eligible_positive_target_shuffle; unique_user_and_anchor",
                "seed": seed,
                "quantile_method": "empirical_floor_index; inclusive_count_bounds; ties_preserved",
                "popularity_measure": "past_interaction_count_in_provided_subset",
                "user_count_bounds": user_bounds,
                "item_count_bounds": item_bounds,
                "past_users": population["past_users"] if population else len(users),
                "past_items": population["past_items"] if population else len(item_counts),
                "eligible_users": len(by_user),
                "eligible_target_pairs": sum(map(len, by_user.values())),
                "eligible_priced_items": len(candidate_pool),
                "flat_profile_pairs_removed": flat_pairs,
                "scope_warning": "provided_subset_relative_popularity; not_sitewide; quantile_ties_expand_band",
            },
            "history_cutoff_exclusive": cutoff,
            "split_policy": "disjoint_profile_users; unique_anchors; 60_20_20",
            "sources": {
                "history": history_evidence,
                "targets": target_evidence,
                "metadata": metadata_evidence,
            },
            "gold_policy": "hidden; target_interaction_not_in_profile; target_is_not_unique_answer",
            "profile_scoring_policy": "past_positive_frequency/max_frequency; category_.35_store_.35_price_.30; no_store_category_.70",
            "distractor_policy": "anchor_and_max_min_profile_affinity_controls_then_seeded_random_fill",
            "profile_diagnostics": {
                "observable_families": sum(row["observable"] for row in diagnostics),
                "families": diagnostics,
            },
            "catalog_time_policy": "retrospective_frozen_metadata; no_claim_of_historical_price_or_stock",
        },
    }
    if population:
        benchmark["manifest"]["population_sha256"] = population["content_sha256"]
        benchmark["manifest"]["population"] = {
            key: copy.deepcopy(population[key])
            for key in (
                "sources",
                "snapshots",
                "min_user_positive",
                "min_item_interactions",
                "candidate_user_limit",
                "eligible_user_population",
                "eligible_item_population",
                "history_cutoff_exclusive",
                "sampling_policy",
            )
        }
        benchmark["manifest"]["sampling"]["popularity_measure"] = (
            "full_provided_train_interaction_count"
        )
        benchmark["manifest"]["sampling"]["scope_warning"] = (
            "capability_conditioned_population; not_sitewide; quantile_ties_expand_band"
        )
    validate_benchmark(benchmark)
    return benchmark
