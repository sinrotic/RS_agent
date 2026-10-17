"""离线导出原始结果、Codex草案及真实重跑的对照；不调用模型、不修改原状态。"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "python_agent"))

from rs_core.offline.evaluation.skill_benchmark.request_contract import validate_request


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def quote_errors(extraction, message):
    errors = []
    def walk(value, path):
        if isinstance(value, dict):
            for key, child in value.items():
                current = f"{path}/{key}"
                if key == "quote" and child is not None and (not isinstance(child, str) or child not in message):
                    errors.append({"json_pointer": current, "quote": child})
                else:
                    walk(child, current)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                current = f"{path}/{index}"
                if path == "/intent/evidence" and (not isinstance(child, str) or child not in message):
                    errors.append({"json_pointer": current, "quote": child})
                else:
                    walk(child, current)
    walk(extraction, "")
    return errors


def validate_and_compare(result, notes):
    ids = [row["candidate_id"] for row in result["entries"]]
    note_ids = [row["candidate_id"] for row in notes["entries"]]
    if len(ids) != 7 or len(set(ids)) != 7 or len(set(note_ids)) != 7 or len(note_ids) != 7 or set(ids) != set(note_ids):
        raise ValueError("必须精确对应七条")
    if result.get("is_gold") is not False or notes.get("is_gold") is not False:
        raise ValueError("仅允许非gold对照")
    paths = result["input_file_sha256"]
    if not all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected for path, expected in paths.items()):
        raise ValueError("原始候选、草案或正式题集发生变化")
    all_calls = []
    diagnostics = {}
    for row in result["entries"]:
        message = row["customer_message"]
        view = row["original_and_draft_review"]
        if view["customer_message"] != message or view["original_status"] != row["original_status"]:
            raise ValueError("原始原话或状态不一致")
        extraction_call, audit_call = row["extraction_call"], row["audit_call"]
        if extraction_call["request_payload"] != {"customer_message": message}:
            raise ValueError("盲提取输入越界")
        payload = audit_call["request_payload"]
        if (set(payload) != {"customer_message", "extraction", "catalog", "profile", "price_unit"}
                or payload["customer_message"] != message or payload["extraction"] != extraction_call["parsed_json"]):
            raise ValueError("审核输入越界或提取被改写")
        all_calls += [extraction_call, audit_call]
        protocol_error = None
        try:
            validate_request(extraction_call["parsed_json"], message)
        except ValueError as error:
            protocol_error = str(error)
        if (protocol_error is None) != row["extraction_protocol_valid"]:
            raise ValueError("现协议与运行时校验结论不同，不得混用")
        new = extraction_call["parsed_json"]
        unknown_for_verify = [unknown["slot"] for unknown in new.get("unknowns", [])
                              if "verify_compatibility" in unknown.get("needed_for", [])
                              and unknown.get("blocking_level") == "needed_for_specific_item"]
        diagnostics[row["candidate_id"]] = {
            "nonliteral_customer_quotes": quote_errors(new, message),
            "compatibility_action_unknown_without_recorded_deferral": bool(
                "verify_compatibility" in new["intent"]["actions"] and unknown_for_verify
                and "verify_compatibility" not in new["clarification"]["unresolved_actions"]),
            "compatibility_diagnostic_scope": "提示跨字段复核；是否当轮请求具体结论需人审，不自动改状态",
            "profile_policy_for_methods_requires_relevance_review": bool(
                new["recipient"]["profile_policy"] == "weak_reference_if_self"
                and "recommend" not in new["intent"]["actions"])}
        note = next(note for note in notes["entries"] if note["candidate_id"] == row["candidate_id"])
        for dispute in note["remaining_disputes"]:
            if dispute["customer_quote"] not in message:
                raise ValueError("分析笔记引用不在顾客原话中")
    if len(all_calls) != 14 or sum(row["model_calls"] for row in result["entries"]) != 14:
        raise ValueError("模型调用数量不一致")
    if not all(call["response_metadata"]["model"] == "gpt-6-luna"
               and call["response_metadata"]["finish_reason"] == "stop" for call in all_calls):
        raise ValueError("返回模型或结束状态不同")
    summary = {**result["summary"],
        "audit_checks_all_pass": sum(all(value == "pass" for value in row["model_audit"]["checks"].values()) for row in result["entries"]),
        "audit_checks_all_pass_and_no_issues": sum(row["model_audit_all_pass"] for row in result["entries"]),
        "all_returned_models": ["gpt-6-luna"],
        "total_tokens": sum(call["response_metadata"]["usage"]["total_tokens"] for call in all_calls),
        "independent_profile_clusters": len({row["statistical_cluster_id"] for row in result["entries"]}),
        "all_original_files_unchanged": True, "model_input_boundaries_verified": True,
        "formal_task_count": result["formal_task_count"], "formal_imports": 0, "new_model_calls_for_comparison": 0}
    return {"schema_version": "rs-request-reextraction-comparison/1", "summary": summary,
            "source_results": result, "assistant_analysis": notes, "deterministic_diagnostics": diagnostics,
            "human_reviewed": False, "is_gold": False, "auto_deploy": False}


def short_requirements(value, legacy=False):
    if value is None:
        return "提取失败，原响应未保存"
    rows = value.get("hard_constraints", []) if legacy else [row for row in value["requirements"] if row["kind"] in {"strict", "approximate"}]
    if not rows:
        return "无严格或结构化近似商品条件"
    return "；".join(f"{row['field']} {row.get('op', row.get('relation'))} {row['value']}" +
                    (f" {row.get('unit')}" if row.get("unit") else "") for row in rows)


def render(comparison, directory):
    result, notes, summary = comparison["source_results"], comparison["assistant_analysis"], comparison["summary"]
    annotations = {note["candidate_id"]: note for note in notes["entries"]}
    lines = ["# 七条购物请求新版提取审核与争议对照", "", notes["conclusion"], "",
        "本次使用实际服务模型 gpt-6-luna，共14次新调用，原有7条原话未改，未生成新请求、未加入正式评测集、未上线。",
        "提取只收到原话；审核收到新提取及原有目录和画像上下文。两轮都是新的上下文，没有收到旧审核或Codex草案。同模型仍可能有相关误差。", "",
        "## 校验结果", "",
        f"提取程序校验通过 {summary['extraction_protocol_valid']}/7；审核程序校验通过 {summary['audit_protocol_valid']}/7。",
        f"模型审核四维全pass为 {summary['audit_checks_all_pass']}/7，其中无issues为 {summary['audit_checks_all_pass_and_no_issues']}/7。",
        f"按本次预览门槛，{summary['pending_human_review']}条待独立人审、{summary['quarantined']}条隔离；所有原始候选状态不变。待人审不是批准，也不是推荐质量得分。",
        f"返回模型全部为gpt-6-luna，结束标记均为stop；服务报告总token数 {summary['total_tokens']}。7条只涉及{summary['independent_profile_clusters']}个画像统计簇，不能据此判断全面覆盖或总体提取准确率。", "",
        "| 场景 | 新提取 | 新审核 | 新预览状态 | 仍需复核 |", "| --- | --- | --- | --- | --- |"]
    for row in result["entries"]:
        note = annotations[row["candidate_id"]]
        title = row["original_and_draft_review"]["title"].split("：")[0]
        raw_audit = row["model_audit"]
        audit_label = "四项pass" if all(value == "pass" for value in raw_audit["checks"].values()) else "提取忠实度fail"
        if raw_audit["issues"]:
            audit_label += "，issues非空"
        lines.append(f"| {title} | {'程序通过' if row['extraction_protocol_valid'] else '引用失败'} | {audit_label} | {'待人审' if row['status'] == 'pending_independent_human_review' else '隔离'} | {note['remaining_disputes'][0]['issue']} |")
    lines += ["", "## 共同争议与建议", "", *[f"- {value}" for value in notes["global_disputes"]], "",
        "建议先复核证据片段、统一字段与单位及需求存放位置、补动作与未知信息的对应规则，再讨论画像相关性和决策支持覆盖。以下判断是Codex分析，不是独立人审，不把草案当作比较真值。本次没有修改协议或正式评分规则。"]
    for index, row in enumerate(result["entries"], 1):
        note = annotations[row["candidate_id"]]
        view = row["original_and_draft_review"]
        draft, new = view["revision_proposal"], row["extraction_call"]["parsed_json"]
        raw_audit = row["model_audit"]
        lines += ["", f"## {index} {view['title'].replace('：', ' ')}", "", "顾客原话：", "", "> " + row["customer_message"], "",
            "| 版本 | 提取与回答策略 |", "| --- | --- |",
            f"| 原始提取 | {note['original_summary']} |", f"| Codex草案 待人审 | {note['draft_summary']} |", f"| 新6-luna提取 | {note['new_summary']} |", "",
            "### 条件的结构化对照", "", "| 版本 | 严格和近似条件 |", "| --- | --- |",
            f"| 原始 | {short_requirements(view['original_validated_extraction'], legacy=True)} |",
            f"| 草案 | {short_requirements(draft)} |", f"| 新模型 | {short_requirements(new)} |", "",
            "| 版本 | 意图和动作 | 澄清模式及暂缓动作 | 对象及画像策略 |", "| --- | --- | --- | --- |",
            f"| 草案 | {draft['intent']['primary']} / {', '.join(draft['intent']['actions'])} | {draft['clarification']['mode']} / {draft['clarification']['unresolved_actions']} | {draft['recipient']['target']} / {draft['recipient']['profile_policy']} |",
            f"| 新模型 | {new['intent']['primary']} / {', '.join(new['intent']['actions'])} | {new['clarification']['mode']} / {new['clarification']['unresolved_actions']} | {new['recipient']['target']} / {new['recipient']['profile_policy']} |", "",
            "这些是结构位置与字面值的对照，字段同义、意图粒度或单位表达不同不自动表示语义错误。", "",
            "### 新提取保留的回答需求", ""]
        lines += [f"- {need['need']}；证据：『{need['quote']}』" for need in new["answer_requirements"]] if new["answer_requirements"] else ["无单独answer_requirements；推荐动作和商品条件另行保留。"]
        lines += ["", "新模型追问：", ""]
        lines += [f"- {q['question']}（{q['necessity']}；{q['reason']}）" for q in new["clarification"]["questions"]] or ["不追问。"]
        if row.get("extraction_protocol_error"):
            lines += ["", "提取程序拒绝原因：" + row["extraction_protocol_error"] + "。"]
        quote_diagnostics = comparison["deterministic_diagnostics"][row["candidate_id"]]["nonliteral_customer_quotes"]
        if quote_diagnostics:
            lines += ["", "非逐字引用：", "", *[f"- `{error['json_pointer']}`：『{error['quote']}』" for error in quote_diagnostics]]
        lines += ["", "### 新审核原结论", "", "维度判断：" + "；".join(f"{key}={value}" for key, value in raw_audit["checks"].items()) + "。", "",
            *[f"- {key}：{value}" for key, value in raw_audit["reasons"].items()], "", "issues：", ""]
        lines += [f"- {value}" for value in raw_audit["issues"]] or ["空。"]
        lines += ["", "### 改善与尚余争议", "", *[f"- 改善：{value}" for value in note["improvements"]], ""]
        for dispute in note["remaining_disputes"]:
            lines += [f"- {dispute['issue']}。依据：{dispute['evidence']} 判读：{dispute['assessment']}"]
        lines += ["", "Codex建议：" + note["assistant_recommended_disposition"] + "。此建议不改变原始或本次模型运行状态。", ""]
        for name, label in (("extraction-call.json", "新提取原响应和输入"), ("audit-call.json", "新审核原响应和输入"), ("result.json", "单条运行留痕")):
            path = (Path(directory) / row["candidate_id"] / name).resolve().as_posix()
            lines.append(f"- [{label}]({path})")
    lines += ["", "## 验证范围", "",
        "原始候选包、原始草案对照包和正式题集的文件哈希均与重跑前一致，正式题集仍为2899条。新旧原话及调用输入边界已核对；本次仅评估样本协议和提取审核表现，没有执行Qwen推荐，没有给推荐打分，没有完成人工质量标注或评分校准。", "",
        "完整旧提取、旧审核、草案、新提取和新审核均保留在reextraction-results.json；comparison.json另存分析笔记和程序诊断。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True)
    parser.add_argument("--notes", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    comparison = validate_and_compare(read(args.results), read(args.notes))
    comparison["source_result_file_sha256"] = hashlib.sha256(Path(args.results).read_bytes()).hexdigest()
    comparison["notes_file_sha256"] = hashlib.sha256(Path(args.notes).read_bytes()).hexdigest()
    destination = Path(args.out_dir)
    destination.mkdir(parents=True, exist_ok=False)
    with (destination / "comparison.json").open("x", encoding="utf-8") as stream:
        json.dump(comparison, stream, ensure_ascii=False, indent=2, allow_nan=False)
    with (destination / "comparison.md").open("x", encoding="utf-8") as stream:
        stream.write(render(comparison, Path(args.results).parent))
    print(json.dumps(comparison["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
