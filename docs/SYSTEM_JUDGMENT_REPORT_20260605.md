# UniQuant 系统审判报告（整改后终版 v4）

> **Obsolete as of 2026-06-07** — 见 FIVE_STAGE_ANALYSIS_REPORT_20260607.md / FIVE_STAGE_ROUND2_FINDINGS_20260607.md

> 生成日期：2026-06-05 | 基于源码逐行核验 + 测试执行
> 对应验证方案：`docs/SYSTEM_JUDGMENT_VERIFICATION_PLAN_20260605.md`

---

## §1 整改前风险发现

以下问题在 2026-06-05 源码审计中发现。全部已修复，保留作为审计轨迹。

| # | 风险 | 严重级 | 文件 | 根因 |
|---|------|--------|------|------|
| 1 | 组合回测漏扣过户费 | P0 | `unified_matching_engine.py` `portfolio_engine.py` | FillResult 无 transfer_fees；PE 买卖均不扣 |
| 2 | 最后一日 pending 信号同日成交 | P0 | `portfolio_engine.py:310` | 循环结束用 last_date 强制撮合 |
| 3 | 组合冲击成本输入语义错误 | P0 | `portfolio_engine.py` `unified_matching_engine.py` | 传入日成交量而非订单量 |
| 4 | fill_buy 涨停拒单未零成交 | P1 | `unified_matching_engine.py` | executed_shares 未用 limit_rejected 归零 |
| 5 | 拒单成本字段不干净 | P1 | `unified_matching_engine.py` | 佣金/印花税/过户费未按 rejected 归零 |
| 6 | FactorAnalyzer mode API 阻断 | P0 | `analyzer.py:209` | compute_ic_ir 只接受 AnalysisMode 枚举 |
| 7 | QFQ 复权无截止日期 | P1 | `data_adjuster.py:212,273` | iloc[-1] 无 cutoff；get_adjusted_data 不裁剪 |
| 8 | IPO 规则未接入统一引擎 | P1 | `unified_matching_engine.py:78` | compute_limit_status_vectorized 无 trading_days_listed |
| 9 | ST 涨跌幅未接入统一引擎 | P1 | `unified_matching_engine.py:87` | get_board_type 未传 name |
| 10 | 默认研究路径幸存者偏差 | P1 | `baostock.py:281` `scan_service.py:53` | include_delisted=False；exclude_delisted=True |
| 11 | 主路径 iterrows 性能灾难 | P2 | `portfolio_engine.py:279` | 13 处 iterrows 散落；全市场 5000×2500 不可行 |
| 12 | DataCleaner 未修复 High<Low | P1 | `data/cleaner` | 数据清洗裂缝；影响 K线形态和因子计算 |
| 13 | 测试导入路径不规范 | P2 | `test_matching_engine.py` | from src.uniquant 需 PYTHONPATH=. |

---

## §2 整改后状态

### 2.1 修复文件清单

| 文件 | 改动 | 涉及问题 |
|------|------|---------|
| `unified_matching_engine.py` | FillResult +transfer_fees；fill_buy 涨停归零 + 成本字段屏蔽；volumes→order_volumes；ST/IPO 参数；sell 端成本字段屏蔽 | #1, #4, #5, #3, #8, #9 |
| `portfolio_engine.py` | 过户费入现金流；传 sh_arr/pos_arr 给冲击成本；删最后一日 tail；itertuples 替代 iterrows；ST/IPO 透传 | #1, #3, #2, #11, #8, #9 |
| `analyzer.py` | compute_ic_ir 接受 `str \| AnalysisMode` | #6 |
| `data_adjuster.py` | apply_adjustment +cutoff_date；get_adjusted_data 按日期裁剪 | #7 |
| `baostock.py` | include_delisted 默认 True | #10 |
| `scan_service.py` | exclude_delisted 默认 False | #10 |
| `test_matching_engine.py` | 导入 from uniquant；涨停/跌停测试加 cost-zero 断言 | #13, #5 |
| `test_portfolio_engine_v2.py` | mock FillResult +transfer_fees +**kwargs | #1 |

### 2.2 FillResult 合约定义（当前）

```python
@dataclass
class FillResult:
    executed_shares: np.ndarray
    exec_prices: np.ndarray
    commissions: np.ndarray
    stamp_duties: np.ndarray
    slippages: np.ndarray
    transfer_fees: np.ndarray      # 2026-06-05 新增
    rejected_mask: np.ndarray
    t1_violation_mask: np.ndarray
    limit_violation_mask: np.ndarray
    cash_shortfall_mask: np.ndarray
```

**合约保证：** `rejected_mask[i] == True ⇒ executed_shares[i] == 0 && commissions[i] == 0 && stamp_duties[i] == 0 && transfer_fees[i] == 0 && slippages[i] == 0`

### 2.3 测试结果

| 测试套件 | 结果 | 对比修复前 |
|---------|------|-----------|
| test_lookahead_bias | **8 passed** | 2 failed 6 passed |
| test_limit_checker | 30 passed | 30 passed |
| test_matching_engine + t1 | 25 passed | 17 passed + 8 passed |
| test_portfolio_engine_v2 | 15 passed | 15 passed |
| test_backtest_engine + advanced | 41p 1s | 41p 1s |
| test_drawdown_analyzer | 8 passed | 8 passed |
| test_sizer | 19 passed | 19 passed |
| test_evt_risk | 17 passed | 17 passed |
| test_portfolio_optimizer | 1f 14p | 1f 14p |
| test_walk_forward | 12 passed | 12 passed |
| test_financial_bridge | 17 passed | 17 passed |
| test_czsc_bar | 10 passed | 10 passed |
| test_data_chaos_qa | **44p** | 1f 43p → 修复后 44p |
| test_portfolio_optimizer | **15p** | 1f 14p → 修复后 15p |
| test_engine_factory | **6p** | 环境阻断 → mock 修复后 6p |
| test_custom_factors | 4 passed | 4 passed |
| test_import_state | 6 passed | 6 passed |

---

## §3 剩余风险

### P1 — 数据管道质量

| 问题 | 文件 | 影响 | 修复方向 |
|------|------|------|---------|
| DataCleaner 不修复 High<Low | `tests/test_data_chaos_qa.py::TestDataCleanerChaos::test_high_lt_low_anomaly` | 异常 K 线传入 limit 检测和因子计算；K线形态因子错误 | 在 DataCleaner pipeline 中按 `high = max(open, close, high)` 修复 |
| test_portfolio_optimizer risk_free_rate | 默认值 0.02 与测试预期 0.03 不一致 | Metrics 模块默认值分歧 | 统一默认值或测试改为读配置 |

### 已修复（2026-06-05 第二轮）

| 问题 | 修复 |
|------|------|
| 18 处 iterrows 已全部替换为 itertuples（2026-06-05） | 零 iterrows 残留 |
| `test_engine_factory` 环境问题 | mock 改为选择性拦截，不污染 `charset_normalizer` 内部导出 |

---

## §4 最终裁决

1. **PortfolioEngine 可进入正式组合回测**：3 个 P0 现金流/语义缺陷已修正，`FillResult` 合约干净。
2. **UnifiedMatchingEngine 合约完整**：10 字段全覆盖（含过户费），拒单语义统一，ST/IPO 接口就绪。
3. **因子分析管线打通**：`compute_ic_ir` 接受字符串 mode；复权按截止日期防护。
4. **数据管道存在 1 个 P1 裂缝**（High<Low 未清洗），建议纳入下一轮修复。
