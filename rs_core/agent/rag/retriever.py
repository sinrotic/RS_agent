from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Protocol

from rs_core.agent.rag.corpus import RAG_EVIDENCE_FIELD_QUOTAS, RAG_PARENT_PROFILE_FIELD, build_parent_profile_text
from rs_core.agent.rag.schema import RagContext, RagEvidence

_FORBIDDEN_PROVENANCE_TOKENS = {
    "diagnostic",
    "eval",
    "future",
    "ground",
    "holdout",
    "label",
    "oracle",
    "target",
    "test",
    "truth",
}
_PROVENANCE_METADATA_KEYS = {"artifact_scope", "provenance", "source_path"}
_TOKEN_RE = re.compile(r"[a-z0-9]+")


class EvidencePolicyViolation(ValueError):
    pass


class CandidateEvidenceRetriever(Protocol):
    def retrieve(
        self,
        query: str,
        candidate_item_ids: Iterable[str],
        max_evidence_per_item: int = 3,
    ) -> list[RagEvidence]: ...


class QueryPlanningEvidenceRetriever(Protocol):
    def retrieve(
        self,
        query: str,
        max_evidence_total: int = 12,
        max_evidence_per_item: int = 3,
    ) -> list[RagEvidence]: ...


@dataclass
class RagPolicy:
    mode: str = "off"
    max_evidence_per_item: int = 3
    max_evidence_total: int = 12
    max_text_chars: int = 180
    strict: bool = False
    allowed_fields: list[str] | None = None

    @property
    def enabled(self) -> bool:
        return self.mode in {"shadow", "explain"}


@dataclass
class InMemoryCandidateCardRetriever:
    item_cards: dict[str, dict[str, Any]]
    fields: list[str] = field(default_factory=lambda: ["title", "category_path", "description", "features"])
    source: str = "candidate_card"

    def retrieve(
        self,
        query: str,
        candidate_item_ids: Iterable[str],
        max_evidence_per_item: int = 3,
    ) -> list[RagEvidence]:
        query_tokens = set(_tokens(query))
        evidence: list[RagEvidence] = []
        for item_id in candidate_item_ids:
            card = self.item_cards.get(str(item_id), {})
            item_evidence: list[RagEvidence] = []
            for field_name in self.fields:
                value = card.get(field_name)
                if value is None and field_name == "category_path":
                    value = card.get("category")
                if value is None:
                    continue
                if isinstance(value, list):
                    text = " ".join(str(item).strip() for item in value if str(item).strip())
                else:
                    text = str(value).strip()
                if not text:
                    continue
                text_tokens = set(_tokens(text))
                score = float(len(query_tokens & text_tokens)) if query_tokens else 0.0
                item_evidence.append(
                    RagEvidence(
                        item_id=str(item_id),
                        field=field_name,
                        text=text,
                        source=self.source,
                        score=score,
                        metadata={"artifact_scope": "candidate_internal", "retriever": "in_memory_candidate_card"},
                    )
                )
            item_evidence.sort(key=lambda row: (-(row.score or 0.0), row.field))
            evidence.extend(item_evidence[:max_evidence_per_item])
        return evidence


