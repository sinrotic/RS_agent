"""合成模型和预审模型均为受控夹具；验证流程，不证明真实顾客自然性。"""

import copy
import json

import pytest

from rs_core.offline.evaluation.skill_benchmark.dataset import fingerprint
from rs_core.offline.evaluation.skill_benchmark.request_contract import DIMENSIONS
from rs_core.offline.evaluation.skill_benchmark.request_contract_v3 import AUDIT_VERSION, REQUEST_VERSION
from rs_core.offline.evaluation.skill_benchmark.request_synthesis import (
    AUDIT, EXTRACT, GENERATE, constraint_fact_report, synthesis_seeds, synthesize_requests,
    validate_extraction,
)

MESSAGE = "想找支中性笔，上课记得快也别糊，二十以内就行。"


def benchmark():
    catalog = [{"item_id": "private-item-0001", "title": "中性笔0.5mm", "category": "pens",
                "price": 12, "currency": "SOURCE_UNIT", "tip_mm": .5},
               {"item_id": "private-item-0002", "title": "中性笔0.7mm", "category": "pens",
                "price": 18, "currency": "SOURCE_UNIT", "tip_mm": .7}]
    profiles, tasks = {}, []
    for split in ("train", "dev", "test"):
        user = "private-user-" + split
        profiles[user] = {"profile_user_id": user, "history_cutoff_exclusive": 10,
            "seen_item_ids": [catalog[0]["item_id"]], "profile_preferences": {},
            "history": [{"user_id": user, "parent_asin": catalog[0]["item_id"],
                         "timestamp": 5, "rating": 5, "item": copy.deepcopy(catalog[0])}]}
        tasks.append({"task_id": user + "-source", "family_id": user,
            "profile_user_id": user, "split": split, "kind": "clear_purchase",
            "review_status": "pending",
            "environment": {"profile_access": {"allowed": True, "bound_profile_user_id": user}},
            "turns": [{"user_message": "旧模板请求：帮我选一款20以内的中性笔。", "limit": 1,
                       "gold": {"k": 1, "hard": [{"field": "category", "op": "eq", "value": "pens"},
                                                 {"field": "price", "op": "lte", "value": 20}], "soft": []}}]})
    return {"schema_version": "rs-skill-benchmark/1", "catalog": catalog, "profiles": profiles,
            "tasks": tasks, "environment": {},
            "manifest": {"catalog_sha256": fingerprint(catalog), "profiles_sha256": fingerprint(profiles)}}


def extraction():
    return {"hard_constraints": [{"field": "price", "op": "lte", "value": 20, "quote": "二十以内"}],
            "soft_preferences": [{"need": "书写不易糊", "quote": "别糊"}],
            "unknowns": [{"slot": "tip_mm", "reason": "未明确笔尖粗细"}],
            "purchase_for": "unknown", "purchase_for_quote": None,
            "needs_clarification": False, "clarification_questions": []}


def protocol_fixture(legacy):
    """测试夹具手工映射，不是生产升级器，也不证明约束语义正确。"""
    return {"schema_version": REQUEST_VERSION,
            "intent": {"primary": "recommendation", "actions": ["recommend"], "evidence": [MESSAGE]},
            "context_facts": [],
            "answer_requirements": [{"kind": "recommendation", "need": "推荐书写用品", "quote": MESSAGE}],
            "requirements": [dict(id=f"hard-{i}", kind="strict", field=row["field"], relation=row["op"],
                                   value=row["value"], unit=None, quote=row["quote"])
                             for i, row in enumerate(legacy["hard_constraints"])] +
                            [dict(id=f"soft-{i}", kind="preference", field="writing", relation="prefer",
                                  value=row["need"], unit=None, quote=row["quote"])
                             for i, row in enumerate(legacy["soft_preferences"])],
            "unknowns": [dict(slot=row["slot"], reason=row["reason"], needed_for=["recommend"],
                              blocking_level="optional_refinement") for row in legacy["unknowns"]],
            "clarification": {"mode": "not_needed", "safe_answer_before_clarification": True, "unresolved_actions": [], "questions": []},
            "recipient": {"target": legacy["purchase_for"], "quote": legacy["purchase_for_quote"],
                          "profile_policy": "weak_reference_if_self", "profile_reason": "仅本人授权且相关时弱参考，不推定适用"}}


class Generator:
    model, identity = "fixture-generator-v1", "fixture-generator-identity"

    def __init__(self, output=None):
        self.output = output if output is not None else {"customer_message": MESSAGE}
        self.calls = []

    def __call__(self, prompt, payload):
        self.calls.append((prompt, copy.deepcopy(payload)))
        return copy.deepcopy(self.output)


