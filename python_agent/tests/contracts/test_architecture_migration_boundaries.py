from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.unit, pytest.mark.smoke]

PROJECT_ROOT = Path(__file__).resolve().parents[2]

LEGACY_IMPORT_ROOTS = {
    "rs_core.artifacts",
    "rs_core.training",
    "rs_core.recsys",
    "rs_core.serving",
    "rs_core.workflow",
    "rs_core.display",
}

PUBLIC_API_FORBIDDEN_FIELD_MARKERS = {
    "agent_tool_trace",
    "diagnostics_path",
    "ground_truth",
    "holdout",
    "label_binary",
    "oracle",
    "score_trace",
    "training_samples",
}

MAIN_APP_SPLIT_ONLY_ROUTES = {"/rank", "/rag/query"}

LEGACY_COMPATIBILITY_IMPORT_WHITELIST = {
    "rs_core/online/contracts/__init__.py": {"rs_core.serving.schemas"},
    "rs_core/online/engine/__init__.py": {"rs_core.serving.schemas"},
    "rs_core/online/runtime/pool500.py": {
        "rs_core.display.builder",
        "rs_core.workflow.hybrid_demo",
        "rs_core.workflow.hybrid_environment",
    },
    "rs_core/agent/adapters/memory.py": {
        "rs_core.serving.session_summary",
    },
    "rs_core/agent/cli.py": {
        "rs_core.display",
        "rs_core.workflow.hybrid_environment",
    },
    "rs_core/agent/explanation/__init__.py": {"rs_core.display.builder"},
    "rs_core/agent/rollout.py": {"rs_core.display"},
    "rs_core/offline/training/multi_turn_sft_generator.py": {"rs_core.serving.application.recommendation_service"},
}


def test_target_architecture_packages_are_importable() -> None:
    from rs_core.agent.engine import AgentOrchestrationEngine
    from rs_core.data.adapters import MilvusAdapter, MinioAdapter, MysqlAdapter, RedisAdapter
    from rs_core.data.engine import DataAssetEngine
    from rs_core.offline.engine import OfflineModelEngine
    from rs_core.online.engine import OnlineRecommendationEngine

    assert MysqlAdapter().handle().contract.backend == "mysql_dataset"
    assert RedisAdapter().handle().contract.backend == "redis"
    assert MinioAdapter().handle().contract.backend == "minio"
    assert MilvusAdapter().handle().contract.backend == "milvus"
    assert DataAssetEngine().health()["engine"] == "DataAssetEngine"
    assert OnlineRecommendationEngine().ready()["engine"] == "OnlineRecommendationEngine"
    assert AgentOrchestrationEngine().ready()["engine"] == "AgentOrchestrationEngine"
    assert OfflineModelEngine().health()["engine"] == "OfflineModelEngine"


def test_main_serving_app_does_not_include_split_only_routes() -> None:
    from rs_core.serving.api.factory import create_app

    route_paths = {path for path, _methods in _public_route_table(create_app().routes)}

    assert MAIN_APP_SPLIT_ONLY_ROUTES.isdisjoint(route_paths)


def test_online_service_route_table_is_online_only() -> None:
    from rs_core.online.engine import OnlineRecommendationEngine
    from rs_core.serving.api.online_app import create_app
    from rs_core.serving.runtime.split_engines import get_online_engine

    app = create_app()
    app.dependency_overrides[get_online_engine] = lambda: OnlineRecommendationEngine()
    try:
        with TestClient(app) as client:
            route_table = _public_route_table(client.app.routes)
            assert route_table == {
                ("/health", ("GET",)),
                ("/ready", ("GET",)),
                ("/recommend", ("POST",)),
                ("/recall", ("POST",)),
                ("/rank", ("POST",)),
            }
            assert client.get("/health").json() == {"status": "ok", "service": "online-service"}
            ready = client.get("/ready").json()
            assert ready["dependencies"]["candidate_pool_client"] == "CandidatePoolClient"
            assert ready["dependencies"]["artifact_client"] == "ArtifactClient"
    finally:
        app.dependency_overrides.clear()


def test_agent_service_route_table_excludes_low_level_recommendation_routes() -> None:
    from rs_core.agent.engine import AgentOrchestrationEngine
    from rs_core.serving.api.agent_app import create_app
    from rs_core.serving.runtime.split_engines import get_agent_engine

    app = create_app()
    app.dependency_overrides[get_agent_engine] = lambda: AgentOrchestrationEngine()
    try:
        with TestClient(app) as client:
            route_table = _public_route_table(client.app.routes)
            assert route_table == {
                ("/health", ("GET",)),
                ("/ready", ("GET",)),
                ("/session/start", ("POST",)),
                ("/chat", ("POST",)),
                ("/chat/stream", ("POST",)),
                ("/feedback", ("POST",)),
                ("/rag/query", ("POST",)),
                ("/session/end", ("POST",)),
                ("/session/{session_id}", ("GET",)),
            }
            assert client.get("/health").json() == {"status": "ok", "service": "agent-service"}
            ready = client.get("/ready").json()
            assert ready["dependencies"]["online_client"] == "OnlineRecommendationClient"
            assert ready["dependencies"]["knowledge_client"] == "KnowledgeDataClient"
    finally:
        app.dependency_overrides.clear()


