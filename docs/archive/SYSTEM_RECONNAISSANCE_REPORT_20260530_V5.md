# UniQuant 系统现状全景侦察报告 (V5)

> **Obsolete as of 2026-06-07** — 见 FIVE_STAGE_ANALYSIS_REPORT_20260607.md / FIVE_STAGE_ROUND2_FINDINGS_20260607.md

> 审计时间：2026-05-30 | 4 路 Subagent 并发审计
> 本报告为 V4 修复后的最终审计

---

## 一、V4 修复验证结果

| # | 修复项 | 状态 | 证据 |
|---|--------|------|------|
| P0-1 | config=None 风险 | ✅ 通过 | 5 个核心文件使用 `get_config()` |
| P0-2 | 统一 Sharpe 口径 | ✅ 通过 | 6 个文件使用 `calculate_sharpe_ratio()` |
| P0-3 | 集成过户费 | ✅ 通过 | `engine.py:76`, `unified_matching_engine.py:111,179` |
| P1-1 | ServiceContainer 锁 | ✅ 通过 | `service_container.py:31,62` 双重检查锁 |
| P1-2 | 手数取整 | ✅ 通过 | 3 处 `// 100 * 100` |

**结论：5/5 项修复全部验证通过。**

---

## 二、新发现的问题

### CRITICAL 级别

| # | 问题 | 文件:行号 |
|---|------|-----------|
| C1 | CostConfig 缺少 `transfer_fee_pct` 字段，`cost_sell` 属性会抛出 `AttributeError` | `cost_model.py:39-44,98` |

### HIGH 级别

| # | 问题 | 文件:行号 |
|---|------|-----------|
| H1 | `portfolio_engine.py:359` `volatility` 变量未定义，`calculate_metrics()` 必崩 | `portfolio_engine.py:359` |
| H2 | `result.py:104` `returns` 变量未定义，`calculate_metrics()` 必崩 | `result.py:104` |
| H3 | `CostConfig.cost_buy` 属性不含过户费，与模块级 `COST_BUY` 不一致 | `cost_model.py:93-94` |

### MEDIUM 级别

| # | 问题 | 文件:行号 |
|---|------|-----------|
| M1 | `robustness_checker.py:207` Sharpe 口径不一致（未减无风险利率） | `robustness_checker.py:207` |
| M2 | 复权因子数据目录为空 | `data/fq/`, `data/factors/` |
| M3 | trading.yaml/factors.yaml 未被 GlobalConfig 加载 | `config_loader.py:66-69` |
| M4 | LPPL `_calculate_confidence` 语义不匹配 (SSE vs RMSE) | `calculator.py:341,552` |

---

## 三、模块状态矩阵

| 包 | 状态 | 遗留问题 |
|---|------|----------|
| **shared/cost_model.py** | ❌ 存在致命逻辑 | CostConfig 缺字段，cost_sell 必崩 |
| **shared/config_loader.py** | ⚠️ 勋强可用 | 3 个 YAML 未统一管理 |
| **data/** | ⚠️ 勋强可用 | fq/factors 目录为空 |
| **brain/lppl/** | ⚠️ 勋强可用 | _calculate_confidence 语义不匹配 |
| **brain/wyckoff/** | ✅ 生产可用 | prior_trend_pct 已修复，scan_signal 完整 |
| **brain/czsc/** | ✅ 生产可用 | CZSCEngineError 统一 |
| **brain/factors/** | ✅ 生产可用 | Walk-Forward 枚举正确 |
| **hands/backtest/** | ❌ 存在致命逻辑 | portfolio_engine.py 和 result.py 变量未定义 |
| **hands/strategies/** | ⚠️ 勋强可用 | B轨 look-ahead bias 无警告 |
| **risk/** | ⚠️ 勋强可用 | EVTRisk 名不副实 |
| **services/** | ✅ 生产可用 | ServiceContainer 双重检查锁 |
| **signal/** | ✅ 生产可用 | 归一化、聚合完整 |
| **ui/** | ✅ 生产可用 | Streamlit 仪表盘完整 |

---

## 四、技术债与高危地带雷达

### 🔴 TOP 3 高危代码位置

**1. `cost_model.py:39-44,98` — CostConfig 缺少字段导致运行时崩溃**
```python
@dataclass
class CostConfig:
    buy_fee_pct: float = COMMISSION_PCT
    sell_fee_pct: float = COMMISSION_PCT
    stamp_tax_pct: float = STAMP_TAX_PCT
    slippage_pct: float = SLIPPAGE_PCT
    min_commission: float = MIN_COMMISSION
    # 缺少: transfer_fee_pct: float = TRANSFER_FEE_PCT

@property
def cost_sell(self) -> float:
    return self.sell_fee_pct + self.stamp_tax_pct + self.transfer_fee_pct  # AttributeError!
```

**2. `portfolio_engine.py:359` — volatility 变量未定义**
```python
return {
    "volatility": volatility,  # NameError: volatility 未定义
    "sharpe_ratio": sharpe,
}
```

**3. `result.py:104` — returns 变量未定义**
```python
trading_days = len(returns)  # NameError: returns 未定义
```

---

## 五、下一步行动建议

### P0 — 紧急修复（影响运行时崩溃）

1. **修复 CostConfig**：添加 `transfer_fee_pct` 字段，修复 `cost_buy` 和 `cost_sell` 属性
2. **修复 portfolio_engine.py**：添加 `volatility` 变量定义
3. **修复 result.py**：将 `returns` 改为 `self.daily_returns`

### P1 — 重要修复

4. **修复 robustness_checker.py Sharpe**：使用 `calculate_sharpe_ratio()` 函数
5. **下载复权因子数据**：运行 `sync_factors_mootdx.py`

### P2 — 改进项

6. **统一配置加载**：将 trading.yaml 纳入 GlobalConfig
7. **修复 LPPL _calculate_confidence**：统一 SSE/RMSE 语义

---

*报告生成时间：2026-05-30 | 基于代码事实，零推测*
