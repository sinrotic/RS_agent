"""离线整理既有候选与人工拟订修订草案；不调用模型，不添加样本，不升级原状态。"""

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "python_agent"))

from rs_core.offline.evaluation.skill_benchmark.dataset import fingerprint, load_benchmark
from rs_core.offline.evaluation.skill_benchmark.request_contract import schema_description, validate_request
from rs_core.offline.evaluation.skill_benchmark.request_contract_v3 import contract_description
from rs_core.offline.evaluation.skill_benchmark.request_synthesis import VERSION, validate_audit


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_review(source, proposals, diagnostics=None):
    """输入输出全复制；未得到可用原话的原始失败槽位只统计、不补造。"""
    if (source.get("schema_version") != VERSION or source.get("is_gold") is not False
            or source.get("contains_test_users") is not False or source.get("human_reviewed") is not False):
        raise ValueError("仅整理非测试、未经人工批准的候选包")
    source_hash = fingerprint(source)
    if proposals.get("source_pack_sha256") != source_hash:
        raise ValueError("修订草案与原始候选包不对应")
    source_ids = [row["candidate_id"] for row in source["entries"]]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("原始候选ID重复")
    originals = {row["candidate_id"]: row for row in source["entries"] if row.get("customer_message")}
    draft_ids = [row["candidate_id"] for row in proposals["entries"]]
    if len(draft_ids) != len(set(draft_ids)) or set(draft_ids) != set(originals):
        raise ValueError("必须逐条对应全部已有原话；禁止新增、重复或漏掉样本")
    if diagnostics is not None and diagnostics.get("source_pack_sha256") != source_hash:
        raise ValueError("诊断材料不属于该原始候选包")
    diagnostic_rows = {row["candidate_id"]: row for row in (diagnostics or {}).get("entries", [])}
    entries = []
    for draft in proposals["entries"]:
        original = originals[draft["candidate_id"]]
        if original.get("split") not in {"train", "dev"} or original.get("is_gold") is not False:
            raise ValueError("不得整理测试用户或gold")
        message = original["customer_message"]
        revision = validate_request(draft["revision_proposal"], message)
        if not isinstance(draft.get("disputes"), list) or not draft["disputes"]:
            raise ValueError("修订需要明确争议点")
        for dispute in draft["disputes"]:
            if (set(dispute) != {"issue", "certainty", "quote", "suggestion"}
                    or dispute["certainty"] not in {"clear_protocol_or_semantic_issue", "interpretation_pending_human_review"}
                    or any(not isinstance(dispute[key], str) or not dispute[key].strip() for key in dispute)
                    or dispute["quote"] not in message):
                raise ValueError("争议点必须有原话依据，并注明解释性争议")
        audit_views = []
        for origin, raw in (("original_saved_model_audit", original.get("raw_model_audit", original.get("model_audit"))),
                            ("previous_supplemental_diagnostic_call", diagnostic_rows.get(draft["candidate_id"], {}).get("raw_model_audit"))):
            if raw is None:
                continue
            view = {"origin": origin, "raw_model_audit": copy.deepcopy(raw), "is_gold": False,
                    "original_status_unchanged": True}
            try:
                validate_audit(raw, message, original["context"])
                view["current_compatibility_check"] = {"protocol_valid": True,
                    "interpretation": "只读格式兼容通过，不表示语义通过或人工批准"}
            except ValueError as error:
                view["current_compatibility_check"] = {"protocol_valid": False, "error": str(error)}
            audit_views.append(view)
        entries.append({"candidate_id": draft["candidate_id"], "title": draft["title"],
            "customer_message": message,
            "lineage": {key: copy.deepcopy(original[key]) for key in
                ("source_task_id", "profile_user_id", "family_id", "statistical_cluster_id", "split", "environment_sha256")},
            "original_status": original["status"], "original_failed_stage": original.get("failed_stage"),
            "original_error_type": original.get("error_type"),
            "original_validated_extraction": copy.deepcopy(original.get("extraction")),
            "original_raw_extraction": copy.deepcopy(original.get("raw_extraction")),
            "raw_extraction_available": "raw_extraction" in original,
            "original_extraction_note": ("原始包保存已验证提取；不声称恢复完整原响应" if "extraction" in original
                else "原提取失败且原响应未保存；缺失不是空需求，新草案不是恢复结果"),
            "original_audit_views": audit_views, "disputes": copy.deepcopy(draft["disputes"]),
            "revision_proposal": revision, "response_guidance": copy.deepcopy(draft["response_guidance"]),
            "revision_author": "codex_assistant_authored_offline_proposal_not_model_reextraction",
            "revision_status": "pending_human_review", "protocol_valid": True,
            "human_reviews": [], "is_gold": False, "auto_deploy": False})
    return {"schema_version": "rs-request-protocol-review/1", "source_pack_sha256": source_hash,
            "source_benchmark_sha256": source["source_benchmark_sha256"],
            "diagnostics_sha256": fingerprint(diagnostics) if diagnostics is not None else None,
            "contract": (contract_description() if all(row["revision_proposal"]["schema_version"] == "rs-shopping-request/3"
                         for row in entries) else schema_description()), "new_model_calls": 0,
            "summary": {"original_slots": len(source["entries"]), "existing_customer_messages": len(entries),
                        "added_customer_messages": 0, "failed_generation_slots_not_reconstructed": len(source["entries"]) - len(entries)},
            "human_reviewed": False, "is_gold": False, "auto_deploy": False,
            "formal_benchmark_modified": False, "original_statuses_modified": False, "entries": entries}