def test_agent_service_unbound_smoke_flow() -> None:
    from rs_core.agent.engine import AgentOrchestrationEngine
    from rs_core.serving.api.agent_app import create_app
    from rs_core.serving.runtime.split_engines import get_agent_engine

    app = create_app()
    app.dependency_overrides[get_agent_engine] = lambda: AgentOrchestrationEngine()
    try:
        with TestClient(app) as client:
            session = client.post("/session/start", json={"user_id": "u1"})
            assert session.status_code == 200
            assert session.json() == {"session_id": "u1"}

            chat = client.post("/chat", json={"session_id": "u1", "message": "想看新品"})
            assert chat.status_code == 200
            assert chat.json()["session_id"] == "u1"
            assert chat.json()["display"]["items"] == []

            rag = client.post("/rag/query", json={"query": "running shoes", "max_chunks": 2})
            assert rag.status_code == 200
            assert rag.json()["data_client"] == "KnowledgeDataClient"
    finally:
        app.dependency_overrides.clear()


def test_agent_engine_calls_online_and_data_clients(tmp_path: Path) -> None:
    from rs_core.agent.engine import AgentOrchestrationEngine

    engine = AgentOrchestrationEngine()
    recommendation = engine.recommend({"user_sequence": {"recent_item_ids": ["i1"]}, "top_k": 1})
    assert recommendation["ranking_trace"]["route"] == "unbound_fallback"

    chunks_path = tmp_path / "chunks.jsonl"
    chunks_path.write_text('{"chunk_id":"c1","item_id":"i1","text":"Trail running shoe"}\n', encoding="utf-8")
    rag = engine.rag_query("running shoes", max_chunks=1, source_path=str(chunks_path))
    assert rag["data_client"] == "KnowledgeDataClient"
    assert rag["evidence_count"] == 1
    assert rag["evidence"][0]["text"] == "Trail running shoe"
    assert engine.memory_ref("u1") == {"session_id": "u1", "backend": "data-client-managed"}
    assert engine.validate_rag_agent_call(
        {"stage": "pre_retrieval_query_support", "query": "running shoes"}
    )["valid"] is True


def test_online_service_unbound_smoke_flow() -> None:
    from rs_core.online.engine import OnlineRecommendationEngine
    from rs_core.serving.api.online_app import create_app
    from rs_core.serving.runtime.split_engines import get_online_engine

    sequence = {"recent_item_ids": ["i3", "i2", "i1"]}
    app = create_app()
    app.dependency_overrides[get_online_engine] = lambda: OnlineRecommendationEngine()
    try:
        with TestClient(app) as client:
            recall = client.post("/recall", json={"user_sequence": sequence, "candidate_pool_size": 2})
            assert recall.status_code == 200
            assert recall.json()["candidate_item_ids"] == ["i3", "i2"]

            rank = client.post("/rank", json={"candidate_item_ids": ["i2", "i1"], "return_top_k": 1})
            assert rank.status_code == 200
            assert rank.json()["ranked_item_ids"] == ["i2"]
    finally:
        app.dependency_overrides.clear()


def test_canonical_split_entrypoints_without_cross_owned_routes() -> None:
    online_imports = _imports_for(PROJECT_ROOT / "rs_core" / "serving" / "api" / "online_app.py")
    agent_imports = _imports_for(PROJECT_ROOT / "rs_core" / "serving" / "api" / "agent_app.py")

    assert "rs_core.agent.engine" not in online_imports
    assert "rs_core.offline.engine" not in online_imports
    assert "rs_core.online.engine" not in agent_imports
    assert "rs_core.offline.engine" not in agent_imports


def test_new_entrypoint_legacy_imports_are_whitelist_only() -> None:
    scan_roots = [
        PROJECT_ROOT / "rs_core" / "data",
        PROJECT_ROOT / "rs_core" / "online",
        PROJECT_ROOT / "rs_core" / "agent",
        PROJECT_ROOT / "rs_core" / "offline",
    ]
    violations: list[str] = []
    seen_whitelist_paths: set[str] = set()

    for root in scan_roots:
        for path in root.rglob("*.py"):
            relative_path = path.relative_to(PROJECT_ROOT).as_posix()
            legacy_imports = _legacy_imports_for(path)
            if not legacy_imports:
                continue
            allowed = LEGACY_COMPATIBILITY_IMPORT_WHITELIST.get(relative_path, set())
            unexpected = legacy_imports - allowed
            if unexpected:
                violations.append(f"{relative_path}: {sorted(unexpected)}")
            seen_whitelist_paths.add(relative_path)

    missing_whitelist_files = sorted(set(LEGACY_COMPATIBILITY_IMPORT_WHITELIST) - seen_whitelist_paths)
    assert missing_whitelist_files == []
    assert violations == []


