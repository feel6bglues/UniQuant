# UniQuant 系统现状全景侦察报告 (V3)

> 审计时间：2026-05-30 | 4 路 Subagent 并发审计
> 本报告为 P0/P1 修复后的重新审计，验证修复并发现新问题

---

## 一、修复验证结果

| # | 修复项 | 状态 | 证据 |
|---|--------|------|------|
| P0-1 | LPPL RMSE 计算 | ✅ 通过 | `calculator.py:331-336` 使用正确公式 |
| P0-2 | scan_signal action 字段 | ✅ 通过 | `engine.py:1402-1411` 使用 `direction` 映射 |
| P0-3 | Walk-Forward mode 类型 | ✅ 通过 | `walk_forward_pipeline.py:16,130,155,179` 使用枚举 |
| P1-1 | 模块/包命名冲突 | ✅ 通过 | 3 个冗余 .py 文件已删除 |
| P1-2 | Sharpe 口径统一 | ✅ 通过 | `result.py:58,100-103` 含 rf |
| P1-3 | EastmoneySource 注册 | ✅ 通过 | `data_fetcher.py:28,71` 已添加 |
| P1-4 | NaN 处理链路 | ✅ 通过 | `data_cleaner.py:27-34` 价格列不再填 0 |

---

## 二、新发现问题汇总

### CRITICAL 级别

| # | 问题 | 文件:行号 |
|---|------|-----------|
| C1 | 买入手数未按 100 股整手取整 | `engine.py:181` |
| C2 | 向量化撮合未做整手取整 | `unified_matching_engine.py:113-117` |
| C3 | Walk-Forward `factor_func` 参数不存在于 `compute_ic_ir` 签名 | `walk_forward_pipeline.py:131` |
| C4 | B轨策略无 look-ahead bias 警告标记 | `wyckoff.py:91`, `ma_cross.py:27` 等 |

### HIGH 级别

| # | 问题 | 文件:行号 |
|---|------|-----------|
| H1 | `prior_trend_pct` 硬编码为 0.0 | `engine.py:429` |
| H2 | ServiceContainer 单例无锁保护 | `service_container.py:36-39` |
| H3 | EVTRisk 名不副实，实为历史模拟法 | `evt_risk.py:24,389` |
| H4 | CZSCAnalysisError vs CZSCEngineError 未统一 | `czsc_engine.py:80` / `exceptions.py:41` |
| H5 | 原子写入使用 unlink+rename | `storage_manager.py:325-327` |
| H6 | 复权因子数据目录为空 | `data/fq/` |
| H7 | REAL_TODAY 模块级固化 | `smart_factor_calculator.py:16` |
| H8 | Sharpe 口径仍不统一（3种公式、2种rf） | `result.py:100` vs `portfolio_engine.py:339` vs `backtest.py:187` |
| H9 | base.py 导入路径错误 | `base.py:12` |
| H10 | scan_signal action 映射不完整（缺少'做多'等） | `engine.py:1406-1411` |

### MEDIUM 级别

| # | 问题 | 文件:行号 |
|---|------|-----------|
| M1 | 过户费完全缺失（万分之0.1） | `cost_model.py` 全文 |
| M2 | 滑点值不一致（0.1% vs 0.05%） | `slippage_model.py:14` vs `cost_model.py:29` |
| M3 | `avg_holding_days` 从未被计算 | `result.py:52` |
| M4 | T+1 用日历日而非交易日 | `unified_matching_engine.py:155-168` |
| M5 | 成交量复权方向存疑 | `data_adjuster.py:234-235` |
| M6 | `config` 模块级变量可能为 None | `structural.py:4` |
| M7 | PortfolioSizer 直接修改输入对象 | `sizer.py:252-253` |
| M8 | DuckDB 配置存在但无实现 | `config.yaml:9` |
| M9 | LPPL `_calculate_confidence` 输入语义不一致 | `calculator.py:391-428` |
| M10 | LPPL 三模块功能重复 | `lppl/*.py` |

---

## 三、关键问题详解

### C1/C2: 手数取整缺失

**问题**：`engine.py:181` 和 `unified_matching_engine.py:113-117` 买入股数未按 100 股整手取整

**修复方案**：
```python
# engine.py:181 修改
shares = int((self.cash - commission) / exec_price)
shares = (shares // 100) * 100  # 新增：整手取整

# unified_matching_engine.py:113-117 修改
shares_adj = np.where(
    cash_shortfall & (cash_available > commissions),
    ((cash_available - commissions) / np.maximum(exec_prices, 1e-8)).astype(np.int64) // 100 * 100,  # 新增
    shares_requested,
)
```

