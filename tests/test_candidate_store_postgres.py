from __future__ import annotations

import subprocess

import pytest

from rs_core.recsys.candidate_store.postgres import NoopCandidateStore, PostgresCandidateStore, _ensure_select_only


def test_postgres_candidate_store_rejects_non_readonly_sql() -> None:
    with pytest.raises(ValueError, match="read-only|SELECT"):
        _ensure_select_only("DELETE FROM usercf_candidates")


def test_noop_candidate_store_returns_empty_lists() -> None:
    store = NoopCandidateStore()

    assert store.health()["status"] == "disabled"
    assert store.user_candidates(user_id="u1", source="usercf_recall", limit=10) == []
    assert store.popular_candidates(limit=10) == []


def test_postgres_candidate_store_uses_select_only_runner() -> None:
    calls: list[tuple[list[str], str]] = []

    def runner(command: list[str], sql: str) -> subprocess.CompletedProcess[str]:
        calls.append((command, sql))
        return subprocess.CompletedProcess(command, 0, stdout='{"source":"popular","parent_asin":"i1","score":1.0}\n', stderr="")

    store = PostgresCandidateStore(runner=runner)
    rows = store.popular_candidates(limit=9999)

    assert rows[0].item_id == "i1"
    assert "LIMIT :'limit'" in calls[0][1]
    assert any(value == "limit=500" for value in calls[0][0])
