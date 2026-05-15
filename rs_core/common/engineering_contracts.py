from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from rs_core.common.config import load_config

_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_PERSONAL_POSIX_PATH_PREFIXES = ("/Users/", "/home/")


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
) -> list[ContractViolation]:
    project_root = Path(root)
    violations: list[ContractViolation] = []
    violations.extend(validate_config_contracts(project_root, config_paths))
    violations.extend(validate_script_entrypoints(project_root, script_paths))
    violations.extend(validate_test_markers(project_root, test_paths))
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
                    message="scripts 入口必须使用 if __name__ == '__main__' 包住执行逻辑。",
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
