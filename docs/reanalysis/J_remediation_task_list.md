# Phase J — 修复任务清单 (基于 7 层逐文件审计)

> **生成**: 2026-07-09 | **基于**: 256 文件, 62,518 LOC, 1,674 tests, 7 层逐文件源代码审计
> **前置阅读**: `docs/reanalysis/I_live_system_map.md`, `docs/reanalysis/E_red_blue_analysis.md`, `docs/remediation/red_blue_remediation_plan.md`
> **修复原则**: 外科手术式修改, TDD 优先, 每轮验收门禁, 与设计一致
> **验证门禁**: 每轮完成后 `pytest tests/ -q --tb=short` + `ruff check src/uniquant/`

---

## 执行轮次总览

| 轮次 | 聚焦 | 任务数 | 预估工时 | 风险 |
|------|------|:------:|:--------:|:----:|
| **R0** | 🔴 数据损坏修复 (H1-H3) | 3 | 2h | 高 — 直接影响结果正确性 |
| **R1** | 🟡 指标错误修复 (H4, M1) | 2 | 1.5h | 高 — metrics 误导用户决策 |
| **R2** | 🟠 P1 工程修复 | 7 | 3h | 中 — 代码质量/边界处理 |
| **R3** | 🔵 P2 深度修复 | 7 | 4h | 低 — 设计完善/代码整洁 |
| **R4** | 📋 文档对齐 + AGENTS.md 更新 | 8 | 1h | 低 — 无代码变更 |
| **R5** | ✅ 最终验证 | — | 0.5h | 验证门禁 |

**总计**: 25 任务, ~12 工时

---

## Round 0 — 🔴 数据损坏修复 (P0 级)

### R0-01: DataValidator 原地修改输入 DataFrame

**文件**: `src/uniquant/data/pipeline/data_validator.py:30-31,45,50`
**问题**: `validate()` 用 `df.loc[mask_error, ...] = ...` 和 `df["high"] = df[...].max(...)` 原地修改调用者的 DataFrame
**修复**: 在 `validate()` 顶部添加 `df = df.copy()` 防止副作用
**验证**: 调用 `test_data_validator.py` 全部测试, 检查 DataFetcher 返回的 DataFrame 不被修改

### R0-02: TradeCalendarManager 持久化方案不兼容

**文件**: `src/uniquant/data/managers/trade_calendar_manager.py:134,147,167`
**问题**: `create_trade_calendar()` 写入 `trade_calendar.csv` (单文件), 但 `generate_trade_calendar(year)` 和 `is_trading_day()` 期望 `trade_calendar_{year}.csv` (按年分文件)
**修复 (方案 A)**: 让 `create_trade_calendar()` 生成按年分文件; 或 (方案 B) 让读取代码支持单文件格式
**验证**: 确认日历数据可读写一致

### R0-03: research_pipeline.py bare except Exception 残留

**文件**: `src/uniquant/services/research_pipeline.py:244`
**问题**: P0-08 声明"已修复"但 bare `except Exception:` 仍在
**修复**: 窄化为 `except (OSError, PermissionError):` (tempfile 清理场景)
**验证**: 确认通过 `pytest tests/test_research_pipeline.py`

---

## Round 1 — 🟡 指标/数据错误修复 (P0 级)

### R1-01: TradeStatistics.sharpe_ratio 使用美元 PnL 而非百分比收益率

**文件**: `src/uniquant/hands/backtest/trade_analysis/statistics.py:159-173`
**问题**: Sharpe ratio 用 `pnl` 值 (美元金额) 而不是百分比收益率, 数学上不正确
**修复**: 改用百分比收益率序列 (如 `pnl / cost_basis`); 或标记为 `_sharpe_ratio_from_pnl` 并添加带百分比版本的正确方法
**验证**: 添加测试验证百分比 Sharpe 与美元 PnL Sharpe 的差异

### R1-02: ResearchDataPack.to_dict() metadata 键碰撞

**文件**: `src/uniquant/shared/interfaces.py:257-259`
**问题**: `result.update(self.metadata)` 将 metadata 键与预定于键合并, 存在碰撞风险
**修复**: 将 metadata 放入嵌套 key (如 `"__metadata__"`) 而不是顶层展开
**验证**: 添加测试验证键碰撞场景

---

## Round 2 — 🟠 P1 工程修复

### R2-01: lppl/engine.py 重复 logger 赋值

**文件**: `src/uniquant/brain/lppl/engine.py:28,955`
**问题**: 第 955 行 `logger = get_logger(__name__)` 覆盖第 28 行的赋值
**修复**: 删除第 955 行的重复 logger 定义
**验证**: `pytest tests/test_lppl*.py`

### R2-02: evt_risk.py max_drawdown 与 VOLATILITY_HIGH 量纲不匹配

**文件**: `src/uniquant/risk/evt_risk.py:247`
**问题**: `max_drawdown > RiskCalculationConstants.VOLATILITY_HIGH` — max_drawdown 是百分比(如 0.2), VOLATILITY_HIGH 是波动率阈值(如 40%)
**修复**: 将比较修复为 `max_drawdown > RiskCalculationConstants.DRAWDOWN_HIGH` 或统一量纲
**验证**: 确认风险检测逻辑正确

### R2-03: PortfolioSizer.allocate() 修改输入 dataclass

**文件**: `src/uniquant/risk/sizer.py:466`
**问题**: `sig.notional = max_notional` 直接修改输入 dataclass, 违反不可变性
**修复**: 使用 `dataclasses.replace()` 返回新实例
**验证**: 确认调用者 dataclass 不被修改

