"""
私募机构级 2/20 治理账本测试套件
=============================================================================
验证:
  1. ACT/365 自然日 2.0% 管理费每日计提 (跨周末/长假自然日无缝对账);
  2. 固化高水位线 (Crystallized HWM) 与 6.0% Hurdle 门槛净值;
  3. 每日业绩报酬准备金暂估 (Daily Carry Accrual) 与回撤冲销 (Reversal);
  4. 法定结算日结转固化与次日准备金清零;
  5. 消除代数死循环与账实一致性对账。
=============================================================================
"""

import numpy as np
import pandas as pd

from uniquant.hands.backtest.institutional_fee_ledger import (
    InstitutionalFeeLedger,
)


class TestInstitutionalFeeLedger:
    """私募 2/20 治理账本测试"""

    def test_act365_management_fee_across_weekend_and_holidays(self):
        """测试 1: ACT/365 自然日管理费在工作日、周末及国庆长假的精准计提"""
        start_date = pd.Timestamp("2024-09-27") # 周五
        ledger = InstitutionalFeeLedger(
            mgmt_fee_rate=0.02,
            carry_rate=0.20,
            hurdle_rate=0.06,
            initial_nav=1.0,
            start_date=start_date
        )

        # Day 1: 9月30日 (周一，历经周五->周一共 3 个自然日)
        snap_mon = ledger.calculate_daily_fair_nav("2024-09-30", raw_nav=1.0)
        expected_mgmt_3d = 1.0 * (0.02 / 365.0) * 3
        assert np.isclose(snap_mon.mgmt_fee_accrued, expected_mgmt_3d, atol=1e-6)

        # Day 2: 10月08日 (节后周二，历经 9月30日->10月8日 共 8 个自然日)
        snap_post_golden_week = ledger.calculate_daily_fair_nav("2024-10-08", raw_nav=1.0)
        expected_mgmt_8d = 1.0 * (0.02 / 365.0) * 8
        assert np.isclose(snap_post_golden_week.mgmt_fee_accrued, expected_mgmt_8d, atol=1e-6)

    def test_hurdle_and_carry_accrual_above_threshold(self):
        """测试 2: 净值跑赢 6% Hurdle 门槛时的业绩报酬准备金每日暂估"""
        start_date = pd.Timestamp("2024-01-01")
        ledger = InstitutionalFeeLedger(
            mgmt_fee_rate=0.02,
            carry_rate=0.20,
            hurdle_rate=0.06,
            initial_nav=1.0,
            start_date=start_date
        )

        # 历经半年 (182.5 天)，raw_nav 达到 1.10
        mid_year_date = pd.Timestamp("2024-07-02")
        snap = ledger.calculate_daily_fair_nav(mid_year_date, raw_nav=1.10)

        # Hurdle = 1.0 * (1 + 0.06 * 183 / 365) = 1.030082
        days = (mid_year_date - start_date).days
        expected_hurdle = 1.0 * (1.0 + 0.06 * (days / 365.0))
        assert np.isclose(snap.hurdle_nav, expected_hurdle, atol=1e-4)

        # nav_after_mgmt 约为 1.10 - 1.10 * (0.02 / 365) * 183 ≈ 1.08896
        # carry_accrued = 0.20 * (nav_after_mgmt - hurdle)
        expected_nav_after_mgmt = 1.10 - 1.10 * (0.02 / 365.0) * days
        expected_carry = 0.20 * (expected_nav_after_mgmt - expected_hurdle)
        assert np.isclose(snap.carry_accrued, expected_carry, atol=1e-4)
        assert np.isclose(snap.net_nav, expected_nav_after_mgmt - expected_carry, atol=1e-4)

    def test_drawdown_carry_reversal_eliminates_circularity(self):
        """测试 3: 净值冲高回撤时准备金 100% 自动冲销释放，净值自动回补消除代数死循环"""
        start_date = pd.Timestamp("2024-01-01")
        ledger = InstitutionalFeeLedger(
            mgmt_fee_rate=0.02,
            carry_rate=0.20,
            hurdle_rate=0.06,
            initial_nav=1.0,
            start_date=start_date
        )

        # Day 100: 净值上涨至 1.15，提取大额准备金
        d1 = pd.Timestamp("2024-04-10")
        snap1 = ledger.calculate_daily_fair_nav(d1, raw_nav=1.15)
        assert snap1.carry_accrued > 0.02

        # Day 101: 遭遇黑天鹅单日暴跌回撤至 1.01 (低于 Hurdle)
        d2 = pd.Timestamp("2024-04-11")
        snap2 = ledger.calculate_daily_fair_nav(d2, raw_nav=1.01)
        # 准备金必须完全冲销归零！
        assert snap2.carry_accrued == 0.0
        # 净值并未被前期暂估永久扣减，扣减的只是 1 日管理费
        mgmt_1d = 1.01 * (0.02 / 365.0) * 1
        assert np.isclose(snap2.net_nav, 1.01 - mgmt_1d, atol=1e-5)

    def test_annual_crystallization_and_hwm_step_up(self):
        """测试 4: 法定年度结算日固化，业绩报酬划转，次日高水位线阶梯上升且准备金清零"""
        start_date = pd.Timestamp("2024-01-01")
        ledger = InstitutionalFeeLedger(
            mgmt_fee_rate=0.02,
            carry_rate=0.20,
            hurdle_rate=0.06,
            initial_nav=1.0,
            start_date=start_date
        )

        # 2024-12-31 法定结算日
        crys_date = pd.Timestamp("2024-12-31")
        snap_crys = ledger.calculate_daily_fair_nav(crys_date, raw_nav=1.20, is_crys_date=True)

        assert snap_crys.is_crystallized is True
        assert snap_crys.crystallized_carry > 0.0
        assert snap_crys.carry_accrued == 0.0 # 固化后已转为支付，暂估归零
        crys_hwm = snap_crys.net_nav
        assert np.isclose(snap_crys.crystallized_hwm, crys_hwm, atol=1e-6)

        # 2025-01-02 新年度首日
        d_next = pd.Timestamp("2025-01-02")
        snap_next = ledger.calculate_daily_fair_nav(d_next, raw_nav=crys_hwm)
        # 高水位线必须锁定在上一年度固化净值
        assert snap_next.crystallized_hwm == crys_hwm
        # 新年度首日门槛以新固化水位为基准
        assert snap_next.hurdle_nav >= crys_hwm
        # 此时净值未超过新门槛，准备金保持为 0
        assert snap_next.carry_accrued == 0.0

    def test_process_nav_series_dataframe_integration(self):
        """测试 5: 全流程批量 DataFrame 驱动核算与对账"""
        dates = pd.date_range("2024-01-01", "2024-12-31", freq="B")
        # 构造一条上升且含波动的真实净值序列
        t = np.linspace(0, 1, len(dates))
        raw_navs = 1.0 + 0.15 * t + 0.02 * np.sin(10 * t)
        df_nav = pd.DataFrame({"date": dates, "raw_nav": raw_navs})

        ledger = InstitutionalFeeLedger(
            mgmt_fee_rate=0.02,
            carry_rate=0.20,
            hurdle_rate=0.06,
            initial_nav=1.0,
            start_date=dates[0]
        )

        res_df = ledger.process_nav_series(df_nav, date_col="date", nav_col="raw_nav")
        assert len(res_df) == len(dates)
        assert "net_nav" in res_df.columns
        assert "crystallized_hwm" in res_df.columns
        assert "hurdle_nav" in res_df.columns
        # 检验最后一行年度结算日固化状态
        last_row = res_df.iloc[-1]
        assert bool(last_row["is_crystallized"]) is True
        assert last_row["crystallized_carry"] > 0.0

    def test_generate_governance_report(self):
        """测试 6: 私募治理账本与公允净值审计核心报表输出"""
        dates = pd.date_range("2024-01-01", "2024-12-31", freq="B")
        t = np.linspace(0, 1, len(dates))
        raw_navs = 1.0 + 0.20 * t
        df_nav = pd.DataFrame({"date": dates, "raw_nav": raw_navs})

        ledger = InstitutionalFeeLedger(
            mgmt_fee_rate=0.02,
            carry_rate=0.20,
            hurdle_rate=0.06,
            initial_nav=1.0,
            start_date=dates[0]
        )
        ledger.process_nav_series(df_nav, date_col="date", nav_col="raw_nav")
        report = ledger.generate_governance_report()

        assert "calendar_days" in report
        assert "trading_days" in report
        assert report["trading_days"] == len(dates)
        assert report["gross_cagr_pct"] > 0
        assert report["net_cagr_pct"] > 0
        assert report["fee_drag_pct"] > 0
        assert report["cumulative_mgmt_fee_paid"] > 0
        assert report["crystallization_events_count"] == 1

    def test_process_continuous_nav_series_recursive_compounding(self):
        """测试 7: 连续状态机递归复利计提与跨年度结晶扣除"""
        # 两年日频时序 (2023-01-01 至 2024-12-31)
        dates_y1 = pd.date_range("2023-01-03", "2023-12-29", freq="B")
        dates_y2 = pd.date_range("2024-01-02", "2024-12-31", freq="B")
        dates = dates_y1.append(dates_y2)

        # 第 1 年 gross 从 1.0 涨至 1.20；第 2 年 gross 从 1.20 涨至 1.44 (每年 +20%)
        t1 = np.linspace(0, 1, len(dates_y1))
        t2 = np.linspace(0, 1, len(dates_y2))
        navs_y1 = 1.0 + 0.20 * t1
        navs_y2 = 1.20 + 0.24 * t2
        raw_navs = np.concatenate([navs_y1, navs_y2])

        df_nav = pd.DataFrame({"date": dates, "raw_nav": raw_navs})
        crys_dates = [dates_y1[-1], dates_y2[-1]]

        ledger = InstitutionalFeeLedger(
            mgmt_fee_rate=0.02,
            carry_rate=0.20,
            hurdle_rate=0.06,
            initial_nav=1.0,
            start_date=dates[0],
        )

        res_df = ledger.process_continuous_nav_series(
            df_nav,
            date_col="date",
            nav_col="raw_nav",
            crystallization_dates=crys_dates,
        )

        # 验证结晶次数为 2 次
        crys_rows = res_df[res_df["is_crystallized"]]
        assert len(crys_rows) == 2

        # 第 1 年年末净值必须扣除管理费与业绩报酬，且低于 gross 1.20
        y1_end_net = crys_rows.iloc[0]["net_nav"]
        assert y1_end_net < 1.20
        assert crys_rows.iloc[0]["crystallized_carry"] > 0.0

        # 第 2 年首日公布净值必须平滑衔接第 1 年年末扣费后的资本底座，不发生虚高跳跃
        y2_start_idx = len(dates_y1)
        y2_start_net = res_df.iloc[y2_start_idx]["net_nav"]
        assert y2_start_net < 1.20
        assert np.isclose(y2_start_net, y1_end_net, atol=0.01)

        # 全周期终值：递归净值必须严格反映连续管理费和两度结晶
        final_net = res_df.iloc[-1]["net_nav"]
        assert 1.0 < final_net < 1.44
        assert ledger.cumulative_crystallized_carry > 0.0
        assert ledger.cumulative_mgmt_fee > 0.0


