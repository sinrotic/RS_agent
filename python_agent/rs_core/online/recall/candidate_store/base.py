from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from rs_core.common.recsys_types import RecallCandidate

MAX_QUERY_LIMIT = 500


class CandidateStore(Protocol):
    def health(self) -> dict[str, Any]: ...

    def item_neighbors(self, *, source: str, seed_items: list[str], limit_per_seed: int) -> list[RecallCandidate]: ...

    def user_candidates(self, *, user_id: str, source: str, limit: int) -> list[RecallCandidate]: ...

    def popular_candidates(self, *, scope: str = "global", bucket: str = "", limit: int = 50) -> list[RecallCandidate]: ...

    def category_candidates(self, *, buckets: list[str], limit_per_bucket: int = 20) -> list[RecallCandidate]: ...

    def user_category_buckets(self, *, user_id: str, limit: int = 5) -> list[str]: ...

    def pool_candidates(self, *, user_id: str, limit: int = 500) -> list[RecallCandidate]: ...


class NoopCandidateStore:
    def health(self) -> dict[str, Any]:
        return {"enabled": False, "status": "disabled", "backend": "noop"}

    def item_neighbors(self, *, source: str, seed_items: list[str], limit_per_seed: int) -> list[RecallCandidate]:
        return []

    def user_candidates(self, *, user_id: str, source: str, limit: int) -> list[RecallCandidate]:
        return []

    def popular_candidates(self, *, scope: str = "global", bucket: str = "", limit: int = 50) -> list[RecallCandidate]:
        return []

    def category_candidates(self, *, buckets: list[str], limit_per_bucket: int = 20) -> list[RecallCandidate]:
        return []

    def user_category_buckets(self, *, user_id: str, limit: int = 5) -> list[str]:
        return []

    def pool_candidates(self, *, user_id: str, limit: int = 500) -> list[RecallCandidate]:
        return []


@dataclass
class SafeCandidateStore:
    inner: CandidateStore

    def health(self) -> dict[str, Any]:
        try:
            return public_status(self.inner.health())
        except Exception as exc:
            return safe_error_status("health_failed", exc)

    def item_neighbors(self, *, source: str, seed_items: list[str], limit_per_seed: int) -> list[RecallCandidate]:
        try:
            return self.inner.item_neighbors(source=source, seed_items=seed_items, limit_per_seed=limit_per_seed)
        except Exception:
            return []

    def user_candidates(self, *, user_id: str, source: str, limit: int) -> list[RecallCandidate]:
        try:
            return self.inner.user_candidates(user_id=user_id, source=source, limit=limit)
        except Exception:
            return []

    def popular_candidates(self, *, scope: str = "global", bucket: str = "", limit: int = 50) -> list[RecallCandidate]:
        try:
            return self.inner.popular_candidates(scope=scope, bucket=bucket, limit=limit)
        except Exception:
            return []

    def category_candidates(self, *, buckets: list[str], limit_per_bucket: int = 20) -> list[RecallCandidate]:
        try:
            return self.inner.category_candidates(buckets=buckets, limit_per_bucket=limit_per_bucket)
        except Exception:
            return []

    def user_category_buckets(self, *, user_id: str, limit: int = 5) -> list[str]:
        try:
            return self.inner.user_category_buckets(user_id=user_id, limit=limit)
        except Exception:
            return []

    def pool_candidates(self, *, user_id: str, limit: int = 500) -> list[RecallCandidate]:
        try:
            return self.inner.pool_candidates(user_id=user_id, limit=limit)
        except Exception:
            return []


def clamp_limit(value: int, *, maximum: int = MAX_QUERY_LIMIT) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 50
    return max(1, min(parsed, maximum))


def public_status(payload: dict[str, Any]) -> dict[str, Any]:
    safe = dict(payload)
    for key in ("dsn", "password", "url", "stderr", "command"):
        safe.pop(key, None)
    return safe


def safe_error_status(reason: str, exc: Exception, backend: str = "candidate_store") -> dict[str, Any]:
    return {"enabled": True, "status": "degraded", "backend": backend, "reason": reason, "error_type": type(exc).__name__}
