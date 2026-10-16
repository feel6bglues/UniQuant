"""守卫：测试模块不得在**导入期**改写进程级环境变量。

背景（2026-10 CI 修复期间实测发现）：``tests/test_import_financial.py`` 曾在模块顶层执行
``os.environ["HOME"] = "/tmp"``。pytest 按文件名顺序导入所有测试模块，且在同一进程内共享
``os.environ`` —— 于是**其后导入的任何模块**看到的 ``HOME`` 都是 ``/tmp``。

后果（实测）：``tests/test_tdx_parser_gbbq_mapping.py`` 用 ``Path.home()`` 兜底定位本机通达信
gbbq 真文件；``HOME`` 被改写后解析到 ``/tmp/...`` → ``skipif`` **静默跳过 5 个真实数据用例**
（本机应 2 skip，实测变 7 skip）。这类"导入期全局状态"缺陷不报错、只静默改变其它用例的行为，
与 CI 收集期崩溃同属"全局状态 + 导入顺序"一族，故以静态守卫锁死。

范围：``tests/`` 下**非 conftest** 的 Python 源码**顶层**语句（AST 级）。
``conftest.py`` 排除 —— 在 conftest 里集中设置环境变量是 pytest 的正当用法，且在收集前统一
生效（对所有用例一致，不产生顺序依赖）。``scripts/`` 不在范围内。

允许的写法：``os.environ.setdefault(...)`` / ``os.environ.get(...)``（不覆盖既有值）；
以及在**函数/夹具内**用 ``monkeypatch.setenv``（自动还原）。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, List, Tuple

TESTS_ROOT = Path(__file__).resolve().parent

_SKIP_DIR_NAMES = frozenset({"__pycache__", "archive"})
_SKIP_FILE_NAMES = frozenset({"conftest.py"})

# 模块级调用型环境改写：os.environ.update(...) / os.putenv(...)
_MUTATING_CALLS = frozenset({"update", "putenv"})


def _iter_test_sources() -> List[Path]:
    """Every Python source under ``tests/`` that pytest imports, minus conftest."""
    return [
        path
        for path in sorted(TESTS_ROOT.rglob("*.py"))
        if not (_SKIP_DIR_NAMES & set(path.parts)) and path.name not in _SKIP_FILE_NAMES
    ]


def _is_os_environ_subscript(node: ast.AST) -> bool:
    """True for an ``os.environ[...]`` subscript expression node."""
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "environ"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "os"
    )


def _is_environ_update_call(node: ast.AST) -> bool:
    """True for a module-level ``os.environ.update(...)`` / ``os.putenv(...)`` call."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return False
    if node.func.attr not in _MUTATING_CALLS:
        return False
    base = node.func.value
    if isinstance(base, ast.Attribute) and base.attr == "environ":
        return True
    return isinstance(base, ast.Name) and base.id == "os"


def _module_level_env_mutations(source: str, filename: str) -> List[Tuple[str, int]]:
    """Return ``(kind, lineno)`` for every import-time environment mutation."""
    hits: List[Tuple[str, int]] = []
    for node in ast.parse(source, filename=filename).body:  # top level only
        targets: List[ast.AST] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AugAssign):
            targets = [node.target]
        if any(_is_os_environ_subscript(target) for target in targets):
            hits.append(("assign", node.lineno))
        if isinstance(node, ast.Expr) and _is_environ_update_call(node.value):
            hits.append(("call", node.lineno))
    return hits


def _regression_sample() -> str:
    """The exact pattern that silently disabled 5 real-data tests (built so this
    guard does not flag its own source)."""
    env_key = "HO" + "ME"
    return f'import os\n\nos.environ["{env_key}"] = "/tmp"\n'


def test_guard_detects_import_time_env_mutation() -> None:
    """Positive control: the guard must actually catch the pattern it exists for."""
    assert _module_level_env_mutations(_regression_sample(), "<sample>")


def test_no_import_time_env_mutation() -> None:
    """No test module may mutate the process environment at import time."""
    offenders: Dict[Path, List[Tuple[str, int]]] = {}
    for path in _iter_test_sources():
        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):  # pragma: no cover - defensive
            continue
        hits = _module_level_env_mutations(source, str(path))
        if hits:
            offenders[path.relative_to(TESTS_ROOT)] = hits

    assert not offenders, (
        "测试模块在导入期改写了进程级环境变量：pytest 在同一进程内顺序导入所有模块，"
        "该改写会静默改变后续模块的行为（实测曾导致 5 个真实数据用例被静默跳过）。"
        "请改为在夹具内 `monkeypatch.setenv(...)`（自动还原），或在 conftest 中集中设置。"
        "违规处：\n"
        + "\n".join(
            f"  {rel}:{line} -> {kind}"
            for rel, hits in sorted(offenders.items())
            for kind, line in hits
        )
    )
