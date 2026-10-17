"""对既有七条原话重新盲提取和预审；不生成请求、不入正式题集、不自动批准。"""

import argparse
import copy
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "python_agent"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rs_core.common.openai_compatible_client import first_message_content, safe_response_metadata
from rs_core.offline.evaluation.skill_benchmark.dataset import fingerprint, load_benchmark
from rs_core.offline.evaluation.skill_benchmark.request_contract import validate_request
from rs_core.offline.evaluation.skill_benchmark.request_contract_v3 import (
    AUDIT_VERSION, REQUEST_VERSION, evidence_report, normalize_request)
from rs_core.offline.evaluation.skill_benchmark.request_synthesis import AUDIT, EXTRACT, VERSION, validate_audit
from skill_evolution import configured_model


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def select_existing(source, review):
    if (source.get("schema_version") != VERSION or source.get("contains_test_users") is not False
            or source.get("is_gold") is not False or source.get("human_reviewed") is not False
            or review.get("source_pack_sha256") != fingerprint(source) or review.get("is_gold") is not False):
        raise ValueError("仅允许与待人审草案对应的原始非测试候选包")
    originals = [row for row in source["entries"] if row.get("customer_message")]
    ids = [row["candidate_id"] for row in originals]
    review_ids = [row["candidate_id"] for row in review["entries"]]
    if (len(ids) != 7 or len(set(ids)) != 7 or len(review_ids) != 7 or len(set(review_ids)) != 7
            or set(ids) != set(review_ids)):
        raise ValueError("必须只处理原有七条，不得新增、遗漏或重复")
    for row in originals:
        if row.get("split") not in {"train", "dev"} or row.get("is_gold") is not False:
            raise ValueError("不允许测试用户或gold进入重跑")
        view = next(view for view in review["entries"] if view["candidate_id"] == row["candidate_id"])
        if (view["customer_message"] != row["customer_message"]
                or view["original_validated_extraction"] != row.get("extraction")
                or view["original_status"] != row["status"]):
            raise ValueError("原话、提取或原状态与对照稿不一致")
    return copy.deepcopy(originals)


