# UniQuant v2.0 — 修复任务工作单

> 日期: 2026-07-06 | 基于 Phase A-K 审计结论
> 总任务数: 31 | 预估总工时: 47h

---

## 使用说明

每个任务包含:

| 字段 | 说明 |
|---|---|
| ID | P0-01 ~ P3-08, 按优先级编号 |
| 来源 | 发现该问题的 Phase 报告 |
| 文件 | 需要修改的具体文件 |
| 问题描述 | 问题定位 |
| 修复方案 | 具体改法（代码级） |
| 验收标准 | 如何验证修复完成 |
| 预估工时 | 包含测试时间 |
| 前置依赖 | 必须先完成的 Task ID |

---

## P0 — 立即修复（5 项, 14.5h）

### P0-01: 修复 FSM 空 DataFrame IndexError 崩溃

| 字段 | 值 |
|---|---|
| **来源** | Phase D |
| **严重级别** | 🔴 CRITICAL — 实盘遇到无数据股票立即崩溃 |
| **文件** | `src/uniquant/brain/fsm/fsm.py` |
| **行号** | 搜索 `df.iloc[-1]` 或 `df.iloc[` 出现处 |
| **问题** | 当输入 DataFrame 为空时（0 行），`df.iloc[-1]` 触发 `IndexError: single positional indexer is out-of-bounds`，且未被 `try/except` 捕获 |
| **修复方案** | 在所有 `df.iloc[-1]` / `df.iloc[0]` / `df.iloc[i]` 前加空 DataFrame 守卫: `if df.empty: return <默认值>` |
| **测试** | 1. 构造空 DataFrame 调用 FSM → 应返回默认值而非崩溃 |
| **验收标准** | 空 DataFrame 输入时 FSM 稳定返回 `ENGINE_FAILED` 状态 |
| **预估工时** | 1h |

---

### P0-02: 修复 Wyckoff Inf 数据 OverflowError 崩溃

| 字段 | 值 |
|---|---|
| **来源** | Phase D |
| **严重级别** | 🔴 CRITICAL — 数据异常时不再 recoverable |
| **文件** | `src/uniquant/brain/wyckoff/engine.py` |
| **问题** | `WYCKOFF_RECOVERABLE_ERRORS` 中不包含 `OverflowError`。当 `pre_close * up_limit_ratio` 乘积溢出（如 Inf × 1.1）时，OverflowError 未被捕获，引擎崩溃 |
| **修复方案** | 在 `WYCKOFF_RECOVERABLE_ERRORS` 中添加 `OverflowError`。同时在相关计算之前加数据守卫: `if np.isinf(pre_close): return <safe_default>` |
| **测试** | 1. 构造 `close=Inf` 的 DataFrame 调用 Wyckoff → 应返回 unknown 而非崩溃 |
| **验收标准** | Inf/NaN 数据输入时 Wyckoff 稳定返回 unknown/NA 状态 |
| **预估工时** | 1h |

---

### P0-03: 修复 eastmoney.py SSL verify=False

| 字段 | 值 |
|---|---|
| **来源** | Phase H |
| **严重级别** | 🟠 HIGH — MITM 攻击风险 |
| **文件** | `src/uniquant/data/sources/eastmoney.py` |
| **行号** | :76 附近 |
| **问题** | `requests.get(url, verify=False)` 关闭 SSL 证书验证，使 HTTPS 连接易受中间人攻击 |
| **修复方案** | 移除 `verify=False` 参数。如果需要使用自定义 CA: `verify='/path/to/ca-bundle.crt'` |
| **测试** | 1. 运行 EastMoney 数据获取 → 应正常返回数据 (SSL 握手成功) 2. 如果远程服务器证书问题导致失败，添加 `REQUESTS_CA_BUNDLE` 环境变量方案 |
| **验收标准** | EastMoney 请求使用默认 SSL 验证 |
| **预估工时** | 0.5h |

---

### P0-04: 添加 signal/db.py 测试覆盖

