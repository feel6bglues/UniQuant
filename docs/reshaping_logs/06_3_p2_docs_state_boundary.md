# 06.3 P2 Documentation State Boundary

日期: 2026-06-08

## 状态

已完成。

本阶段处理 P2-3: 文档/历史审计过多且状态不一致。

## 风险复核

- `docs/` 下存在大量历史审计、迁移计划和状态报告。
- `docs/index.md` 仍把 5 月迁移期状态作为导航入口，包含 `data`、`signal`、`hands` 等层待迁移的旧结论。
- `docs/STATUS.md` 仍记录 2026-05-26 的早期快照，声称代码版本 44 文件、Phase 0 未执行、`data/` 和 `signal/` 缺失。
- 多个历史文档仍引用单文件 `shared/constants.py`、9 个分析引擎等旧结构。
- `config/config.yaml` 中 HTTP 请求头注释仍引用过期的 `constants.py DEFAULT_HEADERS`。

## 修复内容

- 新增 `docs/reshaping_logs/README.md` 作为本轮受控状态机日志索引。
- 明确本轮当前事实源优先级:
  - `AGENTS.md`
  - `MASTER_REMEDIATION_PLAN.md`
  - `docs/reshaping_logs/README.md`
  - `docs/reshaping_logs/01_*.md` 到 `06_*.md`
- 在 `docs/index.md` 顶部加入当前状态提示，说明下方历史迁移期标记可能不反映 2026-06-08 实测源码状态。
- 在 `docs/STATUS.md` 顶部加入历史快照提示，保留原内容但禁止误用为当前状态。
- 将 `config/config.yaml` 的 HTTP header 注释从 `constants.py DEFAULT_HEADERS` 修正为 `shared.constants.NetworkConstants.USER_AGENT`。

## 边界说明

- 本阶段不批量重写历史审计报告，避免把 P2 文档治理扩大为大规模文档迁移。
- 历史文档仍可作为背景材料，但后续修复不得直接把历史报告结论当作当前代码事实。
- `config/config.yaml` 中 `brain.fsm.sell_threshold/buy_block_threshold/circuit_break_threshold` 是本轮之前已有的未提交配置变更；本阶段未改变其数值，只在同一区块清理行尾以通过 `git diff --check`。

## 验证

- `python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"` -> imports OK。
- 文档入口断言: `docs/index.md` 与 `docs/STATUS.md` 均包含 `reshaping_logs/README.md` -> 通过。
- 配置注释断言: `config/config.yaml` 不再包含 `constants.py DEFAULT_HEADERS`，并包含 `shared.constants.NetworkConstants.USER_AGENT` -> 通过。
- `git diff --check -- config/config.yaml docs/index.md docs/STATUS.md docs/reshaping_logs/README.md` -> 通过。

## 下一挂起点

P2-4 网络退避和模拟数据随机标注。