@dataclass
class Small2BigCandidateEvidenceRetriever:
    base_retriever: CandidateEvidenceRetriever
    parent_records: dict[str, dict[str, Any]]
    parent_fields: list[str] | None = None
    parent_profile_max_chars: int = 1000
    max_parent_profiles_total: int = 6
    max_parent_profiles_per_item: int = 1
    min_base_evidence_total: int = 1
    base_max_evidence_per_item: int | None = None
    manifest: dict[str, Any] | None = None
    source: str = "small2big_parent_profile"

    def retrieve(
        self,
        query: str,
        candidate_item_ids: Iterable[str],
        max_evidence_per_item: int = 3,
    ) -> list[RagEvidence]:
        candidate_ids = [str(item_id) for item_id in candidate_item_ids]
        candidate_id_set = set(candidate_ids)
        base_limit = self.base_max_evidence_per_item or max_evidence_per_item
        base_evidence = [row for row in self.base_retriever.retrieve(query, candidate_ids, base_limit) if str(row.item_id) in candidate_id_set]
        if not base_evidence:
            return []

        gate = validate_parent_profile_manifest(self.manifest)
        if not gate["passed"]:
            _annotate_small2big_gate(base_evidence, gate)
            return base_evidence

        hit_ids = _ordered_unique(str(row.item_id) for row in base_evidence if str(row.item_id) in candidate_id_set)
        parent_budget = max(0, int(self.max_parent_profiles_total))
        if len(base_evidence) < max(0, int(self.min_base_evidence_total)):
            parent_budget = 0
        parent_evidence: list[RagEvidence] = []
        per_item_limit = max(0, int(self.max_parent_profiles_per_item))
        counts: dict[str, int] = {}
        for item_id in hit_ids:
            if len(parent_evidence) >= parent_budget:
                break
            if counts.get(item_id, 0) >= per_item_limit:
                continue
            parent = self.parent_records.get(item_id)
            if not parent:
                continue
            text, used_fields = build_parent_profile_text(
                parent,
                fields=self.parent_fields,
                max_chars=self.parent_profile_max_chars,
            )
            if not text:
                continue
            child_rows = [row for row in base_evidence if str(row.item_id) == item_id]
            parent_evidence.append(
                RagEvidence(
                    item_id=item_id,
                    field=RAG_PARENT_PROFILE_FIELD,
                    text=text,
                    source=self.source,
                    score=max((row.score or 0.0) for row in child_rows),
                    metadata={
                        "artifact_scope": "candidate_internal",
                        "retriever": "small2big_parent_profile",
                        "small2big_enabled": True,
                        "small2big_parent_profile": True,
                        "candidate_scoped": True,
                        "candidate_generation_allowed": False,
                        "ranking_input_replacement_allowed": False,
                        "promotion_allowed": False,
                        "direct_recommendation_input_allowed": False,
                        "requires_parent_context_agent": True,
                        "source_item_id": item_id,
                        "parent_projection_fields": used_fields,
                        "child_hit_count": len(child_rows),
                        "child_hit_fields": _ordered_unique(row.field for row in child_rows),
                        "child_retrievers": _ordered_unique(str(row.metadata.get("retriever") or row.source) for row in child_rows),
                        "child_max_score": max((row.score or 0.0) for row in child_rows),
                        "manifest_gate_passed": True,
                    },
                )
            )
            counts[item_id] = counts.get(item_id, 0) + 1

        diagnostics = {
            "enabled": True,
            "applied": bool(parent_evidence),
            "manifest_gate_passed": True,
            "base_hit_count": len(hit_ids),
            "lookup_attempted_count": len(hit_ids),
            "lookup_hit_count": len(parent_evidence),
            "lookup_missing_count": max(0, len(hit_ids) - len(parent_evidence)),
            "profile_added_count": len(parent_evidence),
            "profile_dropped_budget_count": max(0, min(len(hit_ids), parent_budget) - len(parent_evidence)),
            "max_parent_profiles_total": parent_budget,
            "max_parent_profiles_per_item": per_item_limit,
            "candidate_scoped": True,
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "promotion_allowed": False,
        }
        _annotate_small2big_gate(base_evidence + parent_evidence, diagnostics)
        return base_evidence + parent_evidence


