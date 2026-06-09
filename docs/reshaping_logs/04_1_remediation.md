# 阶段 4.1 修复日志：数据流、异常捕获、随机种子

生成时间: 2026-06-08

输入依据:

- `MASTER_REMEDIATION_PLAN.md` 中步骤 4.1 范围。
- `docs/reshaping_logs/02_deep_inspection.md` 中 P0/P1 发现。

范围边界:

- 本阶段仅处理底层数据流前视偏差、异常捕获 Fail-Fast、随机数可复现。
- 未启动阶段 4.2 的接口契约修复。
- 未启动阶段 4.3 的被动风控防线植入。

## 修复项

### 1. DataAligner 删除首段未来价格回填

文件:

- `src/uniquant/data/pipeline/data_aligner.py`

变更:

- 删除价格列 `ffill()` 后的 `bfill()`。
- 删除其它衍生列/自定义列的反向 `bfill`，仅保留历史方向 `ffill()`。
- 停牌或缺失窗口从首日开始时，首段价格缺口保持 `NaN`，避免未来第一个真实 bar 泄漏到过去日期。
- 成交量/成交额仍按停牌语义填充为 `0`。

覆盖风险:

- 修复 P0-4：数据对齐首段 `bfill` 可能引入未来价格。

### 2. FactorRegistry 配置失败不再静默吞噬

文件:

- `src/uniquant/brain/factors/registry.py`

变更:

- 将 `except Exception: pass` 改为分类型处理。
- `ImportError` 仅告警并使用默认注册参数，保持轻量环境兼容。
- 配置结构或运行期错误，包括 `AttributeError`、`KeyError`、`TypeError`、`ValueError`、`RuntimeError`，记录错误后重新抛出。
- 防止 factors 配置损坏时静默启用默认因子权重。

覆盖风险:

- 修复 P0-6：因子配置加载失败被裸 `pass` 吞掉。

### 3. 宏观分析默认路径禁止随机 fallback

文件:

- `src/uniquant/services/analysis/macro_service.py`
- `src/uniquant/services/analysis/macro_analysis_engine.py`

变更:

- `analyze_macro_health(mock=False, seed=42)` 增加显式 mock/seed 参数。
- 真实宏观收益为空时，默认返回:
  - `status: failed`
  - `error: DATA_UNAVAILABLE`
  - `regime: UNKNOWN`
  - `ntf_signal: 未知`
- 仅 `mock=True` 时允许生成模拟收益。
- mock 模式改用 `np.random.default_rng(seed)`，相同 seed 输出可复现。
- 缓存 key 在 mock 模式纳入 seed，避免不同 mock seed 共享缓存结果。

覆盖风险:

- 修复 P0-5：宏观分析无数据时生成未注入 seed 的随机收益。

### 4. Monte Carlo 模拟改为实例级 RNG

文件:

- `src/uniquant/hands/backtest/monte_carlo.py`

变更:

- `MonteCarloSimulator.__init__()` 新增 `seed: Optional[int] = 42`。
- `run_shuffle()` 和 `run_bootstrap()` 不再调用全局 `np.random.seed()`。
- `np.random.permutation()` 和 `np.random.choice()` 改为实例 `np.random.default_rng()`。
- 默认 seed 下结果可复现；传 `seed=None` 时可显式启用非确定性模拟。

覆盖风险:

- 修复阶段 2 队列 D 中 Monte Carlo 随机抽样未统一注入种子的可复现性问题。

## 新增回归测试

文件:

- `tests/test_phase4_1_remediation.py`

覆盖用例:

- 首日停牌/缺失价格不得被第二日真实价格反向填充。
- 因子配置加载器运行期失败必须抛错，且不得完成因子注册。
- 宏观服务真实 returns 为空时不得调用随机 fallback。
- 宏观分析引擎真实 returns 为空时不得调用随机 fallback。
- Monte Carlo 默认 seed 结果不受全局 RNG 状态影响。

## 验证记录

已执行:

```bash
python3 -m pytest tests/test_phase4_1_remediation.py -q
```

结果:

- `5 passed, 2 warnings`

已执行:

```bash
python3 -m pytest tests/test_factor_registry.py tests/test_backtest_advanced.py tests/test_macro_and_scan_regressions.py tests/test_macro_and_fsm_engine_regressions.py tests/test_data_chaos_qa.py -q
```

结果:

- `71 passed, 1 skipped, 3 warnings`

已执行:

```bash
python3 -m pytest tests/test_unified_matching.py tests/test_t1_constraint_boundary.py tests/test_e2e_pipeline.py -q
```

结果:

- `39 passed, 2 warnings`

已执行:

```bash
python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"
```

结果:

- `imports OK`

## 残留风险

- 未运行全量 `pytest tests/ -q`，因为阶段 4.1 只要求针对 P0/P1 子集手术修复，且项目当前存在已知历史失败/收集错误。
- P0-1 分析引擎工厂注入类型断裂未处理，留给阶段 4.2。
- P0-2 FSM 最终决策未进入统一信号收集未处理，留给阶段 4.2。
- P0-3 风险引擎失败默认 Safe/NORMAL 未处理，留给阶段 4.2/4.3 边界决策。
- P1 缓存广播、旧新回测入口统一、数据入口多轨问题未处理，留给后续阶段。
