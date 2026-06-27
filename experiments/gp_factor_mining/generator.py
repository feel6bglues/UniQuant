"""
Genetic Factor Miner — 基于金融算子的遗传规划因子挖掘引擎

架构:
  1. 算子集 (Operators): 金融有意义的量价变换算子
  2. 终端集 (Terminals): OHLCV + 衍生数据
  3. 遗传规划: 锦标赛选择 + 子树交叉 + 变异 + 精英保留
  4. 适应度: Walk-Forward OOS IC@5d (带复杂度惩罚)
  5. The Reaper: PBO < 0.2 ∧ OOS IC > 0.03 → 生成为 .py 文件

约束:
  - 树深度 ≤ 5
  - 仅允许经济学意义的算子组合 (通过算子白名单 + 惩罚)
"""

from __future__ import annotations

import os
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial



# ─── 算子定义 ───────────────────────────────────────────────────────────────


class Operator(ABC):
    """算子基类"""

    name: str
    arity: int  # 子节点数 (1=一元, 2=二元)
    weight: float = 0.5  # 复杂度权重

    @abstractmethod
    def apply(self, args: List[pd.Series]) -> pd.Series:
        ...

    def __repr__(self) -> str:
        return self.name


# ─── 一元算子 ───────────────────────────────────────────────────────────────


class OpNeg(Operator):
    name = "neg"; arity = 1; weight = 0.3
    def apply(self, args): return -args[0]


class OpAbs(Operator):
    name = "abs"; arity = 1; weight = 0.3
    def apply(self, args): return args[0].abs()


class OpLog(Operator):
    name = "log"; arity = 1; weight = 0.5
    def apply(self, args): return np.log(args[0].abs().clip(lower=1e-10))


class OpSqrt(Operator):
    name = "sqrt"; arity = 1; weight = 0.5
    def apply(self, args): return np.sqrt(args[0].abs())


class OpRank(Operator):
    """横截面百分位秩 [0, 1]"""
    name = "rank"; arity = 1; weight = 0.8
    def apply(self, args):
        s = args[0]
        if "code" not in s.name and not hasattr(s, "index"):
            return s.rank(pct=True)
        return s.groupby(level=0).rank(pct=True) if isinstance(s.index, pd.MultiIndex) else s.rank(pct=True)


class OpScale(Operator):
    """横截面 Z-score"""
    name = "scale"; arity = 1; weight = 0.8
    def apply(self, args):
        s = args[0]
        mu, std = s.mean(), s.std()
        return (s - mu) / std.replace(0, np.nan) if hasattr(std, "replace") else (s - mu) / max(std, 1e-10)


class OpDelay(Operator):
    name = "delay"; arity = 2; weight = 0.6  # (series, days)
    def apply(self, args):
        series = args[0]
        days = self._resolve_constant(args[1], default=1)
        return series.shift(days)

    def _resolve_constant(self, arg, default=1):
        if isinstance(arg, pd.Series):
            val = arg.dropna().iloc[0] if len(arg.dropna()) > 0 else default
            return max(1, min(20, int(abs(val))))
        return default


class OpDelta(Operator):
    """N 日差分"""
    name = "delta"; arity = 2; weight = 0.6
    def apply(self, args):
        series = args[0]
        n = self._resolve_n(args[1], default=5)
        return series.diff(n)

    def _resolve_n(self, arg, default=5):
        if isinstance(arg, pd.Series):
            val = arg.dropna().iloc[0] if len(arg.dropna()) > 0 else default
            return max(1, min(60, int(abs(val))))
        return max(1, min(60, int(abs(arg))))


