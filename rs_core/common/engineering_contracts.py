from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from rs_core.common.config import load_config

_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_PERSONAL_POSIX_PATH_PREFIXES = ("/Users/", "/home/")
_ROUTE_REGISTRY_SCHEMA_VERSION = "current_route_registry_v1"
_ROUTE_ALLOWLIST_SCHEMA_VERSION = "engineering_contract_allowlist_v1"
_REQUIRED_ROUTE_KEYS = {
    "current_recall_route",
    "current_ranking_route",
    "current_agent_demo_route",
}
_ALLOWED_ROUTE_STATUSES = {
    "current",
    "provisional_current",
    "candidate",
    "continuation_only",
    "diagnostic_only",
    "historical_unknown",
    "deprecated",
}
_ROUTE_PATH_FIELDS = {
    "authority_refs",
    "config_paths",
    "workflow_paths",
    "script_paths",
    "required_output_paths",
}
_ALLOWLIST_REQUIRED_FIELDS = {"check", "path", "reason", "owner", "created_at", "review_after"}
_POOL500_CONTINUATION_ROUTE = "pool500_recall_continuation_route"
_POOL500_V5_ARTIFACT_GATE_SCHEMA_VERSION = "full_data_pool500_artifact_gate_v5"
_POOL500_V5_ARTIFACT_GATE_WORKFLOW = "rs_core/workflow/full_data_pool500_route_gate.py#full_data_pool500_artifact_gate"
_POOL500_V5_ALLOWED_DECISIONS = {"FULL_POOL500_READY", "DIAGNOSTIC_ONLY_PARTIAL", "STOP"}
_POOL500_FULL_READY_SEMANTICS = "recall_artifact_readiness_only"
_POOL500_SHADOW_MODE = "read_only_shadow_evidence"
_PUBLIC_DISPLAY_FORBIDDEN_FIELDS = {
    "agent_runtime_trace",
    "diagnostics_path",
    "ranking_evidence_path",
    "raw_export_trace_path",
    "trace_ref",
}


@dataclass(frozen=True)
class ContractViolation:
    check: str
    path: str
    message: str


def validate_engineering_contracts(
    root: str | Path,
    config_paths: Iterable[str | Path],
    script_paths: Iterable[str | Path],
    test_paths: Iterable[str | Path] = (),
    route_registry_path: str | Path | None = "configs/governance/current_route_registry.yaml",
    allowlist_path: str | Path | None = "configs/governance/engineering_contract_allowlist.yaml",
    prd_path: str | Path | None = "prd.json",
) -> list[ContractViolation]:
    project_root = Path(root)
    violations: list[ContractViolation] = []
    violations.extend(validate_config_contracts(project_root, config_paths))
    violations.extend(validate_script_entrypoints(project_root, script_paths))
    violations.extend(validate_test_markers(project_root, test_paths))
    if route_registry_path is not None:
        violations.extend(validate_route_registry_contract(project_root, route_registry_path))
    if allowlist_path is not None:
        violations.extend(validate_engineering_allowlist_contract(project_root, allowlist_path))
    if prd_path is not None:
        violations.extend(validate_prd_contract(project_root, prd_path))
    return violations


def validate_config_contracts(
    root: Path,
    config_paths: Iterable[str | Path],
) -> list[ContractViolation]:
    violations: list[ContractViolation] = []
    for raw_path in sorted({Path(path) for path in config_paths}, key=lambda path: path.as_posix()):
        path = _resolve_under_root(root, raw_path)
        display_path = _display_path(root, path)
        if path.parent.name == "configs" and path.name.startswith("_tmp_"):
            violations.append(
                ContractViolation(
                    check="temporary_config_not_tracked",
                    path=display_path,
                    message="临时调参配置不得加入 git；请移出跟踪或改为正式 phase/hybrid_demo 配置。",
                )
            )
        try:
            config = load_config(path)
        except Exception as exc:
            violations.append(
                ContractViolation(
                    check="config_loadable",
                    path=display_path,
                    message=f"配置无法被轻量 loader 读取：{exc}",
                )
            )
            continue
        violations.extend(_path_value_violations(root, display_path, config))
    return violations