| 字段 | 值 |
|---|---|
| **来源** | Phase F |
| **严重级别** | 🔴 CRITICAL — 315 行持久化层零覆盖 |
| **文件** | `tests/test_signal_db.py`（新建）+ `src/uniquant/signal/db.py` |
| **问题** | signal/db.py 包含 SQL 数据库操作的信号持久化层完全没有测试覆盖。任何 SQL 语法错误、连接泄漏、序列化问题都无法被检测 |
| **修复方案** | 1. 分析 signal/db.py 的所有公开函数 2. 使用 SQLite in-memory 数据库创建测试 fixture 3. 为每个 CRUD 操作编写单元测试 4. 测试边界条件（空数据库、重复写入、连接超时） |
| **接口分析** | 先执行: `rg "def " src/uniquant/signal/db.py` 列出所有函数 |
| **测试模板** | ```python
import pytest
from unittest.mock import patch
from your_signal_db_module import save_signal, load_signal, delete_signal

class TestSignalDB:
    def test_save_and_load(self):
        signal = TradingSignal(action='BUY', ...)
        save_signal(signal)
        loaded = load_signal(signal.id)
        assert loaded.action == 'BUY'

    def test_load_nonexistent(self):
        assert load_signal('nonexistent_id') is None

    def test_delete(self):
        signal = TradingSignal(...)
        save_signal(signal)
        delete_signal(signal.id)
        assert load_signal(signal.id) is None
``` |
| **验收标准** | `pytest tests/test_signal_db.py -v --cov=src/uniquant/signal/db.py` 覆盖 ≥80% |
| **前置依赖** | 分析 signal/db.py 接口列表 |
| **预估工时** | 4h |

---

### P0-05: 添加 Prometheus/OpenTelemetry 指标暴露

| 字段 | 值 |
|---|---|
| **来源** | Phase I |
| **严重级别** | 🟠 HIGH — 生产无法监控 |
| **文件** | `src/uniquant/services/` + `config/config.yaml` |
| **问题** | 完全无指标系统。无法监控引擎耗时、错误率、吞吐量、数据延迟 |
| **修复方案** | 1. 在 `pyproject.toml` 添加 `prometheus-client` 依赖 2. 在 `ServiceContainer` 创建 `MetricsCollector` 服务 3. 注册关键 Histogram/Counter: `engine_run_seconds` (引擎耗时)、`signal_collect_total` (信号量)、`backtest_run_seconds` (回测耗时)、`data_fetch_errors_total` (数据错误) 4. 在 HTTP 端口暴露 `/metrics` 端点 |
| **验收标准** | `curl http://localhost:xxxx/metrics` 返回 Prometheus 格式指标 |
| **预估工时** | 8h |

---

## P1 — 本周修复（8 项, 22h）

### P1-01: 清理 .tmp.lock 文件残留

| 字段 | 值 |
|---|---|
| **来源** | Phase C |
| **严重级别** | 🟡 MEDIUM — 数据湖膨胀 |
| **文件** | `data/lake/quotes/daily/` |
| **问题** | 5542 个 `.tmp.lock` 残留文件，数量接近有效 parquet 文件数。可能来自之前未清理的写入进程 |
| **修复方案** | `find data/lake/quotes/daily/ -name "*.tmp.lock" -delete` |
| **验收标准** | `ls data/lake/quotes/daily/*.tmp.lock | wc -l` = 0 |
| **预估工时** | 0.5h |

---

### P1-02: 修复 mutmut 路径错位

| 字段 | 值 |
|---|---|
| **来源** | Phase B |
| **严重级别** | 🟡 MEDIUM — 变异测试无法运行 |
| **文件** | `src/uniquant/shared/config_loader.py` |
| **问题** | `_root_dir = Path(__file__).parent.parent.parent.resolve()` 在 mutmut 复制到 `mutants/src/` 后，路径解析到 `mutants/` 而非项目根，找不到 `config/config.yaml` |
| **修复方案** | 方案 A（推荐）: 添加环境变量覆盖: `root_dir = Path(os.environ.get('UNIQUANT_ROOT', Path(__file__).parent.parent.parent))`。方案 B: mutmut 运行前设置 `UNIQUANT_ROOT` 环境变量 |
| **测试** | `UNIQUANT_ROOT=/path/to/project mutmut run --no-coverage --paths-to-mutate src/uniquant/shared/cost_model.py` |
| **验收标准** | mutmut 成功在 `cost_model.py` 上运行并输出击杀率 |
| **前置依赖** | — |
| **预估工时** | 2h |

---

### P1-03: ProcessPoolExecutor 替换 ThreadPoolExecutor

