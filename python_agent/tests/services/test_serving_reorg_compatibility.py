from __future__ import annotations

import ast
import importlib
import inspect
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.unit, pytest.mark.serving]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_RUNTIME_IMPORTS = {"redis", "minio", "psycopg", "celery", "rq"}
FORBIDDEN_SERVING_LAYER_IMPORTS: set[str] = set()
FORBIDDEN_SERVING_CORE_IMPORT_PREFIXES = ("services",)
CANDIDATE_IMPORTER_BACKEND_DRIVERS = {"cassandra", "mysql", "MySQLdb", "pymysql"}
CANONICAL_SCAN_DIRS = (
    PROJECT_ROOT / "rs_core" / "serving" / "api",
    PROJECT_ROOT / "rs_core" / "serving" / "schemas",
    PROJECT_ROOT / "rs_core" / "serving" / "application",
    PROJECT_ROOT / "rs_core" / "serving" / "domain",
    PROJECT_ROOT / "rs_core" / "serving" / "governance",
    PROJECT_ROOT / "rs_core" / "serving" / "runtime",
    PROJECT_ROOT / "rs_core" / "serving" / "infrastructure",
)
SERVING_CORE_SCAN_DIRS = (
    PROJECT_ROOT / "rs_core" / "serving" / "api",
    PROJECT_ROOT / "rs_core" / "serving" / "schemas",
    PROJECT_ROOT / "rs_core" / "serving" / "application",
    PROJECT_ROOT / "rs_core" / "serving" / "domain",
    PROJECT_ROOT / "rs_core" / "serving" / "governance",
    PROJECT_ROOT / "rs_core" / "serving" / "runtime",
)
DELETED_LEGACY_SERVING_MODULES = {
    "rs_core.serving.adapter_contracts",
    "rs_core.serving.app",
    "rs_core.serving.boundary_map",
    "rs_core.serving.facts",
    "rs_core.serving.manifest_gate",
    "rs_core.serving.schema",
    "rs_core.serving.service",
}
LEGACY_SERVING_SHIM_IMPORT_MEMBERS = {
    "adapter_contracts",
    "app",
    "boundary_map",
    "facts",
    "manifest_gate",
    "schema",
    "service",
}
PACKAGE_ROOT_CONVENIENCE_MEMBERS = {"RecommendationService", "SessionNotFoundError"}
FORBIDDEN_INTERNAL_INFRA_IMPORTS = {"rs_core.data"}
CANONICAL_SERVING_MODULES = {
    "rs_core.serving.api.app",
    "rs_core.serving.api.split_factory",
    "rs_core.serving.schemas",
    "rs_core.serving.schemas.models",
    "rs_core.serving.application.recommendation_service",
    "rs_core.serving.domain.adapter_contracts",
    "rs_core.serving.domain.boundary_map",
    "rs_core.serving.domain.serving_fact",
    "rs_core.serving.governance.manifest_gate",
    "rs_core.serving.infrastructure.stores.candidate_import_plan",
    "rs_core.serving.infrastructure.stores.candidate_store_cassandra",
    "rs_core.serving.infrastructure.stores.candidate_store_mysql",
    "rs_core.serving.runtime.composition",
}
DELETED_LEGACY_PATHS = {
    "rs_core/serving/adapter_contracts.py",
    "rs_core/serving/app.py",
    "rs_core/serving/boundary_map.py",
    "rs_core/serving/facts.py",
    "rs_core/serving/manifest_gate.py",
    "rs_core/serving/schema.py",
    "rs_core/serving/service.py",
}


@pytest.mark.parametrize("module_name", sorted(DELETED_LEGACY_SERVING_MODULES))
def test_deleted_legacy_serving_modules_are_not_importable(module_name: str) -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import importlib; importlib.invalidate_caches(); importlib.import_module({module_name!r})",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert probe.returncode != 0, probe.stdout + probe.stderr
    assert "ModuleNotFoundError" in probe.stderr or "No module named" in probe.stderr