def test_no_services_package_entrypoints_remain() -> None:
    assert not (PROJECT_ROOT / "services").exists()


def test_retired_agent_runtime_package_is_deleted() -> None:
    assert not (PROJECT_ROOT / "rs_core" / "agent_runtime").exists()


def test_retired_semantic_description_package_is_deleted() -> None:
    assert not (PROJECT_ROOT / "rs_core" / "recsys" / "semantic_description").exists()


def test_retired_recsys_package_is_deleted() -> None:
    assert not (PROJECT_ROOT / "rs_core" / "recsys").exists()


def test_retired_recsys_recall_package_is_deleted() -> None:
    assert not (PROJECT_ROOT / "rs_core" / "recsys" / "recall").exists()


def test_retired_recsys_online_retrieval_package_is_deleted() -> None:
    assert not (PROJECT_ROOT / "rs_core" / "recsys" / "online_retrieval").exists()


def test_retired_recsys_rag_package_is_deleted() -> None:
    assert not (PROJECT_ROOT / "rs_core" / "recsys" / "rag").exists()


def test_retired_recsys_ranking_modules_are_deleted() -> None:
    assert not (PROJECT_ROOT / "rs_core" / "recsys" / "ranking.py").exists()
    assert not (PROJECT_ROOT / "rs_core" / "recsys" / "cold_deepfm.py").exists()


def test_retired_recsys_candidate_merge_module_is_deleted() -> None:
    assert not (PROJECT_ROOT / "rs_core" / "recsys" / "candidate_merge.py").exists()


def test_retired_recsys_candidate_store_package_is_deleted() -> None:
    assert not (PROJECT_ROOT / "rs_core" / "recsys" / "candidate_store").exists()


def test_retired_recsys_pool500_artifacts_module_is_deleted() -> None:
    assert not (PROJECT_ROOT / "rs_core" / "recsys" / "pool500_artifacts.py").exists()


def test_retired_recsys_types_module_is_deleted() -> None:
    assert not (PROJECT_ROOT / "rs_core" / "recsys" / "types.py").exists()


def test_retired_recsys_ltr_module_is_deleted() -> None:
    assert not (PROJECT_ROOT / "rs_core" / "recsys" / "ltr.py").exists()


def test_retired_recsys_vector_index_module_is_deleted() -> None:
    assert not (PROJECT_ROOT / "rs_core" / "recsys" / "vector_index.py").exists()


def test_retired_recsys_two_tower_source_manifest_module_is_deleted() -> None:
    assert not (PROJECT_ROOT / "rs_core" / "recsys" / "two_tower_source_manifest.py").exists()


def test_retired_recsys_two_tower_query_module_is_deleted() -> None:
    assert not (PROJECT_ROOT / "rs_core" / "recsys" / "two_tower_query.py").exists()


def test_retired_recsys_two_tower_module_is_deleted() -> None:
    assert not (PROJECT_ROOT / "rs_core" / "recsys" / "two_tower.py").exists()


def test_retired_recsys_evaluation_module_is_deleted() -> None:
    assert not (PROJECT_ROOT / "rs_core" / "recsys" / "evaluation.py").exists()


def test_retired_recsys_vectorstores_package_is_deleted() -> None:
    assert not (PROJECT_ROOT / "rs_core" / "recsys" / "vectorstores").exists()


def test_retired_evaluation_package_is_deleted() -> None:
    assert not (PROJECT_ROOT / "rs_core" / "evaluation").exists()


def test_retired_simulation_package_is_deleted() -> None:
    assert not (PROJECT_ROOT / "rs_core" / "simulation").exists()


def test_retired_training_package_is_deleted() -> None:
    assert not (PROJECT_ROOT / "rs_core" / "training").exists()


