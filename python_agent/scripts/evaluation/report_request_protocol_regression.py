"""七条 v2/v3 回归与离线校验回放；不改模型响应或运行状态，不调用模型。"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "python_agent"))
from rs_core.offline.evaluation.skill_benchmark.request_contract import validate_request
from rs_core.offline.evaluation.skill_benchmark.request_contract_v3 import (
    VALIDATOR_REVISION, evidence_report, normalize_request, contract_description)
from rs_core.offline.evaluation.skill_benchmark.dataset import fingerprint


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def compare(previous, current, notes):
    old = {row["candidate_id"]: row for row in previous["entries"]}
    annotations = {row["candidate_id"]: row for row in notes["entries"]}
    if (len(old) != 7 or len(current["entries"]) != 7 or len(annotations) != 7
            or set(old) != set(annotations) or set(old) != {row["candidate_id"] for row in current["entries"]}
            or any(value.get("is_gold") is not False for value in (previous, current, notes))):
        raise ValueError("只能对照原有七条非gold")
    if previous["source_pack_sha256"] != current["source_pack_sha256"]:
        raise ValueError("原始包不一致")
    for run in (previous, current):
        if not all(sha(path) == expected for path, expected in run["input_file_sha256"].items()):
            raise ValueError("运行输入哈希变化")
    entries, calls = [], []
    for row in current["entries"]:
        identifier, message = row["candidate_id"], row["customer_message"]
        former, view, note = old[identifier], row["original_and_draft_review"], annotations[identifier]
        if message != former["customer_message"] or message != view["customer_message"]:
            raise ValueError("原话变化")
        for claim in note["disputes"]:
            if claim["customer_quote"] not in message:
                raise ValueError("分析笔记伪引用")
        extraction_call, audit_call = row["extraction_call"], row["audit_call"]
        if extraction_call["request_payload"] != {"customer_message": message}:
            raise ValueError("提取不是盲提取")
        raw = extraction_call["parsed_json"]
        if not isinstance(raw, dict) or raw.get("schema_version") != "rs-shopping-request/3":
            raise ValueError("当前回归不是v3原响应")
        payload = audit_call["request_payload"]
        if (set(payload) != {"customer_message", "extraction", "catalog", "profile", "price_unit"}
                or payload["customer_message"] != message or payload["extraction"] != raw):
            raise ValueError("审核输入越界或原提取被改写")
        if any(payload[key] != former["audit_call"]["request_payload"][key]
               for key in ("catalog", "profile", "price_unit")):
            raise ValueError("回归商品或画像上下文变化")
        if row["model_audit"] != audit_call["parsed_json"]:
            raise ValueError("审核原判断被改写")
        calls.extend([extraction_call, audit_call])
        replay = {"validator_revision": VALIDATOR_REVISION, "new_model_calls": 0,
                  "original_status_preserved": row["status"], "automatic_promotion": False}
        try:
            checked = validate_request(raw, message)
            replay.update(protocol_valid=True, normalized_extraction=checked)
        except ValueError as error:
            replay.update(protocol_valid=False, error=str(error))
        normalized, changes = normalize_request(raw)
        evidence = evidence_report(raw, message)
        if evidence != row["evidence_validation"] or changes != row["normalization"]["changes"]:
            raise ValueError("证据或规范化留痕变化")
        entries.append({"candidate_id": identifier, "customer_message": message,
            "original_and_revised_draft": view, "previous_v2_run": former,
            "current_frozen_run": row, "offline_validation_replay": replay,
            "evidence_validation": evidence, "normalization_changes": changes,
            "assistant_analysis_not_human_gold": note})
    if len(calls) != 14 or current["summary"]["model_calls"] != 14:
        raise ValueError("模型调用预算不一致")
    if any(call["response_metadata"].get("model") != "gpt-6-luna"
           or call["response_metadata"].get("finish_reason") != "stop" for call in calls):
        raise ValueError("模型身份或结束状态异常")
    summary = {"requests": 7, "added_requests": 0, "actual_model_calls": 14, "automatic_retries": 0,
        "previous_v2_extraction_valid": previous["summary"]["extraction_protocol_valid"],
        "frozen_v3_extraction_valid": current["summary"]["extraction_protocol_valid"],
        "offline_replay_extraction_valid": sum(row["offline_validation_replay"]["protocol_valid"] for row in entries),
        "all_verbatim_quote_checks_valid": sum(row["evidence_validation"]["all_quotes_valid"] for row in entries),
        "audit_protocol_valid": current["summary"]["audit_protocol_valid"],
        "audit_all_pass_and_no_issues": current["summary"]["new_model_all_pass"],
        "frozen_run_pending_human_review": current["summary"]["pending_human_review"],
        "frozen_run_quarantined": current["summary"]["quarantined"],
        "offline_gate_eligible_not_approved": sum(row["offline_validation_replay"]["protocol_valid"]
            and row["current_frozen_run"].get("model_audit_all_pass", False) for row in entries),
        "total_tokens_reported_by_service": sum(call["response_metadata"]["usage"]["total_tokens"] for call in calls),
        "profile_clusters": len({row["current_frozen_run"]["statistical_cluster_id"] for row in entries}),
        "formal_task_count": current["formal_task_count"], "formal_imports": 0, "human_approvals": 0,
        "qwen_recommendation_run": False, "score_calibration_completed": False,
        "original_statuses_changed": False, "model_responses_or_run_statuses_rewritten": False}
    return {"schema_version": "rs-request-v3-hardening-regression/1", "summary": summary,
        "contract": contract_description(), "assistant_conclusion": notes["conclusion"],
        "same_model_fresh_contexts_not_independent_gold": True,
        "initial_v3_validator_sha256": "7db3abb6b54f4b6afd5232c973dbf361a295bc05e206b37fd1f9cdbde6249c1a",
        "current_v3_validator_sha256": sha(ROOT / "python_agent/rs_core/offline/evaluation/skill_benchmark/request_contract_v3.py"),
        "entries": entries, "human_reviewed": False, "is_gold": False, "auto_deploy": False}


def requirements(value):
    if value is None:
        return "原提取失败且响应未保存，不按空需求处理"
    rows = value.get("requirements", value.get("hard_constraints", []))
    return "；".join(f"{row.get('kind', 'legacy-hard')} / {row['field']} / {row.get('relation', row.get('op'))} / "
        f"{row['value']} {row.get('unit') or ''}" for row in rows) or "没有结构化商品条件（回答目标另列）"


def strategy(value):
    if value is None:
        return "缺失"
    if "intent" not in value:
        return f"旧格式 needs_clarification={value['needs_clarification']}"
    return (f"{value['intent']['actions']}；{value['clarification']['mode']}；"
            f"暂缓={value['clarification']['unresolved_actions']}；画像={value['recipient']['profile_policy']}")


def render(report):
    summary = report["summary"]
    lines = ["# 七条购物请求：v3协议完善及6-luna回归", "", report["assistant_conclusion"], "",
        "只重跑原有7条原话，实际调用gpt-6-luna 14次（每条提取、审核各一次），无生成、无重试、无扩量、无正式导入或上线。",
        "提取只看到原话；审核看到原始新提取及原有商品/画像上下文，不收到旧结果、草案或程序错误。相同模型的新上下文不等于独立模型或人工gold。", "",
        "## 本轮补齐的规则", "",
        "- 字段注册和透明别名转换；长度精确统一为米，近似仍是about；币种不明保持null，不推定预算命中。",
        "- 汇总所有逐字引用错误并给程序计算的证据位置；不拼接或修复模型引用。",
        "- 回答目标分类、条件式决策支持；必要信息只暂缓依赖它的当前动作，通用比较和方法先答。",
        "- 画像适用理由独立于self；送礼不迁移赠送者偏好，纯技术咨询不强制用历史。",
        "- 草案补回取舍目标、撤掉耳机严格数量1、修正接口信息的动作绑定。旧草案不覆盖。", "",
        "## 实测结果与校验修复", "",
        f"逐字引用校验{summary['all_verbatim_quote_checks_valid']}/7，审核协议校验{summary['audit_protocol_valid']}/7。",
        f"运行时提取结构校验{summary['frozen_v3_extraction_valid']}/7；局部澄清校验修复后，仅对原响应作离线回放，结构校验{summary['offline_replay_extraction_valid']}/7。没有追加模型调用，也没有改写首次运行状态。",
        "初次程序沿用了v2的全局阻塞假设，误拒了网线接头样本：模型已暂缓兼容判断并设置必要追问，只是把必要等级写成required_for_requested_answer。v3现在按needed_for确定作用范围，必要信息可以只阻塞兼容动作；原输出标签保留，不改成另一等级。",
        f"模型审核四维全pass且issues为空为{summary['audit_all_pass_and_no_issues']}/7。冻结运行保留{summary['frozen_run_pending_human_review']}条待人审、{summary['frozen_run_quarantined']}条隔离；离线新校验满足预览门槛的{summary['offline_gate_eligible_not_approved']}条也没有自动批准或修改运行状态。",
        f"服务返回模型全部为gpt-6-luna，均正常stop；报告token共{summary['total_tokens_reported_by_service']}。7条涉及{summary['profile_clusters']}个画像簇，不是总体语义准确率评测。", "",
        "| 场景 | 真实回归观察 | 尚余问题 |", "| --- | --- | --- |"]
    for row in report["entries"]:
        note = row["assistant_analysis_not_human_gold"]
        lines.append(f"| {row['candidate_id']} | {note['observed']} | {note['disputes'][0]['issue']} |")
    lines += ["", "## 为什么不能把模型审核当标准答案", "",
        "Windows 11样本的审核把“必须兼容Windows 11”误读成“不能兼容其他系统”。这不是同一个条件：商品支持Windows 10和11并不违反Windows 11需求。操作系统字段的语义仍需明确成兼容支持，而不是产品只能等于一个系统。",
        "第二条的审核称引文末尾分号不存在，但程序定位证明它确实是原话中的连续子串。这是审核误判，不是提取伪引用。该样本的self推断和接口等级仍有独立争议，不能因一个审核理由错误就自动批准整条。",
        "用途强度也存在分歧：咨询背景不应变成硬过滤，但听音乐/接电话可以构成功能需求，不应一律因为没说“必须”就降为可选。当前只有strict/approximate/preference，尚需独立人审确定用途适合做适用性门槛还是偏好；不能以模型全pass替代校准。",
        "以上判断是Codex基于原话和程序证据的分析，不是独立质量标注。首次拒绝结果完整保留，未据分析自动放行。", ""]
    for index, row in enumerate(report["entries"], 1):
        view, current, previous, note = (row["original_and_revised_draft"], row["current_frozen_run"],
            row["previous_v2_run"], row["assistant_analysis_not_human_gold"])
        draft = view["revision_proposal"]
        raw = current["extraction_call"]["parsed_json"]
        normalized = current["normalization"]["normalized_candidate"]
        former = previous["extraction_call"]["parsed_json"]
        lines += [f"## {index} {view['title']}", "", "> " + row["customer_message"], "",
            "| 版本 | 条件 |", "| --- | --- |",
            f"| 最初提取 | {requirements(view['original_validated_extraction'])} |",
            f"| 上一轮6-luna v2 | {requirements(former)} |",
            f"| 修订草案v3 待人审 | {requirements(draft)} |",
            f"| 本轮6-luna 原始v3 | {requirements(raw)} |",
            f"| 程序规范化副本 | {requirements(normalized)} |", "",
            "| 版本 | 动作、澄清与画像 |", "| --- | --- |",
            f"| 上一轮6-luna | {strategy(former)} |", f"| 修订草案 | {strategy(draft)} |",
            f"| 本轮6-luna | {strategy(raw)} |", "", "本轮回答目标：", ""]
        lines += [f"- {need['kind']}：{need['need']}；原话：『{need['quote']}』" for need in raw["answer_requirements"]]
        lines += ["", "本轮追问：", ""]
        lines += [f"- {question['question']}（{question['necessity']}；槽位{question['slots']}）" for question in raw["clarification"]["questions"]] or ["没有追问；不要求为了填槽位盘问顾客。"]
        lines += ["", "本轮画像适用理由：" + raw["recipient"]["profile_reason"], "", "原模型审核：", ""]
        audit = current["model_audit"]
        lines += [f"- {dimension}={audit['checks'][dimension]}：{reason}" for dimension, reason in audit["reasons"].items()]
        lines += ["", "原模型issues：", ""]
        lines += ["- " + issue for issue in audit["issues"]] or ["空。"]
        if current.get("extraction_protocol_error"):
            lines += ["", "冻结运行校验错误：" + current["extraction_protocol_error"]]
        lines += ["", "离线回放：" + ("结构通过" if row["offline_validation_replay"]["protocol_valid"] else "结构未通过") + "；保留原始运行状态，不自动放行。", "",
                  "Codex对照判断（不是人审）：", "", "- " + note["observed"]]
        lines += [f"- {claim['issue']}。顾客依据：『{claim['customer_quote']}』。判读：{claim['assessment']}" for claim in note["disputes"]]
        if row["normalization_changes"]:
            lines += ["", "透明规范化：", "", *[f"- {change['path']}：{change['before']} → {change['after']}。" for change in row["normalization_changes"]]]
        lines += [""]
    lines += ["## 边界与下一步", "",
        "正式评测集仍为2899条，未改旧包状态、旧草案、旧审核和模型响应。协议与校验修复不代表推荐评分已校准：本轮没有执行Qwen推荐、没有满意度标签，也没有人工质量批准。",
        "下一步应先人工裁决用途/兼容强度、购买对象和审核误报，再补语义审核校准；不要扩量或把这七条自动升级gold。完整原提取、v2重跑、v3草案、真实响应、规范化与回放在regression.json中保留。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--notes", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    paths = [Path(args.previous), Path(args.current), Path(args.notes)]
    before = {str(path.resolve()): sha(path) for path in paths}
    report = compare(*[read(path) for path in paths])
    if before != {str(path.resolve()): sha(path) for path in paths}:
        raise ValueError("源文件变化")
    report["input_file_sha256"] = before
    destination = Path(args.out_dir)
    destination.mkdir(parents=True, exist_ok=False)
    write(destination / "regression.json", report)
    with (destination / "regression.md").open("x", encoding="utf-8") as stream:
        stream.write(render(report))
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
