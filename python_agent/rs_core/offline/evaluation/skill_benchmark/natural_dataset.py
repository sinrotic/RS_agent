"""v6：自然表达、环境授权、可选澄清；保留真实用户、类目修正与旧版。"""

import copy
from collections import Counter

from .customer_dataset import CATEGORY_NAMES
from .dataset import fingerprint, validate_benchmark
from .profile_dataset import build_profile_contrast_benchmark, preference_words
from .profile_matching import build_profile_match


def _reference_match(profile, gold):
    conditions = {c["field"]: c["value"] for c in gold["hard"] if c["op"] == "eq"}
    category, path = conditions.get("category"), conditions.get("category_path")
    if not isinstance(category, str) or not isinstance(path, list):
        return None
    fields = ("tip_mm", "connection_type", "store")
    for field in fields:
        if field not in conditions:
            match = build_profile_match(profile, category, path, field)
            if match:
                return match
    return None


def _natural_policy(gold, profile, *, match=None, disabled=False):
    policy = gold["customer_policy"]
    policy["evaluation_policy"] = "natural-shopping/1"
    policy["clarification_need"] = (
        "required"
        if policy["action"] == "clarify"
        else "verification_guidance"
        if policy["action"] == "defer"
        else "not_required"
    )
    policy.pop("profile_match", None)
    policy.pop("history_authorization", None)
    policy["history_role"] = "disabled" if disabled else "weak_reference"
    if not disabled and not gold.get("soft") and policy["action"] == "recommend":
        match = match or _reference_match(profile, gold)
        if match:
            policy.update(
                history_role="environment_reference",
                profile_match=copy.deepcopy(match),
                history_authorization="bound_profile_permission",
            )
    policy["primary_quality"] = "current_request_or_independent_labels; never_history_frequency"
    policy.setdefault("unverified_claims", ["compatibility"])


def _optional(gold, field, *, recipient=False):
    policy = gold["customer_policy"]
    policy.update(
        action="recommend_or_clarify",
        clarification_need="optional",
        required_slots=["recipient_need" if recipient else "profile_preference"],
        clarification_field=field,
        max_questions=2,
    )