class Verifier:
    model, identity = "fixture-verifier-v2", "fixture-verifier-identity"

    def __init__(self, extracted=None, check="pass", issues=None):
        self.extracted = extracted if extracted is not None else extraction()
        self.check, self.issues = check, issues or []
        self.calls = []

    def __call__(self, prompt, payload):
        self.calls.append((prompt, copy.deepcopy(payload)))
        if prompt == EXTRACT:
            return protocol_fixture(copy.deepcopy(self.extracted))
        assert prompt == AUDIT
        return {"schema_version": AUDIT_VERSION, "checks": {key: self.check for key in
                           ("naturalness", "extraction_fidelity", "fact_boundary", "clarification_policy")},
                "reasons": {key: "受控预审，仅测试协议" for key in DIMENSIONS}, "issues": self.issues,
                "evidence": [{"source": "customer", "quote": payload["customer_message"]}]}


def run(generator=None, verifier=None, **kwargs):
    return synthesize_requests(benchmark(), generator or Generator(), verifier or Verifier(),
                               seed_limit=1, variants=1, **kwargs)


def test_isolated_generation_blind_extraction_audit_and_no_gold():
    source, generator, verifier, saved = benchmark(), Generator(), Verifier(), []
    before = fingerprint(source)
    result = synthesize_requests(source, generator, verifier, seed_limit=1, variants=1, checkpoint=saved.append)
    assert fingerprint(source) == before
    assert generator.calls[0][0] == GENERATE
    payload = generator.calls[0][1]
    assert set(payload) == {"catalog", "profile", "price_unit", "style"}
    encoded = json.dumps(payload)
    assert "private-user" not in encoded and "private-item" not in encoded
    assert "gold" not in encoded and "anchor" not in encoded and "旧模板请求" not in encoded
    assert verifier.calls[0] == (EXTRACT, {"customer_message": MESSAGE})
    assert set(verifier.calls[1][1]) == {"customer_message", "extraction", "catalog", "profile", "price_unit"}
    assert result["summary"]["model_calls"] == 3
    row = result["entries"][0]
    assert row["status"] == "pending_independent_human_review"
    assert row["human_reviews"] == [] and row["is_gold"] is False
    assert row["fact_report"]["known_feasible_count"] is None  # 原话未确认货币单位。
    assert row["fact_report"]["unverified_conditions"][0]["field"] == "price"
    assert result["human_reviewed"] is False and result["auto_deploy"] is False
    assert saved == [row]


def test_test_users_excluded_and_original_splits_retained():
    seeds = synthesis_seeds(benchmark(), seed_limit=24)
    assert {row["split"] for row in seeds} == {"train", "dev"}
    assert all(row["family_id"] == row["profile_user_id"] for row in seeds)
    with pytest.raises(ValueError, match="隐藏测试"):
        synthesis_seeds(benchmark(), splits=("test",))


@pytest.mark.parametrize("kind", ["name", "identity", "same_object", "unconfigured"])
def test_roles_must_be_configured_and_different_before_calls(kind):
    generator, verifier = Generator(), Verifier()
    if kind == "name":
        verifier.model = " FIXTURE-GENERATOR-V1 "
    elif kind == "identity":
        verifier.identity = generator.identity
    elif kind == "same_object":
        verifier = generator
    else:
        verifier = None
    with pytest.raises(ValueError, match="不同模型"):
        synthesize_requests(benchmark(), generator, verifier, seed_limit=1, variants=1)
    assert generator.calls == []


def test_budget_checked_before_any_model_call():
    generator, verifier = Generator(), Verifier()
    with pytest.raises(ValueError, match="预算"):
        run(generator, verifier, max_calls=2)
    assert generator.calls == verifier.calls == []


def test_same_model_requires_explicit_preview_permission_and_is_never_gold():
    generator, verifier = Generator(), Verifier()
    verifier.model, verifier.identity = generator.model, generator.identity
    result = run(generator, verifier, allow_shared_model_preview=True)
    assert result["model_independence"] == "shared_model_preview"
    assert result["is_gold"] is False and result["human_reviewed"] is False
    assert result["auto_deploy"] is False
    assert verifier.calls[0][1] == {"customer_message": MESSAGE}
    assert result["summary"]["model_calls"] == 3


def test_shared_preview_does_not_allow_unconfigured_verifier():
    with pytest.raises(ValueError):
        synthesize_requests(benchmark(), Generator(), None, allow_shared_model_preview=True)


@pytest.mark.parametrize("output", [
    {"customer_message": MESSAGE, "gold": {}},
    {"customer_message": ""},
    {"customer_message": "帮private-user-train挑一款笔"},
])
def test_bad_generation_is_quarantined_and_not_sent_to_verifier(output):
    verifier = Verifier()
    result = run(Generator(output), verifier)
    assert result["entries"][0]["status"] == "quarantined"
    assert result["entries"][0]["failed_stage"] == "generation"
    assert verifier.calls == []