| 字段 | 值 |
|---|---|
| **来源** | Phase G |
| **严重级别** | 🟡 MEDIUM — 性能瓶颈 |
| **文件** | `src/uniquant/services/research_pipeline.py` |
| **行号** | 搜索 `ThreadPoolExecutor` |
| **问题** | `run_batch()` 使用 `ThreadPoolExecutor`，引擎计算为纯 CPU 密集型，受 GIL 限制 |
| **修复方案** | 替换 `from concurrent.futures import ThreadPoolExecutor` 为 `ProcessPoolExecutor`。需注意: (1) 引擎模块需支持 `pickle` 序列化 (2) 每个进程需独立初始化 `ServiceContainer` (3) `max_workers` 默认值建议 `os.cpu_count()` |
| **测试** | `pytest tests/test_research_pipeline.py -v` 确认并行化功能正常 |
| **验收标准** | 4 线程运行时 CPU 利用率从 ~25% 提升至 ~80%+ |
| **预估工时** | 4h |

---

### P1-04: 添加 Adapter 层单元测试

| 字段 | 值 |
|---|---|
| **来源** | Phase F |
| **严重级别** | 🟡 MEDIUM — 适配器覆盖率仅 29% |
| **文件** | `tests/test_signal_adapters.py` |
| **问题** | 8 个 Adapter 中仅 NTFAdapter 有单元测试。LPPL/CZSC/Wyckoff/FSM/Regime/Alpha/MA 均无 |
| **修复方案** | 为每个 Adapter 添加测试: (1) 正常输入 → 正确 TradingSignal (2) 空输入 → 默认 HOLD (3) 异常输入 → 不崩溃 |
| **测试模板** | ```python
@pytest.mark.parametrize("adapter_cls,input_key,expected_action", [
    (LPPLAdapter, {'risk_level': 'high', 'confidence': 0.8, 'bubble_confidence': 0.9}, Action.SELL),
    (CZSCAdapter, {'is_3rd_buy': True, 'bi_count': 5}, Action.BUY),
    (WyckoffAdapter, {'wyckoff_phase': 'spring', 'confidence': 0.7, 'spring': True, 'utad': False}, Action.BUY),
])
def test_adapter_signal(adapter_cls, input_key, expected_action):
    adapter = adapter_cls()
    signal = adapter.adapt(input_key, '000001.SZ', '2026-01-01', 100)
    assert signal.action == expected_action
``` |
| **验收标准** | `pytest tests/test_signal_adapters.py --cov=src/uniquant/signal/adapters.py` 覆盖 ≥80% |
| **前置依赖** | — |
| **预估工时** | 4h |

---

### P1-05: 清理 116 处重复代码（data/sources 优先）

| 字段 | 值 |
|---|---|
| **来源** | Phase A |
| **严重级别** | 🟡 MEDIUM — 维护成本 |
| **文件** | `src/uniquant/data/sources/*.py`（优先 78 行高密度重复）|
| **问题** | data/sources 下 3 个数据源文件间 78 行重复（日期解析、列映射逻辑重复） |
| **修复方案** | 1. 在 `src/uniquant/data/sources/` 下创建 `base_source.py` 2. 提取共享逻辑: 日期格式解析、列名映射字典、错误处理 3. 各数据源继承基类 |
| **验收标准** | `pylint --disable=all --enable=duplicate-code src/uniquant/data/sources/` 重复块数减少 ≥50% |
| **预估工时** | 4h |

---

### P1-06: 添加滑点/费用敏感性扫描

| 字段 | 值 |
|---|---|
| **来源** | Phase E |
| **严重级别** | 🟢 LOW — 回测健壮性增强 |
| **文件** | `src/uniquant/hands/backtest/unified_engine.py`（新增方法）+ `tests/test_backtest_sensitivity.py` |
| **问题** | 回测结果对滑点和费用参数高度敏感，但当前使用固定默认值，无敏感性分析 |
| **修复方案** | 在 `BacktestResult` 上添加 `sensitivity_scan()` 方法: 输入滑点范围 [0%, 0.1%, 0.3%, 0.5%] 和佣金率范围 [0.01%, 0.025%, 0.05%]，输出收益差异 |
| **验收标准** | `sensitivity_scan()` 返回 DataFrame，列为滑点/佣金，行为收益率 |
| **预估工时** | 4h |

---

### P1-07: TradingSignal 添加 to_dict() 序列化方法