def build_natural_benchmark(source):
    """从冻结 v5（或 v3）构建新版本，不原地修改历史或伪造人审标签。"""
    validate_benchmark(source)
    if source["manifest"].get("builder_version") == "natural-profile-customer-scenarios/1":
        raise ValueError("自然购物版本不能重复改造；请从冻结 v5 或 v3 重建新产物")
    result = (
        copy.deepcopy(source)
        if source.get("contrast_groups")
        else build_profile_contrast_benchmark(source)
    )
    tasks = {task["task_id"]: task for task in result["tasks"]}
    group_kinds = {
        "authorized": "implicit_profile",
        "uncertain": "optional_preference",
        "override": "current_override",
        "cross_category": "unrelated_history",
    }
    for task in result["tasks"]:
        profile = result["profiles"][task["profile_user_id"]]
        other = task.get("customer_context", {}).get("purchase_for", "self") != "self"
        task["dialogue_policy"] = "conditional_customer/1"
        task.setdefault("environment", {}).update(
            profile_access={
                "allowed": True,
                "bound_profile_user_id": task["profile_user_id"],
                "source": "fixture_account_binding",
                "history_is_positive_review_not_purchase": True,
            }
        )
        for turn in task["turns"]:
            if not any(c["field"] == "currency" for c in turn["gold"]["hard"]):
                turn["gold"]["hard"].append(
                    {
                        "field": "currency",
                        "op": "eq",
                        "value": result["environment"]["shopping_context"]["price_unit"],
                    }
                )
            old_match = turn["gold"]["customer_policy"].get("profile_match")
            disabled = other or turn["gold"]["customer_policy"]["history_role"] == "disabled"
            _natural_policy(turn["gold"], profile, match=old_match, disabled=disabled)
            if task["kind"] == "repeat_purchase":
                turn["gold"]["customer_policy"]["purchase_claim_source"] = (
                    "current_customer_statement"
                )
            turn["user_message"] = (
                turn["user_message"]
                .replace("，不要照以前的来", "")
                .replace("，别照我平时买的来选", "")
            )
    critical = []
    for group in result["contrast_groups"]:
        old_kind = group["kind"]
        group["kind"] = group_kinds.get(old_kind, old_kind)
        spec = group["spec"]
        noun = CATEGORY_NAMES[spec["category"]]
        field, budget = spec["field"], spec["budget"]
        members = [tasks[task_id] for task_id in group["task_ids"]]
        for task in members:
            task["kind"] = f"profile_contrast_{group['kind']}"
            profile = result["profiles"][task["profile_user_id"]]
            original = task["turns"]
            first = original[0]
            if old_kind in {"authorized", "uncertain", "cross_category", "gift"}:
                gold = copy.deepcopy(first["gold"])
                gold["customer_policy"]["action"] = "recommend"
                disabled = old_kind in {"gift", "cross_category"}
                match = build_profile_match(profile, spec["category"], spec["path"], field)
                _natural_policy(gold, profile, match=match, disabled=disabled)
                _optional(gold, field, recipient=old_kind == "gift")
                if old_kind == "gift":
                    message = f"想给家人买{noun}，预算{budget:g}以内，先帮我看看。"
                elif old_kind == "uncertain":
                    message = f"想换{noun}，预算{budget:g}以内，帮我挑一款吧。"
                elif old_kind == "cross_category":
                    message = f"想买{noun}，预算{budget:g}以内，帮我挑一款。"
                else:
                    message = f"想买{noun}，预算{budget:g}以内，先帮我挑一款。"
                    if spec["category"] == "Gel Ink Rollerball Pens":
                        message = f"平时记笔记用，想买中性笔，预算{budget:g}以内，帮我挑一款。"
                        gold["customer_policy"]["unscored_qualitative_needs"] = ["日常记笔记体验"]
                    elif spec["category"] == "Earbud Headphones":
                        message = (
                            f"上下班路上用，想换副入耳式耳机，预算{budget:g}以内，帮我挑一款。"
                        )
                        gold["customer_policy"]["unscored_qualitative_needs"] = ["通勤使用体验"]
                if len(original) > 1:
                    following = copy.deepcopy(original[1])
                else:
                    value = max(match["distribution"], key=match["distribution"].get)
                    following_gold = copy.deepcopy(gold)
                    following_gold["hard"].append({"field": field, "op": "eq", "value": value})
                    following_gold["customer_policy"]["action"] = "recommend"
                    _natural_policy(following_gold, profile, disabled=True)
                    following = {
                        "user_message": f"这次想要{preference_words(field, value)}，预算不变。",
                        "limit": 1,
                        "gold": following_gold,
                    }
                following["continuation"] = "only_after_clarification"
                task["turns"] = [{"user_message": message, "limit": 1, "gold": gold}, following]
                task["environment"]["history_retrieval_role"] = (
                    "disabled" if disabled else "weak_reference"
                )
            elif old_kind == "override":
                first["user_message"] = first["user_message"].replace("，不要照以前的来", "")
        group["relation"] = {
            "implicit_profile": "weak_history_evidence; independent_quality_pending",
            "optional_preference": "safe_reference_or_targeted_question; sparse_history_not_mandatory_question",
            "gift": "recipient_first; own_history_not_recipient_preference",
            "unrelated_history": "no_cross_category_preference_transfer; optional_low_risk_question",
            "current_override": "current_requirement_invariance",
        }[group["kind"]]
        if old_kind == "authorized" and spec["category"] == "Earbud Headphones":
            new_group = copy.deepcopy(group)
            new_group.update(
                group_id=f"{group['pair_id']}-critical-compatibility",
                kind="critical_compatibility",
                relation="device_unknown_requires_confirmation; no_compatibility_guarantee",
            )
            new_group["task_ids"] = []
            for task in members:
                case = copy.deepcopy(task)
                case_id = f"{task['family_id']}-{new_group['group_id']}"
                gold = copy.deepcopy(task["turns"][0]["gold"])
                gold["hard"].append({"field": "connection_type", "op": "eq", "value": "wired"})
                gold["customer_policy"].update(
                    action="clarify",
                    required_slots=["device"],
                    unverified_claims=["compatibility"],
                    max_questions=2,
                )
                _natural_policy(gold, result["profiles"][task["profile_user_id"]], disabled=True)
                guidance = copy.deepcopy(gold)
                guidance["customer_policy"].update(
                    action="defer", clarification_need="verification_guidance"
                )
                case.update(
                    task_id=case_id,
                    contrast_group_id=new_group["group_id"],
                    kind="profile_contrast_critical_compatibility",
                    turns=[
                        {
                            "user_message": f"想买{noun}，预算{budget:g}以内，要插在手机上用，帮我看看。",
                            "limit": 1,
                            "gold": gold,
                        },
                        {
                            "user_message": "我也说不清手机型号和接口，手边暂时没有手机。",
                            "limit": 1,
                            "gold": guidance,
                        },
                    ],
                )
                case["environment"]["history_retrieval_role"] = "disabled"
                result["tasks"].append(case)
                new_group["task_ids"].append(case_id)
            critical.append(new_group)
    result["contrast_groups"].extend(critical)
    result["manifest"].update(
        builder_version="natural-profile-customer-scenarios/1",
        parent_benchmark_sha256=fingerprint(source),
        contrast_groups_sha256=fingerprint(result["contrast_groups"]),
        contrast_coverage=dict(Counter(g["kind"] for g in result["contrast_groups"])),
        profile_match_policy="bound_environment_permission; category_scoped; diagnostic_only; not_hidden_requirement",
        primary_scoring_policy="hard_gated_current_request; optional_independent_relevance; no_history_frequency_bonus",
        clarification_policy="critical_information_required; low_risk_preference_optional; answer_contingent_continuation",
        independent_relevance_status="pending_human_labels",
        human_reviewed=False,
        scoring_calibration_required=True,
        scoring_calibration={"status": "pending_new_version_human_labels", "passed": False},
    )
    validate_benchmark(result)
    return result