def test_source_and_batch_near_duplicates_quarantined():
    verifier = Verifier()
    message = benchmark()["tasks"][0]["turns"][0]["user_message"] + "！"
    result = run(Generator({"customer_message": message}), verifier)
    assert result["entries"][0]["quarantine_reason"] == "duplicate_or_near_duplicate"
    assert verifier.calls == []
    generator = Generator()
    result = synthesize_requests(benchmark(), generator, Verifier(), seed_limit=1, variants=2)
    assert result["entries"][1]["quarantine_reason"] == "duplicate_or_near_duplicate"
    assert result["summary"]["model_calls"] == 4


@pytest.mark.parametrize("check", ["fail", "unknown"])
def test_audit_never_accepts_fail_or_unknown(check):
    result = run(verifier=Verifier(check=check))
    assert result["entries"][0]["status"] == "quarantined"
    assert result["entries"][0]["quarantine_reason"] == "model_audit_fail_or_unknown"


def test_positive_checks_with_issues_still_quarantined():
    result = run(verifier=Verifier(issues=["约束可能有遗漏"]))
    assert result["entries"][0]["status"] == "quarantined"


def test_extraction_quote_must_come_from_customer_not_profile():
    value = extraction()
    value["hard_constraints"][0]["quote"] = "历史表明喜欢0.5mm"
    verifier = Verifier(extracted=value)
    result = run(verifier=verifier)
    assert result["entries"][0]["failed_stage"] == "extraction"
    assert len(verifier.calls) == 1


def test_unknown_purpose_cannot_be_filled_from_history():
    value = extraction()
    value["purchase_for"] = "self"
    with pytest.raises(ValueError, match="原话依据"):
        validate_extraction(value, MESSAGE)


def test_unsupported_conditions_and_catalog_unknowns_are_not_passed():
    value = extraction()
    value["hard_constraints"].append({"field": "battery_hours", "op": "gte", "value": 8, "quote": "八小时"})
    catalog = benchmark()["catalog"]
    catalog[0].pop("price")
    report = constraint_fact_report(catalog, value)
    assert report["known_feasible_count"] == 1 and report["potential_count"] == 2
    assert report["unverified_conditions"][0]["field"] == "battery_hours"
    assert report["counts_cover_all_hard_constraints"] is False


def test_missing_hard_conditions_are_valid_but_have_no_formula_score():
    value = extraction()
    value["hard_constraints"] = []
    result = run(verifier=Verifier(extracted=value))
    assert not any(row["kind"] == "strict" for row in result["entries"][0]["extraction"]["requirements"])
    assert result["entries"][0]["fact_report"]["known_feasible_count"] is None
    assert result["entries"][0]["status"] == "pending_independent_human_review"


def test_exceptions_do_not_leak_secrets_or_retry():
    class BrokenGenerator(Generator):
        def __call__(self, prompt, payload):
            self.calls.append((prompt, payload))
            raise RuntimeError("SECRET_TOKEN_DO_NOT_SAVE")

    generator = BrokenGenerator()
    result = run(generator)
    assert "SECRET_TOKEN_DO_NOT_SAVE" not in json.dumps(result)
    assert result["entries"][0]["error_type"] == "RuntimeError"
    assert len(generator.calls) == 1


def test_profile_permission_required_before_sending_history():
    source = benchmark()
    for task in source["tasks"]:
        task["environment"]["profile_access"]["allowed"] = False
    generator = Generator()
    with pytest.raises(ValueError, match="授权画像"):
        synthesize_requests(source, generator, Verifier(), seed_limit=1, variants=1)
    assert generator.calls == []


def test_audit_evidence_must_exist_in_visible_sources():
    class FabricatingVerifier(Verifier):
        def __call__(self, prompt, payload):
            result = super().__call__(prompt, payload)
            if prompt == AUDIT:
                result["evidence"] = [{"source": "profile", "quote": "用户是学生，已经购买此笔"}]
            return result

    result = run(verifier=FabricatingVerifier())
    assert result["entries"][0]["failed_stage"] == "audit"
    assert result["entries"][0]["raw_model_audit"]["evidence"][0]["quote"] == "用户是学生，已经购买此笔"
    assert result["entries"][0]["protocol_error"] == "预审引用不在可见事实中"


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), "20"])
def test_numeric_constraint_must_be_finite_and_not_bool(value):
    row = extraction()
    row["hard_constraints"][0]["value"] = value
    with pytest.raises(ValueError):
        validate_extraction(row, MESSAGE)
