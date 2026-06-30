from __future__ import annotations

from typing import Any

from rs_lab.experiments.recall.pool500.fallback_completion.config import Pool500FallbackCompletionConfig
from rs_lab.experiments.recall.pool500.governance.fallback_completion_contract import (
    build_fallback_completion_audit,
    validate_fallback_completion_contract,
)


def build_completion_audit_bundle(
    audit_inputs: list[dict[str, Any]],
    config: Pool500FallbackCompletionConfig,
) -> tuple[dict[str, Any], dict[str, Any]]:
    audit = build_fallback_completion_audit(audit_inputs, config.contract)
    validation = validate_fallback_completion_contract(audit, config.contract)
    return audit, validation