def test_serving_phase4_boundaries_are_documented_and_non_overlapping() -> None:
    from rs_core.serving.domain.boundary_map import default_boundary_map

    modules = default_boundary_map().by_name()
    phase4_modules = {
        "ServingRuntimeComposition",
        "OnlineServiceWrapper",
        "AgentServiceWrapper",
        "ServingSplitAppFactory",
        "CandidateImportPlan",
        "CandidateStoreWriters",
        "ServingScriptWrappers",
    }
    owned_by: dict[str, str] = {}
    for module_name in phase4_modules:
        module = modules[module_name]
        assert module.required_tests
        for owned_path in module.owned_paths:
            assert owned_path not in owned_by, f"{owned_path} owned by {owned_by[owned_path]} and {module_name}"
            owned_by[owned_path] = module_name

    assert owned_by["rs_core/serving/runtime/composition.py"] == "ServingRuntimeComposition"
    assert owned_by["rs_core/serving/api/online_app.py"] == "OnlineServiceWrapper"
    assert owned_by["rs_core/serving/api/agent_app.py"] == "AgentServiceWrapper"
    assert owned_by["rs_core/serving/api/split_factory.py"] == "ServingSplitAppFactory"
    assert owned_by["rs_core/serving/infrastructure/stores/candidate_import_plan.py"] == "CandidateImportPlan"
    assert owned_by["rs_core/serving/infrastructure/stores/candidate_store_mysql.py"] == "CandidateStoreWriters"
    assert owned_by["scripts/serving/import_candidate_store_to_mysql.py"] == "ServingScriptWrappers"
    assert "rs_core/serving/api/app.py" not in owned_by
    assert "services/data_worker/main.py" not in owned_by
    assert "services/offline_worker/main.py" not in owned_by


def test_legacy_import_governance_docs_are_present() -> None:
    compatibility_status = (PROJECT_ROOT / "dic" / "architecture" / "RS_AGENT_COMPATIBILITY_BOUNDARY_STATUS.md").read_text(
        encoding="utf-8"
    )
    import_census = (PROJECT_ROOT / "dic" / "architecture" / "RS_AGENT_LEGACY_IMPORT_CENSUS.md").read_text(
        encoding="utf-8"
    )
    hardening_plan = (PROJECT_ROOT / "dic" / "architecture" / "RS_AGENT_POST_MIGRATION_HARDENING_PLAN.md").read_text(
        encoding="utf-8"
    )

    assert "退役等级" in compatibility_status
    assert "当前允许的 compatibility import" in compatibility_status
    assert "RS_AGENT_LEGACY_IMPORT_CENSUS.md" in compatibility_status
    assert "SUMMARY_BY_SCAN" in import_census
    assert "import census 报告" in hardening_plan


def test_agent_phase3_entrypoint_inventory_documents_current_facades() -> None:
    inventory = (PROJECT_ROOT / "dic" / "architecture" / "RS_AGENT_PHASE3_AGENT_RAG_ENTRYPOINT_INVENTORY.md").read_text(
        encoding="utf-8"
    )
    project_structure = (PROJECT_ROOT / "dic" / "PROJECT_STRUCTURE.md").read_text(encoding="utf-8")

    assert "Agent/RAG Phase 3 入口清单" in project_structure
    for marker in [
        "AgentOrchestrationEngine",
        "rs_core/agent/dialogue/__init__.py",
        "rs_core/agent/rag/__init__.py",
        "rs_core/workflow/hybrid_environment.py",
        "rs_core/agent/adapters/rag.py",
        "tests/agent/test_agent_runtime_contracts.py",
        "tests/services/test_serving_smoke.py",
    ]:
        assert marker in inventory
    assert "`rs_core/agent_runtime`、`rs_core/rsagent` 与 `rs_core/recsys/rag` 均已物理删除" in inventory


def test_rag_build_scripts_declare_data_client_artifact_boundary() -> None:
    for relative_path in [
        "scripts/recall/build_rag_bm25_index.py",
        "scripts/recall/build_milvus_rag_index.py",
        "scripts/recall/build_rag_elasticsearch_bm25_index.py",
    ]:
        text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        imports = _imports_for(PROJECT_ROOT / relative_path)
        assert "rs_core.data.clients" in imports
        assert "rs_core.agent.rag" in imports
        assert "KnowledgeDataClient" in text
        assert "knowledge_artifact" in text
        assert not _matching_imports(imports, ("rs_core.agent_runtime", "rs_core.recsys.rag"))


def test_retired_rsagent_package_is_deleted() -> None:
    assert not (PROJECT_ROOT / "rs_core" / "rsagent").exists()
    current_route_registry = (PROJECT_ROOT / "configs" / "governance" / "current_route_registry.yaml").read_text(
        encoding="utf-8"
    )
    assert "rs_core/rsagent" not in current_route_registry


def test_rag_runtime_consumes_data_adapter_contract_resource_refs() -> None:
    for relative_path in [
        "rs_core/workflow/facades.py",
        "rs_core/workflow/hybrid_environment.py",
    ]:
        text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert "KnowledgeDataClient" in text
        assert "adapter_contract" in text
        assert "resource_ref" in text

    workflow_facade_text = (PROJECT_ROOT / "rs_core" / "workflow" / "facades.py").read_text(encoding="utf-8")
    workflow_facade_imports = _imports_for(PROJECT_ROOT / "rs_core" / "workflow" / "facades.py")
    milvus_rag_imports = _imports_for(PROJECT_ROOT / "scripts" / "recall" / "build_milvus_rag_index.py")
    assert "rs_core.data.adapters" in workflow_facade_imports
    assert "MilvusAdapter" in workflow_facade_text
    assert "rs_core.data.adapters" in milvus_rag_imports
    assert "rs_core.agent.rag" in milvus_rag_imports
    assert "rs_core.recsys.rag.milvus_index" not in milvus_rag_imports