@pytest.mark.parametrize("module_name", sorted(CANONICAL_SERVING_MODULES))
def test_canonical_serving_modules_are_importable(module_name: str) -> None:
    probe = subprocess.run(
        [sys.executable, "-c", f"import importlib; importlib.import_module({module_name!r})"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert probe.returncode == 0, probe.stdout + probe.stderr


def test_canonical_schema_package_reexports_model_symbols() -> None:
    canonical_schema = importlib.import_module("rs_core.serving.schemas")
    canonical_models = importlib.import_module("rs_core.serving.schemas.models")

    for symbol in canonical_models.__all__:
        assert getattr(canonical_schema, symbol) is getattr(canonical_models, symbol)


def test_recommendation_service_init_keeps_public_signature_parameters() -> None:
    from rs_core.serving.application.recommendation_service import RecommendationService

    expected_parameters = [
        "config",
        "limit_users",
        "config_overrides",
        "long_memory_config",
        "long_memory_store",
        "persistence_store",
        "session_summary_service",
        "structured_dataset_store",
    ]

    signature = inspect.signature(RecommendationService.__init__)

    assert [name for name in signature.parameters if name != "self"] == expected_parameters


def test_canonical_app_imports_expose_public_seam() -> None:
    canonical_app = importlib.import_module("rs_core.serving.api.app")
    api_package = importlib.import_module("rs_core.serving.api")

    dotted_app = __import__("rs_core.serving.api.app", fromlist=["__name__"])

    assert dotted_app is canonical_app
    assert isinstance(canonical_app.app, FastAPI)
    assert api_package.fastapi_app is canonical_app.app
    assert not isinstance(api_package.app, FastAPI)
    assert api_package.app is canonical_app
    assert api_package.get_service is canonical_app.get_service
    assert api_package.create_app is canonical_app.create_app
    assert isinstance(canonical_app.create_app(), FastAPI)


def test_dependency_override_uses_canonical_get_service_callable() -> None:
    canonical_app = importlib.import_module("rs_core.serving.api.app")

    class FakeService:
        def readiness(self) -> dict[str, object]:
            return {
                "status": "ready",
                "service": "fake-serving",
                "mode": "test",
                "session_state": "fake",
                "online_route": {"status": "fake"},
            }

    canonical_app.app.dependency_overrides[canonical_app.get_service] = lambda: FakeService()
    try:
        with TestClient(canonical_app.app) as client:
            response = client.get("/ready")
    finally:
        canonical_app.app.dependency_overrides.clear()
        canonical_app.get_service.cache_clear()

    assert response.status_code == 200
    assert response.json()["mode"] == "test"


def test_canonical_app_route_table_keeps_public_contract() -> None:
    canonical_app = importlib.import_module("rs_core.serving.api.app")
    route_table = _public_route_table(canonical_app.app.routes)

    assert route_table == {
        ("/health", ("GET",)),
        ("/ready", ("GET",)),
        ("/session/start", ("POST",)),
        ("/chat", ("POST",)),
        ("/feedback", ("POST",)),
        ("/session/end", ("POST",)),
        ("/recommend", ("POST",)),
        ("/feed/refresh", ("POST",)),
        ("/session/{session_id}", ("GET",)),
        ("/recall", ("POST",)),
        ("/demo/e2e", ("POST",)),
        ("/simulation/scene", ("POST",)),
        ("/simulation/batch", ("POST",)),
    }
    assert {"/rank", "/rag/query"}.isdisjoint({path for path, _methods in route_table})


def test_boundary_map_marks_canonical_contracts_owned_and_deleted_shims_absent() -> None:
    from rs_core.serving.domain.boundary_map import default_boundary_map

    boundary_map = default_boundary_map()
    owned_paths = {path for module in boundary_map.modules for path in module.owned_paths}
    compatibility_paths = {path for module in boundary_map.modules for path in module.compatibility_paths}

    assert {
        "rs_core/serving/api/app.py",
        "rs_core/serving/api/factory.py",
        "rs_core/serving/api/split_factory.py",
        "rs_core/serving/api/routers/online.py",
        "rs_core/serving/api/routers/agent.py",
        "rs_core/serving/schemas/models.py",
        "rs_core/serving/runtime/composition.py",
        "rs_core/serving/domain/boundary_map.py",
        "rs_core/serving/domain/adapter_contracts.py",
        "rs_core/serving/domain/serving_fact.py",
        "rs_core/serving/governance/manifest_gate.py",
        "rs_core/serving/infrastructure/stores/candidate_import_plan.py",
        "rs_core/serving/infrastructure/stores/candidate_store_mysql.py",
        "rs_core/serving/infrastructure/stores/candidate_store_cassandra.py",
        "rs_core/serving/api/online_app.py",
        "rs_core/serving/api/agent_app.py",
        "rs_core/serving/runtime/split_engines.py",
        "scripts/serving/import_candidate_store_to_mysql.py",
        "scripts/serving/import_candidate_store_to_cassandra.py",
    }.issubset(owned_paths)
    assert DELETED_LEGACY_PATHS.isdisjoint(owned_paths)
    assert DELETED_LEGACY_PATHS.isdisjoint(compatibility_paths)


def test_canonical_serving_layers_do_not_import_external_backend_clients() -> None:
    violations: list[str] = []
    for directory in CANONICAL_SCAN_DIRS:
        for source_path in sorted(directory.rglob("*.py")):
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
            violations.extend(_forbidden_ast_imports(source_path, tree))
            violations.extend(_forbidden_token_imports(source_path))

    assert violations == []


def test_canonical_serving_layers_do_not_import_forbidden_vector_builders() -> None:
    violations: list[str] = []
    for directory in CANONICAL_SCAN_DIRS:
        for source_path in sorted(directory.rglob("*.py")):
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
            violations.extend(_forbidden_serving_layer_imports(source_path, tree))

    assert violations == []


def test_serving_core_layers_do_not_import_internal_infra_implementations() -> None:
    violations: list[str] = []
    for directory in SERVING_CORE_SCAN_DIRS:
        for source_path in sorted(directory.rglob("*.py")):
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
            violations.extend(_forbidden_internal_infra_imports(source_path, tree))

    assert violations == []


def test_serving_core_layers_do_not_import_service_entrypoints() -> None:
    violations: list[str] = []
    for directory in SERVING_CORE_SCAN_DIRS:
        for source_path in sorted(directory.rglob("*.py")):
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
            violations.extend(_forbidden_prefix_imports(source_path, tree, FORBIDDEN_SERVING_CORE_IMPORT_PREFIXES))

    assert violations == []


def test_canonical_serving_layers_do_not_import_legacy_shims_or_package_root_shortcuts() -> None:
    violations: list[str] = []
    for directory in CANONICAL_SCAN_DIRS:
        for source_path in sorted(directory.rglob("*.py")):
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
            violations.extend(_legacy_shim_imports(source_path, tree))

    assert violations == []


def test_runtime_config_import_does_not_load_retired_vectorstore_graph() -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import rs_core.serving.runtime.config; "
                "bad=[name for name in sys.modules "
                "if name in {'pymilvus', "
                "'rs_core.data.vectorstores.milvus_client', "
                "'rs_core.agent.rag.milvus_index'}]; "
                "print(bad); "
                "raise SystemExit(1 if bad else 0)"
            ),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert probe.returncode == 0, probe.stdout + probe.stderr


def test_main_serving_import_does_not_load_candidate_importer_backend_drivers() -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "from rs_core.serving.api.factory import create_app; "
                "create_app(); "
                f"bad=sorted(name for name in sys.modules if name.split('.', 1)[0] in {CANDIDATE_IMPORTER_BACKEND_DRIVERS!r}); "
                "print(bad); "
                "raise SystemExit(1 if bad else 0)"
            ),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert probe.returncode == 0, probe.stdout + probe.stderr


