"""守卫：日志调用不得出现"格式占位符数量 ≠ 参数数量"。

背景（2026-10 第七轮实测发现，且**只在 CI 解释器上暴露**）：``services/validation_service.py``
的 6 处 ``logger.warning("… calculated={}, expected={}", a, b)`` 把 **``{}`` 风格** 当成了
``%`` 风格参数。stdlib ``logging`` 用 ``msg % args`` 惰性格式化，于是：

1. **真实生产后果（与解释器无关）**：告警本该打印的"哪一项校验失败"被替换成 stderr 上的
   ``--- Logging error ---`` 回溯；更糟的是，若 handler 让格式化异常向上冒泡（结构化/捕获型
   handler 即如此），异常会被方法自身的 ``except (ValueError, KeyError, TypeError)`` 吞掉并走
   通用错误分支 → **``results`` 变成空字典**，恰好在校验失败时丢失全部逐项诊断。
2. **为何本地绿、CI 红**：开发机 ``.venv`` 与 CI 等价环境的 handler 配置不同，同一份代码在
   两边行为不一致（本机 pytest 捕获 handler 吞掉了格式化异常）。这与前几轮"本地绿、CI 红"
   的收集期中断同属一族：**缺陷一直在，只是被环境掩盖**。

修法：``{}`` → ``%s``（消息文本逐字不变）。本守卫以 AST 静态扫描锁死该类，防止复发。

范围：``src/uniquant/`` 下全部 Python 源码（生产代码；``scripts/`` 不在范围内）。判定规则：
取日志方法（``debug/info/warning/warn/error/critical/exception``）调用的**第一个位置参数**，
若它是字符串**字面量**，则统计其中的 ``%`` 转义符数量并与其余位置参数数量比较，不相等即违规。
非字面量（f-string、变量、``+``/``%`` 预格式化结果）静态不可判，跳过。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "src" / "uniquant"

_SKIP_DIR_NAMES = frozenset({"__pycache__", "archive"})

# 日志级别方法名。故意不含 ``log``：``logger.log(level, msg, *args)`` 的消息在**第 2 个**位置参数。
_LOG_METHODS = frozenset(
    {"debug", "info", "warning", "warn", "error", "critical", "exception"}
)

# 完整 %-格式：%[(name)][flags][width][.precision][length]type
# flags 故意**不含空格**——"50% off" 里的 "% o" 会被误判为八进制转换符，
# 而 "进度 50% of" 这类文本在日志中很常见。
_PERCENT_PLACEHOLDER = re.compile(
    r"%(?:\([^)]*\))?[-#0+]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[hlL]?[diouxXeEfFgGcrsa]"
)


def _iter_sources() -> List[Path]:
    """Every Python source under ``src/uniquant/``."""
    return [
        path
        for path in sorted(SOURCE_ROOT.rglob("*.py"))
        if not (_SKIP_DIR_NAMES & set(path.parts))
    ]


def _looks_like_logger(expr: ast.AST) -> bool:
    """True for receivers that read as a logger (``logger`` / ``self._logger`` / ``LOG``)."""
    if isinstance(expr, ast.Name):
        return "log" in expr.id.lower()
    if isinstance(expr, ast.Attribute):
        return "log" in expr.attr.lower()
    return False


def _logging_format_mismatches(source: str, filename: str) -> List[Tuple[int, str, int, int]]:
    """Return ``(lineno, method, placeholders, args)`` for every mismatched logging call."""
    hits: List[Tuple[int, str, int, int]] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr in _LOG_METHODS):
            continue
        if not _looks_like_logger(func.value) or not node.args:
            continue
        message = node.args[0]
        if not (isinstance(message, ast.Constant) and isinstance(message.value, str)):
            continue
        # ``%%`` 是转义后的字面百分号，不是占位符。
        placeholders = len(_PERCENT_PLACEHOLDER.findall(message.value.replace("%%", "")))
        supplied = len(node.args) - 1
        if placeholders != supplied:
            hits.append((node.lineno, func.attr, placeholders, supplied))
    return hits


def _regression_sample() -> str:
    """The exact shape that shipped in ``validation_service.py`` (assembled by
    concatenation so that this file's own source is not a hard-coded match)."""
    message = "Max drawdown validation failed: calculated=" + "{}" + ", expected=" + "{}"
    return (
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        'logger.warning("' + message + '", calc_value, exp_value)\n'
    )


def _legit_samples() -> List[str]:
    """Shapes that must NOT be flagged (regression-proof against overreach)."""
    return [
        'logger.info("Value %s and %d", name, count)\n',
        'logger.info("Theta %(name)s", {"name": "x"})\n',
        'logger.info("Progress: 50% of universe")\n',
        'logger.info("Done: 100%% complete")\n',
        'logger.info("Elapsed %.2fs", seconds)\n',
        'logger.info("No placeholders, no args")\n',
        'logger.exception("boom", exc_info=True)\n',
        'logger.log(logging.INFO, "msg %s", x)\n',  # message is arg[1] -> out of scope
        'self._logger.warning("Signal %s rejected", sym)\n',
    ]


def test_guard_detects_the_known_regression_shape() -> None:
    """Positive control: the guard must actually catch the pattern it exists for."""
    hits = _logging_format_mismatches(_regression_sample(), "<sample>")
    assert hits, "guard failed to detect the {}:-as-%-args regression"
    assert hits[0][2:] == (0, 2), f"unexpected placeholder/arg counts: {hits}"


def test_guard_ignores_legitimate_logging_shapes() -> None:
    """Negative control: correct calls (``%%``, ``%.2f``, mapping keys, lone ``%``) pass."""
    for sample in _legit_samples():
        assert _logging_format_mismatches(sample, "<sample>") == [], sample


def test_no_logging_format_mismatch() -> None:
    """No production logging call may declare a different arity than it supplies."""
    offenders: Dict[Path, List[Tuple[int, str, int, int]]] = {}
    for path in _iter_sources():
        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):  # pragma: no cover - defensive
            continue
        hits = _logging_format_mismatches(source, str(path))
        if hits:
            offenders[path.relative_to(REPO_ROOT)] = hits

    assert not offenders, (
        "日志调用的格式占位符数量与参数数量不一致：stdlib logging 做 `msg % args`，数量不匹配会抛 "
        "TypeError；轻则告警丢失、stderr 打出 '--- Logging error ---'，重则被方法自身的 except 吞掉并"
        "丢失逐项诊断（实测曾使校验失败路径返回空 results）。请改用 `%s` 并保证数量一致。违规处：\n"
        + "\n".join(
            f"  {rel}:{line} -> logger.{method}() placeholders={n_ph} args={n_args}"
            for rel, hits in sorted(offenders.items())
            for line, method, n_ph, n_args in hits
        )
    )
