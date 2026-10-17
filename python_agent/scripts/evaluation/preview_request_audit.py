"""补看候选包中丢失的审核输出，仅诊断，不改变原隔离结论或正式题集。"""

import argparse
import copy
import json
from pathlib import Path

from skill_evolution import configured_model, read, write
from rs_core.offline.evaluation.skill_benchmark.dataset import fingerprint
from rs_core.offline.evaluation.skill_benchmark.request_synthesis import AUDIT, VERSION, validate_audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--max-calls", type=int, default=3)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    if not 1 <= args.max_calls <= 8:
        raise ValueError("诊断调用必须限制为1–8次")
    pack = read(args.source)
    if (pack.get("schema_version") != VERSION or pack.get("is_gold") is not False
            or pack.get("contains_test_users") is not False):
        raise ValueError("只允许非测试、非gold的合成候选包")
    selected = [row for row in pack["entries"] if row.get("failed_stage") == "audit"
                and row.get("extraction") and not row.get("raw_model_audit")][:args.max_calls]
    model = configured_model("RS_REQUEST_VERIFY")
    if model is None:
        raise ValueError("审核模型未配置")
    Path(args.out_dir).mkdir(parents=True, exist_ok=False)
    rows = []
    for original in selected:
        row = {"candidate_id": original["candidate_id"], "original_status": original["status"],
               "original_failed_stage": original["failed_stage"], "is_gold": False}
        try:
            raw = model(AUDIT, {"customer_message": original["customer_message"],
                "extraction": copy.deepcopy(original["extraction"]), **copy.deepcopy(original["context"])})
            row["raw_model_audit"] = raw
            try:
                row["validated_model_audit"] = validate_audit(raw, original["customer_message"], original["context"])
                row["protocol_valid"] = True
            except ValueError as error:
                row.update(protocol_valid=False, protocol_error=str(error))
        except Exception as error:
            row.update(protocol_valid=False, error_type=type(error).__name__)
        rows.append(row)
        write(Path(args.out_dir) / (row["candidate_id"] + ".json"), row)
    result = {"schema_version": "rs-preview-audit-diagnostics/1", "source_pack_sha256": fingerprint(pack),
              "model": model.model, "model_identity": model.identity, "additional_model_calls": len(rows),
              "max_calls": args.max_calls, "is_gold": False, "auto_deploy": False, "entries": rows,
              "interpretation": "新调用的审核诊断，不是恢复旧响应；原候选的隔离状态不变，不作独立金标准"}
    write(Path(args.out_dir) / "diagnostic-audits.json", result)
    print(json.dumps({"additional_model_calls": len(rows), "protocol_valid": sum(row["protocol_valid"] for row in rows),
                      "is_gold": False, "auto_deploy": False}))


if __name__ == "__main__":
    main()