def _public_route_table(routes: list[object]) -> set[tuple[str, tuple[str, ...]]]:
    return {
        (route.path, tuple(sorted(route.methods - {"HEAD", "OPTIONS"})))
        for route in routes
        if getattr(route, "include_in_schema", False)
    }


def _forbidden_ast_imports(source_path: Path, tree: ast.AST) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_name = alias.name.split(".", 1)[0]
                if root_name in FORBIDDEN_RUNTIME_IMPORTS:
                    violations.append(f"{source_path.relative_to(PROJECT_ROOT)}:{node.lineno} imports {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            root_name = node.module.split(".", 1)[0]
            if root_name in FORBIDDEN_RUNTIME_IMPORTS:
                violations.append(f"{source_path.relative_to(PROJECT_ROOT)}:{node.lineno} imports from {node.module}")
    return violations


def _forbidden_serving_layer_imports(source_path: Path, tree: ast.AST) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in FORBIDDEN_SERVING_LAYER_IMPORTS:
                    violations.append(f"{source_path.relative_to(PROJECT_ROOT)}:{node.lineno} imports {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module in FORBIDDEN_SERVING_LAYER_IMPORTS:
            violations.append(f"{source_path.relative_to(PROJECT_ROOT)}:{node.lineno} imports from {node.module}")
    return violations


def _legacy_shim_imports(source_path: Path, tree: ast.AST) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in DELETED_LEGACY_SERVING_MODULES:
                    violations.append(f"{source_path.relative_to(PROJECT_ROOT)}:{node.lineno} imports {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module in DELETED_LEGACY_SERVING_MODULES:
                violations.append(f"{source_path.relative_to(PROJECT_ROOT)}:{node.lineno} imports from {node.module}")
            elif node.module == "rs_core.serving":
                imported_members = {alias.name for alias in node.names}
                legacy_members = imported_members & LEGACY_SERVING_SHIM_IMPORT_MEMBERS
                if legacy_members:
                    violations.append(
                        f"{source_path.relative_to(PROJECT_ROOT)}:{node.lineno} imports legacy serving shim members {sorted(legacy_members)}"
                    )
                convenience_members = imported_members & PACKAGE_ROOT_CONVENIENCE_MEMBERS
                if convenience_members:
                    violations.append(
                        f"{source_path.relative_to(PROJECT_ROOT)}:{node.lineno} imports serving package-root convenience members {sorted(convenience_members)}"
                    )
    return violations


def _forbidden_internal_infra_imports(source_path: Path, tree: ast.AST) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in FORBIDDEN_INTERNAL_INFRA_IMPORTS:
                    violations.append(f"{source_path.relative_to(PROJECT_ROOT)}:{node.lineno} imports {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module in FORBIDDEN_INTERNAL_INFRA_IMPORTS:
            violations.append(f"{source_path.relative_to(PROJECT_ROOT)}:{node.lineno} imports from {node.module}")
    return violations


def _forbidden_prefix_imports(source_path: Path, tree: ast.AST, forbidden_prefixes: tuple[str, ...]) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _matches_forbidden_prefix(alias.name, forbidden_prefixes):
                    violations.append(f"{source_path.relative_to(PROJECT_ROOT)}:{node.lineno} imports {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if _matches_forbidden_prefix(node.module, forbidden_prefixes):
                violations.append(f"{source_path.relative_to(PROJECT_ROOT)}:{node.lineno} imports from {node.module}")
    return violations


def _matches_forbidden_prefix(module_name: str, forbidden_prefixes: tuple[str, ...]) -> bool:
    return any(module_name == prefix or module_name.startswith(f"{prefix}.") for prefix in forbidden_prefixes)


def _forbidden_token_imports(source_path: Path) -> list[str]:
    violations: list[str] = []
    with source_path.open("rb") as handle:
        tokens = list(tokenize.tokenize(handle.readline))
    for index, token in enumerate(tokens):
        if token.type != tokenize.NAME:
            continue
        if token.string == "import" and index + 1 < len(tokens):
            imported = _next_name_token(tokens, index + 1)
            if imported in FORBIDDEN_RUNTIME_IMPORTS:
                violations.append(f"{source_path.relative_to(PROJECT_ROOT)}:{token.start[0]} imports {imported}")
        if token.string == "from" and index + 1 < len(tokens):
            imported = _next_name_token(tokens, index + 1)
            if imported in FORBIDDEN_RUNTIME_IMPORTS:
                violations.append(f"{source_path.relative_to(PROJECT_ROOT)}:{token.start[0]} imports from {imported}")
    return violations


def _next_name_token(tokens: list[tokenize.TokenInfo], start_index: int) -> str | None:
    for token in tokens[start_index:]:
        if token.type in {tokenize.NL, tokenize.NEWLINE, tokenize.ENDMARKER}:
            return None
        if token.type == tokenize.NAME:
            return token.string
    return None
