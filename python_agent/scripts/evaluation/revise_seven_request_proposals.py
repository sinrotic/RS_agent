"""显式修订既有七条 Codex 草案；不是自然语言解析器，不调用模型或导入题集。"""

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "python_agent"))
from rs_core.offline.evaluation.skill_benchmark.request_contract import validate_request
from rs_core.offline.evaluation.skill_benchmark.request_contract_v3 import contract_description, evidence_report
from rs_core.offline.evaluation.skill_benchmark.dataset import fingerprint


KINDS = {"synth-000-00": ["recommendation"], "synth-000-01": ["explanation"],
         "synth-001-01": ["recommendation"], "synth-002-00": ["verification_steps"],
         "synth-002-01": ["comparison", "comparison", "verification_steps"],
         "synth-003-00": ["comparison", "verification_steps"],
         "synth-003-01": ["comparison", "verification_steps"]}


def revise(source, proposals):
    if proposals.get("source_pack_sha256") != fingerprint(source) or proposals.get("is_gold") is not False:
        raise ValueError("草案必须对应未批准原始包")
    result = copy.deepcopy(proposals)
    messages = {row["candidate_id"]: row["customer_message"] for row in source["entries"] if row.get("customer_message")}
    if set(messages) != set(KINDS) or {row["candidate_id"] for row in result["entries"]} != set(KINDS) or len(result["entries"]) != 7:
        raise ValueError("只能修订既有七条")
    for row in result["entries"]:
        identifier, draft = row["candidate_id"], row["revision_proposal"]
        if len(draft["answer_requirements"]) != len(KINDS[identifier]):
            raise ValueError("旧草案结构变化，不能套用本次人工修订")
        draft["schema_version"] = "rs-shopping-request/3"
        for need, kind in zip(draft["answer_requirements"], KINDS[identifier]):
            need["kind"] = kind
        policy = draft["recipient"]["profile_policy"]
        draft["recipient"]["profile_reason"] = {
            "weak_reference_if_self": "只有购买对象确为本人、画像授权且与当前购物相关时才可弱参考；本轮提取看不到历史，不能确认相关性，当前需求优先。",
            "not_relevant": "本轮为技术比较或核查方法；购物评价不证明现有设备与安装条件，无须使用历史。",
            "do_not_transfer_to_recipient": "这是送给朋友的耳机，赠送者历史不代表朋友偏好，不迁移本人画像。"}[policy]
        notes = ["升级v3，回答目标分类与画像适用理由显式保留；原话、旧草案和旧结果不覆盖。"]
        if identifier == "synth-000-01":
            draft["answer_requirements"] += [
                {"kind": "recommendation", "need": "给安装便利、日常可靠优先的适配器选择方向，不提前保证具体兼容。", "quote": "能帮我看看哪种更合适吗？"},
                {"kind": "decision_support", "need": "解释为何便利和可靠性优先于最高速度，以及怎样按这些条件选择。", "quote": "比起追求特别高的速度，我更在意安装别太折腾、日常用着可靠"}]
            for unknown in draft["unknowns"]:
                unknown["needed_for"] = ["verify_compatibility"]
            notes.append("接口/系统版本未知绑定未来具体兼容核查，不把本轮方向性推荐变成拒答门槛。")
        elif identifier == "synth-001-01":
            draft["requirements"] = [need for need in draft["requirements"] if need["field"] != "purchase_quantity"]
            draft["requirements"].append({"id": "uses", "kind": "preference", "field": "use_case", "relation": "prefer",
                "value": "通勤", "unit": None, "quote": "她平时通勤时想少受周围噪声影响"})
            draft["answer_requirements"].append({"kind": "explanation", "need": "解释耳机续航与降噪的选购指标。", "quote": "续航和降噪效果我不太会看"})
            row["disputes"][0]["certainty"] = "interpretation_pending_human_review"
            row["disputes"][0]["suggestion"] = "一副可能只是自然单数，暂不设严格购买数量；尤其不能推定只展示一个推荐，待独立人审。"
            notes.append("撤掉草案中的严格购买数量1，保留原始解释争议；补通勤用途及指标解释目标，逐字引用不拼接。")
        elif identifier == "synth-002-01":
            draft["answer_requirements"].append({"kind": "decision_support", "need": "给换风扇与加装水冷的条件式取舍建议，不虚构设备事实或唯一方案。", "quote": "不太确定哪种改动更合适"})
            notes.append("补回旧草案也遗漏的决策支持，不只罗列比较维度。")
        elif identifier == "synth-003-00":
            draft["answer_requirements"].append({"kind": "compatibility_verdict", "need": "具体转接头能否连接两根现有线暂不能确认，明确待取得接头身份与两端接口后再核查。", "quote": "那个转接头能用吗？"})
            notes.append("兼容结论是当前请求；保留局部暂缓与必要追问，通用走线比较先答。50ft精确换算15.24m，但仍about。")
        elif identifier == "synth-003-01":
            draft["answer_requirements"].append({"kind": "decision_support", "need": "说明成品线、散装线和现有线延长各自适用条件，不强制选唯一商品。", "quote": "不太确定要买成品线还是散装线自己处理"})
            notes.append("补方案选择目标；长度规范到m不改近似强度，未来现场适配信息不阻塞当前核查清单。")
        row["revision_changes"] = notes
        row["draft_before_normalization"] = copy.deepcopy(draft)
        row["revision_proposal"] = validate_request(draft, messages[identifier])
        row["evidence_validation"] = evidence_report(draft, messages[identifier])
    result.update(author="codex_assistant_offline_v3_revision_not_model_extraction", contract=contract_description(),
                  source_v2_proposals_sha256=fingerprint(proposals), new_model_calls=0, added_requests=0,
                  human_reviewed=False, auto_deploy=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--proposals", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    paths = [Path(args.source), Path(args.proposals)]
    before = {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    source, proposals = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    revised = revise(source, proposals)
    after = {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    if before != after:
        raise ValueError("原始输入变化")
    revised["input_file_sha256"] = before
    destination = Path(args.out_dir)
    destination.mkdir(parents=True, exist_ok=False)
    with (destination / "revision-proposals.json").open("x", encoding="utf-8") as stream:
        json.dump(revised, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"revised_existing_drafts": 7, "added_requests": 0, "new_model_calls": 0, "inputs_unchanged": True}))


if __name__ == "__main__":
    main()
