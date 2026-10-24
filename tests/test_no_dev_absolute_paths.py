"""守卫：测试代码不得硬编码开发机绝对路径。

背景（2026-10 CI 收集期中断的根因）：``tests/test_uniquant_production_architecture_gates.py``
曾把 CNMM 兄弟仓的绝对路径插入 ``sys.path`` 并 ``from order_state_machine import ...``。
开发机上该目录存在 → 本地全绿；CI 上不存在 → ``ModuleNotFoundError`` → pytest 报
``Interrupted: 1 error during collection`` → **整个测试作业零用例执行（exit code 2）**，
且被 ruff 失败掩盖了很长时间。这类缺陷"本地绿、CI 红"，定位成本极高，故以静态守卫锁死。

范围：``tests/`` 下 Python 源码中的**字符串字面量**（AST 级——注释不会误伤；
文档字符串本身即字符串字面量，同样受检）。``scripts/`` **不在范围内**——研究脚本
允许保留"环境变量兜底 + 开发机默认值"的写法。``tests/archive/``（gitignored、不收集）跳过。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, List, Tuple

TESTS_ROOT = Path(__file__).resolve().parent
SRC_ROOT = TESTS_ROOT.parent / "src" / "uniquant"

# 绝对家目录路径：POSIX `/home/<user>/…`、`/Users/<user>/…`；Windows `C:\Users\<user>\…`
_HOME_ABSOLUTE_RE = re.compile(r"^(?:/(?:home|Users)|[A-Za-z]:\\{1,2}Users)[/\\][^/\\]+[/\\]")

_SKIP_DIR_NAMES = frozenset({"__pycache__", "archive"})


def _iter_test_sources() -> List[Path]:
    """Yield every Python source under ``tests/`` that pytest actually collects."""
    return [
        path
        for path in sorted(TESTS_ROOT.rglob("*.py"))
        if not (_SKIP_DIR_NAMES & set(path.parts))
    ]


def _iter_src_sources() -> List[Path]:
    """Yield every Python source under ``src/uniquant/``."""
    return [
        path
        for path in sorted(SRC_ROOT.rglob("*.py"))
        if not (_SKIP_DIR_NAMES & set(path.parts))
    ]


def _absolute_home_literals(source: str, filename: str) -> List[Tuple[int, str]]:
    """Return ``(lineno, literal)`` for every hard-coded absolute home path literal."""
    tree = ast.parse(source, filename=filename)
    hits: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _HOME_ABSOLUTE_RE.match(node.value):
                hits.append((node.lineno, node.value))
    return hits


def _regression_sample() -> str:
    """A minimal reproduction of the pattern that broke CI (built by concatenation so
    that this guard does not flag its own source)."""
    dev_path = "/" + "home/" + "someone/project/scratch"
    return f'import sys\nsys.path.insert(0, "{dev_path}")\n'


def test_guard_detects_the_known_regression_pattern() -> None:
    """Positive control: the guard must actually catch the pattern it exists for."""
    assert _absolute_home_literals(_regression_sample(), "<sample>")


def test_no_hardcoded_dev_absolute_paths() -> None:
    """No test module may bake in a developer-machine absolute home path."""
    offenders: Dict[Path, List[Tuple[int, str]]] = {}
    for path in _iter_test_sources():
        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):  # pragma: no cover - defensive
            continue
        hits = _absolute_home_literals(source, str(path))
        if hits:
            offenders[path.relative_to(TESTS_ROOT)] = hits

    assert not offenders, (
        "测试代码出现硬编码的开发机绝对路径；这类写法在 CI 上会以收集期 "
        "ModuleNotFoundError 中断整个测试作业。请改为基于 `Path(__file__)` 的仓库内"
        "相对定位，或 `Path.home()` / 环境变量兜底。违规处：\n"
        + "\n".join(
            f"  {rel}:{line} -> {literal!r}"
            for rel, hits in sorted(offenders.items())
            for line, literal in hits
        )
    )


def test_no_hardcoded_dev_absolute_paths_in_src() -> None:
    """No production module in src/uniquant/ may bake in a developer-machine absolute home path."""
    offenders: Dict[Path, List[Tuple[int, str]]] = {}
    for path in _iter_src_sources():
        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):  # pragma: no cover - defensive
            continue
        hits = _absolute_home_literals(source, str(path))
        if hits:
            offenders[path.relative_to(SRC_ROOT)] = hits

    assert not offenders, (
        "生产代码 (src/uniquant/) 出现硬编码的开发机绝对路径。违规处：\n"
        + "\n".join(
            f"  {rel}:{line} -> {literal!r}"
            for rel, hits in sorted(offenders.items())
            for line, literal in hits
        )
    )
