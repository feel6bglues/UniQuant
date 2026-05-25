# Project Audit Supplement & Fix Priority Roadmap

> **生成日期**: 2026-05-23  
> **范围**: 对 `PROJECT_AUDIT_20260523.md` 原始审计的交叉验证 + 代码库深层补充审计  
> **结论前置**: 原始审计 17 项声明经逐行代码验证全部成立（15 CORRECT / 2 PARTIALLY CORRECT，无误判）。补充审计新发现 17 个问题。合计 **34 项**。

---

## 目录

1. [原始审计验证结果](#一原始审计-17-项验证结果)
2. [补充审计：新发现 17 个问题](#二补充审计新发现-17-个问题)
3. [问题全景图（34 项）](#三问题全景图)
4. [Fix Priority Roadmap（三阶段修复路线图）](#四fix-priority-roadmap)

---

## 一、原始审计 17 项验证结果

### P0 级（全部 CORRECT）

| # | 声明 | 判定 | 关键证据 |
|---|------|------|----------|
| 1 | 导入路径损坏 | **CORRECT** | `tests/test_czsc_engine.py:10` 导入 `uniquant.brain.czsc_engine`，实际路径是 `brain/czsc/czsc_engine.py`。三个测试文件全部使用旧扁平路径。 |
| 2 | 回测同根K线执行 | **CORRECT** | `src/uniquant/hands/backtest/engine.py:320-322` — 信号在 `row["close"]` 生成后立即用同一价格执行，构成 Lookahead Bias。 |
| 3 | 组合回测缺A股约束 | **CORRECT** | `portfolio_engine.py` 对比 `engine.py`：无 T+1 约束、无涨跌停检查、无印花税、无最低佣金、无 pre_close 参数。 |
| 4 | 离线策略使用未来数据 | **CORRECT** | `trade_ma`、`trade_str_reversal`、`trade_wyckoff` 三个函数全部使用 `df[df["date"] > as_of_date]` 遍历未来数据决定出场。 |
| 5 | 因子权重全样本泄露 | **CORRECT** | `scan_service.py:487-489` — 全样本计算 IC/IR 后对同一批数据加权，典型的 In-Sample Overfitting。`FactorAnalyzer` 虽有 `mode` 参数设计意识，但 pipeline 未使用 walk-forward。 |

### P1 级（8 CORRECT / 1 PARTIALLY CORRECT）

| # | 声明 | 判定 | 关键证据 |
|---|------|------|----------|
| 6 | 配置文件未全部加载 | **CORRECT** | `config_loader.py:66-69` 统一模式仅加载 `config.yaml`，忽略 `trading.yaml`、`factors.yaml`、`optimal_params.yaml`。 |
| 7 | AnalysisService 过耦合 | **CORRECT** | `_initialize_dependencies` 在 try/except 中初始化 7 个引擎，任一个导入失败 → `raise` 导致整个服务崩溃。运行时方法中还直接临时实例化 `StorageManager`、`RegimeDetector` 等多个对象。 |
| 8 | DataService 职责过多 | **CORRECT** | 单一类承担 13 种不同职责，`lake` 与 `storage_manager` 是别名但路径逻辑跨对象重复。 |
| 9 | 幸存者偏差 | **CORRECT** | `backtest.py:126` 从 `stock_list.csv` 加载（今日股票列表），代码第 415-418 行自认此偏差。 |
| 10 | 批量回测执行不完整 | **PARTIALLY CORRECT** | T+1 入场**已建模**（`backtest.py:269-270`），但部分成交和滑点确实缺失。 |
| 11 | PBO 使用随机 shuffle | **CORRECT** | `overfitting_detector.py:133-135` — `np.random.shuffle` 破坏时间顺序，docstring 声称的 CPCV 方法未实现（无 purging/embargo）。 |
| 12 | EVTRisk 名实不符 | **CORRECT** | 实际类名是 `HistoricalSimulationRisk`，`EVTRisk` 仅是别名。使用历史分位数法而非 GPD 拟合。 |
| 13 | PositionSizer 简化 | **CORRECT** | HK 手数硬编码 100，缺流动性/波动率/相关性整合。 |
| 14 | 优化器缺防护 | **CORRECT** | 无协方差收缩（Ledoit-Wolf）、无换手惩罚、无行业/板块约束、无基数约束。 |

### P2 级（2 CORRECT / 1 PARTIALLY CORRECT）

| # | 声明 | 判定 | 关键证据 |
|---|------|------|----------|
| 15 | 测试断言弱 | **PARTIALLY CORRECT** | 数据结构单元测试有精确断言，但集成层面 `test_run_backtest_simple` 仅 `isinstance(result, BacktestResult)`。 |
| 16 | DataValidator 修改输入 | **CORRECT** | 4 处原地修改：high/low 交换、high/low 覆盖、date 类型转换。 |
| 17 | 可选依赖影响覆盖率 | **CORRECT** | `backtrader` 条件 skip + 本地 parquet 数据 skip 均确认。 |

---

## 二、补充审计：新发现 17 个问题

> 以下问题原始审计**未覆盖**，本次通过深度审查 `ui/`、`signal/`、`data/sources/`、`shared/` 等模块发现。

### P0-N：严重问题（4 个）

#### P0-N1: 东方财富数据源 SSL 证书验证完全禁用

- **文件**: `src/uniquant/data/sources/eastmoney.py:75`
- **代码**: `response = self.session.get(url, ..., verify=False)`
- **风险**: TLS 证书验证被关闭，所有 HTTPS 请求可被中间人攻击劫持，行情数据可能被篡改。
- **修复**: 删除 `verify=False`；如确有证书问题，配置正确的 CA bundle。

#### P0-N2: JavaScript 代码注入风险

- **文件**: `src/uniquant/data/utils/js_executor.py:37, 56-68, 243`
- **代码**: `self._js_engine.eval(js_content)` 直接执行外部 `ths.js` 文件内容
- **风险**: 如果 `ths.js` 被恶意修改，可执行任意代码。第 56-68 行内联 JS 同样存在注入面。
- **修复**: 对 `ths.js` 做 SHA256 校验；fallback JS 逻辑 (base64) 删除，统一用已有的 Python `_generate_fallback_v_param()`。

#### P0-N3: 硬编码开发者个人路径

- **文件**: `src/uniquant/data/sources/tdx.py:58`
- **路径**: `/home/james/.local/share/tdxcfv/drive_c/tc`
- **风险**: 泄露开发者用户名 `james`；其他机器上路径不存在，通达信数据源完全不可用。
- **修复**: 移除硬编码，仅从 `config.yaml` 读取或使用通用默认路径。

#### P0-N4: `signal/quality.py` 运行时必崩溃 Bug

- **文件**: `src/uniquant/signal/quality.py:60`
- **代码**: `lead_time = target_prices.idxmax().total_seconds() / 3600`
- **风险**: `pd.Series.idxmax()` 在 datetime index 上返回 `Timestamp`，`Timestamp` **没有** `total_seconds()` 方法（该方法属于 `Timedelta`）。任何运行时调用必然 `AttributeError`。
- **修复**: 改为 `(target_prices.idxmax() - target_prices.index[0]).total_seconds() / 3600`

### P1-N：高风险问题（6 个）

#### P1-N1: UI 健康检查导入路径全部错误

- **文件**: `src/uniquant/ui/health_check.py:28-36`
- **问题**: 使用 `src.brain.fsm`、`src.brain.czsc_engine` 等路径而非 `uniquant.brain.fsm`。除非设置特殊 PYTHONPATH，所有 import 失败，健康检查面板永远显示全部模块为 ❌。
- **修复**: 所有 `src.` 前缀替换为 `uniquant.`

#### P1-N2: 函数签名不匹配导致运行时崩溃

- **文件**: `src/uniquant/ui/components.py:350` vs `src/uniquant/ui/dashboard.py:649`
- **问题**: `plot_czsc_full_chart(symbol, czsc_data)` 定义 2 参数，但调用时传 6 个关键字参数 → `TypeError`。
- **修复**: 对齐 `components.py` 中的函数签名。

#### P1-N3: LPPL Calculator 缓存无限制 → 内存泄漏

- **文件**: `src/uniquant/brain/lppl/calculator.py:32`
- **代码**: `self._fit_cache = {}`
- **问题**: 字典缓存无 TTL 过期、无 maxsize 限制。长时间运行（每日扫描数百指数 × 多窗口）时无限增长。
- **修复**: 使用 `functools.lru_cache` 或 `cachetools.TTLCache`。

#### P1-N4: 并行计算超时后已完成结果全部丢失

- **文件**: `src/uniquant/brain/lppl/computation.py:183, 209`
- **问题**: `Parallel(... timeout=300)` 整体超时 → 所有已完成结果全部丢失。单窗口 `future.result(timeout=120)` 同样无兜底。
- **修复**: 捕获超时异常后保留已完成的部分结果；超时值配置化。

#### P1-N5: 信号一致性阈值聚合时丢失原始信号

- **文件**: `src/uniquant/signal/aggregator.py:129-130`
- **问题**: `consensus_threshold` 返回 None 时直接返回空 `AggregatedSignal()`，丢失 `contributing_signals` 和 `sources` 信息。
- **修复**: 返回包含原始信号信息的默认对象。

#### P1-N6: LPPL Regime 检测 MA 回退值导致趋势假阳性

- **文件**: `src/uniquant/brain/lppl/regime.py:85-98`
- **问题**: 数据不足时用 `close[-1]` 作为所有 MA 的回退值 → `current > mas[60] > mas[120] > mas[250]` 永远为 True（所有 MA 都等于当前价）→ `trend_up = True` 为假阳性。
- **修复**: 数据不足时标记为 `"unknown"` 并降低置信度。

### P2-N：中等问题（7 个）

#### P2-N1: 常量定义严重重复

- **文件**: `src/uniquant/shared/constants.py`
- **问题**: `MAJOR_INDEXES` 字典在 `MarketConstants` 类内（第 94 行）和模块级别（第 481 行）各定义一次。文件后缀常量（`FILE_SUFFIX_*` vs `CSV_SUFFIX` 等）也重复。
- **修复**: 保留一处，删除重复。

#### P2-N2: Wyckoff 模块大量硬编码阈值

- **文件**: `src/uniquant/brain/wyckoff/rules.py:36-45, 82-101` + `classifiers.py:53-70, 247`
- **问题**: 量能阈值 (2.0, 1.3, 0.7, 0.4)、回撤阈值 (3%, 5%)、仓位比例 (0.38, 0.58, 0.50, 0.62)、涨跌停映射全部硬编码。
- **修复**: 移至 `WyckoffConfig` 或 `RuleEngineConfig`，通过 YAML 统一管理。

#### P2-N3: 异常捕获过于宽泛

- **文件**: 全项目 20+ 处
- **位置（代表性）**:
  - `src/uniquant/data/lake/storage_manager.py` — 8 处 `except Exception`
  - `src/uniquant/data/parsers/tdx_parser.py` — 6 处 `except Exception`
  - `src/uniquant/brain/lppl/calculator.py:93` — `except Exception as e:`
  - `src/uniquant/brain/lppl/data_manager.py:118` — `except Exception as e:`
- **风险**: 裸捕获隐藏 `AttributeError`、`NameError` 等编程错误，增加调试难度。
- **修复**: 替换为具体异常类型（如 `except (ValueError, IOError, OSError) as e:`）。

#### P2-N4: `interfaces.py` 类型提示不精确

- **文件**: `src/uniquant/shared/interfaces.py:152`
- **代码**: `czsc_bottom: Any`
- **修复**: 改为 `czsc_bottom: Optional[float]`

#### P2-N5: frozen dataclass 包含可变 list

- **文件**: `src/uniquant/shared/constants.py:1110-1118`
- **问题**: `@dataclass(frozen=True)` 但 `short_windows: list[int]` 等字段是可变类型。frozen 只能防止重新赋值，无法防止 `.append()`。
- **修复**: 改为 `tuple[int, ...]`。

#### P2-N6: Signal Database 时间戳处理不一致

- **文件**: `src/uniquant/signal/db.py:89-95`
- **问题**: `datetime.now().timestamp() - minutes * 60` 生成浮点时间戳，混用 `DateTime` 列类型和 `datetime` 对象，可能导致时区相关 bug。
- **修复**: 统一使用 `datetime.now() - timedelta(minutes=minutes)`。

#### P2-N7: LPPL 模块数据管理器异常吞没

- **文件**: `src/uniquant/brain/lppl/data_manager.py:118` + `calculator.py:93`
- **问题**: 裸 `except Exception` 捕获全部异常，无法定位根本原因。
- **修复**: 使用具体异常类型。

---

## 三、问题全景图

| 级别 | 原始审计 | 补充审计 | 合计 |
|------|----------|----------|------|
| **P0** | 5 | 4 | **9** |
| **P1** | 9 | 6 | **15** |
| **P2** | 3 | 7 | **10** |
| **总计** | **17** | **17** | **34** |

### 按问题域分类

| 问题域 | 数量 | 核心风险 |
|--------|------|----------|
| 导入/包管理 | 4 | CI 不可信，测试无法收集，UI 健康检查全红 |
| 回测执行语义 | 4 | 回测结果不可交易，Lookahead Bias |
| 数据泄露/前视偏差 | 3 | 策略表现虚高 |
| 安全/硬编码 | 3 | SSL 禁用、JS 代码注入、路径泄露 |
| 配置管理 | 2 | 配置与运行时行为不一致 |
| 架构耦合 | 3 | 模块初始化脆弱，单点失败 |
| 运行时 Bug | 3 | 功能直接崩溃（quality.py、函数签名不匹配） |
| 数值/量化正确性 | 5 | LPPL 缓存泄漏、阈值硬编码、MA 回退假阳性 |
| 测试质量 | 4 | 断言弱、覆盖率不稳定 |
| 代码质量 | 3 | 类型不精确、异常宽泛、常量重复 |

---

## 四、Fix Priority Roadmap

### Phase 1: 止血（本周，9 项）

> **目标**: 修复会导致运行时崩溃、安全隐患、CI 不可用的问题。

| 序号 | ID | 问题 | 文件 | 行号 | 修复方案 |
|------|-----|------|------|------|----------|
| 1 | P0-N1 | SSL 验证禁用 | `data/sources/eastmoney.py` | 75 | 删除 `verify=False` |
| 2 | P0-N4 | `quality.py` AttributeError | `signal/quality.py` | 60 | 修正为 `(idxmax() - index[0]).total_seconds()` |
| 3 | P0-N3 | 硬编码开发者路径 | `data/sources/tdx.py` | 58 | 移除，仅从 config 读取 |
| 4 | P0-N2 | JS 代码注入风险 | `data/utils/js_executor.py` | 37,56-68 | SHA256 校验 ths.js；删除内联 JS fallback |
| 5 | P0-1 | 导入路径损坏 | `tests/test_czsc_engine.py` 等 | 10, 9, 9 | 修正为子包路径；`conftest.py` 移除 sys.path hack |
| 6 | P1-N1 | UI 健康检查导入全错 | `ui/health_check.py` | 28-36 | `src.` → `uniquant.` |
| 7 | P1-N2 | `plot_czsc_full_chart` 签名不匹配 | `ui/components.py:350` vs `dashboard.py:649` | - | 对齐函数签名 |
| 8 | P0-4 | 策略函数名误导 | `hands/strategies/ma_cross.py` 等 | 24, 21, 88 | `trade_*` → `evaluate_*` 重命名 + docstring |
| 9 | P1-12 | EVTRisk 类名纠正 | `risk/evt_risk.py` | 24, 391 | 模块/类重命名为 `HistoricalSimulationRisk` |

### Phase 2: 修复量化可信度（本月，11 项）

> **目标**: 确保回测结果可交易，消除前视偏差和数据泄露。

| 序号 | ID | 问题 | 文件 | 修复方案 |
|------|-----|------|------|----------|
| 10 | P0-2 | 回测同根K线执行 | `hands/backtest/engine.py:320-322` | t 日生成信号 → t+1 日 open 执行 |
| 11 | P0-3 | 组合回测缺 A 股约束 | `hands/backtest/portfolio_engine.py` | 补齐 T+1/涨跌停/印花税/最低佣金/前收盘价 |
| 12 | P0-5 | 因子权重全样本泄露 | `services/scan_service.py:487-489` | 引入 walk-forward window；IC/IR 用过去窗口计算 |
| 13 | P1-9 | 幸存者偏差 | `hands/strategies/backtest.py:126` | 引入历史 Universe 快照（point-in-time constituents） |
| 14 | P1-10 | 批量回测缺失部分成交/滑点 | `hands/strategies/backtest.py` | 添加 partial fill 模型 + slippage 模型 |
| 15 | P1-11 | PBO 随机 shuffle | `hands/backtest/overfitting_detector.py:133` | 实现真正的 purged time-series CV（purging + embargo） |
| 16 | P1-6 | 配置文件未全部加载 | `shared/config_loader.py:66-69` | 统一加载策略：合并所有 yaml 或明确 ignore 并告警 |
| 17 | P1-N3 | LPPL 缓存内存泄漏 | `brain/lppl/calculator.py:32` | 使用 `functools.lru_cache(maxsize=N)` |
| 18 | P1-N4 | LPPL 并行超时丢失结果 | `brain/lppl/computation.py:183,209` | 捕获超时后保留已完成子任务结果 |
| 19 | P1-N6 | LPPL Regime MA 回退假阳性 | `brain/lppl/regime.py:85-98` | 数据不足时返回 `"unknown"` + 低置信度 |
| 20 | P1-N5 | 信号聚合丢失原始信息 | `signal/aggregator.py:129-130` | 返回带贡献信号信息的默认对象 |

### Phase 3: 加固与重构（下月，14 项）

> **目标**: 架构解耦、代码质量提升、测试加固。

| 序号 | ID | 问题 | 文件 | 修复方案 |
|------|-----|------|------|----------|
| 21 | P1-7 | AnalysisService 过耦合 | `services/analysis_service.py` | 延迟初始化 + 独立工厂；容错降级 |
| 22 | P1-8 | DataService 职责拆分 | `services/data_service.py` | 按职责拆分为 CacheService / QueryService / BatchService |
| 23 | P1-13 | PositionSizer 完善 | `risk/sizer.py:80-99` | 添加流动性/波动率/相关性整合；手数配置化 |
| 24 | P1-14 | 优化器加防护 | `risk/portfolio_optimizer.py:59` | Ledoit-Wolf 收缩 + 换手惩罚 + 行业约束 |
| 25 | P2-16 | DataValidator 不修改输入 | `data/pipeline/data_validator.py:31-65` | 返回新 DataFrame 或显式 `inplace` 参数 |
| 26 | P2-15 | 测试断言加强 | `tests/test_backtest_engine.py` | 集成测试验证 cash/equity/PnL 精确值 |
| 27 | P2-17 | 测试覆盖稳定性 | `tests/test_hands_strategies.py` 等 | 移除条件 skip；使用 mock 数据或 docker 化环境 |
| 28 | P2-N1 | 常量去重 | `shared/constants.py:94,481` | 删除重复定义 |
| 29 | P2-N2 | Wyckoff 阈值配置化 | `brain/wyckoff/rules.py` + `classifiers.py` | 移至 `WyckoffConfig` YAML 管理 |
| 30 | P2-N3 | 异常捕获精确化 | 全项目 20+ 处 | `except Exception` → 具体异常类型 |
| 31 | P2-N4 | 类型提示精确化 | `shared/interfaces.py:152` | `Any` → `Optional[float]` |
| 32 | P2-N5 | frozen dataclass 安全化 | `shared/constants.py:1110` | `list` → `tuple` |
| 33 | P2-N6 | Signal DB 时间戳统一 | `signal/db.py:89-95` | 使用 `timedelta` 替代浮点运算 |
| 34 | P2-N7 | LPPL 模块异常处理 | `brain/lppl/data_manager.py` + `calculator.py` | 细化异常类型 |

---

## 附录：验证方法论

对原始审计 17 项声明的验证采用以下方法：

1. **逐行代码审查**: 每个声明对应文件均完整读取并对比审计描述
2. **路径存在性验证**: 使用 Glob 确认旧路径文件是否真实存在
3. **语义交叉对比**: 如 `engine.py` vs `portfolio_engine.py` 的 A 股约束特性逐接口对比
4. **数据流分析**: 如 `scan_service.py` 中因子权重的全链路追踪

**判定标准**:
- **CORRECT**: 代码行为与审计描述完全一致
- **PARTIALLY CORRECT**: 核心问题存在但细节有偏差
- **INCORRECT**: 审计描述与代码行为矛盾（本次验证中未出现）