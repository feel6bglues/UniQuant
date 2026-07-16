# Phase D — 引擎运行时行为审计报告

> 日期: 2026-07-06
> 方法: 侵入式插桩 + 故障注入 + 全量采样 + 代码静态分析
> 源文件均未修改

---

## 总结

| 指标 | 值 |
|---|---|
| 引擎总数 | 7 (LPPL, CZSC, Wyckoff, FSM, Regime, NTF, Macro) |
| 全量采样 | 100 文件, 0 错误, 0% null, 74-7879 行/股 |
| 致命 BUG | **2** (FSM 空 DataFrame 崩溃, Wyckoff Inf 溢出崩溃) |
| 次要问题 | **3** (LPPL Inf 假阳性, Regime 接口不匹配, CZSC fallback 未消费的 TODO) |
| 信号仲裁 | SELL 优先, 8 适配器, 质量门禁 OOS R² 过滤 |
| 时间序列一致性 | A- (TradingSignal 含 timestamp, bar_date 优先) |
| 内存/CPU | 50 文件 0.25s, 峰值 2.3MB (低风险) |
| 可重复性 | 83 个 seed 引用, conftest 全局 seed=42, 有显式确定性测试 |
| Wyckoff 漏洞 | 2 个新发现 (Inf 溢出, NaN fallback 误判) |

### 主要风险 (按优先级)

1. **CRITICAL**: FSM 引擎空 DataFrame 时 `df.iloc[-1]` 未保护 → IndexError 未被捕获
2. **CRITICAL**: Wyckoff 引擎 Inf 数据时 `pre_close * up_limit_ratio` 溢出 → OverflowError 未被捕获 (WYCKOFF_RECOVERABLE_ERRORS 不含 OverflowError)
3. **HIGH**: LPPL 引擎 Inf 数据产生 "Danger" 假阳性 (confidence=0.6)
4. **MEDIUM**: Regime 引擎 `run_regime_detection` 传递字符串符号而非 DataFrame → 始终失败
5. **LOW**: CZSC fallback 有 4 处 TODO 未接线 (trend, current_state 已计算但未消费)

---

## D1 引擎失败模式谱系

### 测试方法

对每个引擎注入 7 种故障数据: `None`, `空 DataFrame`, `缺失 close 列`, `全 NaN`, `close=0`, `close=Inf`, `单行数据`. 使用 mock orchestrator 隔离引擎层.

### 结果矩阵

| 引擎 | None | 空 DF | 无 close | 全 NaN | close=0 | close=Inf | 单行 |
|---|---|---|---|---|---|---|---|
| **LPPL** | ENGINE_FAILED | ENGINE_FAILED | Safe | Safe | Safe | Danger ⚠️ | Safe |
| **NTF** | NONE | NONE | NONE | NONE | NONE | NONE | NONE |
| **Regime** | failed | failed | failed | failed | failed | failed | failed |
| **FSM** | failed | **CRASH** 🔴 | success | success | success | success | success |
| **CZSC** | CZSCOutput() | CZSCOutput() | CZSCOutput() | CZSCOutput() | CZSCOutput() | CZSCOutput() | CZSCOutput() |
| **Wyckoff** | unknown | unknown | unknown | markdown ⚠️ | unknown | **CRASH** 🔴 | unknown |

### 关键发现

#### 🔴 FSM 空 DataFrame 崩溃 (FSM_AnalysisEngine:96)

```
IndexError: single positional indexer is out-of-bounds
```

原因: `run_fsm_analysis` 在 `df = self.orchestrator._optimize_dataframe(df)` 之后直接调用 `df.iloc[-1]["close"]`，未检查 DataFrame 是否为空。空 DataFrame 走过了 `_optimize_dataframe` 和 `_sample_data` 但未触发 import 失败路径，因此直接进入 `df.iloc[-1]` 导致崩溃。`try/except FSM_RECOVERABLE_ERRORS` 不捕获 `IndexError`。

#### 🔴 Wyckoff Inf 溢出崩溃 (Wyckoff engine -> limit_checker.py:73)

```
OverflowError: cannot convert float infinity to integer
```

原因: `close=np.inf` 的数据通过 `WyckoffEngine.analyze()` → `_detect_limit_moves()` → `is_limit_up()` → `check_limit_status()` → `_round_limit_price()`。`pre_close * up_limit_ratio` 产生 `inf`，然后 `round(inf / tick_size)` 抛出 `OverflowError`。`WYCKOFF_RECOVERABLE_ERRORS` 元组不包含 `OverflowError`，因此异常穿透到外层。

#### ⚠️ LPPL Inf 假阳性 (LPPL engine)

`close=np.inf` 的数据导致 `risk_level="Danger"`, `confidence=0.6`。原因是 LPPL 引擎对 `np.inf` 进行对数运算后产生 NaN/Inf 统计量，`r_squared=0.0` 但 `bubble_detected=True`（`max_pct_change` 为 Inf 超过 0.20 阈值），进入 Danger 分支。