| 字段 | 值 |
|---|---|
| **来源** | Phase F |
| **严重级别** | 🟡 MEDIUM — signal/db.py 前置依赖 |
| **文件** | `src/uniquant/shared/interfaces.py`（TradingSignal 类）|
| **问题** | `TradingSignal` 缺少 `to_dict()` 方法，无法直接序列化到 JSON 用于持久化或网络传输 |
| **修复方案** | 在 TradingSignal class 中添加:
```python
def to_dict(self) -> dict:
    return {
        'action': self.action.value,
        'reason': self.reason,
        'confidence': self.confidence,
        'shares': self.shares,
        'symbol': self.symbol,
        'price': self.price,
        'timestamp': self.timestamp.isoformat() if self.timestamp else None,
        'metadata': self.metadata,
    }

@classmethod
def from_dict(cls, data: dict) -> 'TradingSignal':
    from ... import Action
    return cls(
        action=Action(data['action']),
        reason=data['reason'],
        confidence=data['confidence'],
        shares=data['shares'],
        symbol=data['symbol'],
        price=data['price'],
        timestamp=datetime.fromisoformat(data['timestamp']) if data.get('timestamp') else None,
        metadata=data.get('metadata'),
    )
``` |
| **验收标准** | `TradingSignal(...).to_dict()` → JSON 序列化 → `TradingSignal.from_dict()` → 原始对象，往返一致 |
| **前置依赖** | P0-04 需要这个功能 |
| **预估工时** | 1h |

---

### P1-08: 集成 A 股基准指数到回测结果

| 字段 | 值 |
|---|---|
| **来源** | Phase E |
| **严重级别** | 🟢 LOW — 回测评价完整性 |
| **文件** | `src/uniquant/hands/backtest/unified_engine.py` |
| **问题** | `BacktestResult` 的基准收益率为 0，无法对比 Alpha。无风险利率已改为 3%（bc6337bc），但无基准指数 |
| **修复方案** | 在 `run()` 方法中可选接受 `benchmark_returns: Optional[pd.Series]` 参数。如果提供，计算 `alpha = portfolio_return - benchmark_return` 和 `information_ratio` |
| **验收标准** | 传入沪深300收益序列时，`BacktestResult` 正确计算 alpha 和 IR |
| **预估工时** | 3h |

---

## P2 — 本月修复（10 项, 42h）

### P2-01: Wyckoff 76 复杂度函数拆分

| 字段 | 值 |
|---|---|
| **来源** | Phase A |
| **文件** | `src/uniquant/brain/wyckoff/engine.py` → `_step1_phase_determine` |
| **当前复杂度** | 76 (F级) |
| **修复方案** | 按 7 个 Wyckoff phase 拆分为独立方法: `_detect_accumulation()` / `_detect_markup()` / `_detect_distribution()` / `_detect_markdown()` / `_detect_spring()` / `_detect_utad()` / `_detect_sos()`. 每个方法 ≤20 复杂度 |
| **验收标准** | `radon cc src/uniquant/brain/wyckoff/engine.py -s -n C` 无 C 级以上函数 |
| **预估工时** | 8h |

---

### P2-02: hands 层非法依赖清理

| 字段 | 值 |
|---|---|
| **来源** | Phase A |
| **文件** | `src/uniquant/hands/strategies/backtest.py` 等 |
| **问题** | 5 处 hands→data/brain 非法反向依赖 |
| **修复方案** | 替换 `from uniquant.data.manager import ...` 为通过 services 层访问: `from uniquant.services import ServiceContainer; svc = ServiceContainer(); svc.data_service.get_xxx()` |
| **验收标准** | `rg "^from uniquant\.(data|brain)" src/uniquant/hands/` 返回 0 行 |
| **预估工时** | 4h |

---

### P2-03: LPPL Inf 假阳性修复

| 字段 | 值 |
|---|---|
| **来源** | Phase D |
| **文件** | `src/uniquant/brain/lppl/lppl_model.py` 或相关文件 |
| **问题** | Inf 数据输入时 LPPL 输出 "Danger" 预测 (confidence=0.6)，产生假阳性卖出信号 |
| **修复方案** | 在 LPPL 引擎入口添加 Inf/NaN 数据守卫: `if df['close'].isnull().any() or np.isinf(df['close']).any(): return LPPLOutput(risk_level='unknown', ...)` |
| **验收标准** | Inf 数据输入时 LPPL 返回 `unknown` / NA 而非 `Danger` |
| **预估工时** | 2h |

---

### P2-04: Regime 引擎接口修复

| 字段 | 值 |
|---|---|
| **来源** | Phase D |
| **文件** | `src/uniquant/services/analysis/regime_analysis_engine.py` + `src/uniquant/brain/regime/regime_detector.py` |
| **问题** | `run_regime_detection` 接口不匹配 — 传入 string 符号而非 DataFrame |
| **修复方案** | 在 `regime_analysis_engine.py` 中修复调用: 传递 `data_pack['df']`（DataFrame）而非 `symbol`（string） |
| **验收标准** | `pytest tests/test_regime_detector.py -v` 全部通过，regime 分析正确输出 |
| **前置依赖** | — |
| **预估工时** | 2h |