def render_review(review):
    lines = ["# 七条购物请求：原始提取、争议与修订草案", "",
        "本次仅离线整理原有 7 条顾客原话；新增请求 0 条，新增模型调用 0 次，未入正式评测集，未上线。",
        "原始 8 个槽位包括一次生成 JSON 失败，不补造第 8 条。所有原始隔离状态保持不变。", "",
        "修订草案由 Codex 根据已有原话拟订，不是 6-luna 的重新提取，更不是已批准的标准答案。",
        "结构及逐字证据校验通过，不等于语义正确。原审核仍是同一模型的判断，存在相关误差。", "",
        "## 新协议的边界", "",
        "先判断推荐、比较、兼容咨询或方法咨询，再记录当前条件；近似条件不造容差、不变成硬过滤。",
        "明确要回答的比较维度和核对方法单独放 answer_requirements。背景设备和备选方案不自动变成必购商品。",
        "unknowns 区分当前答案必需、具体商品判断才必需、可选优化。一般解释可先回答，但未知时不能保证具体兼容性。",
        "本人历史仅是经授权的弱偏好，不能覆盖当前需求，不能迁移给收礼人，也不能证明现有设备。", "",
        "| 样本 | 修订意图 | 首要问题 |", "| --- | --- | --- |"]
    for row in review["entries"]:
        lines.append(f"| {row['candidate_id']} {row['title']} | {row['revision_proposal']['intent']['primary']} | {row['disputes'][0]['issue']} |")
    for index, row in enumerate(review["entries"], 1):
        draft = row["revision_proposal"]
        lines += ["", f"## {index}. {row['title']}（{row['candidate_id']}）", "", "顾客原话：", "", "> " + row["customer_message"], "",
            "### 原始提取与审核", "", row["original_extraction_note"], "",
            f"原始状态 `{row['original_status']}`；失败阶段 `{row['original_failed_stage'] or '无协议失败；语义审核失败'}`。"]
        if row["original_validated_extraction"] is not None:
            lines += ["", "```json", json.dumps(row["original_validated_extraction"], ensure_ascii=False, indent=2), "```"]
        if not row["original_audit_views"]:
            lines += ["", "没有保存可展示的审核原响应；本次不重新调用审核模型。"]
        for view in row["original_audit_views"]:
            raw = view["raw_model_audit"]
            lines += ["", "审核来源：" + view["origin"] + "；这是已存在的输出，不是本次调用。",
                      "模型维度判断：" + "；".join(f"{key}={value}" for key, value in raw["checks"].items()) + "。"]
            reasons = raw.get("reasons", raw.get("reason"))
            if isinstance(reasons, dict):
                lines += ["", *[f"- {key}：{value}" for key, value in reasons.items()]]
            else:
                lines += ["", str(reasons)]
            check = view["current_compatibility_check"]
            lines += ["", "当前只读兼容检查：" + ("通过；四维理由对象已被旧格式兼容器接受，原状态不翻转。" if check["protocol_valid"]
                                                      else "不通过；" + check["error"] + "。原文证据未被自动修补。")]
        lines += ["", "### 争议与修订建议", ""]
        for dispute in row["disputes"]:
            certainty = "解释性争议，待人审" if dispute["certainty"] == "interpretation_pending_human_review" else "明确的结构或语义问题"
            lines.append(f"- {dispute['issue']}（{certainty}）。证据：『{dispute['quote']}』。建议：{dispute['suggestion']}")
        lines += ["", "### 修订草案如何使用", "", "请求动作：" + "、".join(draft["intent"]["actions"]) + "。", "",
                  "| 强度 | 条件 | 运算和值 | 单位 |", "| --- | --- | --- | --- |"]
        for need in draft["requirements"]:
            lines.append(f"| {need['kind']} | {need['field']} | {need['relation']} {need['value']} | {need['unit'] or '未明确'} |")
        if not draft["requirements"]:
            lines.append("| — | 无必须购买的商品条件 | 不编造 | — |")
        lines += ["", "明确要回答：" + "；".join(need["need"] for need in draft["answer_requirements"]) + "。", "",
                  "澄清模式：`" + draft["clarification"]["mode"] + "`；可先回答：" + str(draft["clarification"]["safe_answer_before_clarification"]) + "。", ""]
        if draft["clarification"]["unresolved_actions"]:
            lines += ["暂缓给出结论的请求动作：" + "、".join(draft["clarification"]["unresolved_actions"]) + "。", ""]
        for unknown in draft["unknowns"]:
            lines.append(f"- 未知 `{unknown['slot']}`：{unknown['blocking_level']}；用于 {', '.join(unknown['needed_for'])}。{unknown['reason']}")
        lines += ["", "建议追问：", ""]
        questions = draft["clarification"]["questions"]
        lines += [f"- {q['question']}（{q['necessity']}；{q['reason']}）" for q in questions] if questions else ["不设置必须追问；不为了补齐槽位盘问顾客。"]
        lines += ["", "画像参与：`" + draft["recipient"]["profile_policy"] + "`。", "", *[f"- {guidance}" for guidance in row["response_guidance"]], "",
                  "修订状态：待人审；协议校验通过 ≠ 标准答案批准。完整新结构和审核原输出见同目录 review.json。"]
    lines += ["", "## 仍待确认", "", "先确认这些意图、近似条件及追问必要性是否符合购物习惯，再决定是否让模型按新协议重跑。",
              "本次不扩量、不导入正式题集、不改评分权重或校准结论；尚无推荐执行结果，因此也不编造推荐得分。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--proposals", required=True)
    parser.add_argument("--diagnostics")
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    paths = [Path(args.source), Path(args.proposals), Path(args.benchmark)] + ([Path(args.diagnostics)] if args.diagnostics else [])
    before = {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    source = read(args.source)
    benchmark = load_benchmark(args.benchmark)
    if fingerprint(benchmark) != source["source_benchmark_sha256"]:
        raise ValueError("冻结环境与原候选包不对应")
    review = build_review(source, read(args.proposals), read(args.diagnostics) if args.diagnostics else None)
    review["verification"] = {"input_file_sha256": before, "formal_task_count": len(benchmark["tasks"]),
                              "source_benchmark_fingerprint_verified": True,
                              "customer_messages_from_original_only": True,
                              "environment_scope": "原冻结环境引用与哈希保持；本次不重建、不改变工具、库存或画像授权"}
    after = {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    if before != after:
        raise ValueError("输入文件发生变化，停止导出")
    review["verification"]["inputs_unchanged"] = True
    destination = Path(args.out_dir)
    destination.mkdir(parents=True, exist_ok=False)
    with (destination / "review.json").open("x", encoding="utf-8") as stream:
        json.dump(review, stream, ensure_ascii=False, indent=2, allow_nan=False)
    with (destination / "review.md").open("x", encoding="utf-8") as stream:
        stream.write(render_review(review))
    print(json.dumps({**review["summary"], "new_model_calls": 0, "formal_task_count": len(benchmark["tasks"]),
                      "inputs_unchanged": True, "is_gold": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