def validate_script_entrypoints(
    root: Path,
    script_paths: Iterable[str | Path],
) -> list[ContractViolation]:
    violations: list[ContractViolation] = []
    for raw_path in sorted({Path(path) for path in script_paths}, key=lambda path: path.as_posix()):
        path = _resolve_under_root(root, raw_path)
        display_path = _display_path(root, path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            violations.append(
                ContractViolation(
                    check="script_parseable",
                    path=display_path,
                    message=f"脚本无法解析：{exc}",
                )
            )
            continue
        if not _has_main_guard(tree):
            violations.append(
                ContractViolation(
                    check="script_main_guard",
                    path=display_path,
                    message="Python 入口必须使用 if __name__ == '__main__' 包住执行逻辑。",
                )
            )
    return violations


def validate_test_markers(
    root: Path,
    test_paths: Iterable[str | Path],
) -> list[ContractViolation]:
    violations: list[ContractViolation] = []
    allowed_markers = {"unit", "smoke", "slow", "gpu", "experiment", "serving", "frontend"}
    for raw_path in sorted({Path(path) for path in test_paths}, key=lambda path: path.as_posix()):
        path = _resolve_under_root(root, raw_path)
        display_path = _display_path(root, path)
        try:
            markers = test_markers_for_file(path)
        except SyntaxError as exc:
            violations.append(
                ContractViolation(
                    check="test_parseable",
                    path=display_path,
                    message=f"测试文件无法解析：{exc}",
                )
            )
            continue
        if not markers:
            violations.append(
                ContractViolation(
                    check="test_file_marker_required",
                    path=display_path,
                    message="测试文件必须声明文件级 pytestmark，明确属于 unit/smoke/slow/gpu/experiment/serving/frontend。",
                )
            )
            continue
        unsupported = sorted(set(markers) - allowed_markers)
        if unsupported:
            violations.append(
                ContractViolation(
                    check="test_file_marker_registered",
                    path=display_path,
                    message=f"测试文件使用了未注册 marker：{unsupported}",
                )
            )
    return violations


def validate_route_registry_contract(root: Path, registry_path: str | Path) -> list[ContractViolation]:
    path = _resolve_under_root(root, Path(registry_path))
    display_path = _display_path(root, path)
    if not path.exists():
        return [
            ContractViolation(
                check="route_registry_exists",
                path=display_path,
                message="当前主路 registry 不存在。",
            )
        ]
    try:
        registry = load_config(path)
    except Exception as exc:
        return [
            ContractViolation(
                check="route_registry_loadable",
                path=display_path,
                message=f"当前主路 registry 无法读取：{exc}",
            )
        ]
    violations: list[ContractViolation] = []
    if registry.get("schema_version") != _ROUTE_REGISTRY_SCHEMA_VERSION:
        violations.append(
            ContractViolation(
                check="route_registry_schema_version",
                path=display_path,
                message=f"当前主路 registry schema_version 必须是 {_ROUTE_REGISTRY_SCHEMA_VERSION}。",
            )
        )
    routes = registry.get("routes")
    if not isinstance(routes, dict):
        return [
            *violations,
            ContractViolation(
                check="route_registry_routes",
                path=display_path,
                message="当前主路 registry 必须包含 routes 映射。",
            ),
        ]
    missing_routes = sorted(_REQUIRED_ROUTE_KEYS - set(routes))
    if missing_routes:
        violations.append(
            ContractViolation(
                check="route_registry_required_routes",
                path=display_path,
                message=f"当前主路 registry 缺少必要 route：{missing_routes}",
            )
        )
    for route_name, route in sorted(routes.items()):
        route_path = f"{display_path}:{route_name}"
        if not isinstance(route, dict):
            violations.append(
                ContractViolation(
                    check="route_registry_route_shape",
                    path=route_path,
                    message="route 条目必须是映射。",
                )
            )
            continue
        status = route.get("status")
        if status not in _ALLOWED_ROUTE_STATUSES:
            violations.append(
                ContractViolation(
                    check="route_registry_status",
                    path=route_path,
                    message=f"route status 必须属于 {sorted(_ALLOWED_ROUTE_STATUSES)}，实际为 {status!r}。",
                )
            )
        violations.extend(_route_path_violations(root, route_path, route))
    ranking = routes.get("current_ranking_route")
    if isinstance(ranking, dict):
        ranking_pool500_paths = sorted(path for path in _route_declared_paths(ranking) if "pool500" in path.lower())
        if ranking_pool500_paths:
            violations.append(
                ContractViolation(
                    check="pool500_not_ranking_input",
                    path=display_path,
                    message=f"pool500 recall-only 路径不得作为 current_ranking_route 输入：{ranking_pool500_paths}",
                )
            )
    pool500_continuation = routes.get(_POOL500_CONTINUATION_ROUTE)
    if isinstance(pool500_continuation, dict):
        violations.extend(_pool500_continuation_route_violations(display_path, pool500_continuation))
    return violations


def validate_prd_contract(root: Path, prd_path: str | Path) -> list[ContractViolation]:
    path = _resolve_under_root(root, Path(prd_path))
    display_path = _display_path(root, path)
    if not path.exists():
        return [
            ContractViolation(
                check="prd_exists",
                path=display_path,
                message="PRD JSON 不存在。",
            )
        ]
    try:
        prd = load_config(path)
    except Exception as exc:
        return [
            ContractViolation(
                check="prd_loadable",
                path=display_path,
                message=f"PRD JSON 无法读取：{exc}",
            )
        ]
    violations: list[ContractViolation] = []
    stories = prd.get("stories")
    if not isinstance(stories, list):
        return [
            ContractViolation(
                check="prd_stories",
                path=display_path,
                message="PRD JSON 必须包含 stories 列表。",
            )
        ]
    pool500_stories = [story for story in stories if isinstance(story, dict) and _story_mentions_pool500(story)]
    if not pool500_stories:
        violations.append(
            ContractViolation(
                check="prd_pool500_story_required",
                path=display_path,
                message="PRD JSON 必须显式登记 pool500 read-only shadow evidence story。",
            )
        )
        return violations
    criteria_text = "\n".join(_story_acceptance_text(story) for story in pool500_stories)
    required_phrases = {
        "pool500": "prd_pool500_mentions_pool500",
        "read-only shadow evidence": "prd_pool500_read_only_shadow",
        "no candidate generation": "prd_pool500_no_candidate_generation",
        "no current_ranking_route replacement": "prd_pool500_no_ranking_replacement",
        "FULL_POOL500_READY is recall artifact readiness only": "prd_pool500_full_ready_semantics",
        "internal evidence": "prd_pool500_internal_evidence",
        "public display": "prd_pool500_public_display",
    }
    for phrase, check in required_phrases.items():
        if phrase.lower() not in criteria_text.lower():
            violations.append(
                ContractViolation(
                    check=check,
                    path=display_path,
                    message=f"pool500 PRD acceptanceCriteria 必须包含语义：{phrase}",
                )
            )
    missing_forbidden = sorted(field for field in _PUBLIC_DISPLAY_FORBIDDEN_FIELDS if field not in criteria_text)
    if missing_forbidden:
        violations.append(
            ContractViolation(
                check="prd_pool500_public_display_forbidden_fields",
                path=display_path,
                message=f"pool500 PRD 必须列出 public display 禁止字段：{missing_forbidden}",
            )
        )
    return violations


def validate_engineering_allowlist_contract(root: Path, allowlist_path: str | Path) -> list[ContractViolation]:
    path = _resolve_under_root(root, Path(allowlist_path))
    display_path = _display_path(root, path)
    if not path.exists():
        return [
            ContractViolation(
                check="engineering_allowlist_exists",
                path=display_path,
                message="工程治理 warning allowlist 不存在。",
            )
        ]
    try:
        allowlist_config = load_config(path)
    except Exception as exc:
        return [
            ContractViolation(
                check="engineering_allowlist_loadable",
                path=display_path,
                message=f"工程治理 warning allowlist 无法读取：{exc}",
            )
        ]
    violations: list[ContractViolation] = []
    if allowlist_config.get("schema_version") != _ROUTE_ALLOWLIST_SCHEMA_VERSION:
        violations.append(
            ContractViolation(
                check="engineering_allowlist_schema_version",
                path=display_path,
                message=f"工程治理 allowlist schema_version 必须是 {_ROUTE_ALLOWLIST_SCHEMA_VERSION}。",
            )
        )
    entries = allowlist_config.get("allowlist")
    if not isinstance(entries, list):
        return [
            *violations,
            ContractViolation(
                check="engineering_allowlist_shape",
                path=display_path,
                message="工程治理 allowlist 必须是列表。",
            ),
        ]
    for index, entry in enumerate(entries):
        entry_path = f"{display_path}:allowlist[{index}]"
        if not isinstance(entry, dict):
            violations.append(
                ContractViolation(
                    check="engineering_allowlist_entry_shape",
                    path=entry_path,
                    message="allowlist 条目必须是映射。",
                )
            )
            continue
        missing_fields = sorted(_ALLOWLIST_REQUIRED_FIELDS - set(entry))
        if missing_fields:
            violations.append(
                ContractViolation(
                    check="engineering_allowlist_required_fields",
                    path=entry_path,
                    message=f"allowlist 条目缺少字段：{missing_fields}",
                )
            )
        allowed_path = entry.get("path")
        if isinstance(allowed_path, str):
            if _is_personal_absolute_path(allowed_path) or Path(allowed_path).is_absolute():
                violations.append(
                    ContractViolation(
                        check="engineering_allowlist_relative_path",
                        path=entry_path,
                        message=f"allowlist path 必须是 repo-relative：{allowed_path}",
                    )
                )
            elif not (root / allowed_path).exists():
                violations.append(
                    ContractViolation(
                        check="engineering_allowlist_path_exists",
                        path=entry_path,
                        message=f"allowlist path 不存在：{allowed_path}",
                    )
                )
    return violations


def test_markers_for_file(path: str | Path) -> set[str]:
    test_path = Path(path)
    tree = ast.parse(test_path.read_text(encoding="utf-8"), filename=str(test_path))
    return _file_level_pytest_markers(tree)


def select_test_paths_by_markers(
    root: Path,
    test_paths: Iterable[str | Path],
    selected_markers: set[str],
) -> list[str]:
    selected = []
    for raw_path in sorted({Path(path) for path in test_paths}, key=lambda path: path.as_posix()):
        path = _resolve_under_root(root, raw_path)
        if test_markers_for_file(path) & selected_markers:
            selected.append(_display_path(root, path))
    return selected


def _pool500_continuation_route_violations(display_path: str, route: dict[str, Any]) -> list[ContractViolation]:
    route_path = f"{display_path}:{_POOL500_CONTINUATION_ROUTE}"
    violations: list[ContractViolation] = []
    expected_decisions = sorted(_POOL500_V5_ALLOWED_DECISIONS)
    if route.get("role") != "recall":
        violations.append(
            ContractViolation(
                check="pool500_continuation_role",
                path=route_path,
                message="pool500 continuation route 必须保持 role=recall。",
            )
        )
    if route.get("status") != "continuation_only":
        violations.append(
            ContractViolation(
                check="pool500_continuation_status",
                path=route_path,
                message="pool500 continuation route 必须保持 status=continuation_only。",
            )
        )
    if route.get("artifact_gate_schema_version") != _POOL500_V5_ARTIFACT_GATE_SCHEMA_VERSION:
        violations.append(
            ContractViolation(
                check="pool500_v5_artifact_gate_schema",
                path=route_path,
                message=f"pool500 continuation route 必须使用 {_POOL500_V5_ARTIFACT_GATE_SCHEMA_VERSION}。",
            )
        )
    if route.get("artifact_gate_workflow") != _POOL500_V5_ARTIFACT_GATE_WORKFLOW:
        violations.append(
            ContractViolation(
                check="pool500_v5_artifact_gate_workflow",
                path=route_path,
                message=f"pool500 continuation route 必须登记 v5 artifact gate workflow：{_POOL500_V5_ARTIFACT_GATE_WORKFLOW}。",
            )
        )
    allowed_decisions = route.get("allowed_decisions", [])
    if not isinstance(allowed_decisions, list) or sorted(allowed_decisions) != expected_decisions:
        violations.append(
            ContractViolation(
                check="pool500_v5_allowed_decisions",
                path=route_path,
                message=f"pool500 continuation route 的 allowed_decisions 必须精确为 {expected_decisions}。",
            )
        )
    if route.get("candidate_generation_allowed") is not False:
        violations.append(
            ContractViolation(
                check="pool500_candidate_generation_not_allowed",
                path=route_path,
                message="pool500 continuation route 不得授权候选生成。",
            )
        )
    if route.get("ranking_input_replacement_allowed") is not False:
        violations.append(
            ContractViolation(
                check="pool500_ranking_input_replacement_not_allowed",
                path=route_path,
                message="pool500 continuation route 不得授权替换 ranking input。",
            )
        )
    if route.get("shadow_mode") != _POOL500_SHADOW_MODE:
        violations.append(
            ContractViolation(
                check="pool500_shadow_mode",
                path=route_path,
                message=f"pool500 continuation route 必须声明 shadow_mode={_POOL500_SHADOW_MODE}。",
            )
        )
    if route.get("full_pool500_ready_semantics") != _POOL500_FULL_READY_SEMANTICS:
        violations.append(
            ContractViolation(
                check="pool500_full_ready_semantics",
                path=route_path,
                message=f"FULL_POOL500_READY 只能表示 {_POOL500_FULL_READY_SEMANTICS}。",
            )
        )
    public_display_forbidden_fields = route.get("public_display_forbidden_fields")
    if not isinstance(public_display_forbidden_fields, list) or set(public_display_forbidden_fields) != _PUBLIC_DISPLAY_FORBIDDEN_FIELDS:
        violations.append(
            ContractViolation(
                check="pool500_public_display_forbidden_fields",
                path=route_path,
                message=f"pool500 public display 必须禁止内部证据字段：{sorted(_PUBLIC_DISPLAY_FORBIDDEN_FIELDS)}。",
            )
        )
    workflow_paths = route.get("workflow_paths", [])
    if not isinstance(workflow_paths, list) or _POOL500_V5_ARTIFACT_GATE_WORKFLOW not in workflow_paths:
        violations.append(
            ContractViolation(
                check="pool500_v5_workflow_path_registered",
                path=route_path,
                message=f"pool500 continuation route 必须在 workflow_paths 登记 {_POOL500_V5_ARTIFACT_GATE_WORKFLOW}。",
            )
        )
    required_output_paths = route.get("required_output_paths", [])
    if isinstance(required_output_paths, list) and any(
        isinstance(path, str) and "dry_run_verify_worker/manifest.json" in path for path in required_output_paths
    ):
        violations.append(
            ContractViolation(
                check="pool500_dry_run_manifest_not_required_output",
                path=route_path,
                message="pool500 continuation route 不得把 contract-only dry-run verifier manifest 作为 full-ready required_output_path。",
            )
        )
    return violations


def _story_mentions_pool500(story: dict[str, Any]) -> bool:
    searchable = f"{story.get('id', '')}\n{story.get('title', '')}\n{_story_acceptance_text(story)}"
    return "pool500" in searchable.lower()


def _story_acceptance_text(story: dict[str, Any]) -> str:
    criteria = story.get("acceptanceCriteria", [])
    if not isinstance(criteria, list):
        return ""
    return "\n".join(criterion for criterion in criteria if isinstance(criterion, str))


def _route_path_violations(root: Path, route_path: str, route: dict[str, Any]) -> list[ContractViolation]:
    violations: list[ContractViolation] = []
    for field in sorted(_ROUTE_PATH_FIELDS):
        raw_paths = route.get(field, [])
        if raw_paths is None:
            raw_paths = []
        if not isinstance(raw_paths, list):
            violations.append(
                ContractViolation(
                    check="route_registry_path_list",
                    path=route_path,
                    message=f"{field} 必须是路径列表。",
                )
            )
            continue
        for raw_path in raw_paths:
            if not isinstance(raw_path, str) or not raw_path:
                violations.append(
                    ContractViolation(
                        check="route_registry_path_value",
                        path=route_path,
                        message=f"{field} 中的路径必须是非空字符串。",
                    )
                )
                continue
            if "#" in raw_path:
                file_part, _anchor = raw_path.split("#", 1)
            else:
                file_part = raw_path
            if _is_personal_absolute_path(file_part) or Path(file_part).is_absolute():
                violations.append(
                    ContractViolation(
                        check="route_registry_relative_path",
                        path=route_path,
                        message=f"registry 路径必须是 repo-relative：{raw_path}",
                    )
                )
                continue
            if file_part.startswith("old_dic/"):
                violations.append(
                    ContractViolation(
                        check="route_registry_no_old_dic_current",
                        path=route_path,
                        message=f"current route 不得引用 old_dic 作为权威路径：{raw_path}",
                    )
                )
                continue
            if file_part and not (root / file_part).exists():
                violations.append(
                    ContractViolation(
                        check="route_registry_path_exists",
                        path=route_path,
                        message=f"registry 引用路径不存在：{raw_path}",
                    )
                )
    return violations


def _route_declared_paths(route: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for field in _ROUTE_PATH_FIELDS:
        raw_paths = route.get(field, [])
        if isinstance(raw_paths, list):
            paths.extend(path for path in raw_paths if isinstance(path, str))
    return paths


def _path_value_violations(root: Path, display_path: str, value: Any, prefix: str = "") -> list[ContractViolation]:
    violations: list[ContractViolation] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_key = f"{prefix}.{key}" if prefix else str(key)
            violations.extend(_path_value_violations(root, display_path, child, child_key))
        return violations
    if isinstance(value, list):
        for index, child in enumerate(value):
            violations.extend(_path_value_violations(root, display_path, child, f"{prefix}[{index}]"))
        return violations
    if not isinstance(value, str) or not _looks_like_path_key(prefix):
        return violations
    if _is_personal_absolute_path(value):
        violations.append(
            ContractViolation(
                check="no_personal_absolute_paths",
                path=display_path,
                message=f"字段 {prefix} 使用了个人机器绝对路径：{value}",
            )
        )
    return violations


def _looks_like_path_key(key: str) -> bool:
    leaf = key.rsplit(".", 1)[-1]
    return leaf.endswith(("_path", "_dir")) or leaf in {"path", "dir"}


def _is_personal_absolute_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return bool(_WINDOWS_ABSOLUTE_PATH.match(value)) or normalized.startswith(_PERSONAL_POSIX_PATH_PREFIXES)


def _has_main_guard(tree: ast.AST) -> bool:
    return any(isinstance(node, ast.If) and _is_main_guard_test(node.test) for node in ast.walk(tree))


def _file_level_pytest_markers(tree: ast.Module) -> set[str]:
    markers: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets):
                markers.update(_pytest_marker_names(node.value))
    return markers


def _pytest_marker_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute):
        if isinstance(node.value.value, ast.Name) and node.value.value.id == "pytest" and node.value.attr == "mark":
            return {node.attr}
    if isinstance(node, ast.Call):
        return _pytest_marker_names(node.func)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        markers: set[str] = set()
        for element in node.elts:
            markers.update(_pytest_marker_names(element))
        return markers
    return set()


def _is_main_guard_test(node: ast.AST) -> bool:
    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1:
        return False
    if not isinstance(node.ops[0], ast.Eq):
        return False
    left = node.left
    right = node.comparators[0]
    return (
        isinstance(left, ast.Name)
        and left.id == "__name__"
        and isinstance(right, ast.Constant)
        and right.value == "__main__"
    ) or (
        isinstance(right, ast.Name)
        and right.id == "__name__"
        and isinstance(left, ast.Constant)
        and left.value == "__main__"
    )


def _resolve_under_root(root: Path, path: Path) -> Path:
    if path.is_absolute():
        return path
    return root / path


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