### R2-04: source_router.py fetch_with_fallback 忽略 method 参数

**文件**: `src/uniquant/data/source_router.py:232`
**问题**: DataFetcher 传入 `method="fetch"` 但实现忽略该参数
**修复**: 删除 `method` 参数或使其生效
**验证**: 确认 API 干净

### R2-05: eastmoney_base.py _convert_symbol 不处理北交所

**文件**: `src/uniquant/data/sources/eastmoney_base.py:138-145`
**问题**: 北交所股票 (8/4 开头) 被映射到深圳市场前缀 "0"
**修复**: 添加北交所代码分支
**验证**: 确认北交所代码正确映射

### R2-06: manager_logic.py 宽泛 except Exception

**文件**: `src/uniquant/ui/manager_logic.py:140-142`
**问题**: `except Exception as e:` 吞掉 ETF 扫描错误
**修复**: 窄化为已知异常类型
**验证**: 确认异常日志不丢失

### R2-07: dashboard.py 宽泛 except Exception

**文件**: `src/uniquant/ui/dashboard.py:614-623`
**问题**: `except Exception:` 绕过 CZSC 引擎工厂
**修复**: 窄化为 `(ImportError, RuntimeError)`
**验证**: 确认异常可追溯

---

## Round 3 — 🔵 P2 深度修复

### R3-01: cost_model.py 印花税日期逻辑不一致

**文件**: `src/uniquant/shared/cost_model.py:58,152`
**问题**: `calculate_total_cost()` 忽略 `trade_date` 使用固定税率; `CostConfig.calculate_sell_cost()` 使用日期感知税率
**修复**: 统一为日期感知路径
**验证**: 添加日期感知测试

### R3-02: time_provider.py naive datetime

**文件**: `src/uniquant/shared/time_provider.py:51-52`
**问题**: `RealTimeProvider.now()` 返回无时区 datetime
**修复**: 添加 UTC+8 (CST) 时区感知
**验证**: 确认时区感知兼容性

### R3-03: market_rules.py round_lot 卖单取整

**文件**: `src/uniquant/shared/market_rules.py:12-17`
**问题**: 卖单 `round_lot(is_sell=True)` 返回 `max(shares, 0)` 允许任意股数, 违反 A 股整手规则
**修复**: 对满手卖单使用整手取整, 仅允许末笔零股
**验证**: 添加卖单取整测试

### R3-04: market_constants.py 拼写错误

**文件**: `src/uniquant/shared/market_constants.py:1`
**问题**: `A_SHARD_BOARDS` → 应为 `A_SHARE_BOARDS`
**修复**: 修正拼写, 更新所有引用
**验证**: 确认无损坏

### R3-05: AsyncEventBus._pending_futures 无界增长

**文件**: `src/uniquant/shared/event_bus.py:64-68`
**问题**: 发布后追加 futures 到 `_pending_futures` 但从未清理
**修复**: 在 shutdown() 中或定期清理已完成的 futures
**验证**: 确认无内存泄漏

### R3-06: DiskCacheBackend.set() 忽略 ttl 参数

**文件**: `src/uniquant/shared/cache/backends.py:257,280`
**问题**: 接受 `ttl` 参数但存储当前时间而非到期时间
**修复**: 存储 `expires_at = now + ttl` 并在 `get()` 中检查
**验证**: 添加 TTL 到期测试

### R3-07: FSM 字符串比较脆性

**文件**: `src/uniquant/brain/fsm/fsm.py:323`
**问题**: `ma_status` 使用硬编码字符串 `"MA20 > MA60"` 比较, 而非常量
**修复**: 使用 `IndicatorThresholds.FSM_MA_SHORT/LONG` 格式化
**验证**: 确认常量变更不破坏评分

---

## Round 4 — 📋 文档对齐

### R4-01: AGENTS.md 更新

- eastmoney SSL `verify=True` 纠正 (非安全漏洞)
- DataPipelineService 活跃状态纠正
- P0-08 状态修正为"部分修复"
- factor_gate 默认值说明
- datetime.now() 措辞修正
- 文件数/LOC/测试数刷新

### R4-02: I_live_system_map.md 更新

- 活跃 bug 清单更新
- P0 修复验证状态更新
- 死代码清单更新

### R4-03: J_scorecard.md 更新

- eastmoney SSL 条目降级
- signal/db 覆盖率条目修正
- 测试通过率刷新

---

## Round 5 — ✅ 最终验证

```bash
# 1. 完整测试套件 (含 coverage)
pytest tests/ -q --tb=short --cov=src/uniquant/

# 2. Lint 检查
ruff check src/uniquant/

# 3. 导入健康检查
python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"

# 4. 配置健康检查
python3 -c "from uniquant.shared.config_loader import get_config; c = get_config(); print(c.get('base.data_lake.engine'))"

# 5. ServiceContainer 初始化
python3 -c "from uniquant.services import ServiceContainer; c = ServiceContainer(); c.initialize(); print('container ready')"
```

---

## 文件冲突矩阵

| 冲突组 | 文件 | 涉及任务 | 策略 |
|--------|------|----------|------|
| 1 | `research_pipeline.py` | R0-03 | 串行: R0-03 独享 |
| 2 | `cost_model.py` | R3-01 | 串行: R3 独享 |
| 3 | `market_rules.py` | R3-03, R3-04 | 串行: R3 独享 |
| 4 | `event_bus.py` | R3-05 | 串行: R3 独享 |

其余任务分布在互不冲突的不同文件中, 可并行执行。
