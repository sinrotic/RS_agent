from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final


@dataclass(frozen=True)
class BoundaryModule:
    name: str
    responsibility: str
    owned_paths: tuple[str, ...]
    allowed_imports: tuple[str, ...]
    forbidden_imports: tuple[str, ...]
    required_tests: tuple[str, ...]
    compatibility_paths: tuple[str, ...] = ()

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.name:
            errors.append("module name is required")
        if not self.responsibility:
            errors.append(f"{self.name}: responsibility is required")
        if not self.owned_paths:
            errors.append(f"{self.name}: owned_paths is required")
        if not self.required_tests:
            errors.append(f"{self.name}: required_tests is required")
        overlap = set(self.allowed_imports) & set(self.forbidden_imports)
        if overlap:
            errors.append(f"{self.name}: imports cannot be both allowed and forbidden: {sorted(overlap)}")
        return errors


@dataclass(frozen=True)
class BoundaryValidationResult:
    valid: bool
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class BoundaryMap:
    modules: tuple[BoundaryModule, ...] = field(default_factory=tuple)

    def by_name(self) -> dict[str, BoundaryModule]:
        return {module.name: module for module in self.modules}

    def validate(self) -> BoundaryValidationResult:
        errors: list[str] = []
        seen: set[str] = set()
        owned_by: dict[str, str] = {}
        for module in self.modules:
            if module.name in seen:
                errors.append(f"duplicate boundary module: {module.name}")
            seen.add(module.name)
            for owned_path in module.owned_paths:
                canonical_path = _canonical_boundary_path(owned_path)
                previous_owner = owned_by.get(canonical_path)
                if previous_owner is not None:
                    errors.append(f"duplicate owned path: {owned_path} owned by {previous_owner} and {module.name}")
                    continue
                overlapping_path, overlapping_owner = _overlapping_owned_path(owned_path, owned_by)
                if overlapping_path is not None and overlapping_owner is not None:
                    errors.append(f"overlapping owned path: {owned_path} owned by {module.name} overlaps {overlapping_path} owned by {overlapping_owner}")
                owned_by[canonical_path] = module.name
            errors.extend(module.validate())
        missing = REQUIRED_BOUNDARY_MODULES - seen
        if missing:
            errors.append(f"missing required boundary modules: {sorted(missing)}")
        return BoundaryValidationResult(valid=not errors, errors=tuple(errors))


def _overlapping_owned_path(path: str, existing: dict[str, str]) -> tuple[str | None, str | None]:
    normalized = _canonical_boundary_path(path)
    for existing_path, owner in existing.items():
        existing_normalized = _canonical_boundary_path(existing_path)
        if _path_contains(existing_normalized, normalized) or _path_contains(normalized, existing_normalized):
            return existing_path, owner
    return None, None