def test_new_business_modules_do_not_import_infrastructure_sdks_directly() -> None:
    forbidden = {"redis", "psycopg", "minio"}
    for module_root in ["online", "agent", "offline"]:
        for path in (PROJECT_ROOT / "rs_core" / module_root).rglob("*.py"):
            imports = _imports_for(path)
            assert imports.isdisjoint(forbidden), f"{path} imports {imports & forbidden}"


def test_data_asset_readiness_is_secret_safe() -> None:
    from rs_core.data.adapters import RedisAdapter
    from rs_core.data.engine import DataAssetEngine

    engine = DataAssetEngine(redis_adapter=RedisAdapter(config_ref="redis://secret-token@example.test/0", enabled=True))

    readiness = engine.readiness()
    rendered = json.dumps(readiness)

    assert readiness["storage"]["redis"]["status"] == "degraded"
    assert readiness["storage"]["redis"]["config_ref"] == "configured"
    assert "secret-token" not in rendered
    assert "example.test" not in rendered


def test_online_does_not_import_agent_or_rag_internal_modules() -> None:
    forbidden_prefixes = (
        "rs_core.agent",
        "rs_core.agent",
        "rs_core.agent_runtime",
        "rs_core.recsys.rag",
        "rs_core.agent.rag.semantic_description",
    )
    for path in (PROJECT_ROOT / "rs_core" / "online").rglob("*.py"):
        imports = _imports_for(path)
        assert not _matching_imports(imports, forbidden_prefixes), path


def test_agent_uses_online_client_boundary_only() -> None:
    for path in (PROJECT_ROOT / "rs_core" / "agent").rglob("*.py"):
        imports = _imports_for(path)
        if path.name == "__init__.py" and path.parent.name == "clients":
            continue
        assert "rs_core.online.engine" not in imports
        assert "rs_core.online.recall" not in imports
        assert "rs_core.online.ranking" not in imports


def test_offline_does_not_import_service_routes() -> None:
    forbidden_prefixes = ("rs_core.serving.api",)
    for path in (PROJECT_ROOT / "rs_core" / "offline").rglob("*.py"):
        imports = _imports_for(path)
        assert not _matching_imports(imports, forbidden_prefixes), path


def test_display_animation_and_simulation_ownership_is_documented() -> None:
    project_structure = (PROJECT_ROOT / "dic" / "PROJECT_STRUCTURE.md").read_text(encoding="utf-8")
    assert "rs_core/display/" in project_structure
    assert "display payload contract" in project_structure
    assert "纯 UI animation 属于 frontend" in project_structure
    assert "Agent 行为回放属于 `rs_core/agent/simulation`" in project_structure
    assert "离线可视化属于 offline report" in project_structure
    assert not (PROJECT_ROOT / "rs_core" / "animation").exists()
    assert not (PROJECT_ROOT / "rs_core" / "artifacts" / "__init__.py").exists()
    assert (PROJECT_ROOT / "rs_core" / "agent" / "simulation" / "__init__.py").exists()
    assert (PROJECT_ROOT / "rs_core" / "offline" / "simulation" / "__init__.py").exists()


