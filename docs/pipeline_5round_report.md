# Pipeline 5-Round Empirical Test Report

> 生成日期: 2026-06-28 | 脚本: `scripts/pipeline_5round_test.py`
> 数据源: 本地 data lake (11,476 stocks, 5,934 parquet files)

---

## 1. 测试计划

### 1.1 目标

验证端到端研究管线 (`UnifiedResearchPipeline`) 在 5 只不同 A 股上的完整执行：
数据获取 → Brain 引擎分析 (7 引擎) → 信号收集 → 信号仲裁 → 回测撮合。

### 1.2 测试对象

| # | 代码 | 名称 | 板块 | 数据量 | 数据跨度 |
|---|------|------|------|--------|---------|
| 1 | 000001.SZ | 平安银行 | 银行 | 8,184 行 | 1992-01-02 → 2026-06-08 |
| 2 | 600519.SH | 贵州茅台 | 消费/白酒 | 5,935 行 | 2001-08-27 → 2026-06-08 |
| 3 | 000858.SZ | 五粮液 | 消费/白酒 | 6,679 行 | 1998-04-27 → 2026-06-08 |
| 4 | 601318.SH | 中国平安 | 保险 | 4,617 行 | 2007-03-01 → 2026-06-08 |
| 5 | 300750.SZ | 宁德时代 | 新能源 | 1,938 行 | 2018-06-11 → 2026-06-08 |

### 1.3 管线路径

```
DataService.fetch_for_brain()
→ AnalysisService.run_ticker_analysis() [7 引擎: regime, LPPL, NTF, CZSC, Wyckoff, alpha, derived]
→ DecisionBrain.make_decision()
→ TradingSignalCollector.collect()
→ SignalArbitrator.arbitrate_candidates() [已启用]
→ UnifiedBacktestEngine.run()
→ PipelineResult
```

---

## 2. 执行结果

### 2.1 概要

| 指标 | 值 |
|------|----|
| 容器初始化 | 1.2s |
| 总耗时 (5 轮) | 2.8s |
| 平均每轮 | 0.6s |
| 通过率 | **5/5 (100%)** |
| 总信号数 | **0** |
| 总成交数 | **0** |
| 总收益率 | **0.00% (所有轮)** |

### 2.2 单轮耗时

| 股票 | 耗时 | 说明 |
|------|------|------|
| 000001.SZ | 1.4s | 首次运行含懒加载预热 |
| 600519.SH | 0.4s | 缓存命中 |
| 000858.SZ | 0.4s | 缓存命中 |
| 601318.SH | 0.4s | 缓存命中 |
| 300750.SZ | 0.2s | 缓存命中 |

### 2.3 决策输出

所有 5 轮统一输出: `FORCE_WAIT` (confidence=0)

---

## 3. 深度分析

### 3.1 CZSC 引擎故障 — `'CZSCOutput' object has no attribute 'get'`

**根因**: Phase 4 typed output migration (2026-06-17) 将 CZSC 引擎的返回从 `Dict[str, Any]` 改为 `CZSCOutput` (dataclass)。但引擎适配器桥接代码 (`analysis_service_v2.py`) 仍然使用 `.get()` 字典方法访问结果。

**具体位置**: 
```
analysis_service_v2.py: 在执行引擎后尝试 result.get("key") 
                        → CZSCOutput 是 dataclass, 无 .get() 方法
```

**影响**: CZSC 引擎返回的 typed output 无法被下游代码解析, 异常被 `_run_engine` 捕获并吞没。CZSC 的所有信号 (买卖点判定) 丢失。

### 3.2 Wyckoff 引擎故障 — `'WyckoffOutput' object has no attribute 'get'`

**根因**: 与 CZSC 完全相同。Phase 4 将 Wyckoff 输出改为 `WyckoffOutput` (dataclass), 但桥接代码未适配。

**影响**: Wyckoff 所有信号 (吸筹/派发/震荡) 丢失。

### 3.3 Alpha 引擎 — 基准数据路径不匹配

**日志**:
```
数据文件不存在: data/lake/index/000300.SH.parquet
```

**原因**: Alpha 解耦器需要沪深300基准数据, 配置路径 `data/lake/index/000300.SH.parquet`。实际文件为 `data/lake/index/sh000300.parquet`。

**影响**: Alpha 引擎无法计算超额收益/IC, 退化为无信号。

### 3.4 数据源配置验证告警

```
Config validation found 1 issue(s):
  - data_sources.sources must be a list
```

config.yaml: `data_sources.sources` 是一个字典 (keyed by source name), 但验证器期望它是列表。这是配置格式与验证器之间的不匹配——不影响运行时, 因为代码按字典方式使用。

### 3.5 数据湖路径验证偏差

```
Data lake path does not exist: /home/james/.../src/data/lake
```

config.yaml 中的 `base.data_lake.path: "data/lake"` 是相对于项目根的。但配置验证器检查的是相对于 `src/uniquant/` 的路径。这是验证器 bug, 不影响实际数据加载 (StorageManager 使用正确路径)。

### 3.6 管线行为正确性

尽管引擎大量失败, 管线行为是正确的:
1. 每个引擎异常被 `_run_engine` 捕获 → 日志记录 → 继续下一个引擎
2. `DecisionBrain` 在无信号 → 输出 `FORCE_WAIT` (正确保守行为)
3. `TradingSignalCollector` 在空输入 → 空输出 (正确)
4. `UnifiedBacktestEngine` 在空信号 → 空回测 (正确)
5. 所有 5 轮返回 `success=True` 且 error=None (管线层无错误)

---

## 4. 问题总结

| # | 严重度 | 问题 | 影响范围 | 根因 |
|---|--------|------|---------|------|
| P1 | 🔴 **高** | CZSC 引擎 typed output 桥接断裂 | 所有 CZSC 信号丢失 | `CZSCOutput` dataclass 无 `.get()` |
| P1 | 🔴 **高** | Wyckoff 引擎 typed output 桥接断裂 | 所有 Wyckoff 信号丢失 | `WyckoffOutput` dataclass 无 `.get()` |
| P2 | 🟡 **中** | Alpha 基准路径不匹配 | Alpha 引擎无基准数据 | `000300` vs `sh000300` 文件名 |
| P3 | ⚪ **低** | 配置验证器路径偏差 | 告警, 不影响运行 | 验证器基路径错误 |
| P3 | ⚪ **低** | sources 配置格式警告 | 告警, 不影响运行 | Config 格式 vs 验证器期望 |

---

## 5. 建议

1. **立即修复 (P1)**: 在 `analysis_service_v2.py` 的 `_run_czsc()` 和 `_run_wyckoff()` 中, 将 typed output 的 `.get()` 调用改为 dataclass 属性访问 (`output.some_field` 或 `getattr(output, "field", default)`)
2. **短期修复 (P2)**: 创建 `data/lake/index/000300.SH.parquet` 符号链接或修复索引路径配置
3. **中期改进**: 为管线增加"信号产生率"告警——如果多轮信号为零, 发出警告而非静默通过
4. **建议**: 将 `success` 从"管线层无异常"细化为"引擎层至少 N 个引擎产生可用输出", 避免零信号被标记为成功

---

## 6. 结论

管线**编排层**通过 5 轮测试 (100% 通过率, 0 异常抛到顶层), 但 Phase 4 typed output migration (2026-06-17) 引入的 CZSC/Wyckoff 桥接断裂导致**信号产生率为零**。这两处是 P1 级阻塞缺陷。

原始数据: `data/pipeline_5round/results.json`
测试脚本: `scripts/pipeline_5round_test.py`
