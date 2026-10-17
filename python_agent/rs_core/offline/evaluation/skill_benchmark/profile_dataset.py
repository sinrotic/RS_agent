"""在修正后的目录上构建真实用户画像对照；不合成身份或跨集合配对。"""

import copy
from collections import Counter

from .catalog_curation import CURATION_VERSION, curate_item
from .customer_dataset import CATEGORY_NAMES, build_customer_benchmark
from .dataset import fingerprint, validate_benchmark
from .personalized import _preferences
from .profile_matching import build_profile_match, needs_preference_confirmation


SPECS = (
    ("Gel Ink Rollerball Pens", "tip_mm", 20),
    ("Earbud Headphones", "connection_type", 80),
    ("Earbud Headphones", "store", 80),
    ("Power Strips", "store", 60),
    ("Keyboard & Mouse Combos", "store", 60),
)


def preference_words(field, value):
    if field == "tip_mm":
        return f"{value}mm笔尖"
    if field == "connection_type":
        return "无线款" if value == "wireless" else "有线款"
    return f"“{value}”家的"


def curate_source(source):
    validate_benchmark(source)
    result = copy.deepcopy(source)
    result["catalog"] = [curate_item(item) for item in source["catalog"]]
    history_corrections = {}
    for profile in result["profiles"].values():
        for event in profile["history"]:
            if event.get("item"):
                event["item"] = curate_item(event["item"])
                if event["item"].get("category_correction"):
                    history_corrections[event["parent_asin"]] = event["item"]["category_correction"]
        known = [event for event in profile["history"] if event.get("item")]
        profile["profile_preferences"] = _preferences(
            known, {event["parent_asin"]: event["item"] for event in known}
        )
        scoped = []
        for category, field, _ in SPECS:
            paths = sorted(
                {
                    tuple(event["item"].get("category_path", []))
                    for event in known
                    if event["item"].get("category") == category
                }
            )
            for path in paths:
                match = build_profile_match(profile, category, list(path), field)
                if match:
                    scoped.append(match)
        profile["behavioral_preferences"] = scoped
    catalog_changes = [
        {
            "item_id": item["item_id"],
            "corrected_category": item["category"],
            **item["category_correction"],
        }
        for item in result["catalog"]
        if item.get("category_correction")
    ]
    result["manifest"].update(
        catalog_sha256=fingerprint(result["catalog"]),
        profiles_sha256=fingerprint(result["profiles"]),
        catalog_curation_version=CURATION_VERSION,
        catalog_curation={
            "catalog_corrections": catalog_changes,
            "history_unique_items_corrected": len(history_corrections),
            "scope": "known_title_grounded_contradictions; not_full_catalog_semantic_certification",
            "full_semantic_review": "pending",
        },
    )
    validate_benchmark(result)
    return result


def _dominant(match):
    if not match:
        return None
    counts = match["counts"]
    maximum = max(counts.values())
    best = [value for value, count in counts.items() if count == maximum]
    return best[0] if len(best) == 1 else None


