"""用途事实补录：独立规格/测量证据经人工核实后冻结，不从商品标题制造体验真值。"""

import copy
from datetime import datetime
from urllib.parse import urlsplit

from .dataset import fingerprint, validate_benchmark

FACT_TYPES = {
    "weight_g": "number", "battery_hours": "number", "ink_drying_seconds": "number",
    "active_noise_cancellation": "boolean", "connector_spec": "text",
    "water_resistance_rating": "text", "ink_type": "text", "paper_bleed_test": "text",
    "pack_contents": "text", "compatibility_statement": "text",
}


def evidence_pack(benchmark):
    validate_benchmark(benchmark)
    return {"schema_version": "rs-independent-use-evidence/1", "benchmark_sha256": fingerprint(benchmark),
            "records": [], "allowed_facts": FACT_TYPES,
            "instructions": "每条记录填写item_id、field、value、source_kind(manufacturer_specification或independent_measurement)、"
            "source_url、quote、observed_at(带时区ISO日期)、approved=true、两名不同human审核人(reviews含reviewer_id、origin、reason)。"
            "规格声明不等于实测体验；无法证实的事实保持未知。source_url须是实际核实的独立来源，不接受推荐模型自报。",
            "status": "pending_source_collection_and_independent_review", "auto_deploy": False}


def apply_use_evidence(benchmark, pack):
    validate_benchmark(benchmark)
    if (not benchmark["manifest"].get("quality_contract_version")
            or pack.get("schema_version") != "rs-independent-use-evidence/1"
            or pack.get("benchmark_sha256") != fingerprint(benchmark)):
        raise ValueError("用途证据必须属于当前冻结质量题集")
    result, seen = copy.deepcopy(benchmark), set()
    items = {item["item_id"]: item for item in result["catalog"]}
    for record in pack.get("records", []):
        if record.get("approved") is not True:
            continue
        key = record.get("item_id"), record.get("field")
        if key in seen or key[0] not in items or key[1] not in FACT_TYPES:
            raise ValueError("证据商品/属性缺失或重复，不接受质量分冒充商品事实")
        seen.add(key)
        value, kind = record.get("value"), FACT_TYPES[key[1]]
        import math

        if (kind == "number" and (type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 100000)
                or kind == "boolean" and type(value) is not bool
                or kind == "text" and (not isinstance(value, str) or not 1 <= len(value) <= 2000)):
            raise ValueError("独立用途属性的值无效")
        url = urlsplit(record.get("source_url", ""))
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or record.get("source_kind") not in {"manufacturer_specification", "independent_measurement"}
                or not isinstance(record.get("quote"), str) or not 1 <= len(record["quote"]) <= 2000):
            raise ValueError("用途事实需要独立HTTPS来源、证据原话与来源类型")
        try:
            observed = datetime.fromisoformat(record.get("observed_at", "").replace("Z", "+00:00"))
        except (TypeError, ValueError) as error:
            raise ValueError("证据需要带时区的核实时间") from error
        if observed.tzinfo is None:
            raise ValueError("证据核实时间缺少时区")
        reviews = record.get("reviews", [])
        if (not isinstance(reviews, list) or len(reviews) != 2
                or any(row.get("origin") != "human" or not isinstance(row.get("reviewer_id"), str)
                       or not row["reviewer_id"].strip() or not isinstance(row.get("reason"), str)
                       or not row["reason"].strip() for row in reviews)
                or len({row["reviewer_id"] for row in reviews}) != 2):
            raise ValueError("用途事实须经两名独立审核人核实，不能自动信任来源引用")
        items[key[0]].setdefault("verified_use_facts", {})[key[1]] = {
            "value": value, "source_kind": record["source_kind"], "source_url": record["source_url"],
            "quote": record["quote"], "observed_at": record["observed_at"],
            "reviewer_ids": [row["reviewer_id"] for row in reviews],
            "verification_basis": "human_reviewed_source; program_validates_provenance_shape_not_source_truth",
        }
    if not seen:
        raise ValueError("没有获准的独立用途证据，不能伪造补齐结果")
    for task in result["tasks"]:
        task["review_status"] = "pending"
        for turn in task["turns"]:
            turn["gold"].pop("quality_judgments", None)
            turn["gold"].pop("relevance_judgments", None)
    result["manifest"].update(catalog_sha256=fingerprint(result["catalog"]),
        parent_benchmark_sha256=fingerprint(benchmark), use_evidence_sha256=fingerprint(pack),
        human_reviewed=False, quality_label_status="pending_independent_human_labels",
        independent_relevance_status="pending_human_labels",
        scoring_calibration={"passed": False, "status": "facts_changed_relabel_and_recalibrate"})
    validate_benchmark(result)
    return result
