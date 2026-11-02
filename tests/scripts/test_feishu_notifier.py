#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UniQuant 飞书机器人通知器单元测试
==================================
覆盖签名计算、脱机降级 (dry_run)、交互卡片生成与参数校验。
"""

import json
from unittest.mock import MagicMock, patch

from scripts.monitoring.feishu_notifier import FeishuNotifier


class TestFeishuNotifier:
    """飞书通知器测试套件"""

    def test_dry_run_mode_without_network(self):
        """测试在无 Webhook URL 时的自动 dry_run 降级"""
        notifier = FeishuNotifier(webhook_url="", dry_run=False)
        assert notifier.dry_run is True

        res = notifier.send_text("Hello UniQuant")
        assert res["status"] == "dry_run"
        assert res["code"] == 0
        assert res["payload"]["msg_type"] == "text"
        assert res["payload"]["content"]["text"] == "Hello UniQuant"

    def test_signature_generation(self):
        """测试签名计算确定性与合法性"""
        notifier = FeishuNotifier(webhook_url="https://dummy", secret="test_secret_key")
        sig = notifier._generate_sign(1700000000)
        assert isinstance(sig, str)
        assert len(sig) > 0

        # 空 secret 返回空字符串
        notifier_no_secret = FeishuNotifier(webhook_url="https://dummy", secret="")
        assert notifier_no_secret._generate_sign(1700000000) == ""

    def test_send_interactive_card_dry_run(self):
        """测试交互式卡片在 dry_run 下的结构组装"""
        notifier = FeishuNotifier(dry_run=True)
        elements = [{"tag": "div", "text": {"tag": "plain_text", "content": "test"}}]
        res = notifier.send_interactive_card(title="Test Card", elements=elements, color_theme="GREEN")

        assert res["status"] == "dry_run"
        payload = res["payload"]
        assert payload["msg_type"] == "interactive"
        assert payload["card"]["header"]["title"]["content"] == "Test Card"
        assert payload["card"]["header"]["template"] == "green"
        assert payload["card"]["elements"] == elements

    def test_send_macro_cash_report(self):
        """测试纯多头宏观研报卡片的字段填充与三色告警映射"""
        notifier = FeishuNotifier(dry_run=True)

        # 100% 仓位 -> GREEN
        res_bull = notifier.send_macro_cash_report(
            as_of_date="2026-10-27",
            regime_status="BULL_OFFENSE",
            equity_weight_pct=100.0,
            benchmark_price=4000.0,
            benchmark_ma120=3800.0,
            active_triggers=[],
            recommended_stocks=["600519.SH"],
        )
        assert res_bull["payload"]["card"]["header"]["template"] == "green"

        # 50% 仓位 -> YELLOW
        res_caution = notifier.send_macro_cash_report(
            as_of_date="2026-10-27",
            regime_status="CAUTION_DEFENSE",
            equity_weight_pct=50.0,
            benchmark_price=3800.0,
            benchmark_ma120=3900.0,
            active_triggers=["MA120破位"],
            recommended_stocks=["600519.SH"],
        )
        assert res_caution["payload"]["card"]["header"]["template"] == "yellow"

        # 0% 仓位 -> RED
        res_bear = notifier.send_macro_cash_report(
            as_of_date="2026-10-27",
            regime_status="BEAR_PANIC_CASH",
            equity_weight_pct=0.0,
            benchmark_price=3500.0,
            benchmark_ma120=3900.0,
            active_triggers=["流动性冰冻", "LPPL临界破裂"],
            recommended_stocks=[],
        )
        assert res_bear["payload"]["card"]["header"]["template"] == "red"

    @patch("urllib.request.urlopen")
    def test_send_payload_network_success(self, mock_urlopen):
        """测试正常网络请求的发送与解析"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"code": 0, "msg": "success"}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        notifier = FeishuNotifier(webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test", secret="sec")
        res = notifier.send_text("Live Ping")
        assert res["code"] == 0
        assert res["msg"] == "success"
