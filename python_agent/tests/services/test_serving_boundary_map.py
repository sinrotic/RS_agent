from __future__ import annotations

import pytest

from rs_core.serving.domain.boundary_map import REQUIRED_BOUNDARY_MODULES, BoundaryMap, BoundaryModule, default_boundary_map

pytestmark = [pytest.mark.unit, pytest.mark.serving]

DELETED_LEGACY_PATHS = {
    "rs_core/serving/adapter_contracts.py",
    "rs_core/serving/app.py",
    "rs_core/serving/boundary_map.py",
    "rs_core/serving/facts.py",
    "rs_core/serving/manifest_gate.py",
    "rs_core/serving/schema.py",
    "rs_core/serving/service.py",
}


def test_default_boundary_map_covers_required_serving_layers() -> None:
    boundary_map = default_boundary_map()

    assert set(boundary_map.by_name()) == REQUIRED_BOUNDARY_MODULES
    assert boundary_map.validate().valid is True


def test_boundary_module_requires_owned_paths_and_tests() -> None:
    module = BoundaryModule(
        name="Broken",
        responsibility="",
        owned_paths=(),
        allowed_imports=("redis",),
        forbidden_imports=("redis",),
        required_tests=(),
    )

    errors = module.validate()

    assert "Broken: responsibility is required" in errors
    assert "Broken: owned_paths is required" in errors
    assert "Broken: required_tests is required" in errors
    assert any("both allowed and forbidden" in error for error in errors)


def test_boundary_map_reports_missing_required_modules() -> None:
    result = BoundaryMap(modules=()).validate()

    assert result.valid is False
    assert any("missing required boundary modules" in error for error in result.errors)


def test_boundary_map_reports_duplicate_owned_paths() -> None:
    first = BoundaryModule(
        name="ServiceRuntimeApi",
        responsibility="first owner",
        owned_paths=("rs_core/serving/api/",),
        allowed_imports=(),
        forbidden_imports=(),
        required_tests=("tests/test_serving_smoke.py",),
    )
    second = BoundaryModule(
        name="FastAPIApp",
        responsibility="second owner",
        owned_paths=("rs_core/serving/api/",),
        allowed_imports=(),
        forbidden_imports=(),
        required_tests=("tests/test_serving_smoke.py",),
    )

    result = BoundaryMap(modules=(first, second)).validate()

    assert result.valid is False
    assert "duplicate owned path: rs_core/serving/api/ owned by ServiceRuntimeApi and FastAPIApp" in result.errors


def test_boundary_map_reports_overlapping_owned_paths() -> None:
    first = BoundaryModule(
        name="ServiceRuntimeApi",
        responsibility="directory owner",
        owned_paths=("rs_core/serving/api/",),
        allowed_imports=(),
        forbidden_imports=(),
        required_tests=("tests/test_serving_smoke.py",),
    )
    second = BoundaryModule(
        name="FastAPIApp",
        responsibility="file owner",
        owned_paths=("rs_core/serving/api/app.py",),
        allowed_imports=(),
        forbidden_imports=(),
        required_tests=("tests/test_serving_smoke.py",),
    )

    result = BoundaryMap(modules=(first, second)).validate()

    assert result.valid is False
    assert "overlapping owned path: rs_core/serving/api/app.py owned by FastAPIApp overlaps rs_core/serving/api owned by ServiceRuntimeApi" in result.errors


def test_boundary_map_canonicalizes_owned_paths_before_validation() -> None:
    slash_owner = BoundaryModule(
        name="ServiceRuntimeApi",
        responsibility="slash owner",
        owned_paths=("rs_core/serving/api/",),
        allowed_imports=(),
        forbidden_imports=(),
        required_tests=("tests/test_serving_smoke.py",),
    )
    normalized_owner = BoundaryModule(
        name="FastAPIApp",
        responsibility="normalized owner",
        owned_paths=("rs_core/serving/api",),
        allowed_imports=(),
        forbidden_imports=(),
        required_tests=("tests/test_serving_smoke.py",),
    )
    windows_owner = BoundaryModule(
        name="RecommendationService",
        responsibility="windows path owner",
        owned_paths=("rs_core\\serving\\api\\",),
        allowed_imports=(),
        forbidden_imports=(),
        required_tests=("tests/test_serving_smoke.py",),
    )

    duplicate_result = BoundaryMap(modules=(slash_owner, normalized_owner)).validate()
    windows_duplicate_result = BoundaryMap(modules=(slash_owner, windows_owner)).validate()

    assert duplicate_result.valid is False
    assert "duplicate owned path: rs_core/serving/api owned by ServiceRuntimeApi and FastAPIApp" in duplicate_result.errors
    assert windows_duplicate_result.valid is False
    assert "duplicate owned path: rs_core\\serving\\api\\ owned by ServiceRuntimeApi and RecommendationService" in windows_duplicate_result.errors


def test_boundary_map_reports_overlap_without_trailing_slash() -> None:
    directory_owner = BoundaryModule(
        name="ServiceRuntimeApi",
        responsibility="directory owner",
        owned_paths=("rs_core/serving/api",),
        allowed_imports=(),
        forbidden_imports=(),
        required_tests=("tests/test_serving_smoke.py",),
    )
    file_owner = BoundaryModule(
        name="FastAPIApp",
        responsibility="file owner",
        owned_paths=("rs_core/serving/api/app.py",),
        allowed_imports=(),
        forbidden_imports=(),
        required_tests=("tests/test_serving_smoke.py",),
    )

    result = BoundaryMap(modules=(directory_owner, file_owner)).validate()

    assert result.valid is False
    assert "overlapping owned path: rs_core/serving/api/app.py owned by FastAPIApp overlaps rs_core/serving/api owned by ServiceRuntimeApi" in result.errors