#### ⚠️ Regime 引擎接口不匹配

`regime_analysis_engine.py:42` 调用 `regime_detector.detect(symbol)` 传递字符串符号，但 `regime_detector.py:131` 的 `detect(df: pd.DataFrame)` 参数类型为 DataFrame。导致 `Regime` 枚举对象返回后被 `.get()` 调用，异常被 `REGIME_RECOVERABLE_ERRORS` 捕获 → 始终返回 `failed`。

#### ⚠️ Wyckoff NaN fallback 误判

全 NaN 数据（无 date 列）时 fallback 进入 `recent_price_pos = NaN`，`NaN > 0.05` 为 False，误判为 "markdown" 阶段。

---

## D2 全量输出分布 (轻量版 — 100 只采样)

### 采样配置

- 随机种子: 42
- 数据湖: `data/lake/quotes/daily/` (11476 个文件)
- 采样数: 100

### 统计结果

| 指标 | 值 |
|---|---|
| 扫描耗时 | 0.3s |
| 文件错误 | 0/100 |
| 行数 (均值±std) | 3283 ± 2119 |
| 行数 (范围) | 74 ~ 7879 |
| null 百分比 | **0.0%** (所有文件) |
| close 最低 (全样本) | 0.86 |
| close 最高 (全样本) | 9382.60 |
| 最早日期 | 1993-06-14 |
| 最晚日期 | 2026-06-08 |

### 数据质量结论

- 数据湖文件无 null 值，质量高
- 数据覆盖 1993-2026 年，时间跨度 >30 年
- 行数分布右偏（部分新股仅 74 行），小样本引擎需处理

---

## D3 信号冲突全景

### 适配器注册表

8 个适配器通过 `AdapterRegistry` 注册:

| 优先级 | 引擎 | 适配器 | 输出方向 |
|---|---|---|---|
| 0 | LPPL | LPPLAdapter | BUY/SELL/HOLD |
| 1 | FSM | FSMAdapter | BUY/SELL/HOLD (8 种决策映射) |
| 2 | CZSC | CZSCAdapter | BUY (三买) / HOLD |
| 3 | Wyckoff | WyckoffAdapter | BUY/SELL/HOLD |
| 4 | Regime | RegimeAdapter | SELL (FROZEN/STRESSED) / HOLD |
| 5 | NTF | NTFAdapter | SELL (RESISTANCE+高强度) / HOLD/None |
| 6 | AlphaScore | AlphaScoreAdapter | BUY (>0.6) / SELL (<0.3) / None |
| 7 | MAStatus | MAStatusAdapter | BUY/SELL |

### 仲裁规则 (`SignalArbitrator`)

1. **SELL 优先**: 所有 SELL 信号优先于 BUY
2. **质量门禁**: LPPL SELL 信号需 OOS R² ≥ 0.3 阈值
3. **引擎优先级**: LPPL > FSM > CZSC > Wyckoff > Regime > NTF > Alpha
4. **同方向**: 同方向取最高 confidence
5. **仓位计算**: 非 FSM 的 BUY 信号需要 `PositionSizer`

### 冲突频率评估

理论上 8 个引擎同时运行时最多产生 8 个候选信号。仲裁器将过滤 HOLD 后取 actionable 信号。典型冲突场景: LPPL SELL vs Wyckoff BUY → LPPL 胜出 (SELL 优先且优先级更高)。

### 风险

- 仲裁器依赖 `confidence` 字段，但各引擎的 confidence 校准不一致（LPPL 0.0-1.0, FSM 0-1 scale, Wyckoff 字母等级映射）
- 无跨引擎 confidence 归一化

---

## D4 时间序列一致性

### TradingSignal 时间戳模型

```python
@dataclass
class TradingSignal:
    timestamp: Optional[datetime] = None
```

- `TradingSignalCollector.collect()` 支持 `bar_date` 和 `timestamp` 双参数
- `bar_date` (K-line bar 日期) 优先于 `timestamp` (wall clock)
- 信号 normalizer 使用 `get_time_provider().now()` 作为默认时间戳

### 时间戳传播路径

```
Engine → AnalysisService → data_pack → TradingSignalCollector
  → Adapter.adapt(raw_output, symbol, timestamp) → TradingSignal
  → SignalArbitrator.arbitrate_candidates() → 使用 sig.timestamp.date()
```

### 时间提供者

- `RealTimeProvider.now()`: 系统时钟
- `FrozenTimeProvider`: 固定时间，用于回测
- 2 个 `datetime.now()` 调用在 `time_provider.py` 中 (FrozenTimeProvider fallback, 已标记)

### 风险

- 信号 DB 使用 `DateTime` 列但无时区信息
- 时间戳沿 adapter 链逐层传递，无统一的时间戳注入点

---

## D5 内存/CPU Profile (轻量)

### 测试条件

- 读取 50 个 parquet 文件 (随机采样)
- 工具: `tracemalloc`

### 结果

