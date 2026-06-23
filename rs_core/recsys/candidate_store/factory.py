from __future__ import annotations

import os

from rs_core.recsys.candidate_store.postgres import CandidateStore, NoopCandidateStore, build_postgres_candidate_store_from_env


BACKEND_ENV = "RS_CANDIDATE_STORE_BACKEND"


def build_candidate_store_from_env() -> CandidateStore:
    backend = os.environ.get(BACKEND_ENV, "").strip().lower()
    if backend in {"", "postgres"}:
        return build_postgres_candidate_store_from_env()
    if backend == "noop":
        return NoopCandidateStore()
    if backend in {"cassandra", "scylla", "cql"}:
        from rs_core.recsys.candidate_store.cassandra import build_cassandra_candidate_store_from_env

        return build_cassandra_candidate_store_from_env()
    return NoopCandidateStore()