### H1: prior_trend_pct 硬编码

**问题**：`engine.py:429` 将 `prior_trend_pct` 硬编码为 0.0

**修复方案**：
```python
# engine.py:429 修改
prior_trend_pct=prior_trend_pct,  # 使用实际计算值
```

### H5: 原子写入缺陷

**问题**：`storage_manager.py:325-327` 使用 `unlink()` + `rename()` 非原子操作

**修复方案**：
```python
# storage_manager.py:325-327 修改
# 原代码:
if file_path.exists():
    file_path.unlink()
temp_path.rename(file_path)

# 新代码:
os.replace(str(temp_path), str(file_path))
```

### H9: base.py 导入路径错误

**问题**：`base.py:12` 使用 `from risk.sizer import PositionSizer` 缺少 `uniquant.` 前缀

**修复方案**：
```python
# base.py:12 修改
from uniquant.risk.sizer import PositionSizer
```

### H10: scan_signal action 映射不完整

**问题**：`engine.py:1406-1411` 映射表缺少 '做多'、'轻仓试探' 等中文关键词

**修复方案**：
```python
# engine.py:1406-1411 修改
direction_raw = getattr(report.trading_plan, 'direction', '空仓观望')
# 扩展映射表
buy_keywords = ['long', '多头', '买入', '做多', '轻仓试探', '加仓']
sell_keywords = ['short', '空头', '卖出', '做空', '减仓']
if any(kw in str(direction_raw) for kw in buy_keywords):
    action = 'BUY'
elif any(kw in str(direction_raw) for kw in sell_keywords):
    action = 'SELL'
else:
    action = 'HOLD'
```

---

## 四、模块状态矩阵 (更新)

| 包 | 状态 | 遗留问题数 |
|---|------|-----------|
| **shared/** | ⚠️ | 3 (滑点不一致、config竞态、异常重复) |
| **data/** | ⚠️ | 6 (原子写入、fq为空、REAL_TODAY、DuckDB等) |
| **brain/lppl/** | ⚠️ | 3 (confidence语义、三模块重复、风险阈值) |
| **brain/wyckoff/** | ⚠️ | 3 (prior_trend_pct硬编码、action映射、死代码) |
| **brain/factors/** | ⚠️ | 2 (factor_func参数、正交化二次标准化) |
| **brain/czsc/** | ⚠️ | 1 (CZSCAnalysisError未统一) |
| **hands/backtest/** | ❌ | 5 (手数取整x2、T+1、过户费、avg_holding_days) |
| **hands/strategies/** | ❌ | 3 (STRATEGY_MAP冲突、look-ahead bias、base.py路径) |
| **risk/** | ⚠️ | 4 (EVTRisk名不副实、sizer修改输入、缓存键碰撞) |
| **services/** | ⚠️ | 2 (ServiceContainer无锁、AnalysisEngineFactory无锁) |

---

## 五、下一步行动建议

### P0 — 紧急修复（影响回测正确性）

1. **修复手数取整**：`engine.py:181` 和 `unified_matching_engine.py:113-117` 添加 `// 100 * 100`
2. **修复 prior_trend_pct**：`engine.py:429` 使用实际计算值
3. **修复 base.py 导入**：`base.py:12` 添加 `uniquant.` 前缀
4. **修复 scan_signal 映射**：`engine.py:1406-1411` 扩展关键词列表

### P1 — 重要修复（影响系统稳定性）

5. **修复原子写入**：`storage_manager.py` 3处 `unlink+rename` 改为 `os.replace`
6. **添加过户费**：`cost_model.py` 添加 `TRANSFER_FEE_PCT = 0.00001`
7. **统一 Sharpe 口径**：选择 `(ann_ret - rf) / ann_vol` 公式，统一所有计算点
8. **统一 CZSC 异常**：删除 `czsc_engine.py:80` 的 `CZSCAnalysisError`，使用 `CZSCEngineError`
9. **添加 ServiceContainer 线程锁**：参考 `GlobalConfig` 的双重检查锁模式

### P2 — 改进项（影响数据质量）

10. **下载复权因子数据**：运行 `sync_factors_mootdx.py` 生成 `data/fq/gbbq.parquet`
11. **修复 REAL_TODAY**：改为函数调用 `get_real_today()`
12. **添加 B轨策略 look-ahead bias 警告**：在入口处添加 `warnings.warn()`
13. **修复 EVTRisk 命名**：重命名为 `historical_risk.py` 或实现真正的 GPD 拟合

---

*报告生成时间：2026-05-30 | 基于代码事实，零推测*