---

### P2-05: CZSC fallback TODO 接线

| 字段 | 值 |
|---|---|
| **来源** | Phase D |
| **文件** | `src/uniquant/brain/czsc/czsc_engine.py` 或相关文件 |
| **问题** | 4 处 TODO 标记: `trend` 和 `current_state` 已经被计算但未被消费（fallback 未使用计算结果）|
| **修复方案** | 分析 4 处 TODO 的上下文，将已计算的 trend/current_state 值传递给 fallback 路径的输出 |
| **验收标准** | CZSC 输出包含 `trend` 和 `current_state` 字段的合理值 |
| **预估工时** | 4h |

---

### P2-06: 配置 Schema 验证

| 字段 | 值 |
|---|---|
| **来源** | Phase A |
| **文件** | `src/uniquant/shared/config_models.py` + `config/config.yaml` |
| **问题** | 配置文件无 schema 验证，缺失/类型错误的配置项只能在运行时被发现 |
| **修复方案** | 使用 Pydantic 定义 ConfigModel: `class UniQuantConfig(BaseModel): data_lake: DataLakeConfig; refactoring: RefactoringConfig; factor_gate: FactorGateConfig`。在 ServiceContainer.initialize() 中验证 |
| **验收标准** | 配置缺失/类型错误时，ServiceContainer 初始化立即失败并给出明确错误信息 |
| **预估工时** | 6h |

---

### P2-07: 统一 board_type 注册表

| 字段 | 值 |
|---|---|
| **来源** | Phase C_consolidated_issues.md |
| **文件** | 新建 `src/uniquant/shared/board_registry.py` + 修改 `limit_checker.py` / `market_rules.py` |
| **问题** | 两套板类型识别系统并行: `limit_checker.get_board_type()` (string) 和 `market_rules.detect_board()` (BoardType enum) |
| **修复方案** | 1. 新建 `BoardTypeRegistry` 作为唯一真相源 2. `get_board_type()` 和 `detect_board()` 都委托给 Registry 3. 注册表基于股票代码前缀分类 |
| **验收标准** | 6 个测试代码在两个系统中返回语义一致的结果 |
| **预估工时** | 6h |

---

### P2-08: 数据延迟从 28 天降至 <1 天

| 字段 | 值 |
|---|---|
| **来源** | Phase C |
| **文件** | `src/uniquant/data/sources/` + `config/config.yaml` |
| **问题** | 数据湖最新数据日期 2026-06-08，距审计日 28 天 |
| **修复方案** | 1. 检查 TDX/EastMoney 数据源的更新频率 2. 配置定时更新任务（cron/Airflow） 3. 或配置数据源自动 fallback: 优先数据湖 → 缺失时实时拉取 |
| **验收标准** | `df['date'].max()` 距当天 ≤1 天 |
| **预估工时** | 4h |

---

### P2-09: 添加 E2E 测试

| 字段 | 值 |
|---|---|
| **来源** | Phase B/E |
| **文件** | `tests/test_e2e_pipeline.py`（新建）|
| **问题** | 无 E2E 测试覆盖完整链路: Pipeline → Brain(7引擎) → Signal(8适配器) → Arbitrator → Backtest(回测) |
| **修复方案** | 使用 1-2 只股票数据，运行完整 pipeline，验证: (1) 无异常 (2) signal 列表非空 (3) BacktestResult 有合理值 |
| **验收标准** | `pytest tests/test_e2e_pipeline.py -v` 通过 |
| **前置依赖** | P0-01, P0-02 (否则 E2E 会触发崩溃) |
| **预估工时** | 4h |

---

### P2-10: 高频数据接入（分钟/周/月线）

| 字段 | 值 |
|---|---|
| **来源** | Phase C |
| **文件** | `data/lake/quotes/1mins/` 等 + 数据源配置 |
| **问题** | 分钟/周/月线目录完全为空，仅有日线可用 |
| **修复方案** | 在数据源（TDX/AkShare）中配置多周期数据获取: 1mins/5mins 用于日内分析, weekly/monthly 用于长周期技术指标 |
| **验收标准** | `ls data/lake/quotes/1mins/*.parquet | wc -l` > 0 |
| **预估工时** | 4h |