def build_profile_contrast_benchmark(source):
    """v5：保留旧版文件；同需求、同目录、同预算，只改变真实历史画像。"""
    corrected = curate_source(source)
    result = build_customer_benchmark(corrected)
    bases = {
        task["profile_user_id"]: task
        for task in result["tasks"]
        if task["kind"] == "clear_purchase"
    }
    groups, used = [], set()
    pairs = []
    for category, field, budget in SPECS:
        items = [
            item
            for item in result["catalog"]
            if item["category"] == category
            and item["price"] <= budget
            and item.get(field) is not None
        ]
        for path in sorted({tuple(item["category_path"]) for item in items}):
            candidates = [item for item in items if tuple(item["category_path"]) == path]
            values = {str(item[field]) for item in candidates}
            if len(values) < 2:
                continue
            spec = {"category": category, "field": field, "budget": budget, "path": list(path)}
            for split in ("train", "dev", "test"):
                entries = []
                for user, base in bases.items():
                    if user in used or base["split"] != split:
                        continue
                    match = build_profile_match(
                        result["profiles"][user], category, list(path), field
                    )
                    preferred = _dominant(match)
                    if preferred in values:
                        entries.append((user, match, preferred))
                entries.sort(
                    key=lambda entry: (-entry[1]["confidence"], bases[entry[0]]["family_id"])
                )
                while entries:
                    first = entries.pop(0)
                    other_index = next(
                        (i for i, entry in enumerate(entries) if entry[2] != first[2]), None
                    )
                    if other_index is None:
                        break
                    second = entries.pop(other_index)
                    pairs.append((spec, split, (first, second), "preference_difference"))
                    used.update((first[0], second[0]))
    # 没有足够证据时也必须测试；不为补数量编造历史，更不挪动用户 split。
    for split in ("train", "dev", "test"):
        spec = {"category": "Earbud Headphones", "field": "connection_type", "budget": 80}
        paths = [
            item["category_path"]
            for item in result["catalog"]
            if item["category"] == spec["category"] and item.get(spec["field"]) is not None
        ]
        if not paths:
            continue
        spec["path"] = paths[0]
        strong, absent = [], []
        for user, base in bases.items():
            if user in used or base["split"] != split:
                continue
            match = build_profile_match(
                result["profiles"][user], spec["category"], spec["path"], spec["field"]
            )
            if match is None:
                absent.append((user, None, "wireless"))
            elif not needs_preference_confirmation(match):
                strong.append((user, match, _dominant(match)))
        if strong and absent:
            strong.sort(key=lambda entry: (-entry[1]["confidence"], bases[entry[0]]["family_id"]))
            absent.sort(key=lambda entry: bases[entry[0]]["family_id"])
            entries = (strong[0], absent[0])
            pairs.append((spec, split, entries, "evidence_availability"))
            used.update(entry[0] for entry in entries)

    for pair_index, (spec, split, entries, pair_type) in enumerate(pairs):
        category, field, budget, path = (
            spec[key] for key in ("category", "field", "budget", "path")
        )
        noun = CATEGORY_NAMES[category]
        pair_id = f"profile-pair-{pair_index:03d}"
        cluster = f"contrast-cluster-{pair_index:03d}"
        common_value = entries[1][2]

        def gold(
            role="disabled", match=None, *, action="recommend", explicit=None, other_spec=None
        ):
            current = other_spec or spec
            hard = [
                {"field": "currency", "op": "eq", "value": "SOURCE_UNIT"},
                {"field": "category", "op": "eq", "value": current["category"]},
                {"field": "category_path", "op": "eq", "value": current["path"]},
                {"field": "price", "op": "lte", "value": current["budget"]},
            ]
            policy = {
                "action": action,
                "history_role": role,
                "known_slots": ["budget", "category", "quantity"],
            }
            if match is not None and role == "authorized_reference":
                policy.update(
                    profile_match=copy.deepcopy(match),
                    history_authorization="current_customer_request",
                )
            if action == "clarify":
                policy.update(
                    required_slots=["profile_preference"],
                    max_questions=2,
                    clarification_field=current["field"],
                )
            if explicit is not None:
                hard.append({"field": current["field"], "op": "eq", "value": explicit})
            return {"k": 1, "hard": hard, "soft": [], "customer_policy": policy}

        def turn(message, rule):
            return {"user_message": message, "limit": 1, "gold": rule}

        def add_group(kind, members, relation, group_spec=None):
            group_id = f"{pair_id}-{kind}"
            member_ids = []
            for index, (entry, turns) in enumerate(zip(entries, members)):
                user, match, _ = entry
                task = copy.deepcopy(bases[user])
                task_id = f"{task['family_id']}-{group_id}"
                task.update(
                    task_id=task_id,
                    kind=f"profile_contrast_{kind}",
                    turns=turns,
                    contrast_group_id=group_id,
                    contrast_member=index,
                    statistical_cluster_id=cluster,
                    customer_context={
                        "purchase_for": "gift" if kind == "gift" else "self",
                        "scenario_origin": "synthetic_customer_request_with_real_past_evidence",
                        "profile_evidence": copy.deepcopy(match),
                        "no_demographic_inference": True,
                    },
                    environment={
                        "history_retrieval_role": "weak_reference"
                        if kind in {"authorized", "uncertain"}
                        else "disabled"
                    },
                )
                result["tasks"].append(task)
                member_ids.append(task_id)
            groups.append(
                {
                    "group_id": group_id,
                    "pair_id": pair_id,
                    "split": split,
                    "kind": kind,
                    "relation": relation,
                    "pair_type": pair_type,
                    "task_ids": member_ids,
                    "spec": group_spec or spec,
                    "statistical_cluster_id": cluster,
                }
            )

        initial = (
            f"想买{noun}，预算{budget:g}以内，照我以前的习惯先给我选1款参考，不确定的地方说明就好。"
        )
        if pair_type == "preference_difference":
            add_group(
                "authorized",
                [[turn(initial, gold("authorized_reference", entry[1]))] for entry in entries],
                "history_sensitive_quality; not_forced_different_item_ids",
            )
        uncertain = []
        uncertain_message = (
            f"想买{noun}，预算{budget:g}以内，帮我挑1款，照我以前的习惯来；要是拿不准，先问我。"
        )
        for _, match, preferred in entries:
            if needs_preference_confirmation(match):
                uncertain.append(
                    [
                        turn(uncertain_message, gold(action="clarify")),
                        turn(
                            f"这次就要{preference_words(field, preferred)}，预算不变。",
                            gold(explicit=preferred),
                        ),
                    ]
                )
            else:
                uncertain.append([turn(uncertain_message, gold("authorized_reference", match))])
        add_group(
            "uncertain", uncertain, "adapt_to_evidence_strength; confirm_when_sparse_or_unknown"
        )
        override_message = f"想买{noun}，预算{budget:g}以内。这次只要{preference_words(field, common_value)}，不要照以前的来，帮我选1款。"
        add_group(
            "override",
            [[turn(override_message, gold(explicit=common_value))] for _ in entries],
            "current_requirement_invariance",
        )
        gift_first = f"想给家人买{noun}，预算{budget:g}以内，不过还不知道对方想要哪种，帮我挑1款。"
        gift_gold = gold(action="clarify")
        gift_gold["customer_policy"]["required_slots"] = ["recipient_need"]
        gift_reply = (
            f"是给家人的，对方明确要{preference_words(field, common_value)}，就选这种，预算不变。"
        )
        add_group(
            "gift",
            [
                [
                    turn(gift_first, copy.deepcopy(gift_gold)),
                    turn(gift_reply, gold(explicit=common_value)),
                ]
                for _ in entries
            ],
            "recipient_requirement_invariance",
        )
        other = next(
            (
                candidate
                for candidate in SPECS
                if candidate[0] != category and candidate[1] != "store"
            ),
            None,
        )
        if other:
            other_category, other_field, other_budget = other
            other_items = [
                item
                for item in result["catalog"]
                if item["category"] == other_category
                and item["price"] <= other_budget
                and item.get(other_field) is not None
            ]
            if other_items:
                other_path = other_items[0]["category_path"]
                other_spec = {
                    "category": other_category,
                    "field": other_field,
                    "budget": other_budget,
                    "path": other_path,
                }
                other_matches = [
                    build_profile_match(
                        result["profiles"][entry[0]], other_category, other_path, other_field
                    )
                    for entry in entries
                ]
                if all(match is None for match in other_matches):
                    value = str(other_items[0][other_field])
                    cross_message = f"想买{CATEGORY_NAMES[other_category]}，预算{other_budget:g}以内，按我以前的习惯帮我选1款；要是不了解我买这种东西的习惯，先问我。"
                    add_group(
                        "cross_category",
                        [
                            [
                                turn(cross_message, gold(action="clarify", other_spec=other_spec)),
                                turn(
                                    f"这次就要{preference_words(other_field, value)}。",
                                    gold(explicit=value, other_spec=other_spec),
                                ),
                            ]
                            for _ in entries
                        ],
                        "do_not_transfer_unrelated_category_history",
                        other_spec,
                    )
    clusters = {
        entry[0]: f"contrast-cluster-{index:03d}"
        for index, (_, _, entries, _) in enumerate(pairs)
        for entry in entries
    }
    for task in result["tasks"]:
        task["statistical_cluster_id"] = clusters.get(task["profile_user_id"], task["family_id"])
    result["contrast_groups"] = groups
    result["manifest"].update(
        builder_version="profile-contrast-customer-scenarios/1",
        parent_benchmark_sha256=fingerprint(source),
        contrast_groups_sha256=fingerprint(groups),
        profile_match_policy="explicit_customer_authorization_only; category_scoped; confidence=n/(n+2)*coverage; no_implicit_weights",
        primary_scoring_policy="hard_gated_current_request; authorized_history_bonus; current_override_and_recipient_first",
        statistical_policy="paired_users_share_cluster; same_user_never_crosses_split; pair_quality_requires_both_members",
        contrast_sampling="deterministic_evidence_supported_pairs_in_existing_splits; not_population_representative",
        contrast_coverage=dict(Counter(group["kind"] for group in groups)),
    )
    validate_benchmark(result)
    if not groups:
        raise ValueError("没有可验证的画像对照，不允许伪造画像补数量")
    return result