def recorded_call(model, instruction, payload):
    """只保存模型内容和白名单响应元信息；不保存HTTP头、凭证或异常原文。"""
    record = {"request_payload": copy.deepcopy(payload), "instruction_sha256": fingerprint(instruction),
              "requested_model": model.model, "started_at": datetime.now(timezone.utc).isoformat()}
    try:
        response = model.client.chat_completion(model=model.model,
            messages=[{"role": "system", "content": instruction},
                      {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            temperature=0, max_tokens=model.max_tokens, response_format={"type": "json_object"})
        record["response_metadata"] = safe_response_metadata(response)
        content = first_message_content(response)
        record["raw_content"] = content
        record["parsed_json"] = json.loads(content)
        record["call_succeeded"] = True
    except Exception as error:
        record.update(call_succeeded=False, error_type=type(error).__name__)
    record["completed_at"] = datetime.now(timezone.utc).isoformat()
    return record


def rerun_candidate(original, model, directory):
    row = {key: copy.deepcopy(original[key]) for key in ("candidate_id", "customer_message", "source_task_id",
        "profile_user_id", "family_id", "statistical_cluster_id", "split", "environment_sha256")}
    row.update(original_status=original["status"], status="quarantined", model_calls=0,
               human_reviews=[], is_gold=False, auto_deploy=False)
    folder = Path(directory) / row["candidate_id"]
    folder.mkdir(exist_ok=False)
    extraction_call = recorded_call(model, EXTRACT, {"customer_message": row["customer_message"]})
    row["model_calls"] += 1
    write(folder / "extraction-call.json", extraction_call)
    row["extraction_call"] = extraction_call
    raw = extraction_call.get("parsed_json")
    row["evidence_validation"] = evidence_report(raw, row["customer_message"])
    try:
        if not extraction_call["call_succeeded"]:
            raise ValueError("模型调用或JSON解析失败")
        if not isinstance(raw, dict) or raw.get("schema_version") != REQUEST_VERSION:
            raise ValueError("本次重跑必须返回v3需求协议")
        normalized, changes = normalize_request(raw)
        row["normalization"] = {"changes": changes, "normalized_candidate": normalized,
                                "raw_output_preserved": True, "does_not_certify_semantics": True}
        row["extraction"] = validate_request(raw, row["customer_message"])
        row["extraction_protocol_valid"] = True
    except ValueError as error:
        row.update(extraction_protocol_valid=False, extraction_protocol_error=str(error))
    print(json.dumps({"candidate_id": row["candidate_id"], "stage": "extraction",
                      "protocol_valid": row["extraction_protocol_valid"]}, ensure_ascii=False), flush=True)
    # JSON对象即使结构失败仍可以接受语义预审，但不修补、不把程序报错或草案送给审核模型。
    if not extraction_call["call_succeeded"] or not isinstance(raw, dict):
        row["quarantine_reason"] = "extraction_call_or_json_failed_audit_not_callable"
        row["audit_protocol_valid"] = None
        write(folder / "result.json", row)
        return row
    audit_call = recorded_call(model, AUDIT, {"customer_message": row["customer_message"],
        "extraction": copy.deepcopy(raw), **copy.deepcopy(original["context"])})
    row["model_calls"] += 1
    write(folder / "audit-call.json", audit_call)
    row["audit_call"] = audit_call
    try:
        if not audit_call["call_succeeded"]:
            raise ValueError("模型调用或JSON解析失败")
        audit = validate_audit(audit_call["parsed_json"], row["customer_message"], original["context"])
        if audit.get("schema_version") != AUDIT_VERSION:
            raise ValueError("本次重跑必须返回新版审核协议")
        row["model_audit"] = audit
        row["audit_protocol_valid"] = True
        row["model_audit_all_pass"] = all(value == "pass" for value in audit["checks"].values()) and not audit["issues"]
    except ValueError as error:
        row.update(audit_protocol_valid=False, audit_protocol_error=str(error), model_audit_all_pass=False)
    returned_models = [call.get("response_metadata", {}).get("model") for call in (extraction_call, audit_call)]
    row["returned_model_matches_request"] = all(value == model.model for value in returned_models)
    row["completions_finished_normally"] = all(call.get("response_metadata", {}).get("finish_reason") == "stop"
                                               for call in (extraction_call, audit_call))
    if (row["extraction_protocol_valid"] and row["audit_protocol_valid"] and row["model_audit_all_pass"]
            and row["returned_model_matches_request"] and row["completions_finished_normally"]):
        row["status"] = "pending_independent_human_review"
    else:
        row["quarantine_reason"] = "new_protocol_or_model_audit_or_model_identity_failed"
    print(json.dumps({"candidate_id": row["candidate_id"], "stage": "audit",
        "protocol_valid": row["audit_protocol_valid"], "checks": audit_call.get("parsed_json", {}).get("checks")
            if isinstance(audit_call.get("parsed_json"), dict) else None,
        "status": row["status"]}, ensure_ascii=False), flush=True)
    write(folder / "result.json", row)
    return row


def requirement_signature(value):
    """仅比较严格/近似结构键值，不宣称中文释义或同义词语义相同。"""
    return sorted(fingerprint({key: row[key] for key in ("kind", "field", "relation", "value", "unit")})
                  for row in value.get("requirements", []) if row.get("kind") in {"strict", "approximate"})


def compare_with_review(row, review):
    draft = review["revision_proposal"]
    new = row.get("extraction", row["extraction_call"].get("parsed_json"))
    if not row["extraction_protocol_valid"]:
        return {"available": False, "reason": "结构失败，不能自动比较为有效新提取"}
    return {"available": True, "comparison_scope": "exact_structural_fields_not_semantic_agreement_or_truth",
            "primary_intent_equal": new["intent"]["primary"] == draft["intent"]["primary"],
            "requested_action_sets_equal": set(new["intent"]["actions"]) == set(draft["intent"]["actions"]),
            "strict_approximate_signatures_equal": requirement_signature(new) == requirement_signature(draft),
            "clarification_mode_equal": new["clarification"]["mode"] == draft["clarification"]["mode"],
            "unresolved_action_sets_equal": set(new["clarification"]["unresolved_actions"]) == set(draft["clarification"]["unresolved_actions"]),
            "recipient_target_equal": new["recipient"]["target"] == draft["recipient"]["target"],
            "profile_policy_equal": new["recipient"]["profile_policy"] == draft["recipient"]["profile_policy"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--review", required=True)
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--workers", type=int, choices=[1, 2], default=2)
    args = parser.parse_args()
    paths = [Path(args.source), Path(args.review), Path(args.benchmark)]
    before = {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    source, review, benchmark = read(args.source), read(args.review), load_benchmark(args.benchmark)
    selected = select_existing(source, review)
    if fingerprint(benchmark) != source["source_benchmark_sha256"]:
        raise ValueError("冻结环境与原候选包不对应")
    model = configured_model("RS_REQUEST_VERIFY")
    if model is None or model.model != "gpt-6-luna":
        raise ValueError("本次仅允许显式配置用户指定的gpt-6-luna")
    model.client._validate_base_url()
    destination = Path(args.out_dir)
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {"schema_version": "rs-request-reextraction-preview/1", "source_pack_sha256": fingerprint(source),
        "review_sha256": fingerprint(review), "source_benchmark_sha256": fingerprint(benchmark),
        "model": model.model, "model_identity": model.identity, "max_tokens": model.max_tokens,
        "model_independence": "same_model_fresh_contexts_not_independent_gold",
        "role_input_boundaries": {"extraction": ["customer_message"], "audit": ["customer_message", "extraction", "catalog", "profile", "price_unit"]},
        "draft_or_old_audit_sent_to_models": False,
        "max_model_calls": 14, "automatic_retries": 0, "workers": args.workers,
        "request_schema_version": REQUEST_VERSION, "audit_schema_version": AUDIT_VERSION,
        "prompts": {"extraction": EXTRACT, "audit": AUDIT},
        "prompt_sha256": fingerprint({"extraction": EXTRACT, "audit": AUDIT}),
        "input_file_sha256": before, "formal_task_count": len(benchmark["tasks"]),
        "is_gold": False, "human_reviewed": False, "auto_deploy": False,
        "started_at": datetime.now(timezone.utc).isoformat()}
    write(destination / "manifest.json", manifest)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        entries = list(pool.map(lambda row: rerun_candidate(row, model, destination), selected))
    views = {row["candidate_id"]: row for row in review["entries"]}
    for row in entries:
        row["comparison_with_assistant_draft"] = compare_with_review(row, views[row["candidate_id"]])
        row["original_and_draft_review"] = copy.deepcopy(views[row["candidate_id"]])
    after = {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    summary = {"existing_requests": 7, "added_requests": 0, "model_calls": sum(row["model_calls"] for row in entries),
        "extraction_protocol_valid": sum(row["extraction_protocol_valid"] for row in entries),
        "audit_protocol_valid": sum(row["audit_protocol_valid"] is True for row in entries),
        "new_model_all_pass": sum(row.get("model_audit_all_pass", False) for row in entries),
        "pending_human_review": sum(row["status"] == "pending_independent_human_review" for row in entries),
        "quarantined": sum(row["status"] == "quarantined" for row in entries), "input_files_unchanged": before == after}
    result = {**manifest, "completed_at": datetime.now(timezone.utc).isoformat(), "summary": summary,
              "formal_benchmark_modified": before[str(Path(args.benchmark).resolve())] != after[str(Path(args.benchmark).resolve())],
              "entries": entries}
    write(destination / "reextraction-results.json", result)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if before != after:
        raise ValueError("原始输入发生变化；不得据该运行批准样本")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"run_failed": True, "error_type": type(error).__name__}, ensure_ascii=False), flush=True)
        raise SystemExit(1)