---

## P3 — Q3 目标（8 项, 24h+）

### P3-01: 变异测试击杀率基线 ≥80%

| **文件** | `pyproject.toml` + mutmut 配置 |
| **修复方案** | 修复 P1-02 后，制定 mutmut 击杀率基线，新代码提交必须不低于基线 |
| **预估工时** | 4h |

### P3-02: CODEOWNERS + PR 模板

| **文件** | `.github/CODEOWNERS` + `.github/PULL_REQUEST_TEMPLATE.md` |
| **修复方案** | 按模块分配 code owner, 创建 PR 模板包含检查清单 |
| **预估工时** | 1h |

### P3-03: 强制 rate limiting

| **文件** | `config/config.yaml` |
| **修复方案** | 将速率限制从"存在但未强制"改为强制配置 |
| **预估工时** | 2h |

### P3-04: 性能基准测试 CI 集成

| **文件** | `.github/workflows/benchmark.yml` |
| **修复方案** | 使用 pytest-benchmark + asv 捕获性能回归 |
| **预估工时** | 4h |

### P3-05: 清理 12 处 100% 置信度死代码

| **文件** | vulture 输出列表中的文件 |
| **修复方案** | 逐个评估后删除未使用变量/函数 |
| **预估工时** | 4h |

### P3-06: Grafana 仪表盘配置

| **文件** | `deploy/grafana/dashboard.json`（新建）|
| **修复方案** | 基于 P0-05 的 Prometheus 指标配置 Grafana 仪表盘 |
| **预估工时** | 4h |

### P3-07: 覆盖门禁 50% → 80% 阶梯提升

| **文件** | `pyproject.toml` |
| **修复方案** | 每月提升 10%: 50% → 60% → 70% → 80% |
| **预估工时** | 每次提升 1h (共 4h) |

### P3-08: 裸 except 和过度捕获清理

| **文件** | `research_pipeline.py:237` 等 Phase A 发现 |
| **修复方案** | 替换裸 except 为具体异常类型，拆分过度捕获的 except Exception |
| **预估工时** | 4h |

---

## 执行时序依赖图

```
P0-01 (1h)  ──────┐
P0-02 (1h)  ──────┤
P0-03 (0.5h) ─────┤
P0-04 (4h)  ──────┼── P1-07(1h) ──┐
P0-05 (8h)  ──────┤               │
                   │               │
P1-01 (0.5h) ─────┤               │
P1-02 (2h)  ──────┘               │
P1-03 (4h)  ──────────────────────┤
P1-04 (4h)  ──────────────────────┤
P1-05 (4h)  ──────────────────────┤
P1-06 (4h)  ──────────────────────┤
P1-08 (3h)  ──────────────────────┤
                                   │
P2-01 (8h)  ◄── P0-02 done        │
P2-02 (4h)                         │
P2-03 (2h)                         │
P2-04 (2h)                         │
P2-05 (4h)                         │
P2-06 (6h)                         │
P2-07 (6h)                         │
P2-08 (4h)                         │
P2-09 (4h)  ◄── P0-01 + P0-02 done│
P2-10 (4h)                         │
                                   ▼
                              P3-01 ~ P3-08
```

**关键路径**: P0-01/02 → P2-09 (E2E测试需要崩溃修复)

---

## 并行分组建议

| 组 | 任务 | 总工时 |
|---|---|---|
| **G1: 安全与数据** | P0-03(0.5h) + P1-01(0.5h) + P2-10(4h) | 5h |
| **G2: 引擎修复** | P0-01(1h) + P0-02(1h) + P2-01(8h) + P2-03(2h) + P2-04(2h) + P2-05(4h) | 18h |
| **G3: 信号系统** | P0-04(4h) + P1-07(1h) + P1-04(4h) | 9h |
| **G4: 可观测性** | P0-05(8h) + P3-06(4h) | 12h |
| **G5: 回测增强** | P1-06(4h) + P1-08(3h) + P2-09(4h) | 11h |
| **G6: 重构** | P1-05(4h) + P2-02(4h) + P2-06(6h) + P2-07(6h) | 20h |
| **G7: 测试基础设施** | P1-02(2h) + P1-03(4h) + P3-01(4h) + P3-07(4h) | 14h |
| **G8: 后期** | P3-02(1h) + P3-03(2h) + P3-04(4h) + P3-05(4h) + P3-08(4h) | 15h |

**并行执行策略**: G1+G2+G3+G4 可同时开始 → G5+G6+G7 → G8