def _canonical_boundary_path(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def _path_contains(parent: str, child: str) -> bool:
    return child.startswith(f"{parent}/") and child != parent


REQUIRED_BOUNDARY_MODULES: Final[set[str]] = {
    "ServiceRuntimeApi",
    "FastAPIApp",
    "ServingRuntimeComposition",
    "OnlineServiceWrapper",
    "AgentServiceWrapper",
    "ServingSplitAppFactory",
    "RecommendationService",
    "CoreRecommendationRuntime",
    "StateFactsStore",
    "PersistenceStore",
    "InfrastructureBackends",
    "CandidateImportPlan",
    "CandidateStoreWriters",
    "ServingScriptWrappers",
    "AdapterContract",
    "ManifestGate",
    "RouteRegistry",
    "DeploymentGovernanceOptimization",
    "ServingFact",
}


DEFAULT_BOUNDARY_MAP: Final[BoundaryMap] = BoundaryMap(
    modules=(
        BoundaryModule(
            name="ServiceRuntimeApi",
            responsibility="Own public serving API schema, request/response boundaries, health and readiness semantics.",
            owned_paths=("rs_core/serving/schemas/models.py",),
            allowed_imports=("rs_core.serving", "rs_core.common", "fastapi"),
            forbidden_imports=("redis", "minio", "psycopg"),
            required_tests=("tests/services/test_serving_smoke.py", "tests/services/test_serving_boundary_map.py"),
            compatibility_paths=("rs_core/serving/schemas/__init__.py",),
        ),
        BoundaryModule(
            name="FastAPIApp",
            responsibility="Expose the canonical public FastAPI app assembly, dependencies, middleware, exception translation, and main-app routers without merging split-only routes.",
            owned_paths=(
                "rs_core/serving/api/__init__.py",
                "rs_core/serving/api/app.py",
                "rs_core/serving/api/dependencies.py",
                "rs_core/serving/api/exceptions.py",
                "rs_core/serving/api/factory.py",
                "rs_core/serving/api/middleware.py",
                "rs_core/serving/api/routers/__init__.py",
                "rs_core/serving/api/routers/demo.py",
                "rs_core/serving/api/routers/recommendation.py",
                "rs_core/serving/api/routers/runtime.py",
                "rs_core/serving/api/routers/simulation.py",
            ),
            allowed_imports=(
                "fastapi",
                "fastapi.middleware.cors",
                "fastapi.responses",
                "functools",
                "hmac",
                "os",
                "re",
                "rs_core.serving.api",
                "rs_core.serving.application.recommendation_service",
                "rs_core.serving.facades",
                "rs_core.serving.runtime.composition",
                "rs_core.serving.runtime.config",
                "rs_core.serving.schemas",
                "rs_core.offline.simulation",
                "sys",
                "typing",
                "uuid",
            ),
            forbidden_imports=("redis", "minio", "psycopg"),
            required_tests=("tests/services/test_serving_smoke.py", "tests/services/test_serving_reorg_compatibility.py"),
            compatibility_paths=(),
        ),
        BoundaryModule(
            name="ServingRuntimeComposition",
            responsibility="Own cached construction of public, online, and agent serving runtime compositions while api/dependencies.py keeps FastAPI request/auth/env helpers.",
            owned_paths=("rs_core/serving/runtime/composition.py", "rs_core/serving/runtime/split_engines.py"),
            allowed_imports=(
                "functools",
                "os",
                "pathlib",
                "typing",
                "rs_core.agent.engine",
                "rs_core.online.engine",
                "rs_core.serving.application.recommendation_service",
                "rs_core.serving.runtime.config",
                "rs_core.serving.runtime.composition",
            ),
            forbidden_imports=("fastapi", "redis", "minio", "psycopg", "celery", "rq"),
            required_tests=("tests/services/test_serving_reorg_compatibility.py", "tests/contracts/test_architecture_migration_boundaries.py"),
            compatibility_paths=(),
        ),
        BoundaryModule(
            name="OnlineServiceWrapper",
            responsibility="Keep online service entrypoint and dependency wrapper thin over the canonical split app factory and runtime composition.",
            owned_paths=("rs_core/serving/api/online_app.py",),
            allowed_imports=("fastapi", "functools", "rs_core.agent.engine", "rs_core.online.engine", "rs_core.serving.api.split_factory", "rs_core.serving.runtime.composition", "rs_core.serving.runtime.split_engines", "rs_core.serving.schemas"),
            forbidden_imports=("rs_core.serving.api.factory", "rs_core.offline.engine", "redis", "minio", "psycopg"),
            required_tests=("tests/contracts/test_architecture_migration_boundaries.py",),
            compatibility_paths=(),
        ),
        BoundaryModule(
            name="AgentServiceWrapper",
            responsibility="Keep agent service entrypoint and dependency wrapper thin over the canonical split app factory and runtime composition.",
            owned_paths=("rs_core/serving/api/agent_app.py",),
            allowed_imports=("fastapi", "functools", "rs_core.agent.engine", "rs_core.online.engine", "rs_core.serving.api.split_factory", "rs_core.serving.runtime.composition", "rs_core.serving.schemas"),
            forbidden_imports=("rs_core.serving.api.factory", "rs_core.offline.engine", "redis", "minio", "psycopg"),
            required_tests=("tests/contracts/test_architecture_migration_boundaries.py",),
            compatibility_paths=(),
        ),
        BoundaryModule(
            name="ServingSplitAppFactory",
            responsibility="Own split-only online/agent FastAPI app construction and routers without changing the canonical main app route table.",
            owned_paths=("rs_core/serving/api/split_factory.py", "rs_core/serving/api/routers/online.py", "rs_core/serving/api/routers/agent.py"),
            allowed_imports=("fastapi", "typing", "rs_core.serving.api.routers", "rs_core.serving.schemas"),
            forbidden_imports=("rs_core.serving.api.factory", "services", "redis", "minio", "psycopg"),
            required_tests=("tests/contracts/test_architecture_migration_boundaries.py", "tests/services/test_serving_reorg_compatibility.py"),
            compatibility_paths=(),
        ),
        BoundaryModule(
            name="RecommendationService",
            responsibility="Coordinate homepage recommendation, Agent recommendation, immediate feedback, and readiness orchestration.",
            owned_paths=("rs_core/serving/application/recommendation_service.py", "rs_core/serving/runtime/config.py", "rs_core/serving/runtime/readiness.py"),
            allowed_imports=("rs_core.serving", "rs_core.workflow", "rs_core.agent", "rs_core.common"),
            forbidden_imports=("redis", "minio", "psycopg"),
            required_tests=("tests/services/test_serving_smoke.py", "tests/test_serving_facades.py"),
            compatibility_paths=(),
        ),
        BoundaryModule(
            name="CoreRecommendationRuntime",
            responsibility="Keep user-facing synchronous flows in-process: home feed, Agent recommendation, online RAG query, artifact reads, and feedback.",
            owned_paths=("rs_core/agent/runtime/__init__.py", "rs_core/workflow/hybrid_environment.py", "rs_core/workflow/online_recommendation.py"),
            allowed_imports=("rs_core.recsys", "rs_core.agent", "rs_core.serving.domain.adapter_contracts", "rs_core.workflow"),
            forbidden_imports=("rq", "celery", "airflow"),
            required_tests=("tests/services/test_serving_smoke.py", "tests/test_rag_core.py"),
        ),
        BoundaryModule(
            name="StateFactsStore",
            responsibility="Own serving fact builder grouping for sessions, turns, recommendation requests, feedback, session end, and request summary.",
            owned_paths=("rs_core/serving/domain/state_facts_store.py",),
            allowed_imports=("rs_core.serving.domain.serving_fact", "rs_core.serving.persistence", "rs_core.common"),
            forbidden_imports=("rs_core.evaluation", "rs_lab", "sklearn"),
            required_tests=("tests/test_serving_facts.py", "tests/test_serving_persistence.py"),
        ),
        BoundaryModule(
            name="PersistenceStore",
            responsibility="Provide local audit persistence compatibility while canonical stores remain behind contracts.",
            owned_paths=("rs_core/serving/persistence.py", "rs_core/serving/store_contracts.py"),
            allowed_imports=("sqlite3", "json", "rs_core.display", "rs_core.serving.store_contracts"),
            forbidden_imports=("redis", "minio"),
            required_tests=("tests/test_serving_persistence.py", "tests/test_serving_store_contracts.py"),
        ),
        BoundaryModule(
            name="InfrastructureBackends",
            responsibility="Represent non-candidate Store, Cache, Artifact, Knowledge, and Task backend capabilities through adapter protocols and lightweight seams.",
            owned_paths=(
                "rs_core/serving/infrastructure/__init__.py",
                "rs_core/serving/infrastructure/artifacts/",
                "rs_core/serving/infrastructure/cache/",
                "rs_core/serving/infrastructure/knowledge/",
                "rs_core/serving/infrastructure/stores/__init__.py",
                "rs_core/serving/infrastructure/stores/structured_dataset.py",
                "rs_core/serving/infrastructure/tasks/",
            ),
            allowed_imports=("typing", "dataclasses", "pathlib", "rs_core.common", "rs_core.data"),
            forbidden_imports=("redis", "minio", "psycopg"),
            required_tests=("tests/test_serving_adapter_contracts.py",),
            compatibility_paths=(),
        ),
        BoundaryModule(
            name="CandidateImportPlan",
            responsibility="Own pure candidate JSONL path resolution, schema classification, normalization, dedupe, batching, and dry-run reports without backend drivers or writes.",
            owned_paths=("rs_core/serving/infrastructure/stores/candidate_import_plan.py",),
            allowed_imports=("dataclasses", "json", "math", "pathlib", "typing"),
            forbidden_imports=("cassandra", "mysql", "MySQLdb", "pymysql", "redis", "minio", "psycopg"),
            required_tests=("tests/services/test_serving_reorg_compatibility.py", "tests/contracts/test_architecture_migration_boundaries.py"),
            compatibility_paths=(),
        ),
        BoundaryModule(
            name="CandidateStoreWriters",
            responsibility="Own backend-specific candidate store writers behind explicit write flags while reusing CandidateImportPlan for parsing and normalization.",
            owned_paths=(
                "rs_core/serving/infrastructure/stores/candidate_store_mysql.py",
                "rs_core/serving/infrastructure/stores/candidate_store_cassandra.py",
            ),
            allowed_imports=("dataclasses", "datetime", "json", "pathlib", "subprocess", "typing", "rs_core.serving.infrastructure.stores.candidate_import_plan"),
            forbidden_imports=("redis", "minio", "psycopg"),
            required_tests=("tests/services/test_serving_reorg_compatibility.py", "tests/contracts/test_architecture_migration_boundaries.py"),
            compatibility_paths=(),
        ),
        BoundaryModule(
            name="ServingScriptWrappers",
            responsibility="Keep serving candidate import CLI scripts as thin argument parsing wrappers over candidate store writer modules.",
            owned_paths=("scripts/serving/import_candidate_store_to_mysql.py", "scripts/serving/import_candidate_store_to_cassandra.py"),
            allowed_imports=(
                "argparse",
                "json",
                "pathlib",
                "typing",
                "rs_core.serving.infrastructure.stores.candidate_store_mysql",
                "rs_core.serving.infrastructure.stores.candidate_store_cassandra",
            ),
            forbidden_imports=("rs_core.serving.infrastructure.stores.candidate_import_plan", "redis", "minio", "psycopg"),
            required_tests=("tests/services/test_serving_reorg_compatibility.py", "tests/contracts/test_architecture_migration_boundaries.py"),
            compatibility_paths=(),
        ),
        BoundaryModule(
            name="AdapterContract",
            responsibility="Define contract-only interfaces and mocks for store/cache/artifact/knowledge/task without real network backends.",
            owned_paths=("rs_core/serving/domain/adapter_contracts.py",),
            allowed_imports=("typing", "dataclasses", "pathlib"),
            forbidden_imports=("redis", "minio", "psycopg", "celery"),
            required_tests=("tests/test_serving_adapter_contracts.py",),
            compatibility_paths=(),
        ),
        BoundaryModule(
            name="ManifestGate",
            responsibility="Admit serving artifacts only when manifest schema and local artifact/config paths are valid.",
            owned_paths=("rs_core/serving/governance/manifest_gate.py", "configs/artifacts/*.yaml"),
            allowed_imports=("rs_core.common.config", "pathlib", "dataclasses"),
            forbidden_imports=("rs_core.recsys", "rs_lab"),
            required_tests=("tests/test_serving_manifest_gate.py",),
            compatibility_paths=(),
        ),
        BoundaryModule(
            name="RouteRegistry",
            responsibility="Describe active governance routes and required config/output paths consumed through ManifestGate checks.",
            owned_paths=("configs/governance/current_route_registry.yaml",),
            allowed_imports=("rs_core.serving.governance.manifest_gate", "rs_core.common.config"),
            forbidden_imports=("rs_core.recsys", "rs_lab"),
            required_tests=("tests/test_serving_manifest_gate.py",),
            compatibility_paths=(),
        ),
        BoundaryModule(
            name="DeploymentGovernanceOptimization",
            responsibility="Keep optimization artifacts and serving architecture contracts behind governance route entries and prevent direct runtime promotion claims.",
            owned_paths=("rs_core/serving/domain/boundary_map.py",),
            allowed_imports=("rs_core.serving.domain.boundary_map", "rs_core.serving.governance.manifest_gate"),
            forbidden_imports=("rs_core.serving.service",),
            required_tests=("tests/services/test_serving_boundary_map.py", "tests/test_serving_manifest_gate.py"),
            compatibility_paths=(),
        ),
        BoundaryModule(
            name="ServingFact",
            responsibility="Define public-safe serving fact contract and exclude training, evaluation, user profile, oracle, and holdout facts.",
            owned_paths=("rs_core/serving/domain/serving_fact.py",),
            allowed_imports=("dataclasses", "datetime", "typing"),
            forbidden_imports=("rs_core.evaluation", "rs_lab", "pandas", "sklearn"),
            required_tests=("tests/test_serving_facts.py",),
            compatibility_paths=(),
        ),
    )
)


def default_boundary_map() -> BoundaryMap:
    return DEFAULT_BOUNDARY_MAP


__all__ = (
    "BoundaryModule",
    "BoundaryValidationResult",
    "BoundaryMap",
    "REQUIRED_BOUNDARY_MODULES",
    "DEFAULT_BOUNDARY_MAP",
    "default_boundary_map",
)