def test_worker_entrypoints_are_engine_backed_and_lightweight(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    from rs_core.data.runtime.worker import main as data_main
    from rs_core.offline.runtime.worker import main as offline_main

    assert data_main(["health"]) == 0
    assert "DataAssetEngine" in capsys.readouterr().out

    assert data_main(["readiness"]) == 0
    output = capsys.readouterr().out
    assert "DataAssetEngine" in output
    assert "local_file" in output

    assert data_main(["import-dataset", "smoke-dataset", "data/smoke.jsonl", "--split", "train", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "smoke-dataset" in output
    assert "dry_run" in output

    assert data_main(["build-window-dataset", "smoke-window", "data/smoke.jsonl", "--window", "recent-3m", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "smoke-window" in output
    assert "recent-3m" in output
    assert "dry_run" in output

    assert data_main(["build-candidate-pool", "smoke-pool", "item-1", "item-1", "item-2"]) == 0
    output = capsys.readouterr().out
    assert "smoke-pool" in output
    assert "item-2" in output

    knowledge_path = tmp_path / "chunks.jsonl"
    knowledge_path.write_text('{"chunk_id":"c1","item_id":"item-1","text":"hello"}\n', encoding="utf-8")
    assert data_main(["build-knowledge-chunks", str(knowledge_path), "--limit", "1"]) == 0
    output = capsys.readouterr().out
    assert "c1" in output
    assert "hello" in output

    assert data_main(["register-artifact", "smoke-artifact", "outputs/smoke.json", "--kind", "report"]) == 0
    output = capsys.readouterr().out
    assert "smoke-artifact" in output
    assert "report" in output

    assert offline_main(["start-training-job", "smoke-train", "--model-family", "stub"]) == 0
    output = capsys.readouterr().out
    assert "smoke-train" in output
    assert "dry_run_ready" in output

    assert offline_main(["register-model-artifact", "smoke-model", "models/smoke", "--model-family", "stub"]) == 0
    output = capsys.readouterr().out
    assert "smoke-model" in output
    assert "stub" in output

    assert offline_main(["run-evaluation-smoke", "--eval-id", "smoke-test"]) == 0
    output = capsys.readouterr().out
    assert "smoke-test" in output
    assert "smoke_passed" in output

    assert offline_main(["run-experiment-smoke", "--experiment-id", "experiment-smoke"]) == 0
    output = capsys.readouterr().out
    assert "experiment-smoke" in output
    assert "smoke_planned" in output

    assert offline_main(["run-simulation-smoke", "--simulation-id", "simulation-smoke", "--sample-count", "1"]) == 0
    output = capsys.readouterr().out
    assert "simulation-smoke" in output
    assert "offline_only" in output


def test_online_facades_expose_migrated_boundaries() -> None:
    recall_text = (PROJECT_ROOT / "rs_core" / "online" / "recall" / "__init__.py").read_text(encoding="utf-8")
    ranking_text = (PROJECT_ROOT / "rs_core" / "online" / "ranking" / "__init__.py").read_text(encoding="utf-8")
    rag_text = (PROJECT_ROOT / "rs_core" / "agent" / "rag" / "__init__.py").read_text(encoding="utf-8")
    assert "rs_core.online.recall" in recall_text
    assert "rs_core.recsys.recall" not in recall_text
    assert "rs_core.online.ranking" in ranking_text
    assert "rs_core.online.ranking.cold_deepfm" in ranking_text
    assert "rs_core.agent.adapters.rag" in rag_text
    assert "rs_core.agent.rag.semantic_description" in rag_text


def test_serving_runtime_host_routes_through_online_runtime_boundary() -> None:
    service_text = (PROJECT_ROOT / "rs_core" / "serving" / "application" / "recommendation_service.py").read_text(encoding="utf-8")
    online_runtime_text = (PROJECT_ROOT / "rs_core" / "online" / "runtime" / "__init__.py").read_text(encoding="utf-8")
    pool500_text = (PROJECT_ROOT / "rs_core" / "online" / "runtime" / "pool500.py").read_text(encoding="utf-8")
    retired_workflow_facade = PROJECT_ROOT / "rs_core" / "workflow" / "online_recommendation.py"

    assert "build_online_pool500_recommender" in service_text
    assert "rs_core.workflow.online_recommendation" not in service_text
    assert "rs_core.workflow.online_recommendation" not in online_runtime_text
    assert "OnlinePool500Recommender.from_environment" in online_runtime_text
    assert "class OnlinePool500Recommender" in pool500_text
    assert not retired_workflow_facade.exists()


def test_script_wrappers_route_to_new_engines() -> None:
    expected = {
        "scripts/data/engine_cli.py": "rs_core.data.runtime.worker",
        "scripts/artifacts/engine_cli.py": "rs_core.data.runtime.worker",
        "scripts/training/offline_engine_cli.py": "rs_core.offline.runtime.worker",
        "scripts/evaluation/offline_engine_cli.py": "rs_core.offline.runtime.worker",
        "scripts/experiments/engine_cli.py": "rs_core.offline.runtime.worker",
        "scripts/ci/generate_frontend_types.py": "frontend/src/types/index.ts",
    }
    for relative_path, marker in expected.items():
        text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert marker in text


def test_agent_and_offline_runtime_entrypoints_use_canonical_facades() -> None:
    hybrid_environment_imports = _imports_for(PROJECT_ROOT / "rs_core" / "workflow" / "hybrid_environment.py")
    workflow_facade_imports = _imports_for(PROJECT_ROOT / "rs_core" / "workflow" / "facades.py")
    hybrid_demo_imports = _imports_for(PROJECT_ROOT / "rs_core" / "workflow" / "hybrid_demo.py")
    qwen_smoke_imports = _imports_for(PROJECT_ROOT / "scripts" / "training" / "smoke_qwen_training_env.py")
    simulation_eval_imports = _imports_for(PROJECT_ROOT / "scripts" / "evaluation" / "run_simulation_evaluation.py")
    agent_eval_imports = _imports_for(PROJECT_ROOT / "scripts" / "evaluation" / "run_agent_evaluation.py")
    rag_bm25_imports = _imports_for(PROJECT_ROOT / "scripts" / "recall" / "build_rag_bm25_index.py")
    milvus_rag_imports = _imports_for(PROJECT_ROOT / "scripts" / "recall" / "build_milvus_rag_index.py")

    for imports in [hybrid_environment_imports, workflow_facade_imports]:
        assert "rs_core.agent.rag" in imports
        assert "rs_core.recsys.rag" not in imports

    assert {"rs_core.agent.contracts", "rs_core.agent.decision", "rs_core.agent.feedback", "rs_core.agent.inference", "rs_core.agent.rerank"}.issubset(hybrid_demo_imports)
    assert "rs_core.rsagent.decision" not in hybrid_demo_imports
    assert "rs_core.rsagent.feedback_rerank" not in hybrid_demo_imports
    assert "rs_core.rsagent.schema" not in hybrid_demo_imports
    assert "rs_core.rsagent.policy" not in hybrid_demo_imports
    assert "rs_core.rsagent.inference_policy" not in hybrid_demo_imports

    hybrid_demo_text = (PROJECT_ROOT / "rs_core" / "workflow" / "hybrid_demo.py").read_text(encoding="utf-8")
    assert "from rs_core.agent.model_clients import QwenLocalClient" in hybrid_demo_text
    assert "from rs_core.agent.model_clients.qwen_client import QwenLocalClient" not in hybrid_demo_text

    assert "rs_core.offline.training" in qwen_smoke_imports
    assert "rs_core.offline.training.config" not in qwen_smoke_imports
    assert "rs_core.offline.training.reward_adapter" not in qwen_smoke_imports

    for imports in [simulation_eval_imports, agent_eval_imports]:
        assert "rs_core.offline.simulation" in imports
        assert "rs_core.simulation" not in imports

    for imports in [rag_bm25_imports, milvus_rag_imports]:
        assert "rs_core.agent.rag" in imports
        assert not _matching_imports(imports, ("rs_core.recsys.rag",))


def test_test_directory_module_layers_exist() -> None:
    for directory in ["data", "offline", "online", "agent", "services", "contracts"]:
        assert (PROJECT_ROOT / "tests" / directory).is_dir()


def test_deploy_service_entrypoints_exist() -> None:
    expected_paths = [
        ".dockerignore",
        "deploy/docker/frontend.Dockerfile",
        "deploy/docker/online_service.Dockerfile",
        "deploy/docker/agent_service.Dockerfile",
        "deploy/docker/data_worker.Dockerfile",
        "deploy/docker/offline_worker.Dockerfile",
        "deploy/docker-compose.yml",
        "deploy/nginx/nginx.conf",
        "scripts/ci/gateway_smoke.py",
        "scripts/ci/run_gateway_smoke.py",
        "scripts/ci/run_migration_hardening_checks.py",
        "scripts/ci/generate_service_openapi_snapshots.py",
        "dic/architecture/RS_AGENT_ONLINE_SERVICE_OPENAPI_SNAPSHOT.json",
        "dic/architecture/RS_AGENT_AGENT_SERVICE_OPENAPI_SNAPSHOT.json",
    ]

    missing = [path for path in expected_paths if not (PROJECT_ROOT / path).exists()]
    assert missing == []

    compose = (PROJECT_ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "frontend:" in compose
    assert "online_service:" in compose
    assert "agent_service:" in compose
    assert "data_worker:" in compose
    assert "offline_worker:" in compose
    assert "postgres:" not in compose
    assert "mysql:" in compose
    assert "redis:" in compose
    assert "minio:" in compose
    assert "milvus-standalone:" in compose
    assert "milvus-etcd:" in compose
    assert "milvus-minio:" in compose
    assert "qdrant:" not in compose.lower()
    assert "elasticsearch:" in compose
    assert "RS_ELASTICSEARCH_URI" in compose
    assert "RS_ELASTICSEARCH_INDEX" in compose

    local_compose = (PROJECT_ROOT / "deploy" / "local" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "elasticsearch:" in local_compose
    assert "../../db/elasticsearch" in local_compose
    assert "RS_ELASTICSEARCH_URI" in local_compose

    nginx_conf = (PROJECT_ROOT / "deploy" / "nginx" / "nginx.conf").read_text(encoding="utf-8")
    for route in [
        "/api/recommend",
        "/api/recall",
        "/api/rank",
        "/api/chat",
        "/api/session/",
        "/api/feedback",
        "/api/rag/",
        "/api/health/online",
        "/api/health/agent",
    ]:
        assert route in nginx_conf


def test_service_openapi_snapshots_are_stable() -> None:
    from scripts.ci.generate_service_openapi_snapshots import SNAPSHOTS, snapshot_payloads

    payloads = snapshot_payloads()
    for service_name, relative_path in SNAPSHOTS.items():
        snapshot = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert snapshot == payloads[service_name]
        parsed = json.loads(snapshot)
        assert parsed["openapi"].startswith("3.")
        assert parsed["paths"]

    online_paths = set(json.loads((PROJECT_ROOT / SNAPSHOTS["online"]).read_text(encoding="utf-8"))["paths"])
    agent_paths = set(json.loads((PROJECT_ROOT / SNAPSHOTS["agent"]).read_text(encoding="utf-8"))["paths"])
    assert online_paths == {"/health", "/ready", "/recommend", "/recall", "/rank"}
    assert agent_paths == {"/health", "/ready", "/session/start", "/chat", "/chat/stream", "/feedback", "/rag/query", "/session/end", "/session/{session_id}"}


def test_service_public_contracts_do_not_expose_internal_fields() -> None:
    from scripts.ci.generate_service_openapi_snapshots import SNAPSHOTS

    for relative_path in SNAPSHOTS.values():
        snapshot_text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8").lower()
        leaked_markers = sorted(marker for marker in PUBLIC_API_FORBIDDEN_FIELD_MARKERS if marker in snapshot_text)
        assert leaked_markers == []


def test_frontend_clients_use_public_gateway_contracts_only() -> None:
    shared = (PROJECT_ROOT / "frontend" / "src" / "api" / "shared.ts").read_text(encoding="utf-8")
    online_client = (PROJECT_ROOT / "frontend" / "src" / "api" / "onlineClient.ts").read_text(encoding="utf-8")
    agent_client = (PROJECT_ROOT / "frontend" / "src" / "api" / "agentClient.ts").read_text(encoding="utf-8")
    session_client = (PROJECT_ROOT / "frontend" / "src" / "api" / "sessionClient.ts").read_text(encoding="utf-8")
    demo_client = (PROJECT_ROOT / "frontend" / "src" / "api" / "demoClient.ts").read_text(encoding="utf-8")
    frontend_types = (PROJECT_ROOT / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")

    assert "DEFAULT_API_BASE_URL = '/api'" in shared
    assert "'/recommend'" in online_client
    assert "'/recall'" in online_client
    assert "'/rank'" in online_client
    assert "'/feed/refresh'" not in online_client
    assert "'/feed/refresh'" not in agent_client
    assert "'/session/start'" in agent_client
    assert "'/chat'" in agent_client
    assert "'/feedback'" in agent_client
    assert "'/session/end'" in agent_client
    assert "./agentClient" in session_client
    assert "'/demo/e2e'" in demo_client
    assert "'/simulation/scene'" in demo_client
    assert "'/simulation/batch'" in demo_client
    for marker in ["RecommendFromSequenceRequest", "RecallRequest", "RankRequest", "RagQueryRequest"]:
        assert marker in frontend_types
    leaked_markers = sorted(marker for marker in PUBLIC_API_FORBIDDEN_FIELD_MARKERS if marker in frontend_types.lower())
    assert leaked_markers == []


def test_docker_context_and_gateway_smoke_are_documented() -> None:
    dockerignore = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8")
    for ignored in [".venv/", "data/", "outputs/", ".ruff_cache/", "__pycache__/", "frontend/node_modules/", "db/elasticsearch/"]:
        assert ignored in dockerignore

    deploy_readme = (PROJECT_ROOT / "deploy" / "README.md").read_text(encoding="utf-8")
    for profile in ["frontend", "online", "agent", "gateway", "worker", "infra"]:
        assert f"`{profile}`" in deploy_readme
    assert "scripts/ci/gateway_smoke.py" in deploy_readme
    assert "scripts/ci/run_gateway_smoke.py" in deploy_readme
    assert "scripts/ci/run_migration_hardening_checks.py" in deploy_readme
    assert "默认不启动" in deploy_readme
    assert "不会默认启动 infra" in deploy_readme
    assert "12GB 可承受、14GB 上限" in deploy_readme
    assert "full-data import" in deploy_readme
    assert "自动执行 `down`" in deploy_readme

    gateway_smoke = (PROJECT_ROOT / "scripts" / "ci" / "gateway_smoke.py").read_text(encoding="utf-8")
    for route in [
        "/api/recommend",
        "/api/recall",
        "/api/rank",
        "/api/session/start",
        "/api/chat",
        "/api/feedback",
        "/api/rag/query",
    ]:
        assert route in gateway_smoke


def _public_route_table(routes: list[object]) -> set[tuple[str, tuple[str, ...]]]:
    return {
        (route.path, tuple(sorted(route.methods - {"HEAD", "OPTIONS"})))
        for route in routes
        if getattr(route, "include_in_schema", False)
    }


def _imports_for(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _legacy_imports_for(path: Path) -> set[str]:
    return {
        module
        for module in _imports_for(path)
        if any(module == legacy_root or module.startswith(f"{legacy_root}.") for legacy_root in LEGACY_IMPORT_ROOTS)
    }


def _matching_imports(imports: set[str], prefixes: tuple[str, ...]) -> set[str]:
    return {module for module in imports if any(module == prefix or module.startswith(f"{prefix}.") for prefix in prefixes)}
