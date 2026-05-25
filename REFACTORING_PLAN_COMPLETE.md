# UniQuant 完整问题清单与重构计划

> 合并自：
> - `PROJECT_AUDIT_20260523.md`（原始审计，17 项）
> - `PROJECT_AUDIT_SUPPLEMENT_20260523.md`（补充审计 + 交叉验证，新 17 项）
> - `REFACTORING_PLAN.md`（原始重构计划，28 项，6 阶段）
> - 针对原始计划的二次审计校验（发现遗漏 + 建议修正）
> - **v3.0 三次审计校验**：基于代码实证的全面核实，修正过时描述，补充遗漏问题
>
> **最终总计：53 项问题 / 9 阶段重构计划**
> 版本: v3.0

---

## 目录

1. [问题全景图](#1-问题全景图)
2. [完整问题清单（53 项）](#2-完整问题清单)
3. [重构阶段总览](#3-重构阶段总览)
4. [Phase-S: 安全 & 崩溃修复](#phase-s-安全--崩溃修复)
5. [Phase-0: 基础设施修复](#phase-0-基础设施修复)
6. [Phase-1a: 回测执行修复](#phase-1a-回测执行修复)
7. [Phase-1b: 核心路径向量化](#phase-1b-核心路径向量化)
8. [Phase-2a: 信号与决策链](#phase-2a-信号与决策链)
9. [Phase-2b: 因子系统修复](#phase-2b-因子系统修复)
10. [Phase-3: 回撤归因与风险引擎](#phase-3-回撤归因与风险引擎)
11. [Phase-4: 工程债务清理](#phase-4-工程债务清理)
12. [Phase-5: 死代码清理](#phase-5-死代码清理)
13. [Phase-6: A 股微观结构补齐](#phase-6-a-股微观结构补齐)
14. [验证与验收标准](#14-验证与验收标准)
15. [文件变更清单](#15-文件变更清单)

---

## 1. 问题全景图

### 按严重性

| 级别 | 原始审计 | 补充审计 | 二次审计 | **v3.0 三次审计（新增）** | 合计 |
|------|----------|----------|----------|--------------------------|------|
| **P0** | 5 | 4 | 2 | 1（engine.py 未接入 UME） | **12** |
| **P1** | 9 | 6 | 4 | 2（UME T+1 非向量化 + 组合同日成交） | **21** |
| **P2** | 3 | 7 | 10 | 0 | **20** |
| **总计** | **17** | **17** | **16** | **3** | **53** |

### 按问题域

| 问题域 | 数量 | 严重性分布 |
|--------|------|------------|
| 安全漏洞 / 硬编码 | 4 | P0 x4 |
| 导入 / 包管理 | 4 | P0 x2, P1 x2 |
| 运行时崩溃 Bug | 3 | P0 x2, P1 x1 |
| 回测执行语义 | 7 | P0 x3, P1 x4（含 v3.0 新增 2 项） |
| 数据泄露 / 前视偏差 | 3 | P0 x1, P1 x2 |
| 信号 / 决策链正确性 | 5 | P0 x2, P1 x3 |
| 配置管理 | 2 | P1 x2 |
| 架构耦合 | 3 | P1 x3 |
| 向量化缺失 | 1 | P1 x1（19 处 iterrows） |
| 回撤归因缺失 | 1 | P1 x1（无 MDD duration / Calmar / CVaR） |
| A 股微观结构缺失 | 1 | P2 x1（复权 / 停牌 / 新股 / 板块差异） |
| 数值 / 量化正确性 | 5 | P1 x3, P2 x2 |
| 测试质量 | 4 | P1 x1, P2 x3 |
| 代码质量 | 10 | P1 x2, P2 x8 |

---

## 2. 完整问题清单（53 项）

### 2.1 P0 级问题（12 项）

| ID | 来源 | 问题名 | 文件 | 行号 | 风险 |
|----|------|--------|------|------|------|
| **P0-01** | 原始 #1 | 导入路径损坏 | `tests/conftest.py`, `tests/test_czsc_engine.py` 等 | 10 | CI 不可信，测试不可收集 |
| **P0-02** | 原始 #2 | 回测同根 K 线执行 | `hands/backtest/engine.py` | 320-322 | 回测虚高，Lookahead Bias |
| **P0-03** | 原始 #3 | ~~组合回测缺 A 股约束~~ → **已部分修复** | `hands/backtest/portfolio_engine.py` | 全文件 | ⚠️ 见下方状态说明 |
| **P0-04** | 原始 #4 | 策略函数未来数据 | `hands/strategies/ma_cross.py` 等 | 24,21,88 | 离线标注被误当信号 |
| **P0-05** | 原始 #5 | 因子权重全样本泄露 | `services/scan_service.py` | 487-489 | 打分虚高，过拟合 |
| **P0-06** | 原始+补充 | EVT 命名欺诈 | `risk/evt_risk.py` | 24,39 | 名实不符，用户误导 |
| **P0-07** | 补充 P0-N1 | SSL 验证禁用 | `data/sources/eastmoney.py` | 75 | MITM 攻击风险 |
| **P0-08** | 补充 P0-N2 | JS 代码注入 | `data/utils/js_executor.py` | 37,66 | 任意代码执行 |
| **P0-09** | 补充 P0-N3 | 硬编码开发者路径 | `data/sources/tdx.py` | 58 | 隐私泄露 + 数据源不可用 |
| **P0-10** | 补充 P0-N4 | quality.py AttributeError | `signal/quality.py` | 60 | 运行时必崩溃 |
| **P0-11** | 补充+审计 | CZSC 键名不匹配 | `services/analysis_service.py` | 949 | 第三类买点信号永远 false |
| **P0-12** | v3.0 新增 | **engine.py 未接入统一撮合引擎** | `hands/backtest/engine.py` | 全文件 | 两套执行逻辑并存，不可比 |

> **P0-03 状态说明**：经 v3.0 代码实证核实，`PortfolioEngine` **已重构为使用 `UnifiedMatchingEngine`**（含 T+1、涨跌停、印花税、最低佣金、非线性滑点）。原 P0-03 的核心约束缺失问题已解决，但仍有残留问题（见 P1-20、P1-21）。严重性降级为 P1。

### 2.2 P1 级问题（21 项）

| ID | 来源 | 问题名 | 文件 | 行号 | 风险 |
|----|------|--------|------|------|------|
| **P1-01** | 原始 #6 | 配置文件未全部加载 | `shared/config_loader.py` | 66-69 | 配置与运行时行为不一致 |
| **P1-02** | 原始 #7 | AnalysisService 过耦合 | `services/analysis_service.py` | 97-170 | 单点失败，测试困难 |
| **P1-03** | 原始 #8 | DataService 职责过多 | `services/data_service.py` | 全文件 | 路径知识重复，变更风险 |
| **P1-04** | 原始 #9 | 幸存者偏差 | `hands/strategies/backtest.py` | 126 | 策略表现虚高 |
| **P1-05** | 原始 #10 | 批回测缺部分成交/滑点 | `hands/strategies/backtest.py` | 313-322 | 出口风险低估 |
| **P1-06** | 原始 #11 | PBO 使用随机 shuffle | `hands/backtest/overfitting_detector.py` | 133-135 | 过拟合风险低估 |
| **P1-07** | 原始 #7（补充） | FSM 命名 MA 交叉 | `brain/fsm/fsm.py` | N/A | 命名误导 |
| **P1-08** | 原始 #13 | PositionSizer 简化 | `risk/sizer.py` | 80-99 | 手数硬编码 |
| **P1-09** | 原始 #14 | 优化器缺防护 | `risk/portfolio_optimizer.py` | 59 | 协方差不稳定 |
| **P1-10** | 补充 P1-N1 | UI 健康检查导入全错 | `ui/health_check.py` | 28-36 | UI 全红 |
| **P1-11** | 补充 P1-N2 | 函数签名不匹配 | `ui/components.py:350`, `dashboard.py:649` | - | TypeError |
| **P1-12** | 补充 P1-N3 | LPPL 缓存泄漏 | `brain/lppl/calculator.py` | 32 | 内存无限增长 |
| **P1-13** | 补充 P1-N4 | LPPL 超时丢结果 | `brain/lppl/computation.py` | 209 | 已算的拿不到 |
| **P1-14** | 补充 P1-N5 | 信号聚合丢原始信息 | `signal/aggregator.py` | 129-130 | 空信号返回无效对象 |
| **P1-15** | 补充 P1-N6 | LPPL MA 回退假阳性 | `brain/lppl/regime.py` | 85-98 | 趋势被误判 |
| **P1-16** | 二次审计 | 向量化缺失 | 全项目 20 处 iterrows | 多处 | 性能 100x 损失 |
| **P1-17** | 二次审计 | 回撤归因缺失 | 全项目 | - | MDD Duration/Calmar/CVaR 无 |
| **P1-18** | 补充+审计 | DI 容器死代码 | `shared/di_container.py` | 全文件 | 废弃状态 |
| **P1-19** | 补充+审计 | 装饰器堆叠重试失效 | `shared/error_handling.py` | 364-373, 460-470 | 重试永不触发 |
| **P1-20** | v3.0 新增 | **UME T+1 检查非向量化** | `hands/backtest/unified_matching_engine.py` | 156-171 | 组合回测性能瓶颈 |
| **P1-21** | v3.0 新增 | **PortfolioEngine.run() 同日信号同日成交** | `hands/backtest/portfolio_engine.py` | 262-265 | 组合回测前瞻偏差 |

### 2.3 P2 级问题（20 项）

| ID | 来源 | 问题名 | 文件 | 行号 | 风险 |
|----|------|--------|------|------|------|
| **P2-01** | 原始 #12 | 回测测试断言弱 | `tests/test_backtest_engine.py` | - | 错误不被捕获 |
| **P2-02** | 原始 #15 | DataValidator 修改输入 | `data/pipeline/data_validator.py` | 28-66 | 隐藏 Bug |
| **P2-03** | 原始 #16 | 可选依赖影响覆盖 | `tests/test_hands_strategies.py` 等 | - | 覆盖率不确定 |
| **P2-04** | 原始 #17 | 无退市股票数据 | `hands/strategies/backtest.py` | - | 幸存者偏差未量化 |
| **P2-05** | 补充 P2-N1 | 常量重复（8 类以上） | `shared/constants.py` | 94,481 等 | 维护困难 |
| **P2-06** | 补充 P2-N2 | Wyckoff 硬编码阈值 | `brain/wyckoff/rules.py` 等 | 36-45,82-101 | 不可配置 |
| **P2-07** | 补充 P2-N3 | 宽泛异常捕获 | 全项目 20+ 处 | - | 隐藏真实错误 |
| **P2-08** | 补充 P2-N4 | interfaces.py 类型不精确 | `shared/interfaces.py` | 152 | 类型系统弱 |
| **P2-09** | 补充 P2-N5 | frozen dataclass 含可变 list | `shared/constants.py` | 1110 | 违反 frozen 原则 |
| **P2-10** | 补充 P2-N6 | 信号 DB 时间戳混乱 | `signal/db.py` | 89-95 | 时区 Bug |
| **P2-11** | 补充 P2-N7 | LPPL 异常吞没 | `brain/lppl/data_manager.py` + `calculator.py` | - | 调试困难 |
| **P2-12** | 二次审计 | 前复权/后复权未集成到回测 | 全项目（数据源有，引擎无） | - | 回测价格失真 |
| **P2-13** | 二次审计 | 停牌模拟缺失 | `portfolio_engine.py` | - | 假设可交易已停牌股票 |
| **P2-14** | 二次审计 | 科创板/创业板/北交所板块差异 | 全项目 | - | 涨跌停不一致 |
| **P2-15** | 二次审计 | 新股过滤缺失 | 全项目 | - | 新股波动干扰 |
| **P2-16** | 二次审计 | 印花税/两融标的未覆盖 | `portfolio_engine.py` | - | 成本模型不完整 |
| **P2-17** | 二次审计 | 应力测试场景不完整 | `ui/manager_logic.py` | 448 | 缺少历史危机模拟 |
| **P2-18** | 二次审计 | 全局 MDD 仅有，缺滚动/持续 | `risk/evt_risk.py` | 216-231 | 回撤深度不可评估 |
| **P2-19** | 二次审计 | 循环依赖 regime.py | `hands/strategies/regime.py` | 40 | import 链循环 |
| **P2-20** | 原始审计 | 配置边界未定义（config 缺失加载策略） | `shared/config_loader.py` | 全文件 | 出现不符 |

---

## 3. 重构阶段总览

| 阶段 | 名称 | 估计 | 处理问题 | 交付物 |
|------|------|------|----------|--------|
| **Phase-S** | 安全 & 崩溃修复 | 1 天 | P0-07~P0-11, P1-10, P1-11 | 4 安全漏洞 + 3 运行时 Bug 修复 |
| **Phase-0** | 基础设施修复 | 2-3 天 | P0-01, P1-01, P2-03, P2-20 | 可复现测试环境、统一配置加载 |
| **Phase-1a** | 回测执行统一 | 5-7 天 | P0-02, P0-03↓P1, P0-12, P1-21, P1-04, P1-05, P2-01 | 统一撮合内核、消除同Bar成交 |
| **Phase-1b** | 核心路径向量化 | 5-7 天 | P1-16, P1-20 | iterrows 消除、UME T+1 向量化 |
| **Phase-2a** | 信号与决策链 | 5-7 天 | P0-11, P1-14, P1-15, P1-07, P1-12, P1-13 | 统一决策链、信号正确性 |
| **Phase-2b** | 因子系统修复 | 3-5 天 | P0-04, P0-05, P1-06 | 扩展窗口滚动 IC、PBO 时序化 |
| **Phase-3** | 回撤归因 & 风险引擎 | 5-7 天 | P1-17, P1-08, P1-09, P2-17, P2-18 | 全维度回撤分析、压力测试场景 |
| **Phase-4** | 工程债务清理 | 5-7 天 | P0-06, P1-02, P1-03, P1-18, P1-19, P2-02~P2-11, P2-19 | 命名纠正、架构解耦、代码质量 |
| **Phase-5** | 死代码清理 | 2-3 天 | P2-04 | DI 容器移除、退市股票 |
| **Phase-6** | A 股微观结构补齐 | 3-5 天 | P2-12~P2-16 | 复权、停牌、板块差异、新股过滤 |

**总估计：36-52 天（约 7-10 周）**

> **v3.0 变更**：Phase-1a 因 UME 已存在而工作量缩减，但新增 P0-12（engine.py 接入 UME）和 P1-21（组合同日成交），净工作量持平。Phase-1b 新增 P1-20（UME T+1 向量化）。

---

## 4. Phase-S: 安全 & 崩溃修复

**目标：上线不会炸。** 优先修 4 个 P0 安全漏洞 + 3 个运行时崩溃。

### Task S.1: 修复 eastmoney SSL 验证禁用（P0-07）

- **文件**: `src/uniquant/data/sources/eastmoney.py:75`
- **核实**: ✅ 第 75 行 `verify=False` 确认存在
- **当前**: `response = self.session.get(url, verify=False)`
- **修复**: 删除 `verify=False`。如确有证书问题，配置 CA bundle 路径而非全局禁用
- **验收**: `grep -r "verify=False" src/` 无结果

### Task S.2: 修复 JS 代码注入风险（P0-08）

- **文件**: `src/uniquant/data/utils/js_executor.py:37,66`
- **核实**: ✅ 第 37 行 `eval(js_content)` 执行外部文件，第 66 行 `eval(default_js)` 执行硬编码 JS
- **修复**:
  1. 对 `ths.js` 做 SHA256 校验，篡改时拒绝执行
  2. 第 66 行硬编码 JS 本身无注入风险，但应添加来源注释
  3. 改用已存在的 Python `_generate_fallback_v_param()` 替代 JS fallback
- **验收**: 外部 JS 文件被篡改时抛出 `IntegrityError`

### Task S.3: 修复硬编码开发者路径（P0-09）

- **文件**: `src/uniquant/data/sources/tdx.py:58`
- **核实**: ✅ 第 58 行硬编码 `/home/james/.local/share/tdxcfv/drive_c/tc`
- **修复**: 移除硬编码，仅从 `config.yaml` 的 `base.tdx.path` 读取
- **验收**: `grep -r "/home/james" src/` 无结果

### Task S.4: 修复 quality.py AttributeError（P0-10）

- **文件**: `src/uniquant/signal/quality.py:60`
- **核实**: ✅ `idxmax()` 返回 `Timestamp`，无 `total_seconds()` 方法
- **当前**: `leading_time = target_prices.idxmax().total_seconds() / 3600`
- **修复**: `(target_prices.idxmax() - target_prices.index[0]).total_seconds() / 3600`
- **验收**: 调用 `get_signal_quality()` 不抛 `AttributeError`

### Task S.5: 修复 UI 健康检查导入（P1-10）

- **文件**: `src/uniquant/ui/health_check.py:28-36`
- **核实**: ✅ 全部使用 `src.` 前缀（如 `src.brain.fsm`），应为 `uniquant.brain.fsm`
- **修复**: 全部替换为 `uniquant.` 前缀
- **验收**: UI 健康检查页面至少 1 个模块显示绿色

### Task S.6: 修复 plot_czsc_full_chart 签名不匹配（P1-11）

- **文件**: `src/uniquant/ui/components.py:350` vs `src/uniquant/ui/dashboard.py:649`
- **核实**: ✅ 定义 2 参数 `(symbol, czsc_data)` → 返回 `None`；调用 5 关键字参数 `(df, bi_list, zhongshu_list, bs_points, ticker)` → 期望返回 chart 对象
- **修复**: 对齐函数签名，返回 `st_pyecharts` 可用对象
- **验收**: CZSC 图表页面不抛 `TypeError`

### Task S.7: 修复 CZSC 键名不匹配（P0-11）

- **文件**: `services/analysis_service.py:947-949`
- **核实**: ✅ 第 947 行 fallback 字典用 `third_buy`，第 949 行 `czsc_result.get("third_buy", False)` 从正常返回值（键名 `is_3rd_buy`）中取值，永远返回 `False`
- **修复**: 统一为 `is_3rd_buy`
- **验收**: CZSC 三买信号可正常触发

**Phase-S 退出标准**: 全部 7 个修复合入，新增回归测试。无 `verify=False`、无硬编码路径、无 `AttributeError` 崩溃。

---

## 5. Phase-0: 基础设施修复

**目标：让项目可构建、可测试、可复现。**

### Task 0.1: 修复虚拟环境 + 可编辑安装（P0-01）

- **核实**: ✅ `conftest.py` 使用 `sys.path.insert`，非标准方式
- **修复**:
  1. 重建 venv: `python3 -m venv --clear .venv && pip install -e ".[dev]"`
  2. 删除 `conftest.py` 的 `sys.path.insert` 块
  3. 新增 `pythonpath = ["src"]` 到 `pyproject.toml` 的 `[tool.pytest.ini_options]`
  4. 添加 `pytest --collect-only -q` 到 CI gate
- **文件**: `pyproject.toml`, `tests/conftest.py`
- **验收**: `python -m pytest --collect-only -q` 在无路径 hack 情况下通过

### Task 0.2: 统一配置加载（P1-01, P2-20）

- **核实**: ✅ `GlobalConfig._load_config()` 仅加载 `config.yaml`，跳过 `trading.yaml`/`factors.yaml`/`optimal_params.yaml`
- **修复**:
  1. `GlobalConfig._load_config()` 新增 3 个 yaml 加载，按确定顺序合并
  2. 删除独立 `yaml.safe_load()` 调用（wyckoff.py:32, wyckoff_strategy.py:34, loader.py:9, cost_model.py:75）
  3. 替换为 `GlobalConfig.get("trading.xxx")`
  4. 启动时打印已加载的配置文件列表
- **验收**: 删除独立 yaml 加载后功能不变；启动日志列出所有已加载配置

### Task 0.3: 依赖缺失处理（P2-03）

- **修复**:
  1. 明确核心/可选依赖边界
  2. 可选依赖降级时 `logger.warning`
  3. 启动时验证关键依赖
- **验收**: 非核心依赖缺失时不影响核心功能

### Task 0.4: 旧导入路径兼容 Shim（P0-01 补充）

- **修复**: 添加向前兼容 shim 模块（`from .czsc.czsc_engine import *`）+ `DeprecationWarning`
- **文件**: `src/uniquant/brain/czsc_engine.py`, `ntf_engine.py`, `regime_detector.py`（新增）
- **验收**: 旧路径 import 正常，触发警告

**Phase-0 退出标准**: 全部测试在无手动 `PYTHONPATH` 环境下收集通过。

---

## 6. Phase-1a: 回测执行统一

**目标：让回测结果可信、可交易。统一单资产与组合引擎的执行语义。**

> **v3.0 关键变更**：`UnifiedMatchingEngine` 已存在且 `PortfolioEngine` 已接入。本阶段核心任务从"补齐约束"转为"统一引擎 + 消除同Bar成交"。

### Task 1a.1: BacktestEngine 接入 UnifiedMatchingEngine（P0-12, P0-02）

- **文件**: `hands/backtest/engine.py`
- **核实**:
  - ✅ P0-02 确认：第 320 行 `current_price = row["close"]`，信号和成交同 Bar
  - ✅ P0-12 确认：`engine.py` 无任何 `UnifiedMatchingEngine` 引用，与 `portfolio_engine.py` 使用两套执行逻辑
- **修复**:
  1. **重构 `BacktestEngine` 使用 `UnifiedMatchingEngine`**：删除 `execute_buy`/`execute_sell`/`_calculate_commission`/`_calculate_slippage`/`_check_t1_constraint`/`_check_limit_constraint` 等旧方法，改为调用 `self.matching.fill_buy()`/`self.matching.fill_sell()`
  2. **修复同 Bar 成交**：主循环 `range(len(df) - 1)`，信号基于 `df.iloc[:idx+1]`，成交价使用 `df.iloc[idx+1]["open"]`，预收盘价使用 `df.iloc[idx]["close"]`，时间戳使用 `dates[idx+1]`
  3. **信号视野限制**：`signal_generator(df.iloc[:idx+1], idx, context)` — 策略只能看到当前及之前数据
  4. 新增 `execution_mode` 参数：`"next_open"`（默认，生产级）/ `"same_bar_research"`（研究用，标记为不可交易）
- **验收**:
  - `BacktestEngine` 与 `PortfolioEngine` 使用同一 `UnifiedMatchingEngine` 实例
  - 信号时间 ≠ 成交时间
  - 会计级测试覆盖：费用、滑点、PnL、T+1、限价、手数、现金守恒

### Task 1a.2: PortfolioEngine.run() 修复同日信号同日成交（P1-21）

- **文件**: `hands/backtest/portfolio_engine.py:262-265`
- **核实**: ✅ `batch_close_positions` 和 `batch_open_positions` 使用同日 `close` 价格成交
- **修复**:
  1. 信号日 `t` 的信号在 `t+1` 以 `open` 价格执行
  2. `run()` 方法需维护"待执行信号队列"，次日开盘时执行
  3. 新增 `execution_mode` 参数与 `BacktestEngine` 一致
- **验收**: 组合回测信号日 ≠ 成交日

### Task 1a.3: 跨截面回测应用最低佣金（P1-05）

- **文件**: `hands/strategies/backtest.py`
- **核实**: ✅ 第 313-322 行纯百分比成本，`MIN_COMMISSION` 仅作为元数据记录未执行
- **修复**: 成本计算加入 `max(commission, MIN_COMMISSION)` 强制执行
- **验收**: 小资金交易成本不低于最低佣金

### Task 1a.4: 幸存者偏差处理（P1-04, P2-04）

- **文件**: `hands/strategies/backtest.py`
- **修复**:
  1. 集成 `is_delisted()` 检查
  2. 结果中添加 `delisted: true` 标记
  3. 提供 `with_delisted / without_delisted` 对比
- **验收**: 报告明确标识幸存者偏差

### Task 1a.5: 测试断言加强（P2-01）

- **文件**: `tests/test_backtest_engine.py`, `tests/test_portfolio_engine.py`（新增）
- **修复**:
  - 加入会计级断言：`assert abs(cash + position_value - initial_capital - total_pnl) < 1e-6`
  - 新增 5 个场景的 `BacktestEngine` ↔ `PortfolioEngine` 一致性测试
  - 新增 T+1 违规拒绝测试、涨跌停拒绝测试、最低佣金测试
- **验收**: 现金守恒、费用精确、约束生效

**Phase-1a 退出标准**: 单资产与组合引擎共享 `UnifiedMatchingEngine`。信号-成交分离。会计级测试覆盖费用、滑点、PnL、T+1、限价、手数和现金守恒。

---

## 7. Phase-1b: 核心路径向量化

**目标：消除 20 处 iterrows，提升性能 50-100x。**

> **v3.0 关键变更**：回测主循环因路径依赖（持仓状态、现金余额、T+1）不可纯向量化，改为半向量化 + Numba JIT 方案。

### Task 1b.1: BacktestEngine 半向量化 + Numba JIT

- **文件**: `hands/backtest/engine.py`
- **当前**: `for idx in range(len(df))` + `row["close"]` 逐行
- **修复**:
  1. **信号预计算向量化**：技术指标/因子值用 NumPy 批量计算，存入 `signals_arr`
  2. **执行循环保留但优化**：用 NumPy 数组替代 DataFrame 访问，避免 `iloc` 开销
  3. **可选 Numba JIT**：对纯数值循环使用 `@njit` 加速（需处理 `TradeCalendarManager` 调用）
- **验收**: 等价结果，1 年日频数据耗时 <200ms（当前 ~5s）

### Task 1b.2: PortfolioEngine 日级信号循环优化

- **文件**: `hands/backtest/portfolio_engine.py:234,262`
- **当前**: 2 处 `for _, row in day_signals.iterrows()`
- **修复**:
  1. 日信号用 `groupby("date")` + 向量化构建 `sig_dict`
  2. 价格查询用 DataFrame 索引直接定位替代逐行 try/except
- **验收**: 100 只股票 3 年回测 <30s

### Task 1b.3: UME T+1 检查向量化（P1-20）

- **文件**: `hands/backtest/unified_matching_engine.py:156-171`
- **核实**: ✅ 第 156-171 行逐行循环调用 `get_trade_calendar()`，每次卖出都查数据库
- **修复**:
  1. 预加载交易日历为 `pd.DatetimeIndex` 查找表
  2. T+1 检查改为向量化：`trade_dates.searchsorted(buy_dates) < trade_dates.searchsorted(current_dates)`
  3. 缓存日历数据避免重复查询
- **验收**: 100 只股票卖出操作 T+1 检查 <10ms

### Task 1b.4: SignalIntegrator 交易循环向量化

- **文件**: `hands/backtest/signal_integrator.py:57,71`
- **修复**: 交易 PnL / 统计用 DataFrame 内置函数

### Task 1b.5: 策略文件热路径向量化

- **文件**: `wyckoff.py:111`, `wyckoff_strategy.py:121`, `str_reversal.py:33`
- **修复**: `shift` + `rolling` + 条件组合代替循环

### Task 1b.6: Data Pipeline / Manager iterrows 清理

- **文件**: `data/scripts/*.py`, `data/managers/*.py`, `data/utils/*.py`
- **目标**: 9 处 iterrows 全部评估并向量化或优化

### Task 1b.7: 向量化回归测试

- **文件**: `tests/test_vectorization.py`（新增）
- **内容**: 验证向量化结果与逐行结果一致（`assert_allclose 1e-10`）；性能基准测试

**Phase-1b 退出标准**: 全部 20 处 iterrows 消除。核心路径性能提升 50x+。向量化结果与逐行结果一致。

---

## 8. Phase-2a: 信号与决策链修复

**目标：让生产决策链使用所有引擎信号，回测忠实复现生产逻辑。**

### Task 2a.1: 统一信号表示（P0-11 巩固）

- **文件**: `shared/interfaces.py`, `signal/models.py`
- **修复**:
  1. 定义统一 `Signal` 协议：`engine_type`, `direction`, `confidence[0,1]`, `weights`, `raw_metrics`
  2. `MarketSignalContext` 从统一 `Signal` 派生
  3. 统一键名 `is_3rd_buy`

### Task 2a.2: 统一生产决策与回测路径（P1-14 巩固）

- **文件**: `brain/fsm/fsm.py`, `signal/aggregator.py`, `hands/backtest/signal_integrator.py`
- **核实**: ✅ 生产用加分，回测用加权平均/多数投票，路径不一致
- **修复**:
  1. `DecisionBrain._calculate_score()` 替换为 `SignalAggregator.aggregate()` 调用
  2. `DecisionBrain` 保持 veto/buy_blocker/transition 逻辑
  3. `AggregatedSignal()` 无参构造返回 `None` 而非无效对象（P1-14 修正）

### Task 2a.3: 决策路径一致性测试

- **文件**: `tests/test_decision_path_consistency.py`（新增）
- **内容**: 5 个标准场景（强买入、强卖出、中性、Wyckoff、极端风险）中生产和回测路径决策一致

### Task 2a.4: LPPL 缓存修复（P1-12）

- **文件**: `brain/lppl/calculator.py:32`
- **核实**: ✅ `self._fit_cache = {}` 无淘汰机制，无限增长
- **修复**: `cachetools.LRUCache(maxsize=128)` + TTL 过期

### Task 2a.5: LPPL 超时保留部分结果（P1-13）

- **文件**: `brain/lppl/computation.py:209`
- **核实**: ✅ 超时后静默丢弃，无汇总警告
- **修复**: 捕获 `TimeoutError` 保留已完成子任务，结果中标注数据完整性

### Task 2a.6: LPPL Regime MA 假阳性（P1-15）

- **文件**: `brain/lppl/regime.py:85-98`
- **核实**: ✅ 数据不足时 `mas[p] = close[-1]`，混合真实/虚假 MA 导致趋势误判
- **修复**: 数据不足以计算某 MA 时，不将该 MA 纳入趋势判断，降低置信度

### Task 2a.7: 策略函数命名与守卫（P0-04）

- **文件**: `hands/strategies/ma_cross.py`, `str_reversal.py`, `wyckoff.py`
- **核实**: ✅ `trade_*` 函数使用 `shift(-N)` 未来数据
- **修复**:
  1. 重命名为 `evaluate_*` / `label_*`
  2. 添加 `mode` 参数：`"backtest"` / `"live"`
  3. `mode == "live"` 时抛出 `NotImplementedError`
  4. Docstring 标注 "OFFLINE BACKTEST LABEL — NOT FOR LIVE TRADING"

**Phase-2a 退出标准**: `DecisionBrain` 使用 `SignalAggregator`。5 个标准场景生产/回测一致。LPPL 工作正确。

---

## 9. Phase-2b: 因子系统修复

**目标：消除因子层面的数据泄露和过拟合。**

> **v3.0 关键变更**：Task 2b.1 从单次时间分割改为扩展窗口滚动，与 Task 2b.2 统一。

### Task 2b.1: 扩展窗口滚动 IC 加权（P0-05）

- **文件**: `brain/factors/analyzer.py`, `brain/factors/composer.py`, `services/scan_service.py`
- **核实**: ✅ `scan_service.py:487-489` 在同一 `combined_df` 上优化 IC/IR 权重后打分
- **修复**:
  1. ~~单次 `temporal_split(df, test_size=0.3)`~~ → **扩展窗口滚动**：
     ```
     Train: [0, T1] → 计算权重 → Score: (T1, T2]
     Train: [0, T2] → 计算权重 → Score: (T2, T3]
     ...
     ```
  2. `FactorComposer` 新增 `expanding_ic_weights()` 方法
  3. `mode="live"` 时仅使用已训练窗口的权重，不使用 `shift(-period)`
  4. |train_IC - test_IC| > 0.1 时触发过拟合警告
- **验收**: 生产扫描不使用全样本 IC 打分；滚动 IC 权重可复现

### Task 2b.2: WalkForwardPipeline 实现

- **文件**: `services/scan_service.py`
- **修复**:
  1. 新增 `WalkForwardPipeline` 类，封装扩展窗口逻辑
  2. 配置化窗口大小（默认 `train=252, test=63` 交易日）
  3. 输出包含每个窗口的 IC/IR/权重/评分
- **验收**: `--mode live` 运行时不使用未来信息

### Task 2b.3: PBO 真正时序划分（P1-06）

- **文件**: `hands/backtest/overfitting_detector.py:133-135`
- **核实**: ✅ `np.random.shuffle` 破坏时序，无 seed 控制
- **修复**:
  1. 实现 purged K-fold + embargo 期基于最大持仓窗口
  2. 添加 `seed` 参数，使用 `np.random.default_rng(seed)` 替代全局随机状态
- **验收**: PBO 结果可复现；时序完整性不被破坏

**Phase-2b 退出标准**: 生产扫描不使用全样本 IC 打分。过拟合格栅被定义和测试。PBO 可复现。

---

## 10. Phase-3: 回撤归因与风险引擎

**目标：补齐回撤归因分析。**

### Task 3.1: 滚动最大回撤（MDD）实现

- **文件**: `risk/drawdown_analyzer.py`（新增）
- **内容**（全部使用 NumPy 向量化，禁止 `iterrows`）:
  1. `rolling_max_drawdown(equity: np.ndarray, window: int = 252)` — 滚动窗口 MDD
     $$MDD_t = \max\left(0, \frac{\max_{\tau \le t} P_\tau - P_t}{\max_{\tau \le t} P_\tau}\right)$$
  2. `drawdown_duration(equity: np.ndarray)` — 回撤持续期
  3. `calmar_ratio(returns: np.ndarray, periods: int = 252)` — 年化收益 / 最大回撤
  4. `ulcer_index(equity: np.ndarray)` — 溃疡指数

### Task 3.2: 尾部风险度量

- **文件**: `risk/drawdown_analyzer.py`
- **内容**:
  1. `cvar(returns: np.ndarray, alpha=0.05)` — Conditional VaR
  2. `expected_shortfall(returns: np.ndarray, alpha=0.05)` — ES 别名
  3. `tail_ratio(returns: np.ndarray)` — 95th / 5th 分位数比

### Task 3.3: 压力测试场景补齐（P2-17）

- **场景**:
  1. 2015 年股灾（流动性危机、千股跌停）
  2. 2016 年熔断
  3. 2018 年全年单边下跌
  4. 2020 年新冠疫情
  5. 2024 年 2 月微盘踩踏
  6. 自选日期回撤
- **验收**: 所有场景可从 UI 一键运行

### Task 3.4: 回撤归因报告

- **输出**:
  1. 分阶段回撤分解（板块、时间）
  2. 回撤恢复期分析
  3. 超高斯分布尾部检验
- **验收**: `BacktestResult` 包含 `drawdown_analysis` 字段

### Task 3.5: PositionSizer 完善（P1-08）

- **文件**: `risk/sizer.py:80-99`
- **修复**: 手数配置化；整合流动性/波动率/相关性

### Task 3.6: 优化器加防护（P1-09）

- **文件**: `risk/portfolio_optimizer.py:59`
- **修复**: Ledoit-Wolf 协方差收缩 + 换手惩罚 + 行业约束

**Phase-3 退出标准**: 全部 MDD/Duration/Calmar/CVaR 实现，5 个压力场景可用，尾部风险报告合入回测结果。

---

## 11. Phase-4: 工程债务清理

**目标：命名正确、架构可维护、代码质量达标。**

### Task 4.1: EVT 命名纠正（P0-06）

- **文件**: `risk/evt_risk.py` → `risk/historical_risk.py`
- **修复**:
  1. 创建 `historical_risk.py`，类名 `HistoricalSimulationRisk`
  2. 保留 `evt_risk.py` 为 `DeprecationWarning` 封装
  3. 更新所有引用
- **验收**: 废弃警告可见，无破坏性变化

### Task 4.2: 修复装饰器堆叠重试失效（P1-19）

- **文件**: `shared/error_handling.py:364-373, 460-470`
- **核实**: ✅ `handle_network_errors` 和 `handle_api_errors` 中 `retry_on_exception` 在外、`handle_errors` 在内，异常被内层吞掉，重试永不触发
- **修复**: 交换装饰器顺序：`@handle_errors` 在外，`@retry_on_exception` 在内
- **注意**: 交换后重试期间异常会被记录多次，需确认日志监控不受影响
- **验收**: 异常时触发重试，全部失败返回 default

### Task 4.3: AnalysisService 解耦（P1-02）

- **文件**: `services/analysis_service.py:97-170`
- **核实**: ✅ `__init__` 中一次性构造 7 个分析引擎，每个引擎持有 `self`（双向依赖）
- **修复**:
  1. 引擎创建延迟初始化（`@property` + `functools.cached_property`）
  2. 引擎通过工厂/注册表获取，不直接持有 `AnalysisService` 引用
  3. 引擎所需依赖通过构造函数注入
- **验收**: 仅调用 `analyze_ticker()` 时不加载 LPPL/NTF 等未使用引擎

### Task 4.4: DataService 职责拆分（P1-03）

- **文件**: `services/data_service.py`
- **核实**: ✅ 已部分重构为门面模式（`CacheCoordinator`/`DataQualityService`/`StockQueryService`），但仍有 40+ 方法
- **修复**:
  1. `StorageManager` 为 lake 布局唯一权威
  2. `DataService` 进一步收窄公共 API，仅保留高层编排接口
  3. 透传方法移至子服务
- **验收**: `DataService` 公共方法 <15 个

### Task 4.5: DataValidator 防御性复制（P2-02）

- **文件**: `data/pipeline/data_validator.py:28-66`
- **核实**: ✅ 第 28-33 行交换 high/low、第 56/61/65 行修改列值，均为就地修改
- **修复**: `validate()` 内部 `df = df.copy()`；返回 `Tuple[bool, pd.DataFrame]`
- **验收**: 调用后原始 DataFrame 不变

### Task 4.6: 常量去重 + frozen dataclass 修复（P2-05, P2-09）

- **文件**: `shared/constants.py`
- **核实**: ✅ 8 类以上常量重复（MAJOR_INDEXES、缓存TTL、超时、重试、数据验证等）；`WindowConfig` 的 `frozen=True` 无法阻止 `list.append()`
- **修复**:
  1. 统一重复常量到单一来源
  2. `list[int]` → `tuple[int, ...]`，`list(range(...))` → `tuple(range(...))`

### Task 4.7: Wyckoff 硬编码阈值配置化（P2-06）

- **文件**: `brain/wyckoff/rules.py`, `classifiers.py`
- **修复**: 阈值移至 `WyckoffConfig` YAML

### Task 4.8: 宽泛异常捕获精确化（P2-07, P2-11）

- **文件**: 全项目 20+ 处
- **修复**: `except Exception` → 具体异常类型

### Task 4.9: 类型提示精确化（P2-08）

- **文件**: `shared/interfaces.py:152`
- **修复**: `Any` → `Optional[float]`

### Task 4.10: 信号 DB 时间戳统一（P2-10）

- **文件**: `signal/db.py:89-95`
- **核实**: ✅ `datetime.now().timestamp()` 转 float 再 `datetime.fromtimestamp()` 转回，round-trip 多余且可能时区偏差
- **修复**: `datetime.now() - timedelta(minutes=minutes)` 直接计算 cutoff；统一 UTC

### Task 4.11: 循环依赖移除（P2-19）

- **文件**: `hands/strategies/regime.py:40`
- **核实**: ✅ 函数级延迟导入 `from uniquant.hands.strategies.backtest import COST_BUY, COST_SELL`，实际定义在 `shared.cost_model`
- **修复**: 改为 `from uniquant.shared.cost_model import COST_BUY, COST_SELL`

### Task 4.12: FSM 重复实现合并

- **文件**: `services/analysis/signal_service.py`, `services/analysis/fsm_analysis_engine.py`
- **修复**: `SignalAnalysisService.run_fsm_analysis()` 改为调用 `FsmAnalysisEngine` + `@deprecated`

**Phase-4 退出标准**: 全部代码质量项目修复。全局覆盖率 >= 70%。

---

## 12. Phase-5: 死代码清理

### Task 5.1: DI 容器移除（P1-18）

- **文件**: `shared/di_container.py`
- **核实**: ✅ 生产代码无引用，仅测试文件使用
- **修复**: 删除 `di_container.py` 及其测试文件

### Task 5.2: FSM 状态持久化加锁

- **文件**: `brain/fsm/fsm.py`
- **修复**: `filelock` + `os.replace()` 原子写入

### Task 5.3: 错误统计导出

- **文件**: `shared/error_handling.py`
- **修复**: `get_error_stats()` 接入 `HealthService`

---

## 13. Phase-6: A 股微观结构补齐

**目标：让回测反映真实的 A 股交易约束。**

> **v3.0 变更**：Task 6.3（板块差异）已在 `UnifiedMatchingEngine.compute_limit_status_vectorized()` 中部分实现，工作量缩减。

### Task 6.1: 复权数据集成到回测（P2-12）

- **修复**:
  1. 在 `BacktestEngine` 和 `PortfolioEngine` 中统一使用前复权 `qfq` 数据
  2. 支持配置化复权类型选择
  3. 提供复权因子审计功能（`adjust_factor_manager.py` 已有但未集成）
- **验收**: 回测价格与券商软件同源

### Task 6.2: 停牌模拟（P2-13）

- **修复**:
  1. 检测零成交 / 零换手日
  2. 停牌期间跳过开仓操作
  3. 持仓股票复牌后可按复牌日价格成交
- **验收**: 长期停牌股票测试正确

### Task 6.3: 板块差异建模完善（P2-14）

- **当前状态**: `UnifiedMatchingEngine` 已实现板块差异涨跌停（`MarketConstants.LIMIT_RATIO`），但 `get_board_type()` 的板块标签来源需验证
- **修复**:
  1. 验证 `stock_metadata_manager` 板块标签与 `get_board_type()` 的一致性
  2. 新股前 N 日无涨跌停规则
- **验收**: 各板块涨跌停边界正确

### Task 6.4: 新股过滤（P2-15）

- **修复**:
  1. 上市天数 < 60 的股票默认过滤
  2. 可配置 IPO 过滤天数
- **验收**: 新股不进入回测宇宙

### Task 6.5: 成本模型补齐（P2-16）

- **修复**:
  1. 印花税可配置（`StampDuty: 0.0005`）— `UnifiedMatchingEngine` 已支持
  2. 两融标的标记可卖空
  3. 非两融标的不允许卖空

**Phase-6 退出标准**: 前复权默认；停牌/板块/新股/成本全部生效。回测结果与真实交易假设一致。

---

## 14. 验证与验收标准

### 14.1 全局覆盖率目标

| 阶段 | 新增测试 | 覆盖率要求 |
|------|----------|------------|
| Phase-S | 7+ | 修复点 100% |
| Phase-0 | 5+ | 基础设施 90%+ |
| Phase-1a | 20+ | UME 85%+, BacktestEngine 80%+, PortfolioEngine 75%+ |
| Phase-1b | 15+ | 向量化核心路径 80%+ |
| Phase-2a | 15+ | 决策链 75%+ |
| Phase-2b | 10+ | 因子系统 80%+ |
| Phase-3 | 20+ | 风险引擎 85%+ |
| Phase-4 | 10+ | 全局 70%+ |
| Phase-5 | 5+ | 全局 75%+ |
| Phase-6 | 10+ | 全局 75%+ |

### 14.2 量化验收标准

- 一切测试在无手动 `PYTHONPATH` 环境下收集
- `BacktestEngine` 与 `PortfolioEngine` 共享 `UnifiedMatchingEngine`，相同输入差异 <1%
- 信号日 ≠ 成交日（两个引擎均满足）
- 20 处 `iterrows` 全部消除；1 年日频数据回测 <200ms
- 5 个决策场景中生产和回测路径一致
- |train_IC - test_IC| > 0.1 时触发警告
- MDD/Duration/Calmar/CVaR 全部实现
- 5 个压力场景从 UI 一键运行
- 前复权默认；停牌/板块/新股/成本全部生效

### 14.3 发布检查清单

- [ ] `pytest tests/ --cov=uniquant` 通过且覆盖率 >= 75%
- [ ] 无 `verify=False` 残留
- [ ] 无 `/home/james` 硬编码
- [ ] 无 `sys.path.insert` 残留
- [ ] `GlobalConfig` 管理全部 yaml
- [ ] `BacktestEngine` 使用 `UnifiedMatchingEngine`
- [ ] `BacktestEngine` 成交使用 `open[t+1]`
- [ ] `PortfolioEngine.run()` 成交使用 `open[t+1]`
- [ ] 两个引擎共享同一 `UnifiedMatchingEngine` 实现
- [ ] 无 iterrows 在核心路径
- [ ] `HistoricalSimulationRisk` 回退 `risk_level` 键
- [ ] 前复权被统一使用
- [ ] 回撤归因报告在每次回测中包含

---

## 15. 文件变更清单

| 文件 | 修改类型 | 涉及 Task |
|------|----------|-----------|
| `src/uniquant/data/sources/eastmoney.py` | 修改 | S.1 |
| `src/uniquant/data/utils/js_executor.py` | 修改 | S.2 |
| `src/uniquant/data/sources/tdx.py` | 修改 | S.3 |
| `src/uniquant/signal/quality.py` | 修改 | S.4 |
| `src/uniquant/ui/health_check.py` | 修改 | S.5 |
| `src/uniquant/ui/components.py` | 修改 | S.6, 3.3 |
| `src/uniquant/services/analysis_service.py` | 修改 | S.7, 4.3, 2a.1 |
| `src/uniquant/brain/czsc/czsc_engine.py` | 修改 | S.7 |
| `tests/conftest.py` | 修改 | 0.1 |
| `pyproject.toml` | 修改 | 0.1, 0.3 |
| `src/uniquant/brain/czsc_engine.py` | 新增 shim | 0.4 |
| `src/uniquant/brain/ntf_engine.py` | 新增 shim | 0.4 |
| `src/uniquant/brain/regime_detector.py` | 新增 shim | 0.4 |
| `src/uniquant/shared/config_loader.py` | 修改 | 0.2 |
| `src/uniquant/hands/backtest/engine.py` | **大幅重构** | 1a.1, 1b.1 |
| `src/uniquant/hands/backtest/unified_matching_engine.py` | 修改 | 1b.3 |
| `src/uniquant/hands/backtest/portfolio_engine.py` | 修改 | 1a.2, 1b.2, 6.1, 6.2, 6.3, 6.5 |
| `src/uniquant/hands/backtest/signal_integrator.py` | 修改 | 1b.4 |
| `src/uniquant/hands/strategies/backtest.py` | 修改 | 1a.3, 1a.4 |
| `tests/test_portfolio_engine.py` | 新增 | 1a.2, 1a.5 |
| `tests/test_unified_matching_engine.py` | 新增 | 1a.1, 1a.5 |
| `tests/test_vectorization.py` | 新增 | 1b.7 |
| `src/uniquant/hands/strategies/wyckoff.py` | 修改 | 1b.5, 4.7, 2a.7 |
| `src/uniquant/hands/strategies/wyckoff_strategy.py` | 修改 | 1b.5 |
| `src/uniquant/hands/strategies/str_reversal.py` | 修改 | 1b.5, 2a.7 |
| `src/uniquant/hands/strategies/ma_cross.py` | 修改 | 2a.7 |
| `src/uniquant/shared/interfaces.py` | 修改 | 2a.1, 4.9 |
| `src/uniquant/signal/models.py` | 修改 | 2a.1 |
| `src/uniquant/signal/aggregator.py` | 修改 | 2a.2 |
| `src/uniquant/brain/fsm/fsm.py` | 修改 | 2a.2, 5.2 |
| `tests/test_decision_path_consistency.py` | 新增 | 2a.3 |
| `src/uniquant/brain/lppl/calculator.py` | 修改 | 2a.4, 4.8 |
| `src/uniquant/brain/lppl/computation.py` | 修改 | 2a.5 |
| `src/uniquant/brain/lppl/regime.py` | 修改 | 2a.6 |
| `src/uniquant/brain/lppl/data_manager.py` | 修改 | 4.8 |
| `src/uniquant/brain/factors/analyzer.py` | 修改 | 2b.1 |
| `src/uniquant/brain/factors/composer.py` | 修改 | 2b.1 |
| `src/uniquant/services/scan_service.py` | 修改 | 2b.1, 2b.2, 1b.6 |
| `src/uniquant/hands/backtest/overfitting_detector.py` | 修改 | 2b.3 |
| `src/uniquant/risk/drawdown_analyzer.py` | 新增 | 3.1, 3.2, 3.3, 3.4 |
| `tests/test_drawdown_analyzer.py` | 新增 | 3.1, 3.2 |
| `src/uniquant/hands/backtest/report_generator.py` | 修改 | 3.4 |
| `src/uniquant/ui/manager_logic.py` | 修改 | 3.3 |
| `src/uniquant/ui/dashboard.py` | 修改 | 3.3, S.6 |
| `src/uniquant/risk/sizer.py` | 修改 | 3.5 |
| `src/uniquant/risk/portfolio_optimizer.py` | 修改 | 3.6 |
| `src/uniquant/risk/evt_risk.py` | 新增废弃封装 | 4.1 |
| `src/uniquant/risk/historical_risk.py` | 新增 | 4.1 |
| `src/uniquant/shared/error_handling.py` | 修改 | 4.2, 5.3 |
| `src/uniquant/services/data_service.py` | 修改 | 4.4 |
| `src/uniquant/data/lake/storage_manager.py` | 修改 | 4.4 |
| `src/uniquant/data/pipeline/data_validator.py` | 修改 | 4.5 |
| `src/uniquant/shared/constants.py` | 修改 | 4.6 |
| `src/uniquant/brain/wyckoff/rules.py` | 修改 | 4.7 |
| `src/uniquant/brain/wyckoff/classifiers.py` | 修改 | 4.7 |
| `src/uniquant/signal/db.py` | 修改 | 4.10 |
| `src/uniquant/hands/strategies/regime.py` | 修改 | 4.11 |
| `src/uniquant/services/analysis/signal_service.py` | 修改 | 4.12 |
| `src/uniquant/shared/di_container.py` | 删除 | 5.1 |
| `src/uniquant/data/managers/adjust_factor_manager.py` | 修改（集成到回测） | 6.1 |
| `src/uniquant/data/managers/stock_metadata_manager.py` | 修改 | 6.3 |
| `src/uniquant/data/scripts/update_daily_data_akshare.py` | 修改 | 1b.6 |
| `src/uniquant/data/scripts/update_daily_incremental.py` | 修改 | 1b.6 |
| `src/uniquant/data/scripts/download_baostock_pro.py` | 修改 | 1b.6 |
| `src/uniquant/data/utils/smart_factor_calculator.py` | 修改 | 1b.6 |
| `src/uniquant/brain/wyckoff/trading.py` | 修改 | 1b.6 |

---

## 附录 A：问题到 Task 映射矩阵

| 问题 ID | 问题描述 | 严重性 | 对应 Task |
|---------|----------|--------|-----------|
| P0-01 | 导入路径损坏 | P0 | 0.1, 0.4 |
| P0-02 | 回测同根 K 线执行 | P0 | 1a.1 |
| P0-03 | 组合回测缺 A 股约束（已部分修复） | P0→P1 | 1a.2 |
| P0-04 | 策略函数未来数据 | P0 | 2a.7 |
| P0-05 | 因子权重全样本泄露 | P0 | 2b.1, 2b.2 |
| P0-06 | EVT 命名欺诈 | P0 | 4.1 |
| P0-07 | SSL 验证禁用 | P0 | S.1 |
| P0-08 | JS 代码注入 | P0 | S.2 |
| P0-09 | 硬编码开发者路径 | P0 | S.3 |
| P0-10 | quality.py AttributeError | P0 | S.4 |
| P0-11 | CZSC 键名不匹配 | P0 | S.7, 2a.1 |
| **P0-12** | **engine.py 未接入 UME** | **P0** | **1a.1** |
| P1-01 | 配置文件未全部加载 | P1 | 0.2 |
| P1-02 | AnalysisService 过耦合 | P1 | 4.3 |
| P1-03 | DataService 职责过多 | P1 | 4.4 |
| P1-04 | 幸存者偏差 | P1 | 1a.4 |
| P1-05 | 批回测缺部分成交/滑点 | P1 | 1a.3 |
| P1-06 | PBO 随机 shuffle | P1 | 2b.3 |
| P1-07 | FSM 命名 MA 交叉 | P1 | 4.1 |
| P1-08 | PositionSizer 简化 | P1 | 3.5 |
| P1-09 | 优化器缺防护 | P1 | 3.6 |
| P1-10 | UI 健康检查导入全错 | P1 | S.5 |
| P1-11 | 函数签名不匹配 | P1 | S.6 |
| P1-12 | LPPL 缓存泄漏 | P1 | 2a.4 |
| P1-13 | LPPL 超时丢结果 | P1 | 2a.5 |
| P1-14 | 信号聚合丢原始信息 | P1 | 2a.2 |
| P1-15 | LPPL MA 回退假阳性 | P1 | 2a.6 |
| P1-16 | 向量化缺失（20 处 iterrows） | P1 | 1b.1~1b.7 |
| P1-17 | 回撤归因缺失 | P1 | 3.1, 3.2, 3.4 |
| P1-18 | DI 容器死代码 | P1 | 5.1 |
| P1-19 | 装饰器堆叠重试失效 | P1 | 4.2 |
| **P1-20** | **UME T+1 检查非向量化** | **P1** | **1b.3** |
| **P1-21** | **PortfolioEngine.run() 同日成交** | **P1** | **1a.2** |
| P2-01~P2-20 | （同 v2.0） | P2 | （同 v2.0 对应 Task） |

---

## 附录 B：v3.0 相对 v2.0 的变更摘要

| 变更项 | v2.0 | v3.0 | 理由 |
|--------|------|------|------|
| P0-03 状态 | "完全缺失 A 股约束" | **已部分修复**，降级为 P1 | `UnifiedMatchingEngine` 已存在且 `PortfolioEngine` 已接入 |
| P0-12 | 不存在 | **新增：engine.py 未接入 UME** | 代码实证发现两套执行逻辑并存 |
| P1-20 | 不存在 | **新增：UME T+1 非向量化** | 代码实证发现逐行循环查日历 |
| P1-21 | 不存在 | **新增：组合同日成交** | 代码实证发现 `run()` 方法同日信号同日成交 |
| Task 1a.1 | 仅改成交价为 `open[idx+1]` | **重构为接入 UME + 信号视野限制** | 仅改成交价不够，需统一执行引擎 |
| Task 1a.2 | 补齐 T+1/涨跌停/印花税 | **修复同日成交 + 验证 UME** | UME 已实现约束，需修复 `run()` 逻辑 |
| Task 1b.1 | 纯向量化 | **半向量化 + Numba JIT** | 回测主循环有路径依赖，纯向量化不可行 |
| Task 2b.1 | 单次 `temporal_split` | **扩展窗口滚动** | A 股因子时变特性显著，单次分割不够严谨 |
| Task 6.3 | 从零实现板块差异 | **验证已有实现 + 补充新股规则** | `UME` 已含板块差异涨跌停 |
| 总问题数 | 50 | **53** | 新增 3 项经代码实证确认的问题 |
