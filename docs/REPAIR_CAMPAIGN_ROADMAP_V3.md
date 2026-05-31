# UniQuant 修复战役路线图 v3.0（最终核验版）

> **制定日期**: 2026-05-31
> **版本**: v3.0 (深度核验修正版)
> **制定依据**: 7份审计文档 × 4路并行Agent深度源码核验 × 15项附加发现
> **综合评分**: 4.6/10 — 数值正确性 4.0, A股合规性 5.0, 线程安全 4.5, 配置一致性 4.0, 代码质量 5.5

---

## 目录
1. [战役优先级矩阵 (Triage Matrix)](#1)
2. [完整Bug清单（去重核验后 45 项）](#2)
3. [依赖拓扑图 (Dependency DAG)](#3)
4. [多阶段修复冲刺计划 (4 Sprints)](#4)
5. [Subagent 并发派发指南](#5)
6. [阶段性熔断与回归指标](#6)
7. [全局回滚策略](#7)
8. [审计文档误报清单](#8)
9. [附录：深度核验修正对照表](#9)
10. [附录：附加发现清单](#10)

---

<h2 id="1">一、战役优先级矩阵 (Triage Matrix)</h2>

### 1.1 致命五角星（P0，互不依赖，可并行修复）

| 排名 | Bug ID | 问题 | 评级 | 模块 | 前置条件 | 工时 |
|------|--------|------|------|------|----------|------|
| 1 | **B-004** | LPPL `best_cost` 已是 RMSE，再 `np.sqrt` 双重开方 → 置信度完全失效 | **P0** | `brain/lppl/engine.py:348` | 无 | 10min |
| 2 | **B-001** | 印花税 `max_year < 2024` 应为 `date >= 2023-08-28` → 2023H2 多扣一倍 | **P0** | `hands/strategies/backtest.py:321` | 无 | 45min |
| 3 | **G2\*** | `evt_metrics["risk_level"]` KeyError + `== "CRITICAL"` 值与 `regime` 返回值不匹配 | **P0** | `brain/fsm/fsm.py:371` + `risk/evt_risk.py:92` | 无 | 15min |
| 4 | **B-027** | `_hash_dataframe` 仅采样 head/tail 5行 + `generate_cache_key` Series同款bug | **P0** | `shared/cache/__init__.py:21-51` | 无 | 30min |
| 5 | **B-006** | `MemoryCacheBackend` get/set/delete 零锁 + `DiskCacheBackend.delete()` 零锁 | **P0** | `shared/cache/backends.py:28-301` | 无 | 30min |

> \*G2 源自动态压力测试交叉验证发现，非原始审计报告

### 1.2 协议层根节点（P0-P1，Layer 0）

| 排名 | Bug ID | 问题 | 评级 | 前置条件 | 工时 | 代理人 |
|------|--------|------|------|----------|------|--------|
| 6 | **B-002** | CZSC `AnalysisError` 未导入 → 模块加载 NameError | **P0** | 无 | 5min | A |
| 7 | **B-003** | `Indicators=None` 后无 None 检查 → 直接调用 `.calc_ma()` 崩溃 | **P0** | 无 | 5min | A |
| 8 | **B-005** | `np.abs(tc-t)` 数学错误 → 虚假对称波形 | **P0** | 无 | 15min | A |
| 9 | **B-010** | `LPPLEngine(config=config)` TypeError + `detect_bubble` 期望 DataFrame 收到 Series | **P0** | 无 | 15min | A |
| 10 | **B-012** | `run_backtest` 不传 volume/avg_daily_volume → 非线性滑点永不为零 + `required_cols` 缺 `"volume"` | **P0** | 无 | 30min | C |
| 11 | **B-009** | `from_yaml` 滑点单位转换：YAML `0.1` 应为 `0.05`（万5为标准）+ `from_env` 缺 transfer_fee | **P0** | 无 | 30min | C |
| 12 | **B-013** | `handle_errors` 异常捕获顺序错误：子类被父类拦截 | **P1** | 无 | 15min | B |
| 13 | **B-024** | `LoggerFactory.__new__` 无锁 + `_initialized` 竞态 + 模块级 `_factory` 竞态（3处） | **P1** | 无 | 20min | D |
| 14 | **B-025** | `AnalysisEngineFactory._lazy_init` 无锁 → 引擎双重初始化 + 泄漏 | **P1** | 无 | 15min | D |
| 15 | **D-05** | `handle_network_errors` 装饰器顺序错误 → 重试永不生效 | **P2** | B-013 | 10min | B |

### 1.3 配置与规则层（P1-P2，Layer 1-2）

| 排名 | Bug ID | 问题 | 评级 | 前置条件 | 工时 | 代理人 |
|------|--------|------|------|----------|------|--------|
| 16 | **B-010c** | YAML vs 常量 9 处冲突 + `alpha_decoupler.py` 第3组冲突值 | **P1** | B-009 | 75min | E |
| 17 | **B-028** | `from_yaml` 缺 `stamp_tax_pct`/`transfer_fee_pct` + YAML 缺字段定义 | **P1** | B-009 | 20min | E |
| 18 | **B-008** | GEM/STAR 价格笼子 ±1% 应为 ±2% | **P1** | 无 | 5min | F |
| 19 | **B-022\*** | 北交所价格笼子 ±1% 应为 **±5%**（修正：原方案 3% 错误） | **P2** | 无 | 5min | F |
| 20 | **B-015** | IPO 涨跌停规则完全缺失（主板+44%/-36%，科创/创业板前5日无限制） | **P1** | 无 | 40min | F |
| 21 | **B-016** | 北交所前缀 `["8","4"]` 含新三板 + 缺 `"920"`（2024年起新股） | **P2** | 无 | 10min | F |
| 22 | **B-034** | `detect_board()` 永不返回 ST（无 `name` 参数） | **P1** | 无 | 20min | F |
| 23 | **B-030** | 价格笼子未区分集合竞价/连续竞价时段 | **P1** | B-008 | 20min | F |
| 24 | **B-011** | LPPL 代价函数 SSE vs RMSE 不统一（core.py vs engine.py） | **P1** | B-004 | 20min | G |
| 25 | **B-012t** | LPPL tau 处理 3 种方式不统一（1e-8/1e-10/NaN）+ `cost_function` 不检查 NaN | **P1** | B-004 | 25min | G |
| 26 | **B-026** | 缓存无哨兵对象 → 无法区分"None 值"和"未命中" | **P1** | B-006 | 15min | E |
| 27 | **B-036** | `GlobalConfig` 缺 `set()`/`reload()` 方法 | **P2** | 无 | 20min | E |
| 28 | **B-009u** | 三套滑点实现不统一（0.05%/0.1%/动态） | **P1** | B-009 | 30min | E |
| 29 | **B-037\*** | LPPL DE `maxiter=100` 不足 → 修正为 **500**（原方案 300 仍不足） | **P2** | B-011 | 5min | G |
| 30 | **B-009e** | `from_env` 缺 `transfer_fee_pct` 环境变量映射 | **P2** | B-009 | 10min | E |

### 1.4 逻辑与边界层（P1-P2，Layer 2-3）

| 排名 | Bug ID | 问题 | 评级 | 前置条件 | 工时 | 代理人 |
|------|--------|------|------|----------|------|--------|
| 31 | **B-007** | CIRCUIT_BREAK 完全不可达（PYRAMID/EXIT 在 `make_decision` 中可达） | **P1** | 无 | 30min | H |
| 32 | **B-031\*** | 卖出阈值硬编码 `-0.5` + `_check_buy_blockers` 硬编码 `-0.3`（2处） | **P2** | B-007 | 15min | H |
| 33 | **D-07** | `_check_buy_blockers` `-0.3` 硬编码（B-031 扩展） | **P2** | B-031 | 0min | H |
| 34 | **B-014** | `with_timeout` 守护线程无法取消 → 改用 `ThreadPoolExecutor` | **P1** | 无 | 20min | I |
| 35 | **B-020** | 集合竞价时段完全缺失（9:15-9:25, 14:57-15:00） | **P2** | B-030 | 15min | I |
| 36 | **B-029** | MarketHours 无节假日日历（数据存在于 TradeCalendarManager 但未使用） | **P1** | 无 | 30min | I |
| 37 | **B-032\*** | 3处函数级 `import` requests/urllib3/pandas → 提至模块级 | **P2** | B-013 | 10min | B |
| 38 | **D-13** | LPPL calculator `cost_function` 不检查 NaN → NaN 传播到 DE 优化器 | **P1** | B-012t | 10min | G |
| 39 | **B-019\*** | LPPL 5-7 种独立/内联实现（非审计报告的 4 种） | **P2** | B-011+B-012t | 45min | J |

### 1.5 架构治理层（P2-P3，Layer 4）

| 排名 | Bug ID | 问题 | 评级 | 前置条件 | 工时 | 代理人 |
|------|--------|------|------|----------|------|--------|
| 40 | **B-018** | 两套 DI 容器并存 + `DIContainer` 80 行死代码 | **P2** | 无 | 60min | K |
| 41 | **B-017** | UI 层 5 处 DAG 违规 | **P2** | B-018 | 60min | K |
| 42 | **B-035** | T+1 使用日历日而非交易日判断 | **P2** | 无 | 30min | L |
| 43 | **B-023/B-038** | 零股卖出规则缺失（`round_lot` 需 `ceil` 参数） | **P2** | 无 | 15min | L |
| 44 | **B-021** | signal/wyckoff/策略/高级回测零测试覆盖 | **P2** | 全部修复完成 | 120min | L |
| 45 | **D-09** | `DIContainer` 死代码清理 | **P3** | B-018 | 0min | K |

---

<h2 id="3">三、依赖拓扑图 (Dependency DAG)</h2>

```
Layer 0 (根节点 — 15项，互不依赖，可全部并行):
┌──────────────────────────────────────────────────────────────────────────────┐
│ B-001 stamp_tax  │ B-002 CZSC导入   │ B-003 FSM None    │ B-004 RMSE       │
│ B-005 abs错误    │ B-006 缓存无锁    │ B-010 LPPL构造    │ B-012 成交量     │
│ B-027 哈希碰撞   │ G2    KeyError    │ B-009 滑点转换    │ B-013 异常顺序   │
│ B-024 日志锁     │ B-025 工厂锁      │ D-05   重试顺序   │                  │
└──────────────────────────────────────────────────────────────────────────────┘
        ↓ (数值正确性必须先修复，否则上层修复无意义)
Layer 1 (核心算法 + A股规则 — 依赖 Layer 0):
┌──────────────────────────────────────────────────────────────────────────────┐
│ B-008 价格笼子   │ B-022 北交所笼子  │ B-015 IPO规则    │ B-016 北交所前缀 │
│ B-034 ST识别     │ B-030 笼子时段    │ B-026 缓存哨兵   │ B-036 set/reload │
│ B-009e env传值   │ B-028 YAML缺字段  │ B-010c 配置冲突   │ B-009u 滑点统一   │
│ B-037 DE迭代数   │ B-011 LPPL代价    │ B-012t LPPL tau   │ D-13  NaN传播    │
└──────────────────────────────────────────────────────────────────────────────┘
        ↓
Layer 2 (逻辑补全 — 依赖 Layer 1):
┌──────────────────────────────────────────────────────────────────────────────┐
│ B-007 FSM状态   │ B-031 阈值不对称  │ D-07   -0.3硬编码 │ B-014 with_timeout│
│ B-020 集合竞价   │ B-029 节假日      │ B-032 import提升  │ B-019 LPPL去重    │
└──────────────────────────────────────────────────────────────────────────────┘
        ↓
Layer 3 (架构治理 — 依赖 Layer 2):
┌──────────────────────────────────────────────────────────────────────────────┐
│ B-018 DI合并    │ B-017 UI DAG     │ B-035 T+1统一     │ B-023 零股卖出    │
│ B-021 测试覆盖   │ D-09   死代码清理 │                    │                   │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

<h2 id="4">四、多阶段修复冲刺计划 (4 Sprints)</h2>

### Sprint 1: 基建与排雷 (Infrastructure & Data Core)

**目标**: 消除所有 P0 缺陷和 Layer 0 根节点，恢复核心引擎可加载性和数值正确性
**工时**: 4-5h | **Bug**: 18项（含4项附加发现） | **并行**: 4路

| Bug ID | 文件:行 | 修复内容 | 工时 | 代理人 |
|--------|---------|---------|------|--------|
| B-004 | `brain/lppl/engine.py:348` | `rmse = best_cost`（best_cost 已是 RMSE） | 10min | A |
| B-001 | `hands/strategies/backtest.py:218-321` | 逐笔交易判断 + `_get_stamp_tax()` 函数 | 45min | C |
| G2\* | `brain/fsm/fsm.py:371,385` + `risk/evt_risk.py:92` | `evt_metrics["risk_level"]` → 值映射层 `{"CRISIS":"CRITICAL",...}` + L385同步修复 | 15min | A |
| B-027 | `shared/cache/__init__.py:21-51` | `_hash_dataframe` 全量哈希 + `generate_cache_key` 的 Series/Index 同款修复 | 30min | B |
| B-006 | `shared/cache/backends.py:28-301` | MemoryCacheBackend 加 `RLock` + DiskCacheBackend.delete() 加锁 | 30min | B |
| B-002 | `brain/czsc/czsc_engine.py:16,148,443` | 添加 `from ...shared.exceptions import AnalysisError` | 5min | A |
| B-003 | `brain/fsm/fsm.py:112` | 添加 `if Indicators is None: raise ImportError(...)` | 5min | A |
| B-005 | `brain/lppl/visualizer.py:123` | `np.abs(tc-t)` → NaN mask | 15min | A |
| B-010 | `services/analysis/lppl_analysis_engine.py:45` + `engine.py:974` | `LPPLEngine()` 无参数 + `close` 包装为 DataFrame | 15min | A |
| B-012 | `hands/backtest/engine.py:305-357` | `required_cols` + 预计算 `avg_daily_volume` + 传递参数 | 30min | C |
| B-009 | `shared/cost_model.py:85` + `config/trading.yaml:51` | YAML `0.1` → `0.05`（代码转换 `/100` 正确） | 15min | C |
| B-013 | `shared/error_handling.py:86-144` | 重排异常捕获：AlphaTacticianError → expected → Exception | 15min | B |
| B-024 | `shared/logger_factory.py:31-173` | 添加双重检查锁（_new_ + `_initialized` + 模块级 `_factory`） | 20min | D |
| B-025 | `services/analysis/engine_factory.py:18-69` | `_lazy_init` + `brain` 属性添加 `threading.Lock()` | 15min | D |
| D-05 | `shared/error_handling.py:362` | `@handle_errors` 和 `@retry_on_exception` 顺序调换 | 10min | B |
| B-032 | `shared/error_handling.py:350,416,449` | 3 处 `import` 提至模块级 | 10min | B |

**Sprint 1 Subagent 调度**:
```
Agent A (brain走廊): czsc_engine.py, fsm.py, engine.py, visualizer.py, lppl_analysis_engine.py
                     → B-002, B-003, B-004, B-005, B-010, G2
Agent B (shared走廊): backends.py, error_handling.py, cache/__init__.py
                     → B-006, B-013, B-027, D-05, B-032
Agent C (hands走廊): backtest.py, cost_model.py, engine.py, trading.yaml
                    → B-001, B-009, B-012
Agent D (thread-safety): logger_factory.py, engine_factory.py
                        → B-024, B-025
文件独占性: ✅ 4路 Agent 文件列表完全不相交
```

---

### Sprint 2: 引擎重装 (Algorithms & A-Share Rules)

**目标**: 修复 A 股交易规则合规性，建立"单一真值源"，统一滑点/LPPL 实现
**工时**: 5-6h | **Bug**: 15项（含1项附加） | **并行**: 3路

| Bug ID | 文件:行 | 修复内容 | 工时 | 代理人 |
|--------|---------|---------|------|--------|
| B-010c | `config/*.yaml` + `constants/*.py` + `alpha_decoupler.py:42-43` | 对齐 3 组市值阈值到唯一 YAML 真值源 | 75min | E |
| B-009e | `shared/cost_model.py:48-68` | `from_env` 添加 `LPPL_COST_TRANSFER_FEE` 映射 | 10min | E |
| B-028 | `shared/cost_model.py:83-88` + `config/trading.yaml` | `from_yaml` 读 `stamp_tax_pct`/`transfer_fee_pct` + YAML 添加字段 | 20min | E |
| B-026 | `shared/cache/backends.py:72-73` + `cache/__init__.py` | 添加 `_SENTINEL` 哨兵对象；`smart_cache` 识别哨兵 | 15min | E |
| B-036 | `shared/config_loader.py` | GlobalConfig 添加 `set(key_path, value)` + `reload()` | 20min | E |
| B-009u | `shared/cost_model.py:29` + `slippage_model.py:15` + `engine.py:101` | `DefaultSlippage.estimate()` 改为引用 `SLIPPAGE_PCT=0.0005` | 30min | E |
| B-008 | `shared/market_rules.py:27-28` | GEM/STAR `price_collar_pct` 0.01→0.02 | 5min | F |
| B-022\* | `shared/market_rules.py:29` | 北交所 `price_collar_pct` 0.01→**0.05**（修正：原方案 0.03 错误） | 5min | F |
| B-015 | `shared/limit_checker.py` | 添加 IPO 涨跌停规则：+44%/-36%, 前5日/前1日无限制 | 40min | F |
| B-016 | `shared/constants/market.py:70` | 北交所 `["8","4"]` → `["83","87","920"]` + 市场检测同步 | 10min | F |
| B-034 | `shared/market_rules.py:34-48` | `detect_board()` 添加 `name` 参数 + ST 前缀检测 | 20min | F |
| B-030 | `shared/price_collar.py` + `shared/market_rules.py` | 添加 `trading_phase` 参数 → 集合竞价不应用笼子 | 20min | F |
| B-011 | `brain/lppl/core.py:119` + `engine.py:135` | 统一为 RMSE：core.py SSE→RMSE | 20min | G |
| B-012t\* | `brain/lppl/core.py:74` + `engine.py:125` + `calculator.py:188` | 统一 tau 为 1e-8 clamp + 加 NaN 检查 | 25min | G |
| D-13 | `brain/lppl/calculator.py:215` | `cost_function` 添加 `np.isfinite` 检查，NaN 时返回 penalty | 10min | G |
| B-037\* | `brain/lppl/engine.py:57` | DE `maxiter` 100→**500**（修正：原方案 300 仍不足） | 5min | G |

**Sprint 2 Subagent 调度**:
```
Agent E (config权威): config/*.yaml, constants/*, cost_model.py, config_loader.py,
                      slippage_model.py, alpha_decoupler.py, cache/backends.py
                     → B-010c, B-009e, B-028, B-026, B-036, B-009u
Agent F (A股合规): market_rules.py, limit_checker.py, constants/market.py,
                    price_collar.py, market.py
                   → B-008, B-022, B-015, B-016, B-034, B-030
Agent G (LPPL统一): brain/lppl/core.py, engine.py, calculator.py
                   → B-011, B-012t, D-13, B-037
区域隔离: Agent E 只改 data.py/technical.py/risk.py; Agent F 只改 market.py BOARD_PREFIX
文件独占性: ✅ 3路 Agent 文件列表完全不相交
```

---

### Sprint 3: 逻辑补全与边界 (Logic Completion & Edge Cases)

**目标**: 完成 FSM 状态机逻辑，补充集合竞价/节假日日历，LPPL 去重
**工时**: 3-4h | **Bug**: 9项 | **并行**: 3路

| Bug ID | 文件:行 | 修复内容 | 工时 | 代理人 |
|--------|---------|---------|------|--------|
| B-007 | `brain/fsm/fsm.py:95-424` | 添加 CIRCUIT_BREAK 触发逻辑（单日跌幅阈值检查）+ 修复转换表 | 30min | H |
| B-031 | `brain/fsm/fsm.py:288,342` | L288: `-0.5`→参数化；L342: `-0.3`→参数化 | 15min | H |
| B-014 | `shared/utils.py:18-118` | `with_timeout` 改用 `concurrent.futures.ThreadPoolExecutor` | 20min | I |
| B-020 | `shared/constants/market.py:112-229` | MarketHours 添加集合竞价时段 + `is_call_auction()` 方法 | 15min | I |
| B-029 | `shared/constants/market.py:128-160` + `data/managers/trade_calendar_manager.py:13-52` | MarketHours 添加节假日日历 | 30min | I |
| B-019 | `brain/lppl/`（5个文件） | 以 calculator.py VarPro 为权威，删除重复实现 | 45min | J |
| B-021a | `tests/test_signal.py`（新文件） | signal/（5个模块）基础单元测试 | 30min | J |
| B-021b | `tests/test_wyckoff.py`（新文件） | wyckoff/ 核心分类器测试 | 30min | J |

**Sprint 3 Subagent 调度**:
```
Agent H (fsm-logic): brain/fsm/fsm.py
                     → B-007, B-031
Agent I (perf-safety): shared/utils.py, shared/constants/market.py,
                        data/managers/trade_calendar_manager.py
                       → B-014, B-020, B-029
Agent J (lppl-dedup+test): brain/lppl/ (5 files), tests/ (新文件)
                           → B-019, B-021a, B-021b
文件独占性: ✅ 3路 Agent 文件列表完全不相交
```

---

### Sprint 4: 架构治理 (Architecture Governance)

**目标**: 消除架构级违规，统一 DI/T+1，完成测试覆盖
**工时**: 4-5h | **Bug**: 6项 | **并行**: 2路

| Bug ID | 文件:行 | 修复内容 | 工时 | 代理人 |
|--------|---------|---------|------|--------|
| B-018 | `shared/di_container.py` + `services/service_container.py` | 合并 DI 容器 → DIContainer 删除，ServiceContainer 保留并增强 | 60min | K |
| B-017 | `ui/dashboard.py:612` + `lppl_visualizer.py:9-10` + `manager_portfolio_analytics_service.py:23,64,113` | UI 通过 services 门面访问 → 消除 DAG 违规 | 60min | K |
| B-035 | `hands/backtest/unified_matching_engine.py:165` | T+1 改为基于交易日历索引差值检查 | 30min | L |
| B-023/B-038 | `shared/market_rules.py:20-21` | `round_lot` 添加 `ceil` 参数 + 类型标注更新 | 15min | L |
| B-021c | `tests/test_strategies.py`（新文件） | 策略层（6个策略）单元测试 | 30min | L |
| B-021d | `tests/test_backtest_advanced.py`（新文件） | 回测高级功能测试 | 30min | L |

**Sprint 4 Subagent 调度**:
```
Agent K (架构清理): di_container.py, service_container.py, UI层(3 files)
                   → B-018 → B-017 (依赖排序: DI合并先于UI修复)
Agent L (测试+边界): unified_matching_engine.py, market_rules.py, tests/ (新文件)
                    → B-035, B-023/B-038, B-021c, B-021d
文件独占性: ✅ 2路 Agent 文件列表完全不相交
```

---

## 5. Subagent 并发派发总图

```
时间轴 →
┌──────────────────────────────────────────────────────────────────────────────────┐
│ Sprint 1 (4-5h)     │ Sprint 2 (5-6h)      │ Sprint 3 (3-4h)    │ Sprint 4 (4-5h)│
├──────────────────────┼───────────────────────┼─────────────────────┼────────────────┤
│  ┌─ Agent A ──────┐  │  ┌─ Agent E ──────┐  │  ┌─ Agent H ──┐   │  ┌─ Agent K ──┐ │
│  │ brain/czsc     │  │  │ config/*.yaml   │  │  │ brain/fsm  │   │  │ UI layer   │ │
│  │ brain/fsm      │  │  │ constants/*     │  │  │            │   │  │ DI容器     │ │
│  │ brain/lppl/*   │  │  │ cost_model.py   │  │  └────────────┘   │  └────────────┘ │
│  │ services/lppl  │  │  │ config_loader   │  │  ┌─ Agent I ──┐   │  ┌─ Agent L ──┐ │
│  └────────────────┘  │  │ slippage_model  │  │  │ utils.py   │   │  │ matching   │ │
│  ┌─ Agent B ──────┐  │  │ alpha_decoupler │  │  │ market.py  │   │  │ market_    │ │
│  │ shared/cache/*  │  │  └────────────────┘  │  └────────────┘   │  │ rules.py   │ │
│  │ shared/error_   │  │  ┌─ Agent F ──────┐  │  ┌─ Agent J ──┐   │  │ tests/     │ │
│  │ handling.py     │  │  │ market_rules    │  │  │ brain/lppl │   │  └────────────┘ │
│  └────────────────┘  │  │ limit_checker   │  │  │ tests/*    │   │                │
│  ┌─ Agent C ──────┐  │  │ constants/      │  │  └────────────┘   │                │
│  │ hands/backtest  │  │  │ market          │  │                   │                │
│  │ cost_model.py   │  │  │ price_collar   │  │                   │                │
│  └────────────────┘  │  └────────────────┘  │                   │                │
│  ┌─ Agent D ──────┐  │  ┌─ Agent G ──────┐  │                   │                │
│  │ logger_factory  │  │  │ brain/lppl/*   │  │                   │                │
│  │ engine_factory  │  │  │ (代价+tau+DE)   │  │                   │                │
│  └────────────────┘  │  └────────────────┘  │                   │                │
│ 并行度: 4路          │ 并行度: 3路          │ 并行度: 3路       │ 并行度: 2路    │
└──────────────────────┴───────────────────────┴─────────────────────┴────────────────┘
                         ↓                       ↓                    ↓
                   [熔断门禁]               [熔断门禁]           [熔断门禁]
                   Sprint 1 通过            Sprint 2 通过         Sprint 3 通过
```

---

## 6. 阶段性熔断与回归指标

### Sprint 1 熔断门禁

| # | 验证项 | 命令/断言 | 通过标准 |
|---|--------|---------|---------|
| 1 | 导入链 | `python -c "import uniquant; import uniquant.shared; import uniquant.brain.czsc.czsc_engine; import uniquant.brain.fsm.fsm; from uniquant.shared.cache.backends import MemoryCacheBackend,DiskCacheBackend; print('OK')"` | OK |
| 2 | LPPL数值 | `pytest tests/ -k lppl -xvs` 或 cost_weight 在 0.3-0.95 范围 | 通过 |
| 3 | 线程安全 | 20线程 × 1000次 set/get 并发测试 | 零数据损坏 |
| 4 | 核心测试 | `pytest tests/test_engine_factory.py -xvs` | 全部通过 |
| 5 | 代码质量 | `ruff check src/uniquant/ --select E,F` | 零新增 error |
| 6 | 缓存哈希 | head/tail/中间不同行的 DataFrame 产生不同哈希 | 无碰撞 |

### Sprint 2 熔断门禁

| # | 验证项 | 通过标准 |
|---|--------|---------|
| 1 | 配置一致性 | YAML vs Python 常量零冲突 |
| 2 | 价格笼子 | GEM/STAR ±2%, 北交所 ±5%, 主板 ±2% |
| 3 | 北交所前缀 | `["83","87","920"]`, 不含 `"4"` |
| 4 | ST检测 | `detect_board("600123.SH", name="ST某某")` → BoardType.ST |
| 5 | LPPL收敛 | 5 次运行 RMSE 范围差 < 20% |
| 6 | 全量导入 | `python -c "import uniquant; print('OK')"` |

### Sprint 3 熔断门禁

| # | 验证项 | 通过标准 |
|---|--------|---------|
| 1 | FSM状态 | 7/7 状态全部可达 |
| 2 | 节假日 | 春节/国庆正确标记非交易日 |
| 3 | 集合竞价 | 9:20 `is_call_auction()` True; 10:00 False |
| 4 | 超时 | `with_timeout` 超时后线程可取消 |
| 5 | 新测试 | `pytest tests/test_signal.py tests/test_wyckoff.py -xvs` |
| 6 | LPPL去重 | 仅 1 个 `lppl_func` 权威实现 |

### Sprint 4 熔断门禁

| # | 验证项 | 通过标准 |
|---|--------|---------|
| 1 | DAG零违规 | `grep -rn "^from.*uniquant\.\(brain\|data\|risk\)" src/uniquant/ui/` → 零匹配 |
| 2 | DI合并 | `python -c "from services.service_container import ServiceContainer; s=ServiceContainer(); s.initialize(); print('OK')"` |
| 3 | T+1 | 跨周末 T+1 正确禁止 |
| 4 | 零股卖出 | `round_lot(50, is_sell=True)=50`, `round_lot(150, is_sell=False)=100` |
| 5 | 全量回归 | `pytest tests/ -xvs --cov=src/uniquant --cov-report=term-missing` > 70% |

---

## 7. 全局回滚策略

| 触发条件 | 回滚动作 |
|---------|---------|
| Sprint 1 导入链失败 | `git stash` → 回到基线 → 定位修复后重试 |
| Sprint 2 配置冲突不可收敛 | 回滚 B-010c，保留 YAML 原值，仅修正常量 |
| Sprint 3 FSM 引入新死状态 | 回滚 B-007，保持 4 状态版本 |
| Sprint 4 覆盖率 < 50% | 不合并，作为独立分支提交 |

---

## 8. 审计文档误报清单

| 审计声称 | 核实结论 | 说明 |
|---------|---------|------|
| `services/__init__.py` 8个幽灵导入 | 已修复 | 已用 `__getattr__` 懒加载 |
| `brain/lppl/__init__.py` 7个幽灵导入 | 已修复 | 已用 try/except |
| 最大回撤阈值 0.15 vs 0.20 | 误报 | 均为 0.15 |
| `not LimitStatus` 永远 False | 误报 | 返回 bool, not bool 正确 |
| LPPL 4 种独立实现 | 低估 | 实际 5-7 种变体 |

---

## 9. 附录：v2.0 → v3.0 深度核验修正对照

| 原条目 | 原方案 | 修正 | 原因 |
|--------|--------|------|------|
| G2 | `.get()` + `== "CRITICAL"` | 添加 `{"CRISIS":"CRITICAL"}` 值映射层 | `regime` 返回 "CRISIS" 非 "CRITICAL" |
| B-022 | 笼子 0.03 (±3%) | **0.05** (±5%) | 北交所实际规则 ±5% |
| B-031 | 仅修第288行 | 补充第342行 `-0.3` | 第二处硬编码 |
| B-037 | maxiter 300 | **500** | 7维搜索需更多迭代 |
| B-016 | `["83","87"]` | `["83","87","920"]` | 2024年起 920 新股 |
| B-019 | 4 种实现 | **5-7 种** | 含内联 + Numba 变体 |
| B-001 | 30min | **45min** | 需 `process_stock` 改造 |
| B-012 | 15min | **30min** | 需预计算 + 列验证 |
| B-028 | 仅代码修复 | **YAML 文件也需改** | 字段缺失 |
| B-010c | 2 组冲突 | **3 组**（含 alpha_decoupler.py） | 第 3 组冲突 |
| B-032 | 1 处 import | **3 处**同一文件 | 另有同类违规 |
| D-05 | — | 装饰器顺序错误 | 重试永不触发 |

---

## 10. 附录：15 项深度核验附加发现

| # | 文件:行 | 问题 | 评级 | 相关Bug |
|---|---------|------|------|---------|
| D-01 | `backends.py:186` | DiskCacheBackend `self._lock` 从未使用 | P3 | B-006 |
| D-02 | `backends.py:289-301` | DiskCacheBackend.delete() 无锁保护 | **P1** | B-006 |
| D-03 | `engine.py:305` | `required_cols` 缺 `"volume"` | **P1** | B-012 |
| D-04 | `error_handling.py:51-60` | `_resolve_log_level` 死代码 | P3 | — |
| D-05 | `error_handling.py:362` | 装饰器顺序错误 → 重试永不触发 | **P2** | B-013 |
| D-07 | `fsm.py:342` | `_check_buy_blockers` 中 `-0.3` 硬编码 | **P2** | B-031 |
| D-08 | `fsm.py:95` | `infer_state()` 无 `@handle_errors` 保护 | P2 | — |
| D-09 | `di_container.py` | DIContainer 80 行死代码 | P3 | B-018 |
| D-11 | `engine.py:278` | `@handle_errors` 返回空 `BacktestResult` 屏蔽故障 | **P2** | — |
| D-12 | `fsm.py` | `infer_state()` 全程无异常处理 | P2 | — |
| D-13 | `calculator.py:215` | `cost_function` 不检查 NaN → 传播到 DE | **P1** | B-012t |
| D-15 | `interfaces.py:130` | `calculate_metrics` 声明 DataFrame 接受 Series | P2 | G2 |

---

## 汇总统计

| Sprint | Bug数 | 子代理 | 并行度 | 工时 | 门禁 |
|--------|-------|--------|--------|------|------|
| 1 | 18 | 4 (A/B/C/D) | 4路 | 4-5h | 6 |
| 2 | 16 | 3 (E/F/G) | 3路 | 5-6h | 6 |
| 3 | 9 | 3 (H/I/J) | 3路 | 3-4h | 6 |
| 4 | 6 | 2 (K/L) | 2路 | 4-5h | 5 |
| **总计** | **45** | **12** | **2-4路** | **17-20h** | **23** |

> *路线图版本: v3.0 | 制定: 2026-05-31 | 核验: 4路并行Agent深度源码逐行核实 | 基于代码事实*