| 指标 | 值 |
|---|---|
| 读取耗时 | 0.25s |
| 峰值内存 | 2.3 MB |
| 当前内存 | 2.1 MB |
| 吞吐量 | ~200 文件/s |

### 结论

- 单文件 parquet 读取内存开销极低，适合批量处理
- 50 文件并行处理峰值 < 5MB，无须担心内存
- 当前架构下磁盘 I/O 是瓶颈，非 CPU/内存

---

## D6 引擎结果可重复性

### 种子使用统计

- 83 处 `seed`/`random_state`/`deterministic`/`repeatable` 引用
- `conftest.py:5` 全局 `np.random.seed(42)`
- `test_p1_reproducibility.py` 显式验证 Monte Carlo seed 传递
- `test_p2_randomness_annotations.py` 验证 `macro_engine` 的 `seed=42` 参数

### 关键引擎确定性

| 引擎 | 确定性 | 证据 |
|---|---|---|
| LPPL | 无随机性 | 纯数学计算，输入确定则输出确定 |
| CZSC | 无随机性 | 纯技术指标计算 |
| Wyckoff | 无随机性 | 规则驱动分析 |
| FSM | 无随机性 | 状态机逻辑 |
| Regime | 无随机性 | 熵 + Z-Score 计算 |
| Macro | 确定性 (mock 模式) | `seed=42`, `np.random.default_rng(seed)` |

### 结论

- 所有引擎输入确定则输出确定，无随机成分
- Macro 的 mock 模式使用显式种子，可重复
- 有 2 个测试文件专门验证可重复性

---

## D7 Wyckoff 深度分析

### 当前状态

- `reanalysis/02_engine_correctness_audit.md` 给出 Wyckoff 整体评级 A-
- 未找到关于 B 级/B-grade 缺口的明确记录
- 代码 `wyckoff_analysis_engine.py` 243 行, `brain/wyckoff/` 下 16 个文件

### 新发现的漏洞 (B 级)

#### B1: Inf 输入溢出崩溃

**严重性**: HIGH
**路径**: `WyckoffAnalysisEngine.run_wyckoff_analysis()` → `WyckoffEngine.analyze()` → `_analyze_single()` → `_step3_phase_c_t1()` → `_detect_limit_moves()` → `detect_limit_moves()` → `is_limit_up()` → `check_limit_status()` → `_round_limit_price()`
**原因**: `WYCKOFF_RECOVERABLE_ERRORS` 不包含 `OverflowError`，`Inf` 价格数据穿透到 `round(inf / tick_size)` 崩溃
**修复**: 将 `OverflowError` 加入 `WYCKOFF_RECOVERABLE_ERRORS` 元组，或在 `run_wyckoff_analysis` 入口处增加 `np.isfinite()` 检查

#### B2: NaN 数据 fallback 误判

**严重性**: MEDIUM
**路径**: NaN close/volume 数据 → fallback 分支 → `recent_price_pos = NaN` → `NaN > 0.05` 为 False → 误判为 "markdown"
**修复**: fallback 中增加 `pd.isna()` 检查，NaN 时返回 `WyckoffOutput(phase="unknown")`

#### B3: 价格序列恒定检测

**严重性**: LOW
**路径**: `close=0` 数据触发 "价格序列恒定: UNKNOWN" 日志，但实际返回 `WyckoffOutput(phase="unknown")`，降级正确
**状态**: 已存在保护逻辑

### 与 reanalysis 报告对比

| 项目 | 原报告 | 本次发现 |
|---|---|---|
| 整体评级 | A- | 确认 A- |
| 已知缺口 | 无 | 2 个新 B 级漏洞 |
| 测试覆盖 | 未特别评估 | 覆盖基本路径，但缺失 Inf/NaN 边界测试 |

---

## 附录: 修复建议

### 立即修复 (P0)

1. **FSM 空 DataFrame 保护**: 在 `run_fsm_analysis()` 的 `df.iloc[-1]` 前增加 `if df.empty: return {"status": "failed", ...}`
2. **Wyckoff Inf 保护**: 将 `OverflowError` 加入 `WYCKOFF_RECOVERABLE_ERRORS`，或在入口处验证 `np.isfinite()`

### 短期修复 (P1)

3. **LPPL Inf 假阳性**: 在 `_fallback_lppl_analysis` 中增加 `np.isfinite()` 检查，Inf 数据返回 `risk_level="ENGINE_FAILED"`
4. **Wyckoff NaN fallback**: 在 fallback 的 `recent_price_pos` 使用后增加 `if pd.isna(recent_price_pos): return WyckoffOutput(phase="unknown")`

### 中期修复 (P2)

5. **Regime 接口不匹配**: `run_regime_detection` 应传递 DataFrame 而非字符串符号
6. **CZSC fallback TODO**: 将 trend/current_state 计算结果写入 CZSCOutput
7. **跨引擎 confidence 归一化**: 在仲裁器前增加 confidence 归一化层

---

## ANALYSIS COMPLETE