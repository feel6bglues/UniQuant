"""GP 因子挖掘 — 遗传算子 arity/别名稳健性回归测试。

背景 (2026-08-19): 真实数据 GP 全量运行在 mine() Gen 1 崩
`IndexError` (to_formula 缺子节点) — 根因是 `_subtree_crossover`
把 `backup1.children` 列表对象直接赋给另一输出树 (跨树列表/节点别名),
后续 in-place 变异/清洗会静默破坏对方树, 产生 min(1子)/abs(2子) 型
arity 失配, 而 XO 后检查因别名延迟才显形。修复: 移植子树用深拷贝
+ `_sanitize_tree` 对终结点清空 children。本测试锁该回归。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS = PROJECT_ROOT / "experiments" / "gp_factor_mining"
for _p in (str(PROJECT_ROOT), str(EXPERIMENTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from generator import GPConfig, GPTree, GeneticFactorMiner, Node  # noqa: E402


def _arity_correct(tree: GPTree) -> int:
    """返回树中 arity 失配的节点数 (算子子节点数 != 算子 arity)。"""
    bad = [0]

    def walk(node: Node) -> None:
        if node.op is not None:
            if len(node.children) != node.op.arity:
                bad[0] += 1
        for c in node.children:
            walk(c)

    walk(tree.root)
    return bad[0]


def _terminal_with_children(tree: GPTree) -> int:
    """返回既非算子却又带子节点的终结点个数 (别名残留信号)。"""
    cnt = [0]

    def walk(node: Node) -> None:
        if node.op is None and (node.terminal is not None or node.const_value is not None):
            if node.children:
                cnt[0] += 1
        for c in node.children:
            walk(c)

    walk(tree.root)
    return cnt[0]


def _make_miner(seed: int = 42):
    cfg = GPConfig(pop_size=40, n_generations=1, n_jobs=1, seed=seed)
    return GeneticFactorMiner(config=cfg)


@pytest.mark.parametrize("seed", [42, 7, 2026])
def test_crossover_mutation_chain_never_breaks_arity(seed):
    """500 轮 xo→mut 组合循环后交叉的两个后代必须全程 arity 一致。"""
    m = _make_miner(seed=seed)
    pop = m._init_population()
    for tree in pop:
        assert _arity_correct(tree) == 0, "初始种群即存在失配树"

    rng = np.random.default_rng(seed)
    import copy

    for _ in range(500):
        p1, p2 = _pick(pop, rng)
        c1 = copy.deepcopy(p1)
        c2 = copy.deepcopy(p2)
        if rng.random() < 0.7:
            c1, c2 = m._subtree_crossover(c1, c2)
        assert _arity_correct(c1) == 0, f"XO 后 c1 arity 失配: {c1.to_formula()}"
        assert _arity_correct(c2) == 0, f"XO 后 c2 arity 失配: {c2.to_formula()}"
        assert _terminal_with_children(c1) == 0, f"XO 后 c1 残留终结点带子: {c1.to_formula()}"
        assert _terminal_with_children(c2) == 0, f"XO 后 c2 残留终结点带子: {c2.to_formula()}"
        if rng.random() < 0.2:
            c1 = m._point_mutation(c1)
        if rng.random() < 0.2:
            c2 = m._point_mutation(c2)
        assert _arity_correct(c1) == 0, f"变异后 c1 arity 失配: {c1.to_formula()}"
        assert _arity_correct(c2) == 0, f"变异后 c2 arity 失配: {c2.to_formula()}"
        # 修复后必须仍可求值 (to_formula 不再抛 IndexError)
        assert c1.to_formula() and c2.to_formula()


def _pick(pop, rng):
    i = int(rng.integers(0, len(pop)))
    j = int(rng.integers(0, len(pop)))
    return pop[i], pop[j]


def test_crossover_outputs_share_no_node_objects():
    """交叉后两个输出树不得共享任何节点对象 (别名回归锁)。

    修复前 backup1.children 列表被两个输出树共享, 节点对象也可经
    parent1.root=backup1 进入对方树 — 断言两树节点集合不相交。
    """
    m = _make_miner(seed=3)
    pop = m._init_population()
    p1, p2 = pop[0], pop[1]

    def _nodes(tree: GPTree) -> set[int]:
        out = set()

        def walk(n: Node):
            out.add(id(n))
            for c in n.children:
                walk(c)

        walk(tree.root)
        return out

    for _ in range(200):
        import copy

        c1, c2 = m._subtree_crossover(copy.deepcopy(p1), copy.deepcopy(p2))
        n1, n2 = _nodes(c1), _nodes(c2)
        assert not (n1 & n2), f"两个输出树共享节点对象 (共 {len(n1 & n2)})"


def test_sanitize_clears_children_on_terminal_nodes():
    """终结点带子节点被 _sanitize_tree 清空 (别名残留的兜底修复)。"""
    t = Node(terminal=MagicMock(name="close"))
    t.children.append(Node(const_value=1.0))
    tree = GPTree(t)
    m = _make_miner()
    out = m._sanitize_tree(tree)
    assert out.root.children == []
    assert _terminal_with_children(out) == 0


def test_mine_end_to_end_survives(tmp_path):
    """小面板 mine() 全流程 (进化→候选) 不再崩溃, 且产出可序列化公式。"""
    rng = np.random.default_rng(0)
    dates = pd.date_range("2020-01-01", periods=300, freq="D")
    rows = []
    for code in range(20):
        px = rng.normal(100, 5, 300).cumsum() + 1000
        for d, close in zip(dates, px):
            rows.append({"code": f"{code:06d}.SZ", "date": d, "close": close})
    df = pd.DataFrame(rows)
    df["ret"] = df.groupby("code")["close"].pct_change()
    df["amount"] = df["close"] * abs(rng.normal(1e6, 2e5, len(df)))

    pdf = df.copy()
    pdf["date"] = pd.to_datetime(pdf["date"])
    pdf = pdf.set_index(["code", "date"], drop=False)
    pdf.index = pdf.index.set_names(["code_idx", "date_idx"])

    m = GeneticFactorMiner(config=GPConfig(pop_size=16, n_generations=2, n_jobs=2, seed=42))
    res = m.mine(pdf, n_jobs=2)
    assert isinstance(res, list)
    for tree, _fitness in res:
        assert isinstance(tree.to_formula(), str)
        assert _arity_correct(tree) == 0