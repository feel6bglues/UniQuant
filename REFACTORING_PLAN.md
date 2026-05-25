# UniQuant 重构工作计划

> 基于 2026-05-23 深度代码审计生成。审计覆盖 60+ 源文件、59 个测试文件、28 个问题点。
> 版本: v1.0

---

## 目录

1. [方法论与原则](#1-方法论与原则)
2. [重构阶段总览](#2-重构阶段总览)
3. [Phase-0: 基础设施修复（3-5天）](#phase-0-基础设施修复3-5天)
4. [Phase-1: 回测引擎修复（5-7天）](#phase-1-回测引擎修复5-7天)
5. [Phase-2: 信号与决策链修复（5-7天）](#phase-2-信号与决策链修复5-7天)
6. [Phase-3: 因子系统修复（3-5天）](#phase-3-因子系统修复3-5天)
7. [Phase-4: 工程债务清理（5-7天）](#phase-4-工程债务清理5-7天)
8. [Phase-5: 死代码清理（2-3天）](#phase-5-死代码清理2-3天)
9. [验证与验收标准](#9-验证与验收标准)
10. [附录: 问题点索引](#10-附录-问题点索引)

---

## 1. 方法论与原则

### 1.1 优先级矩阵

| 紧迫度\影响力 | 高影响 | 低影响 |
|---|---|---|
| **高紧迫度** | Phase-0 (基础设施), Phase-1 (回测引擎), Phase-2 (信号决策链), Phase-3 (因子系统) | Phase-4 (工程债务) |
| **低紧迫度** | Phase-5 (死代码清理) | (忽略) |

### 1.2 编码规范

- 所有修复必须附带对应的回归测试
- 禁止引入新的 `sys.path.insert` 模式
- 函数签名中废弃函数按 `deprecated` -> `warnings.warn` -> 移除三步走
- 所有 DataFrame 修改必须显式 `.copy()` 或返回新 DataFrame
- 不允许 import 链超过 3 级的循环依赖（惰性导入不解决设计问题）

### 1.3 测试要求

- 每个 PR 必须包含: 1+ 单元测试 + 1+ 集成测试
- `PortfolioEngine` 测试覆盖率从 0% 提升至 60%+
- `BacktestEngine` 测试覆盖率从 ~65% 提升至 80%+
- 新增 `BacktestEngine <-> PortfolioEngine` 一致性测试(不少于 5 个场景)

---

## 2. 重构阶段总览

| 阶段 | 名称 | 估计 | 包含问题 | 交付物 |
|---|---|---|---|---|
| **Phase-0** | 基础设施修复 | 3-5天 | #9, #10 | 可复现的测试环境、统一配置加载 |
| **Phase-1** | 回测引擎修复 | 5-7天 | #1, #4, #13, NEW-7, NEW-8, #23 | 正确的回测定价、T+1/涨跌停、完整佣金 |
| **Phase-2** | 信号与决策链修复 | 5-7天 | NEW-2, NEW-3, NEW-1, NEW-5, #5 | CZSC信号正确传递、决策链统一 |
| **Phase-3** | 因子系统修复 | 3-5天 | #2, #3, #17 | 滚动窗口IC、训练/测试分割 |
| **Phase-4** | 工程债务清理 | 5-7天 | #6, #7, #8, NEW-6, NEW-9, NEW-10, #11, #14 | 命名纠正、装饰器修复、重复代码合并 |
| **Phase-5** | 死代码清理 | 2-3天 | #15, #16, #20, NEW-4 | 死代码删除、缓存修复、幸存者偏差标记 |

**总估计: 23-34天(约5-7周)**

---

## 3. Phase-0: 基础设施修复(3-5天)

**目标: 让项目可构建、可测试、可复现。** 所有后续修复都依赖于一个稳定的测试基础设施。

### Task 0.1: 修复虚拟环境 + 可编辑安装(#9)

- **状态**: open
- **估计**: 1天
- **文件**: `pyproject.toml`, `tests/conftest.py`

**问题**: tests/conftest.py:10 使用 `sys.path.insert(0, str(project_root))`。虚拟环境 `.venv/` 的 Python 解释器路径指向不存在的位置。

**修复步骤**:
1. 重建虚拟环境:
   ```
   python3 -m venv --clear .venv
   source .venv/bin/activate
   pip install --upgrade pip
   ```
2. 安装带 `[test]` extra 的可编辑包:
   ```
   pip install -e ".[test]"
   ```
3. 验证 `pyproject.toml` 的 `[project.optional-dependencies]` 包含 `test` 章节
4. 删除 tests/conftest.py:5-13 的 `sys.path.insert` 块
5. 验证 `pytest tests/` 从头到尾运行成功

**验收标准**: `python3 -m pytest tests/test_import_state.py` 在无 `sys.path.insert` 的情况下通过。

### Task 0.2: 统一配置加载(#10)

- **状态**: open
- **估计**: 1-2天
- **文件**: `shared/config_loader.py`, `config/*.yaml`

**问题**: `trading.yaml`、`factors.yaml`、`optimal_params.yaml` 由 4+ 个模块独立加载，`GlobalConfig` 不管理它们。

**修复步骤**:
1. `GlobalConfig._load_config()` 新增 `trading.yaml`、`factors.yaml`、`optimal_params.yaml` 到加载列表
2. 规范化 DATA_DIR 和 LAKE_DIR 的默认路径一致性
3. 删除以下文件中的独立 `yaml.safe_load()` 调用:
   - `hands/strategies/wyckoff.py:32`
   - `hands/strategies/wyckoff_strategy.py:34`
   - `shared/loader.py:9`
   - `shared/cost_model.py:75`
4. 替换为 `GlobalConfig.get("trading.xxx")` 统一调用

**验收标准**: 删除独立 yaml 加载代码后，原有功能正常运行。

### Task 0.3: 依赖缺失处理

- **状态**: open
- **估计**: 0.5-1天
- **文件**: `pyproject.toml`

**问题**: 可选依赖导入失败时静默降级，可能导致测试误报。

**修复步骤**:
1. 检查 `pyproject.toml` 中所有 `[project.optional-dependencies]`
2. 将核心依赖标记为必需，研究工具标记为可选
3. 可选依赖的降级应做 logger.warning 而非静默
4. 引入依赖检查器在启动时验证关键依赖

**验收标准**: 启动日志明确显示缺失的可选依赖。

---

## 4. Phase-1: 回测引擎修复(5-7天)

**目标: 让回测结果可信。**

### Task 1.1: 修复 Same-Bar Fill(#1) [P0]

- **状态**: open
- **估计**: 2天
- **文件**: `hands/backtest/engine.py`

**问题**: `run_backtest()` 信号在 `idx` 生成，成交用 `close[idx]`。正确: 信号 `close[t]`, 成交 `open[t+1]`。

**修复步骤**:
1. 修改主循环 `range(len(df))` -> `range(len(df) - 1)`
2. 成交价使用 `df.iloc[idx + 1]["open"]`
3. 预收盘价使用 `df.iloc[idx]["close"]`
4. 时间戳使用 `dates[idx + 1]`
5. 更新并新增测试验证信号和成交不在同一 bar

**验收标准**: 原有测试全部通过(接受 <0.5% 数值偏差)。新测试验证信号/成交时间分离。

### Task 1.2: PortfolioEngine 补齐缺失功能(#4) [P0]

- **状态**: open
- **估计**: 2-3天
- **文件**: `hands/backtest/portfolio_engine.py`

**问题**: 缺失 T+1 约束、涨跌停检查、最低佣金、印花税、买入日期跟踪。

**修复步骤**:
- a) Position 数据类新增 `buy_date: Optional[pd.Timestamp]` 字段
- b) `_calculate_commission()` 增加最低佣金和印花税
- c) 在 `close_position()` 添加 T+1 检查(参考 engine.py:114-139)
- d) 在 `open_position()` 和 `close_position()` 添加涨跌停检查
- e) Kelly 仓位: `avg_loss == 0` 时回退至固定比例(NEW-7)
- f) `open_position()` 尊重调用者显式传递的 `shares > 0`
- g) 新增完整测试文件 `tests/test_portfolio_engine.py`

**验收标准**: PortfolioEngine 与 BacktestEngine 在相同输入下差异 <1%。T+1/涨跌停/最低佣金全部生效。

### Task 1.3: 在 Cross-Sectional Backtest 中应用 MIN_COMMISSION(#13)

- **状态**: open
- **估计**: 0.5天
- **文件**: `hands/strategies/backtest.py`

**问题**: 纯百分比成本模型，未应用最低佣金。

**修复步骤**:
- 方案B(简化): `MIN_COMMISSION_PCT = MIN_COMMISSION / 100000`(假设平均单笔 10 万)
- `effective_buy = max(COMMISSION_PCT, MIN_COMMISSION_PCT)`
- 文档中明确标记简化方案的假设值

**验收标准**: 文档说明最低佣金的处理方式及假设。

### Task 1.4: StorageManager 原子写入修复(NEW-8)

- **状态**: open
- **估计**: 0.5天
- **文件**: `data/lake/storage_manager.py`

**问题**: `unlink()` + `rename()` 两步操作非原子。

**修复步骤**:
1. `temp_path.rename(file_path)` -> `os.replace(temp_path, file_path)`
2. 移除手动 `unlink()`
3. 同样修复 `save_factor()` 和 `write_data()`
4. 读操作添加 `FileLock`

**验收标准**: 并发读写不会导致损坏或 `FileNotFoundError`。

### Task 1.5: 修复回测测试质量断言(#23)

- **状态**: open
- **估计**: 0.5天
- **文件**: `tests/test_backtest_engine.py`

**修复步骤**:
1. 在 `test_full_backtest_cycle` 中加入:
   - `assert result.total_trades >= 5`
   - `assert result.win_rate > 0`
   - `assert result.max_drawdown > 0`
   - `assert result.sharpe_ratio != 0`
2. 新增 `test_backtest_pnl_reasonable`

**验收标准**: 断言通过且不因种子变化脆弱。

---

## 5. Phase-2: 信号与决策链修复(5-7天)

**目标: 让生产决策链使用所有引擎信号，回测忠实复现生产逻辑。**

### Task 2.1: 修复 CZSC 第三类买点信号丢失(NEW-2) [P0]

- **状态**: open
- **估计**: 0.5天
- **文件**: `brain/czsc/czsc_engine.py`, `services/analysis_service.py`

**问题**: `czsc_engine` 返回 `is_3rd_buy`，但 `analysis_service` 读取 `third_buy`。键名不匹配导致信号永远 False。

**修复步骤**:
1. 统一键名为 `"is_3rd_buy"`(与 `MarketSignalContext` 属性名一致)
2. 在 `analysis_service.py:949` 将 `czsc_result.get("third_buy", False)` 改为 `czsc_result.get("is_3rd_buy", False)`
3. 新增测试验证 `data_pack` 包含正确的 `is_3rd_buy` 值

**验收标准**: 检测到第三类买点时，`DecisionBrain` 正确收到 `ctx.is_3rd_buy == True`。

### Task 2.2: 统一生产决策与回测决策逻辑(NEW-3) [P0]

- **状态**: open
- **估计**: 3-4天
- **文件**: `brain/fsm/fsm.py`, `signal/aggregator.py`, `hands/backtest/signal_integrator.py`

**问题**: 生产用硬编码加分，回测用加权平均/多数投票。两套完全不同的决策路径。

**修复步骤**:

**阶段 2.2a: 统一信号表示**(1天)
1. 定义统一 `Signal` 接口(`interfaces.py`)
2. `Signal` 接口包含: `engine_type`, `direction`, `confidence[0,1]`, `weights`, `raw_metrics`
3. `MarketSignalContext` 从统一 `Signal` 派生

**阶段 2.2b: 统一聚合方法**(1-2天)
1. `DecisionBrain._calculate_score()` 替换为 `SignalAggregator.aggregate()` 调用
2. `DecisionBrain` 保持 veto/buy_blocker/transition 逻辑不变

**阶段 2.2c: 一致性回归测试**(1天)
1. 创建 `tests/test_decision_path_consistency.py`
2. 定义 5 个标准场景: 强买入、强卖出、中性、Wyckoff、极端风险
3. 场景数据固化在 fixture 中

**验收标准**: 5 个标准场景中，生产与回测路径的决策输出一致。

### Task 2.3: 修复 risk_level KeyError(NEW-1) [P0]

- **状态**: open
- **估计**: 0.5天
- **文件**: `risk/evt_risk.py`, `brain/fsm/fsm.py`

**问题**: `fsm.py:362` 访问 `evt_metrics["risk_level"]`，但 `calculate_metrics()` 的返回字典中无该键。

**修复步骤**:
1. 在 `calculate_metrics()` 中添加 `risk_level` 键
2. 实现 `_compute_risk_level()`: 基于 regime + max_drawdown + var_95 的综合评分
3. `ctx.returns` 为 None/空时默认 `risk_scaler = 1.0`

**验收标准**: 不抛出 `KeyError`。`risk_level` 为 "CRITICAL"/"HIGH"/"NORMAL" 之一。

### Task 2.4: 修复 FSM 分析缓存死代码(NEW-5)

- **状态**: open
- **估计**: 0.5天
- **文件**: `services/analysis/fsm_analysis_engine.py`, `services/analysis/signal_service.py`

**问题**: 缓存写入逻辑在 `if df is None:` 内部，但执行到此处时 df 永远非 None。

**修复步骤**:
1. 将缓存写逻辑移出 `if df is None:` 块
2. 返回前无条件调用 cache_set
3. cache_key 依赖于 symbol, lookback_period, timestamp

**验收标准**: 第二次调用命中缓存，运行时间显著缩短。

### Task 2.5: 策略函数命名与守卫(#5)

- **状态**: open
- **估计**: 1天
- **文件**: `hands/strategies/ma_cross.py`, `str_reversal.py`, `wyckoff.py`, `regime.py`, `registry.py`

**问题**: 4 个 `trade_*` 函数实际是离线标注函数，名称暗示可交易。

**修复步骤**:
1. 添加 `mode` 参数，默认 `"backtest"`
2. `mode == "live"` 时抛出 `NotImplementedError`
3. 添加类型注解 `LabelResult` vs `SignalResult`
4. Docstring 标注: "OFFLINE BACKTEST LABEL -- NOT A TRADEABLE SIGNAL"

**验收标准**: `trade_ma(df, as_of_date, mode="live")` 抛出清晰错误。

---

## 6. Phase-3: 因子系统修复(3-5天)

### Task 3.1: 因子的训练/测试分割(#3) [P0]

- **状态**: open
- **估计**: 2天
- **文件**: `brain/factors/analyzer.py`, `brain/factors/composer.py`, `services/scan_service.py`

**问题**: `compute_ic_ir` 在全样本上计算 IC，`compute_weighted_factor` 在同样全样本上打分。

**修复步骤**:
1. 在 `analyze_factors()` 中引入时间分割: `train_df, test_df = temporal_split(df, test_size=0.3)`
2. `compute_ic_ir` 仅在 `train_df` 上计算
3. `compose_scores` 在全 `combined_df` 上打分
4. `FactorComposer` 新增 `expanding_ic` 方法(滚动窗口)
5. 新增测试验证 |train_IC - test_IC| > 0.1 时触发过拟合警告

**验收标准**: 训练/测试 IC 差异在报告中显示，过拟合时发出警告。

### Task 3.2: 前瞻性守卫在调用链激活(#2)

- **状态**: open
- **估计**: 1天
- **文件**: `brain/factors/analyzer.py`, `services/scan_service.py`

**问题**: `mode="live"` 守卫存在且正确，但无调用方传递此参数。

**修复步骤**:
1. `scan_service.py` 暴露 `mode` 参数
2. CLI/UI 入口新增 `--mode` 参数: `backtest` / `live`
3. `--mode live` 时使用滚动窗口，不 shift(-period)

**验收标准**: `--mode live` 运行时 `compute_ic_ir` 不抛出 ValueError。

### Task 3.3: LPPL 计算缓存(#17)

- **状态**: open
- **估计**: 1天
- **文件**: `brain/lppl/engine.py`, `brain/lppl/calculator.py`

**问题**: `_process_window` 每次创建新 `LPPLCalculator` 实例，`_fit_cache` 缓存无效。

**修复步骤**:
1. `LPPLEngine` 中创建一次性 `LPPLCalculator` 实例在所有调用间共享
2. 或将 `_fit_cache` 提升为类级缓存
3. 重叠窗口的 LPPL 拟合命中缓存

**验收标准**: 性能提升 30%+。

---

## 7. Phase-4: 工程债务清理(5-7天)

### Task 4.1: 命名纠正(#6, #7, #8)

- **状态**: open
- **估计**: 2天
- **文件**: 多个

**问题**: `evt_risk.py` 文件/别名/日志均错误命名为 "EVT"。`FSM.infer_state` 是 MA 交叉。

**修复步骤**:

a) **evt_risk.py 重命名**:
1. 创建 `risk/historical_risk.py`，类名 `HistoricalSimulationRisk`
2. 保留 `risk/evt_risk.py` 作为废弃封装，发出 `DeprecationWarning`
3. 更新所有引用: `from historical_risk` 而非 `evt_risk`
4. `EVTRiskError` -> `HistoricalRiskError`(保留别名，标记废弃)
5. 更新 docstring 和日志消息

b) **FSM 命名澄清**:
1. `FSM.infer_state` 新增 `trend_classifier()` 语义别名
2. 缩小 `FSM` 类 docstring 范围

**验收标准**: 废弃警告可见，无破坏性变化。

### Task 4.2: 修复装饰器堆叠导致重试失效(NEW-6)

- **状态**: open
- **估计**: 0.5天
- **文件**: `shared/error_handling.py`

**问题**: `handle_network_errors` 中 `@retry_on_exception`(外层) + `@handle_errors`(内层)。内层吞异常后外层不触发重试。

**修复步骤**:
1. 交换装饰器顺序: `@handle_errors` 在外层兜底，`@retry_on_exception` 在内层先重试
2. 添加测试验证重试在被捕获异常时正确触发

**验收标准**: 函数抛出异常时触发重试，全部失败后返回 `default_return`。

### Task 4.3: 合并重复的 run_fsm_analysis 实现(NEW-10)

- **状态**: open
- **估计**: 1天
- **文件**: `services/analysis/fsm_analysis_engine.py`, `services/analysis/signal_service.py`

**问题**: 两个 ~130 行的 `run_fsm_analysis()` 几乎相同。

**修复步骤**:
1. 保留 `FsmAnalysisEngine.run_fsm_analysis()` 作为规范实现
2. `SignalAnalysisService.run_fsm_analysis()` 改为调用前者
3. `SignalAnalysisService` 版本标记 `@deprecated`

**验收标准**: 两个调用入口返回一致的结果。

### Task 4.4: AnalysisService 内联引擎创建重构(NEW-9)

- **状态**: open
- **估计**: 1天
- **文件**: `services/analysis_service.py`

**问题**: 引擎在 `_run_*` 方法内内联创建，`AnalysisEngine` 对象从未被主流水线使用。

**修复步骤**:
1. `__init__()` 中创建引擎延迟初始化属性
2. `_run_regime_detection()` 等改为调用 `self.regime_engine.analyze()`
3. `DataFetcher` 在服务级别共享

**验收标准**: `AnalysisService` 惰性初始化引擎，第一次分析时创建。

### Task 4.5: DataValidator 防御性复制(#11)

- **状态**: open
- **估计**: 0.5天
- **文件**: `data/pipeline/data_validator.py`

**问题**: `validate()` 在 5 处修改调用者 DataFrame，无 `.copy()`。

**修复步骤**:
1. `validate()` 内部执行任何修改前 `df = df.copy()`
2. 新增 `validate_and_clean()` 返回 `Tuple[bool, pd.DataFrame]`
3. `validate()` 标记 deprecated

**验收标准**: 调用 `validate()` 后调用方原始 DataFrame 不变。

### Task 4.6: 修复循环依赖(#14)

- **状态**: open
- **估计**: 0.5天
- **文件**: `hands/strategies/regime.py`

**问题**: `regime.py:40` 从 `backtest.py` 导入 COST_BUY/COST_SELL，形成 `backtest -> registry -> regime -> backtest` 循环链。

**修复步骤**:
1. 导入改为 `from uniquant.shared.cost_model import COST_BUY, COST_SELL`

**验收标准**: 删除 `backtest.py` 中 COST_BUY 的 import 后 `regime.py` 不崩溃。

---

## 8. Phase-5: 死代码清理(2-3天)

### Task 5.1: DI 容器移除(NEW-4)

- **状态**: open
- **估计**: 0.5天
- **文件**: `shared/di_container.py`

**问题**: `DIContainer` singleton 从未被生产代码导入或使用。

**修复步骤**:
1. 标记 deprecated
2. 确认所有依赖已迁移
3. 一个版本后删除

**验收标准**: `grep -r "DIContainer" src/` 无结果(注释除外)。

### Task 5.2: 幸存者偏差标记与退市股票集成(#15, #16)

- **状态**: open
- **估计**: 1天
- **文件**: `hands/strategies/backtest.py`

**问题**: 回测宇宙使用今天股票列表，`is_delisted()` 存在但未被使用。

**修复步骤**:
1. `process_stock()` 集成 `is_delisted()` 检查
2. 在结果中添加 `delisted: true` 标记
3. 统计提供 `with_delisted / without_delisted` 对比
4. `universe_has_delisted_stocks` 改为动态计算

**验收标准**: 报告中明确标识幸存者偏差的估算影响。

### Task 5.3: FSM 状态持久化加锁(#20)

- **状态**: open
- **估计**: 0.5天
- **文件**: `brain/fsm/fsm.py`

**问题**: JSON 状态文件在并发读写时可能损坏。

**修复步骤**:
1. 使用 `filelock` 或 `fcntl.flock` 保护读写
2. 写入使用原子模式: 临时文件 -> `os.replace()`
3. 添加超时机制

**验收标准**: 10 个并发进程下 FSM 状态文件不损坏。

### Task 5.4: 错误统计导出

- **状态**: open
- **估计**: 0.5天
- **文件**: `shared/error_handling.py`

**问题**: `_error_stats` 被累加但 `get_error_stats()` 从未被调用。

**修复步骤**:
1. 将 `get_error_stats()` 接入 `HealthService`
2. 添加监控: 某错误类型 1h > 10 次发出告警

**验收标准**: 错误统计可通过 `HealthService` 查询。

---

## 9. 验证与验收标准

### 9.1 回归测试标准

| 阶段 | 新增测试 | 覆盖率要求 |
|---|---|---|
| Phase-0 | 5+ | 基础设施 90%+ |
| Phase-1 | 20+ | PortfolioEngine 60%+, BacktestEngine 80%+ |
| Phase-2 | 15+ | 决策链 75%+ |
| Phase-3 | 10+ | 因子系统 80%+ |
| Phase-4 | 10+ | 全局 70%+ |
| Phase-5 | 5+ | 全局 75%+ |

### 9.2 发布检查清单

- [ ] `pytest tests/ --cov=uniquant` 通过且覆盖率 >= 70%
- [ ] 无 `sys.path.insert` 残留
- [ ] `GlobalConfig` 管理所有 yaml
- [ ] `BacktestEngine.run_backtest()` 使用 `open[t+1]` 成交
- [ ] `PortfolioEngine` 包含 T+1 / 涨跌停 / 最低佣金
- [ ] CZSC `is_3rd_buy` 在生产流水线中正确传递
- [ ] `DecisionBrain._calculate_score()` 使用 `SignalAggregator`
- [ ] `HistoricalSimulationRisk` 返回 `risk_level` 键
- [ ] `risk/evt_risk.py` 标记 Deprecated

---

## 10. 附录: 问题点索引

| 编号 | 原始ID | 严重性 | 模块 | 阶段 |
|---|---|---|---|---|
| #1 | same-bar fill | P0 | BacktestEngine | Phase-1 |
| #2 | 因子前瞻泄露 | P2 | FactorAnalyzer | Phase-3 |
| #3 | IC 全样本泄露 | P0 | FactorComposer | Phase-3 |
| #4 | PortfolioEngine 缺失 | P0 | PortfolioEngine | Phase-1 |
| #5 | 策略不可交易 | P1 | Strategies | Phase-2 |
| #6 | EVT 命名欺诈 | P0 | evt_risk | Phase-4 |
| #7 | 假装 HMM | P1 | evt_risk | Phase-4 |
| #8 | FSM MA 交叉 | P1 | FSM | Phase-4 |
| #9 | conftest sys.path | P1 | 测试基础设施 | Phase-0 |
| #10 | ConfigLoader | P1 | 配置加载 | Phase-0 |
| #11 | DataValidator 变异 | P1 | DataValidator | Phase-4 |
| #13 | MIN_COMMISSION | P1 | backtest.py | Phase-1 |
| #14 | 循环依赖 | P2 | regime.py | Phase-4 |
| #15 | 幸存者偏差 | P1 | backtest.py | Phase-5 |
| #16 | 无退市股票 | P1 | backtest.py | Phase-5 |
| #17 | LPPL 重复计算 | P2 | LPPLEngine | Phase-3 |
| #20 | FSM 竞态 | P2 | FSM | Phase-5 |
| #23 | 测试无断言 | P2 | test_backtest_engine | Phase-1 |
| #25 | 无一致性测试 | P2 | 测试覆盖 | Phase-1 |
| NEW-1 | risk_level KeyError | P0 | fsm.py | Phase-2 |
| NEW-2 | CZSC 键名不匹配 | P0 | czsc_engine | Phase-2 |
| NEW-3 | 双信号系统 | P0 | 决策链 | Phase-2 |
| NEW-4 | DI 容器死代码 | P1 | DI Container | Phase-5 |
| NEW-5 | FSM 缓存死代码 | P1 | FSM Analysis | Phase-2 |
| NEW-6 | 重试失效 | P1 | error_handling | Phase-4 |
| NEW-7 | Kelly 返回 0 | P1 | PortfolioEngine | Phase-1 |
| NEW-8 | 非原子写入 | P1 | StorageManager | Phase-1 |
| NEW-9 | 引擎被绕过 | P1 | AnalysisService | Phase-4 |
| NEW-10 | 双重实现 | P1 | FSM Analysis | Phase-4 |

---

## 附录 A: 文件变更清单

| 文件 | 修改 | Task |
|---|---|---|
| `pyproject.toml` | 修改 | 0.1, 0.3 |
| `tests/conftest.py` | 修改 | 0.1 |
| `tests/test_portfolio_engine.py` | 新增 | 1.2, 1.5 |
| `tests/test_decision_path_consistency.py` | 新增 | 2.2 |
| `tests/test_factor_overfitting.py` | 新增 | 3.1 |
| `shared/config_loader.py` | 修改 | 0.2 |
| `shared/di_container.py` | 废弃标记 | 5.1 |
| `shared/error_handling.py` | 修改 | 4.2, 5.4 |
| `risk/evt_risk.py` | 废弃标记 | 4.1 |
| `risk/historical_risk.py` | 新增 | 4.1 |
| `risk/structural.py` | 修改(类名) | 4.1 |
| `brain/fsm/fsm.py` | 修改 | 2.2, 2.3, 4.1, 5.3 |
| `brain/czsc/czsc_engine.py` | 修改 | 2.1 |
| `brain/factors/analyzer.py` | 修改 | 3.1, 3.2 |
| `brain/factors/composer.py` | 修改 | 3.1 |
| `brain/lppl/engine.py` | 修改 | 3.3 |
| `brain/lppl/calculator.py` | 修改 | 3.3 |
| `hands/backtest/engine.py` | 修改 | 1.1 |
| `hands/backtest/portfolio_engine.py` | 大幅修改 | 1.2, NEW-7 |
| `hands/strategies/backtest.py` | 修改 | 1.3, 5.2 |
| `hands/strategies/ma_cross.py` | 修改(命名) | 2.5 |
| `hands/strategies/str_reversal.py` | 修改(命名) | 2.5 |
| `hands/strategies/wyckoff.py` | 修改(命名) | 2.5 |
| `hands/strategies/regime.py` | 修改 | 2.5, 4.6 |
| `hands/strategies/registry.py` | 修改 | 2.5 |
| `services/analysis_service.py` | 修改 | 2.1, 4.4 |
| `services/analysis/fsm_analysis_engine.py` | 修改 | 2.4, 4.3 |
| `services/analysis/signal_service.py` | 修改 | 2.4, 4.3 |
| `services/scan_service.py` | 修改 | 3.1, 3.2 |
| `data/lake/storage_manager.py` | 修改 | 1.4, NEW-8 |
| `data/pipeline/data_validator.py` | 修改 | 4.5 |
| `signal/aggregator.py` | 修改 | 2.2 |
| `signal/models.py` | 修改 | 2.2 |
| `shared/interfaces.py` | 修改 | 2.2 |
| `config/*.yaml` | 可能修改 | 0.2 |