def validate_parent_profile_manifest(manifest: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        return {"passed": False, "failure_reason": "missing_manifest"}
    required = {
        "train_only": True,
        "no_holdout": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "raw_profile_public_projection": True,
    }
    for key, expected in required.items():
        if manifest.get(key) is not expected:
            return {"passed": False, "failure_reason": f"invalid_{key}"}
    if not (manifest.get("source_hash") or manifest.get("source_manifest_hash") or manifest.get("source_manifest_path")):
        return {"passed": False, "failure_reason": "missing_source_hash"}
    for key in ("source_path", "source_manifest_path", "parent_store_path", "provenance"):
        value = manifest.get(key)
        if value is not None and _forbidden_manifest_tokens(str(value)):
            return {"passed": False, "failure_reason": f"forbidden_{key}"}
    if not manifest.get("schema_version"):
        return {"passed": False, "failure_reason": "missing_schema_version"}
    return {"passed": True, "failure_reason": None}


def _annotate_small2big_gate(evidence: list[RagEvidence], diagnostics: dict[str, Any]) -> None:
    for row in evidence:
        row.metadata.setdefault("small2big", diagnostics)


def _forbidden_manifest_tokens(value: str) -> list[str]:
    return [token for token in _tokens(value) if token in _FORBIDDEN_PROVENANCE_TOKENS]


def _ordered_unique(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    rows: list[str] = []
    for value in values:
        text = str(value)
        if text and text not in seen:
            seen.add(text)
            rows.append(text)
    return rows


def build_rag_context_for_ranked_candidates(
    query: str,
    candidate_item_ids: list[str],
    evidence: Iterable[RagEvidence] | None = None,
    retriever: CandidateEvidenceRetriever | None = None,
    policy: RagPolicy | None = None,
    metadata: dict[str, Any] | None = None,
) -> RagContext:
    active_policy = policy or RagPolicy()
    context_metadata = dict(metadata or {})
    if not active_policy.enabled:
        context_metadata["rag_policy"] = {"mode": active_policy.mode, "enabled": False}
        return RagContext(query=query, candidate_item_ids=list(candidate_item_ids), evidence=[], metadata=context_metadata)

    candidate_ids = [str(item_id) for item_id in candidate_item_ids]
    candidate_id_set = set(candidate_ids)
    raw_evidence = list(evidence or [])
    if retriever is not None:
        raw_evidence.extend(retriever.retrieve(query, candidate_ids, active_policy.max_evidence_per_item))

    allowed_fields = set(active_policy.allowed_fields or [])
    kept: list[RagEvidence] = []
    dropped_item_scope = 0
    violations: list[dict[str, Any]] = []
    for row in raw_evidence:
        if str(row.item_id) not in candidate_id_set:
            dropped_item_scope += 1
            continue
        if allowed_fields and row.field not in allowed_fields:
            continue
        violation_tokens = evidence_policy_violation_tokens(row)
        if violation_tokens:
            violation = {
                "item_id": row.item_id,
                "field": row.field,
                "source": row.source,
                "tokens": violation_tokens,
            }
            violations.append(violation)
            if active_policy.strict:
                raise EvidencePolicyViolation(f"RAG evidence failed provenance gate: {violation}")
            continue
        kept.append(row)

    kept = _limit_field_quota_per_item(kept)
    kept = _limit_per_item(kept, active_policy.max_evidence_per_item)
    kept, dropped_budget = _limit_total(kept, active_policy.max_evidence_total)
    kept, truncated_text = _truncate_evidence_text(kept, active_policy.max_text_chars)
    context_metadata["rag_policy"] = {
        "mode": active_policy.mode,
        "enabled": True,
        "strict": active_policy.strict,
        "max_evidence_per_item": active_policy.max_evidence_per_item,
        "max_evidence_total": active_policy.max_evidence_total,
        "max_text_chars": active_policy.max_text_chars,
    }
    context_metadata["rag_diagnostics"] = {
        "input_evidence_count": len(raw_evidence),
        "kept_evidence_count": len(kept),
        "dropped_non_candidate_evidence_count": dropped_item_scope,
        "dropped_policy_violation_count": len(violations),
        "dropped_budget_overflow_count": dropped_budget,
        "truncated_text_count": truncated_text,
        "max_evidence_per_item": active_policy.max_evidence_per_item,
        "max_evidence_total": active_policy.max_evidence_total,
        "max_text_chars": active_policy.max_text_chars,
        "policy_violations": violations,
    }
    return RagContext(query=query, candidate_item_ids=candidate_ids, evidence=kept, metadata=context_metadata)


def build_query_rag_context_for_planning(
    query: str,
    evidence: Iterable[RagEvidence] | None = None,
    retriever: QueryPlanningEvidenceRetriever | None = None,
    policy: RagPolicy | None = None,
    metadata: dict[str, Any] | None = None,
) -> RagContext:
    active_policy = policy or RagPolicy(mode="shadow")
    context_metadata = dict(metadata or {})
    if not active_policy.enabled:
        context_metadata["rag_policy"] = {"mode": active_policy.mode, "enabled": False}
        return RagContext(query=query, candidate_item_ids=[], evidence=[], metadata=context_metadata)

    raw_evidence = list(evidence or [])
    if retriever is not None:
        raw_evidence.extend(
            retriever.retrieve(
                query,
                max_evidence_total=active_policy.max_evidence_total,
                max_evidence_per_item=active_policy.max_evidence_per_item,
            )
        )

    allowed_fields = set(active_policy.allowed_fields or [])
    kept: list[RagEvidence] = []
    violations: list[dict[str, Any]] = []
    for row in raw_evidence:
        if allowed_fields and row.field not in allowed_fields:
            continue
        violation_tokens = evidence_policy_violation_tokens(row)
        if violation_tokens:
            violation = {
                "item_id": row.item_id,
                "field": row.field,
                "source": row.source,
                "tokens": violation_tokens,
            }
            violations.append(violation)
            if active_policy.strict:
                raise EvidencePolicyViolation(f"RAG evidence failed provenance gate: {violation}")
            continue
        kept.append(row)

    kept = _limit_field_quota_per_item(kept)
    kept = _limit_per_item(kept, active_policy.max_evidence_per_item)
    kept, dropped_budget = _limit_total(kept, active_policy.max_evidence_total)
    kept, truncated_text = _truncate_evidence_text(kept, active_policy.max_text_chars)
    context_metadata["rag_policy"] = {
        "mode": active_policy.mode,
        "enabled": True,
        "strict": active_policy.strict,
        "max_evidence_per_item": active_policy.max_evidence_per_item,
        "max_evidence_total": active_policy.max_evidence_total,
        "max_text_chars": active_policy.max_text_chars,
    }
    context_metadata["rag_diagnostics"] = {
        "input_evidence_count": len(raw_evidence),
        "kept_evidence_count": len(kept),
        "dropped_non_candidate_evidence_count": 0,
        "dropped_policy_violation_count": len(violations),
        "dropped_budget_overflow_count": dropped_budget,
        "truncated_text_count": truncated_text,
        "max_evidence_per_item": active_policy.max_evidence_per_item,
        "max_evidence_total": active_policy.max_evidence_total,
        "max_text_chars": active_policy.max_text_chars,
        "policy_violations": violations,
        "retrieval_scope": "query_planning",
        "candidate_scoped": False,
    }
    context_metadata.update({
        "retrieval_scope": "query_planning",
        "candidate_scoped": False,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
    })
    return RagContext(query=query, candidate_item_ids=[], evidence=kept, metadata=context_metadata)


def evidence_policy_violation_tokens(evidence: RagEvidence) -> list[str]:
    values = [evidence.source]
    for key in _PROVENANCE_METADATA_KEYS:
        value = evidence.metadata.get(key)
        if value is not None:
            values.append(str(value))
    found = sorted({token for value in values for token in _tokens(value) if token in _FORBIDDEN_PROVENANCE_TOKENS})
    return found


def _limit_per_item(evidence: list[RagEvidence], max_evidence_per_item: int) -> list[RagEvidence]:
    counts: dict[str, int] = {}
    limited: list[RagEvidence] = []
    for row in sorted(evidence, key=lambda item: (-(item.score or 0.0), item.item_id, item.field)):
        count = counts.get(row.item_id, 0)
        if count >= max_evidence_per_item:
            continue
        counts[row.item_id] = count + 1
        limited.append(row)
    return limited


def _limit_field_quota_per_item(evidence: list[RagEvidence]) -> list[RagEvidence]:
    counts: dict[tuple[str, str], int] = {}
    limited: list[RagEvidence] = []
    for row in sorted(evidence, key=lambda item: (-(item.score or 0.0), item.item_id, item.field)):
        key = (row.item_id, row.field)
        if counts.get(key, 0) >= _field_quota(row.field):
            continue
        counts[key] = counts.get(key, 0) + 1
        limited.append(row)
    return limited


def _field_quota(field_name: str) -> int:
    return int(RAG_EVIDENCE_FIELD_QUOTAS.get(field_name, 10_000))


def _limit_total(evidence: list[RagEvidence], max_evidence_total: int) -> tuple[list[RagEvidence], int]:
    if max_evidence_total <= 0:
        return [], len(evidence)
    retained = evidence[:max_evidence_total]
    return retained, max(0, len(evidence) - len(retained))


def _truncate_evidence_text(evidence: list[RagEvidence], max_text_chars: int) -> tuple[list[RagEvidence], int]:
    if max_text_chars <= 0:
        return [replace(row, text="", metadata={**row.metadata, "text_truncated": bool(row.text), "original_text_chars": len(row.text)}) for row in evidence], sum(1 for row in evidence if row.text)
    truncated: list[RagEvidence] = []
    truncated_count = 0
    for row in evidence:
        if len(row.text) <= max_text_chars:
            truncated.append(row)
            continue
        truncated_count += 1
        truncated.append(replace(row, text=row.text[:max_text_chars] + "...", metadata={**row.metadata, "text_truncated": True, "original_text_chars": len(row.text)}))
    return truncated, truncated_count


def _tokens(value: str) -> list[str]:
    return _TOKEN_RE.findall(value.lower())