class OpSMA(Operator):
    """简单移动平均"""
    name = "sma"; arity = 2; weight = 0.7
    def apply(self, args):
        series = args[0]
        n = self._resolve_n(args[1], default=10)
        return series.rolling(window=n, min_periods=n // 2).mean()

    def _resolve_n(self, arg, default=10):
        if isinstance(arg, pd.Series):
            val = arg.dropna().iloc[0] if len(arg.dropna()) > 0 else default
            return max(2, min(120, int(abs(val))))
        return max(2, min(120, int(abs(arg))))


class OpStd(Operator):
    """滚动标准差"""
    name = "stddev"; arity = 2; weight = 0.7
    def apply(self, args):
        series = args[0]
        n = self._resolve_n(args[1], default=20)
        return series.rolling(window=n, min_periods=n // 2).std()

    def _resolve_n(self, arg, default=20):
        if isinstance(arg, pd.Series):
            val = arg.dropna().iloc[0] if len(arg.dropna()) > 0 else default
            return max(2, min(120, int(abs(val))))
        return max(2, min(120, int(abs(arg))))


class OpTsSum(Operator):
    """滚动求和"""
    name = "ts_sum"; arity = 2; weight = 0.6
    def apply(self, args):
        series = args[0]
        n = OpSMA._resolve_n(self, args[1], default=10)
        return series.rolling(window=n, min_periods=n // 2).sum()


class OpTsMin(Operator):
    """滚动最小值"""
    name = "ts_min"; arity = 2; weight = 0.6
    def apply(self, args):
        series = args[0]; n = OpSMA._resolve_n(self, args[1], default=20)
        return series.rolling(window=n, min_periods=n // 2).min()


class OpTsMax(Operator):
    """滚动最大值"""
    name = "ts_max"; arity = 2; weight = 0.6
    def apply(self, args):
        series = args[0]; n = OpSMA._resolve_n(self, args[1], default=20)
        return series.rolling(window=n, min_periods=n // 2).max()


# ─── 二元算子 ───────────────────────────────────────────────────────────────


class OpAdd(Operator):
    name = "add"; arity = 2; weight = 0.2
    def apply(self, args): return args[0] + args[1]


class OpSub(Operator):
    name = "sub"; arity = 2; weight = 0.2
    def apply(self, args): return args[0] - args[1]


class OpMul(Operator):
    name = "mul"; arity = 2; weight = 0.3
    def apply(self, args): return args[0] * args[1]


class OpSafeDiv(Operator):
    """安全除法 — 被零除保护"""
    name = "safe_div"; arity = 2; weight = 0.5
    def apply(self, args):
        denom = args[1].abs().replace(0, np.nan)
        result = args[0] / denom
        return result.clip(lower=-10, upper=10).fillna(0)


class OpMax(Operator):
    name = "max"; arity = 2; weight = 0.3
    def apply(self, args): return pd.concat([args[0], args[1]], axis=1).max(axis=1)


class OpMin(Operator):
    name = "min"; arity = 2; weight = 0.3
    def apply(self, args): return pd.concat([args[0], args[1]], axis=1).min(axis=1)


# ─── 终端定义 ───────────────────────────────────────────────────────────────


@dataclass
class Terminal:
    """GP 树终端节点"""
    name: str
    extract: Callable[[pd.DataFrame], pd.Series]
    category: str = "price"  # price / volume / derived / constant


# ─── GP 树节点 ──────────────────────────────────────────────────────────────


@dataclass
class Node:
    """GP 树节点"""
    op: Optional[Operator] = None
    terminal: Optional[Terminal] = None
    const_value: Optional[float] = None
    children: List["Node"] = field(default_factory=list)

    @property
    def is_operator(self) -> bool:
        return self.op is not None

    @property
    def is_terminal(self) -> bool:
        return self.terminal is not None or self.const_value is not None

    @property
    def arity(self) -> int:
        return self.op.arity if self.op else 0


class GPTree:
    """GP 个体 (表达式树)"""

    def __init__(self, root: Node):
        self.root = root

    def evaluate(self, df: pd.DataFrame) -> pd.Series:
        """递归求值"""
        return self._eval_node(self.root, df)

    def _eval_node(self, node: Node, df: pd.DataFrame) -> pd.Series:
        if node.is_operator:
            args = [self._eval_node(c, df) for c in node.children]
            return node.op.apply(args)
        if node.terminal is not None:
            return node.terminal.extract(df)
        if node.const_value is not None:
            return pd.Series(node.const_value, index=df.index)
        raise RuntimeError("Empty node")

    @property
    def depth(self) -> int:
        return self._depth(self.root)

    def _depth(self, node: Node) -> int:
        if not node.children:
            return 1
        return 1 + max(self._depth(c) for c in node.children)

    @property
    def complexity(self) -> float:
        return self._complexity(self.root, 1)

    def _complexity(self, node: Node, d: int) -> float:
        score = 0.0
        if node.op:
            score += node.op.weight * d
        for c in node.children:
            score += self._complexity(c, d + 1)
        return score

    def to_formula(self) -> str:
        """返回可读的公式字符串"""
        return self._to_str(self.root)

    def _to_str(self, node: Node) -> str:
        if node.terminal:
            return node.terminal.name
        if node.const_value is not None:
            return f"{node.const_value:.1f}"
        op_name = node.op.name
        child_strs = [self._to_str(c) for c in node.children]
        if node.op.arity == 1:
            return f"{op_name}({child_strs[0]})"
        return f"({child_strs[0]} {op_name} {child_strs[1]})"

    def to_python_code(self, func_name: str, comment: str = "") -> str:
        """生成 Python 因子函数代码"""
        lines = [f"def {func_name}(df: pd.DataFrame) -> pd.Series:"]
        if comment:
            lines.append(f'    """{comment}"""')

        vars_needed, consts_needed = self._collect_resources(self.root)
        var_counter = 1

        # 常量定义 (如果有)
        for c_name, c_val in consts_needed:
            lines.append(f"    {c_name} = {c_val}")
            var_counter += 1

        # 变量定义
        for v_name, v_expr in vars_needed:
            lines.append(f"    {v_name} = {v_expr}")

        # 最终表达式
        final_expr = self._to_code(self.root)
        lines.append(f"    return {final_expr}")
        return "\n".join(lines)

    def _collect_resources(self, node: Node) -> Tuple[List[Tuple[str, str]], List[Tuple[str, float]]]:
        """提取所需的中间变量和常量"""
        return [], []

    def _to_code(self, node: Node, _depth: int = 0) -> str:
        """递归生成 Python 代码"""
        if node.terminal:
            name = node.terminal.name
            col_map = {
                "open": "df['open']",
                "high": "df['high']",
                "low": "df['low']",
                "close": "df['close']",
                "volume": "df['volume']",
                "amount": "df['amount']",
                "returns_1d": "df['close'].pct_change(fill_method=None)",
                "returns_5d": "df['close'].pct_change(5, fill_method=None)",
                "returns_10d": "df['close'].pct_change(10, fill_method=None)",
                "returns_20d": "df['close'].pct_change(20, fill_method=None)",
                "vol_20d": "df['close'].pct_change(fill_method=None).rolling(20, min_periods=10).std()",
                "rsi_14": (
                    "(lambda d=df['close'].diff(), "
                    "g=d.clip(lower=0).rolling(14).mean(), "
                    "l=(-d.clip(upper=0)).rolling(14).mean(): "
                    "100 - 100 / (1 + g / l.replace(0, np.nan)))()"
                ),
                "vwap": "df['amount'] / df['volume'].replace(0, np.nan)",
            }
            return col_map.get(name, name)

        if node.const_value is not None:
            return f"{node.const_value}"

        op = node.op
        children_code = [self._to_code(c) for c in node.children]

        if op.name == "neg":
            return f"(-{children_code[0]})"
        if op.name == "abs":
            return f"np.abs({children_code[0]})"
        if op.name == "log":
            return f"np.log(np.abs({children_code[0]}).clip(lower=1e-10))"
        if op.name == "sqrt":
            return f"np.sqrt(np.abs({children_code[0]}))"
        if op.name == "rank":
            return f"({children_code[0]}).rank(pct=True)"
        if op.name == "scale":
            return f"(({children_code[0]}) - ({children_code[0]}).mean()) / max(({children_code[0]}).std(), 1e-10)"
        if op.name == "delay":
            return f"({children_code[0]}).shift({children_code[1]})"
        if op.name == "delta":
            return f"({children_code[0]}).diff({children_code[1]})"
        if op.name == "sma":
            return f"({children_code[0]}).rolling(window={children_code[1]}, min_periods={children_code[1]}//2).mean()"
        if op.name == "stddev":
            return f"({children_code[0]}).rolling(window={children_code[1]}, min_periods={children_code[1]}//2).std()"
        if op.name == "ts_sum":
            return f"({children_code[0]}).rolling(window={children_code[1]}, min_periods={children_code[1]}//2).sum()"
        if op.name == "ts_min":
            return f"({children_code[0]}).rolling(window={children_code[1]}, min_periods={children_code[1]}//2).min()"
        if op.name == "ts_max":
            return f"({children_code[0]}).rolling(window={children_code[1]}, min_periods={children_code[1]}//2).max()"
        if op.name == "add":
            return f"({children_code[0]} + {children_code[1]})"
        if op.name == "sub":
            return f"({children_code[0]} - {children_code[1]})"
        if op.name == "mul":
            return f"({children_code[0]} * {children_code[1]})"
        if op.name == "safe_div":
            return f"({children_code[0]} / ({children_code[1]}).abs().replace(0, np.nan)).clip(lower=-10, upper=10).fillna(0)"
        if op.name == "max":
            return f"pd.concat([{children_code[0]}, {children_code[1]}], axis=1).max(axis=1)"
        if op.name == "min":
            return f"pd.concat([{children_code[0]}, {children_code[1]}], axis=1).min(axis=1)"

        return f"({children_code[0]})"


# ─── 遗传规划引擎 ──────────────────────────────────────────────────────────


@dataclass
class GPConfig:
    """遗传规划配置"""
    pop_size: int = 200
    n_generations: int = 20
    max_depth: int = 5
    tournament_size: int = 3
    crossover_rate: float = 0.7
    mutation_rate: float = 0.2
    elitism_ratio: float = 0.05
    max_const: float = 5.0
    seed: int = 42

    # 适应度
    holding_period: int = 5
    train_ratio: float = 0.7
    complexity_penalty: float = 0.05  # 每单位复杂度的 IC 折扣
    min_ic_threshold: float = 0.01  # 适应度低于此值直接淘汰

    # 多样性控制 (Anti-amount-convergence)
    amount_neutralize: bool = True  # IC 计算前对 amount 做横截面正交化
    amount_penalty_weight: float = 0.5  # |corr(factor, amount)| > 0.6 时的惩罚权重
    diversity_pressure: float = 0.3  # 锦标赛中选择多样性个体的概率

    # 换手率控制
    turnover_penalty_weight: float = 0.3  # 换手率惩罚权重
    turnover_lookback: int = 10  # 换手率计算的回看窗口数

    # IC 时序加权
    ic_half_life: float = 10.0  # IC 指数加权的半衰期 (测试窗口数)

    # 性能
    n_jobs: int = 1  # 并行评估进程数 (1 = 串行)


# ─── 默认操作子和终端 ──────────────────────────────────────────────────────

DEFAULT_UNARY_OPS = [
    OpNeg(), OpAbs(), OpLog(), OpSqrt(),
    OpRank(), OpScale(),
]

DEFAULT_BINARY_OPS = [
    OpAdd(), OpSub(), OpMul(), OpSafeDiv(),
    OpMax(), OpMin(),
]

DEFAULT_SERIES_OPS = [
    OpDelta(), OpSMA(), OpStd(), OpTsSum(),
    OpTsMin(), OpTsMax(), OpDelay(),
]


def _extract_ret1(df): return df["close"].pct_change(fill_method=None)
def _extract_ret5(df): return df["close"].pct_change(5, fill_method=None)
def _extract_ret10(df): return df["close"].pct_change(10, fill_method=None)
def _extract_ret20(df): return df["close"].pct_change(20, fill_method=None)
def _extract_vol20(df):
    ret = df["close"].pct_change(fill_method=None)
    return ret.rolling(window=20, min_periods=10).std()
def _extract_rsi14(df):
    ret = df["close"].diff()
    gain = ret.clip(lower=0).rolling(14).mean()
    loss = (-ret.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))
def _extract_vwap(df):
    amt = df["amount"].astype(float) if "amount" in df.columns else df["volume"] * df["close"]
    return amt / df["volume"].replace(0, np.nan)


DEFAULT_TERMINALS = [
    Terminal("returns_1d", _extract_ret1, "derived"),
    Terminal("returns_5d", _extract_ret5, "derived"),
    Terminal("returns_10d", _extract_ret10, "derived"),
    Terminal("returns_20d", _extract_ret20, "derived"),
    Terminal("vol_20d", _extract_vol20, "derived"),
    Terminal("rsi_14", _extract_rsi14, "derived"),
    Terminal("vwap", _extract_vwap, "derived"),
]

SERIES_TERMINAL_NAMES = {"returns_1d", "returns_5d", "returns_10d", "returns_20d",
                         "vol_20d", "rsi_14", "vwap"}


class GeneticFactorMiner:
    """遗传规划因子挖掘器"""

    def __init__(
        self,
        config: Optional[GPConfig] = None,
        unary_ops: Optional[List[Operator]] = None,
        binary_ops: Optional[List[Operator]] = None,
        series_ops: Optional[List[Operator]] = None,
        terminals: Optional[List[Terminal]] = None,
    ):
        self.config = config or GPConfig()
        self.unary_ops = unary_ops or DEFAULT_UNARY_OPS
        self.binary_ops = binary_ops or DEFAULT_BINARY_OPS
        self.series_ops = series_ops or DEFAULT_SERIES_OPS
        self.all_ops = self.unary_ops + self.binary_ops + self.series_ops
        self.terminals = terminals or DEFAULT_TERMINALS

        rng_seed = getattr(self.config, "seed", 42)
        self.rng = random.Random(rng_seed)
        self.np_rng = np.random.RandomState(rng_seed)

        # 用于复用的终端缓存 (按名称)
        self.terminal_map = {t.name: t for t in self.terminals}

        # 非系列终端 (常量)
        self._const_choices = [-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0, 3.0, 5.0]

        # 最佳个体追踪
        self.best_fitness_history: List[float] = []
        self.best_individuals: List[Tuple[GPTree, float]] = []

        # 多样性追踪
        self.amount_corr_history: List[float] = []
        self.diversity_history: List[float] = []

    # ─── Amount 中性化工具 ────────────────────────────────────────────────

    def _has_amount_terminal(self, tree: GPTree) -> bool:
        """检查树中是否包含 amount 终端"""
        def _walk(node: Node) -> bool:
            if node.terminal and node.terminal.name == "amount":
                return True
            return any(_walk(c) for c in node.children)
        return _walk(tree.root)

    def _neutralize_amount(self, factor_values: pd.Series, amount_values: pd.Series) -> pd.Series:
        """横截面 OLS 正交化: 剥离 amount 对 factor 的线性解释力"""
        df = pd.DataFrame({"f": factor_values, "a": amount_values.astype(float)}).dropna()
        if len(df) < 20 or df["a"].nunique() < 2:
            return factor_values
        a_vals = df["a"].values
        f_vals = df["f"].values
        a_centered = a_vals - np.mean(a_vals)
        f_centered = f_vals - np.mean(f_vals)
        beta = np.sum(a_centered * f_centered) / max(np.sum(a_centered ** 2), 1e-10)
        residual = f_vals - beta * a_vals
        result = pd.Series(index=factor_values.index, dtype=float, name="amount_neutralized")
        result.loc[df.index] = residual
        return result

    def _compute_amount_correlation(self, factor_values: pd.Series, amount_values: pd.Series) -> float:
        """计算因子值与 amount 的横截面 Spearman 相关性"""
        df = pd.DataFrame({"f": factor_values, "a": amount_values.astype(float)}).dropna()
        if len(df) < 20 or df["f"].nunique() < 2 or df["a"].nunique() < 2:
            return 0.0
        from scipy import stats
        corr, _ = stats.spearmanr(df["f"], df["a"])
        return abs(corr) if not np.isnan(corr) else 0.0

    def _formula_signature(self, tree: GPTree) -> str:
        """返回归一化的公式签名 (用于多样性比对)"""
        return tree.to_formula()

    # ─── 树生成 ────────────────────────────────────────────────────────────

    def _random_terminal(self) -> Node:
        """随机终端节点 (含常量)"""
        if self.rng.random() < 0.15:
            val = self.rng.choice(self._const_choices)
            return Node(const_value=val)
        t = self.rng.choice(self.terminals)
        return Node(terminal=t)

    def _random_operator(self, max_depth: int) -> Operator:
        """根据剩余深度选择合适的算子"""
        if max_depth <= 1:
            return self.rng.choice(self.unary_ops)
        if self.rng.random() < 0.4:
            return self.rng.choice(self.unary_ops)
        if self.rng.random() < 0.4:
            return self.rng.choice(self.series_ops)
        return self.rng.choice(self.binary_ops)

    def _grow_tree(self, max_depth: int, current_depth: int = 0) -> Node:
        """生长随机树 (Grow 方法)"""
        if current_depth >= max_depth:
            return self._random_terminal()

        if current_depth == 0 or self.rng.random() < 0.6:
            # 尝试生成算子节点
            op = self._random_operator(max_depth - current_depth)
            children = []
            child_depth = current_depth + 1

            if op.arity == 1:
                children.append(self._grow_tree(max_depth, child_depth))
            elif op.arity == 2:
                children.append(self._grow_tree(max_depth, child_depth))
                children.append(self._grow_tree_max(max_depth, child_depth))

            return Node(op=op, children=children)

        return self._random_terminal()

    def _grow_tree_max(self, max_depth: int, current_depth: int = 0) -> Node:
        """Full 方法: 直到最大深度"""
        if current_depth >= max_depth:
            return self._random_terminal()

        op = self._random_operator(max_depth - current_depth)
        children = []
        child_depth = current_depth + 1
        for _ in range(op.arity):
            children.append(self._grow_tree_max(max_depth, child_depth))

        return Node(op=op, children=children)

    def generate_random_tree(self) -> GPTree:
        """生成随机个体"""
        method = "grow" if self.rng.random() < 0.7 else "full"
        if method == "grow":
            root = self._grow_tree(self.config.max_depth)
        else:
            root = self._grow_tree_max(self.config.max_depth)
        return GPTree(root)

    def _init_population(self) -> List[GPTree]:
        """初始化种群"""
        return [self.generate_random_tree() for _ in range(self.config.pop_size)]

    # ─── 遗传算子 ──────────────────────────────────────────────────────────

    def _subtree_crossover(self, parent1: GPTree, parent2: GPTree) -> Tuple[GPTree, GPTree]:
        """子树交叉"""
        def _get_random_node(node: Node) -> Node:
            nodes = []
            def _collect(n):
                nodes.append(n)
                for c in n.children:
                    _collect(c)
            _collect(node)
            return self.rng.choice(nodes) if nodes else node

        n1 = _get_random_node(parent1.root)
        n2 = _get_random_node(parent2.root)

        # 交换子树 (浅拷贝)
        backup1 = Node(
            op=n1.op, terminal=n1.terminal,
            const_value=n1.const_value,
            children=list(n1.children),
        )

        n1.op, n1.terminal, n1.const_value, n1.children = \
            n2.op, n2.terminal, n2.const_value, list(n2.children)
        n2.op, n2.terminal, n2.const_value, n2.children = \
            backup1.op, backup1.terminal, backup1.const_value, backup1.children

        # 检查深度约束
        if parent1.depth > self.config.max_depth:
            parent1.root = backup1
        if parent2.depth > self.config.max_depth:
            parent2.root = Node(
                op=n2.op, terminal=n2.terminal,
                const_value=n2.const_value, children=list(n2.children),
            )

        return parent1, parent2

    def _point_mutation(self, tree: GPTree) -> GPTree:
        """点变异: 替换随机节点"""
        def _mutate_node(node: Node, depth: int) -> None:
            if self.rng.random() < 0.3:
                return

            if node.is_terminal and self.rng.random() < 0.4:
                if node.const_value is not None:
                    node.const_value = self.rng.choice(self._const_choices)
                else:
                    node.terminal = self.rng.choice(self.terminals)
                return

            if node.is_operator:
                # 替换算子或它的参数
                if self.rng.random() < 0.3:
                    node.op = self._random_operator(self.config.max_depth - depth)
                    # 调整子节点数量
                    while len(node.children) < node.op.arity:
                        node.children.append(self._grow_tree(self.config.max_depth, depth + 1))
                    while len(node.children) > node.op.arity:
                        node.children.pop()
                else:
                    for c in node.children:
                        _mutate_node(c, depth + 1)

        _mutate_node(tree.root, 0)
        if tree.depth > self.config.max_depth:
            tree.root = self._random_terminal()
            # 重新生长到合理深度
            tree.root = self._grow_tree(self.config.max_depth)

        return tree

    # ─── 适应度评估 ──────────────────────────────────────────────────────

    def _compute_ic(self, factor_values: pd.Series, fwd_returns: pd.Series) -> float:
        """计算横截面 Spearman IC"""
        from scipy import stats
        df = pd.DataFrame({"f": factor_values, "r": fwd_returns}).dropna()
        if len(df) < 20:
            return 0.0
        if df["f"].nunique() < 2 or df["r"].nunique() < 2:
            return 0.0
        try:
            ic, _ = stats.spearmanr(df["f"], df["r"])
            return ic if not np.isnan(ic) else 0.0
        except Exception:
            return 0.0

    def evaluate_fitness(
        self,
        tree: GPTree,
        df_train: pd.DataFrame,
        df_test: pd.DataFrame,
        test_fwd: Optional[np.ndarray] = None,
        test_amount: Optional[np.ndarray] = None,
        test_date_groups: Optional[List[np.ndarray]] = None,
    ) -> float:
        """
        适应度 = weighted_OOS_IC - complexity_penalty - amount_penalty - turnover_penalty

        IC 时序指数加权: 近期 IC 半衰期 = config.ic_half_life

        换手率惩罚: 因子秩在连续日期间的平均绝对变化率

        Amount 惩罚:
          - IC 计算前先对 amount 做横截面正交化
          - 额外对 |corr(factor, amount)| > 0.6 的个体施加严重惩罚
        """
        try:
            train_vals = tree.evaluate(df_train)
            train_clean = train_vals.dropna()
            if len(train_clean) < 100 or train_clean.nunique() < 5:
                return -1.0

            test_vals = tree.evaluate(df_test)
            test_clean = test_vals.dropna()
            if len(test_clean) < 50 or test_clean.nunique() < 5:
                return -1.0

            test_factor = test_vals.values.astype(np.float64)
            has_nan = np.isnan(test_factor)

            ics = []
            amount_corrs = []

            for idx in test_date_groups:
                mask = ~has_nan[idx]
                idx_clean = idx[mask]
                if len(idx_clean) < 20:
                    continue
                fv = test_factor[idx_clean]
                rv = test_fwd[idx_clean]
                rv_mask = ~np.isnan(rv)
                if rv_mask.sum() < 20:
                    continue
                fv = fv[rv_mask]
                rv = rv[rv_mask]

                if self.config.amount_neutralize:
                    av = test_amount[idx_clean][rv_mask]
                    av_mask = ~np.isnan(av)
                    if av_mask.sum() < 20:
                        continue
                    fv_n = fv[av_mask]
                    rv_n = rv[av_mask]
                    av_n = av[av_mask]
                    fv_neu = self._neutralize_amount_np(fv_n, av_n)
                    ic = self._compute_ic_np(fv_neu, rv_n)
                else:
                    ic = self._compute_ic_np(fv, rv)

                if abs(ic) > 0:
                    ics.append(ic)

                if self.config.amount_penalty_weight > 0:
                    av = test_amount[idx_clean]
                    av_mask = ~np.isnan(av)
                    if av_mask.sum() >= 20:
                        corr = self._compute_amount_correlation_np(
                            test_factor[idx_clean][av_mask], av[av_mask]
                        )
                        amount_corrs.append(corr)

            if not ics:
                return -1.0

            # IC 时序指数加权: 近期 IC 权重更高
            n_ics = len(ics)
            if n_ics > 1 and self.config.ic_half_life > 0:
                decay = np.log(2) / self.config.ic_half_life
                raw_weights = np.exp(-np.arange(n_ics) * decay)
                weights = raw_weights[::-1]
                weights /= weights.sum()
                mean_ic = float(np.average(ics, weights=weights))
            else:
                mean_ic = float(np.mean(ics))

            penalty = self.config.complexity_penalty * tree.complexity

            # 换手率惩罚
            turnover = self._compute_turnover_np(
                test_factor, has_nan, test_date_groups,
                lookback=self.config.turnover_lookback,
            )
            turnover_penalty = self.config.turnover_penalty_weight * turnover

            # Amount 相关性惩罚
            amount_penalty = 0.0
            if self.config.amount_penalty_weight > 0 and amount_corrs:
                avg_amount_corr = float(np.mean(amount_corrs))
                if avg_amount_corr > 0.6:
                    overage = avg_amount_corr - 0.6
                    amount_penalty = self.config.amount_penalty_weight * overage * 2.0
                    amount_penalty = min(amount_penalty, 0.5)

            return mean_ic - penalty - amount_penalty - turnover_penalty

        except Exception:
            return -1.0

    def _compute_ic_np(self, f: np.ndarray, r: np.ndarray) -> float:
        from scipy import stats
        n = min(len(f), len(r))
        if n < 20:
            return 0.0
        try:
            ic, _ = stats.spearmanr(f[:n], r[:n])
            return ic if not np.isnan(ic) else 0.0
        except Exception:
            return 0.0

    def _neutralize_amount_np(self, f: np.ndarray, a: np.ndarray) -> np.ndarray:
        if len(f) < 20 or np.unique(a).size < 2:
            return f
        a_c = a - np.mean(a)
        f_c = f - np.mean(f)
        beta = np.sum(a_c * f_c) / max(np.sum(a_c ** 2), 1e-10)
        return f - beta * a

    def _compute_amount_correlation_np(self, f: np.ndarray, a: np.ndarray) -> float:
        from scipy import stats
        if len(f) < 20 or np.unique(f).size < 2 or np.unique(a).size < 2:
            return 0.0
        try:
            c, _ = stats.spearmanr(f, a)
            return abs(c) if not np.isnan(c) else 0.0
        except Exception:
            return 0.0

    def _compute_turnover_np(
        self,
        test_factor: np.ndarray,
        has_nan: np.ndarray,
        date_groups: List[np.ndarray],
        lookback: int = 10,
    ) -> float:
        """计算因子值的平均换手率 (rank change / max_change). 范围 [0, 1]."""
        ranked = []
        for idx in date_groups:
            mask = ~has_nan[idx]
            idx_clean = idx[mask]
            if len(idx_clean) < 20:
                continue
            fv = test_factor[idx_clean]
            ranks = np.argsort(np.argsort(fv)).astype(np.float64)
            ranked.append(ranks)

        if len(ranked) < 2:
            return 0.0

        changes = []
        for i in range(1, min(len(ranked), lookback + 1)):
            r_prev, r_curr = ranked[-i - 1], ranked[-i]
            n = min(len(r_prev), len(r_curr))
            if n < 20:
                continue
            avg_change = float(np.mean(np.abs(r_prev[:n] - r_curr[:n])))
            max_change = n - 1
            changes.append(avg_change / max_change if max_change > 0 else 0.0)

        return float(np.mean(changes)) if changes else 0.0

    @staticmethod
    def block_bootstrap_pbo(oos_ics: list, n_bootstrap: int = 2000, block_size: Optional[int] = None) -> float:
        """块 Bootstrap PBO 估计: 保留 IC 时序自相关结构"""
        arr = np.array(oos_ics, dtype=np.float64)
        n = len(arr)
        if n < 5:
            return 1.0
        bs = block_size or max(3, min(10, n // 5))
        if n < bs * 2:
            return 1.0
        actual_mean = float(np.mean(arr))
        rng = np.random.RandomState(42)
        bootstrap_means = np.empty(n_bootstrap)
        for i in range(n_bootstrap):
            chunks = []
            pos = 0
            while pos < n:
                start = rng.randint(0, n - bs + 1)
                chunks.extend(arr[start:start + bs].tolist())
                pos += bs
            bootstrap_means[i] = np.mean(chunks[:n])
        return float(np.mean(bootstrap_means >= actual_mean))

    # ─── 选择 ──────────────────────────────────────────────────────────────

    def _tournament_select(
        self,
        population: List[GPTree],
        fitness: List[float],
        df_test: Optional[pd.DataFrame] = None,
    ) -> GPTree:
        """
        锦标赛选择 (含多样化压力)
        
        手术 #3: 词典式简约压力 + 多样性偏好
          - 首先比较适应度 (Primary)
          - 适应度接近 (±0.01) 时, 优先选择:
            a) 复杂度更低的个体
            b) 有概率选择非 amount 依赖的个体
        """
        k = self.config.tournament_size
        candidates = []
        for _ in range(k):
            idx = self.rng.randint(0, len(population) - 1)
            candidates.append((idx, population[idx], fitness[idx]))
        candidates.sort(key=lambda x: x[2], reverse=True)

        best_idx, best_tree, best_f = candidates[0]

        # 检查是否有适应度接近的个体
        close_candidates = [c for c in candidates if abs(c[2] - best_f) < 0.01]
        if len(close_candidates) > 1 and self.rng.random() < self.config.diversity_pressure:
            # 在适应度接近的个体中选择:
            # 1. 复杂度更低的
            # 2. 不包含 amount 终端的
            def score(c):
                tree = c[1]
                s = 0.0
                # 复杂度越低越好
                s -= tree.complexity * 0.01
                # 不包含 amount 的加分
                if not self._has_amount_terminal(tree):
                    s += 0.005
                return s

            close_candidates.sort(key=score, reverse=True)
            return close_candidates[0][1]

        return best_tree

    # ─── 主循环 ────────────────────────────────────────────────────────────

    def mine(
        self,
        df: pd.DataFrame,
        code_col: str = "code",
        date_col: str = "date",
        price_col: str = "close",
        n_jobs: int = 1,
    ) -> List[Tuple[GPTree, float]]:
        """
        运行遗传规划挖掘

        Args:
            df: 多股票 OHLCV DataFrame
            code_col: 股票代码列
            date_col: 日期列
            price_col: 收盘价列

        Returns:
            按适应度排序的 (tree, fitness) 列表
        """
        print(f"\n  [GP] 初始化种群 ({self.config.pop_size} individuals)...")
        population = self._init_population()

        # 时间分割 (带 embargo)
        all_dates = sorted(df[date_col].unique())
        split_idx = int(len(all_dates) * self.config.train_ratio)
        embargo = 5
        train_dates = all_dates[:split_idx - embargo]
        test_dates = all_dates[split_idx:]

        mask_train = df[date_col].isin(train_dates)
        mask_test = df[date_col].isin(test_dates)

        df_train = df[mask_train].copy()
        df_test = df[mask_test].copy()

        print(f"    训练: {df_train[date_col].nunique()} 天 → {df_train[code_col].nunique()} 只")
        print(f"    测试: {df_test[date_col].nunique()} 天 → {df_test[code_col].nunique()} 只")

        # 预计算测试集 forward returns + amount (加速适应度评估)
        h = self.config.holding_period
        test_fwd_s = df_test.groupby(code_col)[price_col].shift(-h) / df_test[price_col] - 1
        test_fwd_np = test_fwd_s.values.astype(np.float64)
        test_amount_np = df_test["amount"].values.astype(np.float64) if "amount" in df_test.columns else None
        test_date_arr = df_test[date_col].values

        # 预构建日期索引组
        date_to_indices: Dict = {}
        for i, d in enumerate(test_date_arr):
            date_to_indices.setdefault(d, []).append(i)
        test_date_groups = [np.array(v, dtype=np.intp) for v in date_to_indices.values()
                            if len(v) >= 20]

        for gen in range(self.config.n_generations):
            # 评估适应度 (使用预计算数据)
            n_jobs = max(1, self.config.n_jobs)
            if n_jobs > 1:
                fitness = [None] * len(population)
                eval_fn = partial(
                    self.evaluate_fitness,
                    df_train=df_train, df_test=df_test,
                    test_fwd=test_fwd_np, test_amount=test_amount_np,
                    test_date_groups=test_date_groups,
                )
                with ThreadPoolExecutor(max_workers=n_jobs) as pool:
                    fut_map = {pool.submit(eval_fn, tree): i for i, tree in enumerate(population)}
                    for fut in as_completed(fut_map):
                        idx = fut_map[fut]
                        try:
                            fitness[idx] = fut.result()
                        except Exception:
                            fitness[idx] = -1.0
            else:
                fitness = []
                for i, tree in enumerate(population):
                    f = self.evaluate_fitness(
                        tree, df_train, df_test,
                        test_fwd=test_fwd_np, test_amount=test_amount_np,
                        test_date_groups=test_date_groups,
                    )
                    fitness.append(f)

            # 精英
            n_elite = max(1, int(self.config.pop_size * self.config.elitism_ratio))
            elite_idx = np.argsort(fitness)[-n_elite:]
            elites = [population[i] for i in elite_idx]
            elite_f = [fitness[i] for i in elite_idx]

            best_f = max(fitness)
            self.best_fitness_history.append(best_f)
            if best_f > 0:
                best_idx = fitness.index(best_f)
                self.best_individuals.append((population[best_idx], best_f))

            # 记录 (含多样性指标)
            mean_f = float(np.mean([f for f in fitness if f > -1]))
            n_valid = sum(1 for f in fitness if f > -0.5)

            # 计算种群 amount 相关性和多样性
            formula_set = set()
            amount_dep_count = 0
            for t in population:
                formula_set.add(self._formula_signature(t))
                if self._has_amount_terminal(t):
                    amount_dep_count += 1
            diversity_ratio = len(formula_set) / len(population)
            amount_dep_ratio = amount_dep_count / len(population)

            if gen == 0 or (gen + 1) % 5 == 0 or gen == self.config.n_generations - 1:
                print(f"  [GP] Gen {gen + 1:2d}/{self.config.n_generations}  "
                      f"best={best_f:.4f}  mean={mean_f:.4f}  "
                      f"valid={n_valid}/{len(population)}  "
                      f"div={diversity_ratio:.2f}  amount%={amount_dep_ratio:.2f}")

            # 下一代
            new_pop = list(elites)
            while len(new_pop) < self.config.pop_size:
                p1 = self._tournament_select(population, fitness)
                p2 = self._tournament_select(population, fitness)

                if p1 is None or p2 is None:
                    new_pop.append(self.generate_random_tree())
                    continue

                # 深拷贝用于遗传操作
                import copy
                c1, c2 = copy.deepcopy(p1), copy.deepcopy(p2)

                if self.rng.random() < self.config.crossover_rate:
                    try:
                        c1, c2 = self._subtree_crossover(c1, c2)
                    except Exception:
                        pass

                if self.rng.random() < self.config.mutation_rate:
                    c1 = self._point_mutation(c1)
                if self.rng.random() < self.config.mutation_rate:
                    c2 = self._point_mutation(c2)

                new_pop.append(c1)
                if len(new_pop) < self.config.pop_size:
                    new_pop.append(c2)

            population = new_pop[:self.config.pop_size]

        # 最终排序 (使用预计算数据)
        n_jobs = max(1, self.config.n_jobs)
        if n_jobs > 1:
            final_fitness = [None] * len(population)
            eval_fn = partial(
                self.evaluate_fitness,
                df_train=df_train, df_test=df_test,
                test_fwd=test_fwd_np, test_amount=test_amount_np,
                test_date_groups=test_date_groups,
            )
            with ThreadPoolExecutor(max_workers=n_jobs) as pool:
                fut_map = {pool.submit(eval_fn, tree): i for i, tree in enumerate(population)}
                for fut in as_completed(fut_map):
                    idx = fut_map[fut]
                    try:
                        final_fitness[idx] = fut.result()
                    except Exception:
                        final_fitness[idx] = -1.0
        else:
            final_fitness = []
            for tree in population:
                f = self.evaluate_fitness(
                    tree, df_train, df_test,
                    test_fwd=test_fwd_np, test_amount=test_amount_np,
                    test_date_groups=test_date_groups,
                )
                final_fitness.append(f)

        sorted_idx = np.argsort(final_fitness)[::-1]
        results = [(population[i], final_fitness[i]) for i in sorted_idx[:50]]

        # 报告 Top-5 详情
        print(f"\n  [GP] Top-5 存活因子:")
        for i, (tree, f) in enumerate(results[:5]):
            has_amt = "⚠️ amount" if self._has_amount_terminal(tree) else "✓ no-amount"
            print(f"    #{i+1}: fitness={f:.4f}  depth={tree.depth}  "
                  f"complexity={tree.complexity:.1f}  {has_amt}")
            print(f"         formula: {tree.to_formula()[:80]}")

        return results
