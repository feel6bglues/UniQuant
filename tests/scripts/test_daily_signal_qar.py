"""
CNMM-QAR 每日实盘信号与对冲指令调度流水线测试
=============================================================================
验证:
1. daily_signal_qar CLI 运行正常;
2. 生成 75/25 资本架构与多空配置结果;
3. 3 PB 账户套保分仓合法有效;
4. 输出文件正确落盘且符合 JSON 契约。
=============================================================================
"""

import json
import pytest

from scripts.canslim.daily_signal_qar import run_daily_pipeline


class TestDailySignalQARPipeline:
    """CNMM-QAR 生产级日常调度流水线测试"""

    def test_run_daily_pipeline_75_25(self, tmp_path):
        """测试 75/25 合规对冲实盘调度流水线"""
        res = run_daily_pipeline(
            as_of="2024-05-06",
            track="75/25-IH",
            aum_rmb=50_000_000.0,
            output_dir=tmp_path,
        )

        assert res["as_of_date"] == "2024-05-06"
        assert res["strategy_track"] == "75/25-IH"
        assert res["aum_rmb"] == 50_000_000.0

        # 资本配置验证
        cap = res["capital_allocation"]
        assert cap["equity_long_value"] == 37_500_000.0
        assert cap["futures_short_notional"] == 37_500_000.0
        assert cap["cash_buffer_value"] == 12_500_000.0

        # 选股与治理合规验证
        univ = res["universe_summary"]
        assert univ["selected_stocks_count"] == 40
        assert univ["governance_compliant"] is True
        assert len(res["target_stock_weights"]) == 40
        # 权重总和严格等于 0.75
        assert pytest.approx(sum(res["target_stock_weights"].values()), abs=1e-5) == 0.75

        # 期货分仓验证
        futures_info = res["futures_hedging_orders"]
        assert futures_info["num_accounts"] == 3
        assert futures_info["all_accounts_within_speculative_limit"] is True
        total_contracts = sum(a["allocated_contracts"] for a in futures_info["accounts"])
        assert total_contracts == futures_info["total_short_contracts_needed"]

        # 落盘文件验证
        out_json = tmp_path / "2024-05-06.json"
        assert out_json.exists()
        with open(out_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["as_of_date"] == "2024-05-06"
        assert data["universe_summary"]["selected_stocks_count"] == 40