def test_serving_api_and_schema_boundaries_use_canonical_files_only() -> None:
    modules = default_boundary_map().by_name()

    schema_module = modules["ServiceRuntimeApi"]
    assert "rs_core/serving/schemas/models.py" in schema_module.owned_paths
    assert "rs_core/serving/schema.py" not in schema_module.compatibility_paths
    assert "rs_core/serving/schema.py" not in schema_module.owned_paths

    app_module = modules["FastAPIApp"]
    assert "rs_core/serving/api/app.py" in app_module.owned_paths
    assert "rs_core/serving/api/factory.py" in app_module.owned_paths
    assert "rs_core/serving/api/split_factory.py" not in app_module.owned_paths
    assert "rs_core/serving/api/routers/online.py" not in app_module.owned_paths
    assert "rs_core/serving/api/routers/agent.py" not in app_module.owned_paths
    assert "rs_core.serving.service" not in app_module.allowed_imports
    assert "rs_core.serving.application.recommendation_service" in app_module.allowed_imports
    assert "rs_core.serving.runtime.composition" in app_module.allowed_imports
    assert "rs_core.serving.runtime.config" in app_module.allowed_imports
    assert "rs_core.serving.facades" in app_module.allowed_imports
    assert "rs_core.serving.schemas" in app_module.allowed_imports
    assert "rs_core/serving/app.py" not in app_module.compatibility_paths
    assert "rs_core/serving/app.py" not in app_module.owned_paths
    assert app_module.compatibility_paths == ()


def test_deleted_legacy_shims_are_not_boundary_paths() -> None:
    boundary_map = default_boundary_map()
    owned_paths = {path for module in boundary_map.modules for path in module.owned_paths}
    compatibility_paths = {path for module in boundary_map.modules for path in module.compatibility_paths}

    assert DELETED_LEGACY_PATHS.isdisjoint(owned_paths)
    assert DELETED_LEGACY_PATHS.isdisjoint(compatibility_paths)


def test_state_facts_store_owns_canonical_grouping_not_legacy_shim() -> None:
    module = default_boundary_map().by_name()["StateFactsStore"]

    assert "rs_core/serving/domain/state_facts_store.py" in module.owned_paths
    assert "rs_core/serving/facts.py" not in module.owned_paths
    assert "rs_core/serving/facts.py" not in module.compatibility_paths


def test_infrastructure_backends_forbid_real_network_clients() -> None:
    module = default_boundary_map().by_name()["InfrastructureBackends"]

    assert {"redis", "minio", "psycopg"}.issubset(module.forbidden_imports)
    assert "rs_core/serving/infrastructure/stores/structured_dataset.py" in module.owned_paths
    assert "rs_core/serving/infrastructure/stores/candidate_import_plan.py" not in module.owned_paths
    assert "rs_core/serving/infrastructure/stores/candidate_store_mysql.py" not in module.owned_paths
    assert "rs_core/serving/infrastructure/stores/candidate_store_cassandra.py" not in module.owned_paths
    assert "rs_core/serving/domain/adapter_contracts.py" not in module.owned_paths
    assert "rs_core/serving/adapter_contracts.py" not in module.compatibility_paths


def test_serving_phase4_boundary_modules_are_non_overlapping() -> None:
    modules = default_boundary_map().by_name()

    assert modules["ServingRuntimeComposition"].owned_paths == (
        "rs_core/serving/runtime/composition.py",
        "rs_core/serving/runtime/split_engines.py",
    )
    assert modules["ServingRuntimeComposition"].compatibility_paths == ()
    assert modules["ServingRuntimeComposition"].forbidden_imports == ("fastapi", "redis", "minio", "psycopg", "celery", "rq")

    assert modules["OnlineServiceWrapper"].owned_paths == ("rs_core/serving/api/online_app.py",)
    assert "rs_core.offline.engine" in modules["OnlineServiceWrapper"].forbidden_imports
    assert modules["AgentServiceWrapper"].owned_paths == ("rs_core/serving/api/agent_app.py",)
    assert "rs_core.offline.engine" in modules["AgentServiceWrapper"].forbidden_imports

    split_factory = modules["ServingSplitAppFactory"]
    assert split_factory.owned_paths == (
        "rs_core/serving/api/split_factory.py",
        "rs_core/serving/api/routers/online.py",
        "rs_core/serving/api/routers/agent.py",
    )
    assert "rs_core.serving.api.factory" in split_factory.forbidden_imports

    assert modules["CandidateImportPlan"].owned_paths == ("rs_core/serving/infrastructure/stores/candidate_import_plan.py",)
    assert {"cassandra", "mysql", "MySQLdb", "pymysql"}.issubset(modules["CandidateImportPlan"].forbidden_imports)
    assert modules["CandidateStoreWriters"].owned_paths == (
        "rs_core/serving/infrastructure/stores/candidate_store_mysql.py",
        "rs_core/serving/infrastructure/stores/candidate_store_cassandra.py",
    )
    assert modules["ServingScriptWrappers"].owned_paths == (
        "scripts/serving/import_candidate_store_to_mysql.py",
        "scripts/serving/import_candidate_store_to_cassandra.py",
    )


def test_core_runtime_uses_canonical_adapter_contract_boundary() -> None:
    module = default_boundary_map().by_name()["CoreRecommendationRuntime"]

    assert "rs_core.serving.adapter_contracts" not in module.allowed_imports
    assert "rs_core.serving.domain.adapter_contracts" in module.allowed_imports
