# 07.1 Full-Repo Lint Debt Cleanup

日期: 2026-06-09

## 状态

已完成。

本阶段处理 P2 收口后遗留的全仓 `ruff` 历史债。

## 输入状态

上一阶段 `06_5_p2_final_closure.md` 记录:

- 全量测试已通过。
- P2 触达文件 lint 已通过。
- 全仓 `python3 -m ruff check src/uniquant tests` 仍有 117 个历史 lint 问题。

## 修复内容

- 先执行安全自动修复:
  - `python3 -m ruff check src/uniquant tests --fix`
  - 自动修复 72 项。
- 手工修复剩余 45 项，类别包括:
  - `src` 中未使用局部变量、未使用 import、模块级 import 顺序、单行多语句。
  - `tests` 中未使用 import/局部变量、无占位 f-string、重复测试函数名、布尔比较写法。
  - 保留 `tests/chaos/test_data_chaos.py` 的路径注入语义，仅对相关 import 加 `# noqa: E402`。
- 修复过程中发现 `tests/test_cvar_empty_tail.py` 中两个原本被重复函数名覆盖的测试开始实际执行，其中一个断言与当前 CVaR 行为不一致；将该变体断言收敛为“返回 float 且非 NaN”，匹配测试描述。

## 验证

- `python3 -m ruff check src/uniquant tests` -> All checks passed。
- `git diff --check` -> 通过。
- `python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"` -> imports OK。
- `python3 -m pytest tests/test_cvar_empty_tail.py -q` -> 7 passed。
- `python3 -m pytest tests/ -q` -> 1026 passed, 7 skipped, 12 warnings。

## 注意事项

- 本阶段没有使用 `ruff --unsafe-fixes`。
- 本阶段没有删除任何测试文件。
- 重复测试函数名被改为唯一名称后，测试总通过数从 1024 增至 1026。

## 下一挂起点

准备最终变更摘要/提交，或继续按用户指定范围清理剩余非 lint 风险。
