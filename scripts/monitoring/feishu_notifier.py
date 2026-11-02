#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UniQuant 飞书机器人通知与量化研报推送服务
========================================
核心职责:
1. 提供飞书自定义机器人 Webhook 通信接口，支持 HMAC-SHA256 签名鉴权;
2. 支持富文本交互式卡片 (Interactive Card) 构造，针对多头状态、空仓预警与对账报告定制模板;
3. 严格遵循无网络/脱机降级保护 (dry_run 模式)，确保研究环境与 CI 环境 100% 稳定运行;
4. 提供 CLI 命令行入口，无缝挂载至 ops_health_check.sh 巡检流水线。
========================================
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


class FeishuNotifier:
    """飞书自定义机器人通知器 (支持签名鉴权与交互卡片)"""

    COLOR_MAP = {
        "GREEN": "green",
        "YELLOW": "yellow",
        "RED": "red",
        "BLUE": "blue",
        "GREY": "grey",
    }

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        secret: Optional[str] = None,
        dry_run: bool = False,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.webhook_url = webhook_url or os.getenv("FEISHU_WEBHOOK_URL", "")
        self.secret = secret or os.getenv("FEISHU_SECRET", "")
        self.dry_run = dry_run or (not self.webhook_url)
        self.timeout_seconds = timeout_seconds

    def _generate_sign(self, timestamp: int) -> str:
        """计算飞书 Webhook HMAC-SHA256 安全签名"""
        if not self.secret:
            return ""
        string_to_sign = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            self.secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        return base64.b64encode(hmac_code).decode("utf-8")

    def _send_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """执行底层 HTTP POST 请求 (带签名与脱机降级)"""
        if self.dry_run:
            return {
                "status": "dry_run",
                "code": 0,
                "msg": "Payload logged in dry_run mode",
                "payload": payload,
            }

        timestamp = int(time.time())
        if self.secret:
            payload["timestamp"] = str(timestamp)
            payload["sign"] = self._generate_sign(timestamp)

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.webhook_url,
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                raw_response = resp.read().decode("utf-8")
                return json.loads(raw_response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return {"status": "error", "code": -1, "msg": str(exc)}

    def send_text(self, text: str) -> Dict[str, Any]:
        """发送纯文本消息"""
        payload = {"msg_type": "text", "content": {"text": text}}
        return self._send_payload(payload)

    def send_interactive_card(
        self,
        title: str,
        elements: List[Dict[str, Any]],
        color_theme: str = "BLUE",
    ) -> Dict[str, Any]:
        """发送飞书交互式卡片"""
        header_color = self.COLOR_MAP.get(color_theme.upper(), "blue")
        card: Dict[str, Any] = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": header_color,
            },
            "elements": elements,
        }
        payload = {"msg_type": "interactive", "card": card}
        return self._send_payload(payload)

    def send_macro_cash_report(
        self,
        as_of_date: str,
        regime_status: str,
        equity_weight_pct: float,
        benchmark_price: float,
        benchmark_ma120: float,
        active_triggers: List[str],
        recommended_stocks: List[str],
        cash_rate_pct: float = 2.50,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """发送纯多头宏观仓位与空仓安全阀研报卡片"""
        color = "GREEN" if equity_weight_pct >= 80.0 else ("YELLOW" if equity_weight_pct > 0.0 else "RED")
        title = f"【UniQuant 纯多头研究研报】{as_of_date} 仓位与防御决策"

        stocks_preview = ", ".join(recommended_stocks[:8])
        if len(recommended_stocks) > 8:
            stocks_preview += f" ... 等共 {len(recommended_stocks)} 只"
        elif not recommended_stocks:
            stocks_preview = "无 (当前处于 100% 空仓防御状态)"

        triggers_text = "\\n- ".join(active_triggers) if active_triggers else "各项宏观指标平稳，无下行预警触发"

        elements: List[Dict[str, Any]] = [
            {
                "tag": "div",
                "fields": [
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**宏观安全阀状态:**\\n`{regime_status}`",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**目标多头仓位:**\\n**{equity_weight_pct:.1f}%** (现金: {100.0 - equity_weight_pct:.1f}%)",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**基准点位 vs MA120:**\\n{benchmark_price:.2f} / {benchmark_ma120:.2f}",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**现金无风险年化:**\\n{cash_rate_pct:.2f}% (货币基金计息)",
                        },
                    },
                ],
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**🛡️ 宏观安全阀触发明细:**\\n- {triggers_text}",
                },
            },
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**📈 优选持仓池 (Z-CNMM 排雷 + CFO 造血):**\\n{stocks_preview}",
                },
            },
        ]

        if note:
            elements.append({
                "tag": "note",
                "elements": [{"tag": "plain_text", "content": note}],
            })

        return self.send_interactive_card(title=title, elements=elements, color_theme=color)


def main() -> int:
    """CLI 入口，支持快速验证与测试"""
    parser = argparse.ArgumentParser(description="UniQuant 飞书告警推送 CLI")
    parser.add_argument("--test", action="store_true", help="发送测试文本卡片")
    parser.add_argument("--webhook", type=str, default="", help="飞书 Webhook URL")
    parser.add_argument("--secret", type=str, default="", help="飞书签名秘钥")
    parser.add_argument("--dry-run", action="store_true", help="模拟脱机打印，不实际发网络请求")
    args = parser.parse_args()

    notifier = FeishuNotifier(webhook_url=args.webhook, secret=args.secret, dry_run=args.dry_run)
    if args.test:
        res = notifier.send_macro_cash_report(
            as_of_date="2026-10-27",
            regime_status="CAUTION_DEFENSE (谨慎防御)",
            equity_weight_pct=50.0,
            benchmark_price=3920.50,
            benchmark_ma120=3980.20,
            active_triggers=["沪深300指数处于 120 日均线下方", "全市场中位数换手率走弱"],
            recommended_stocks=["600519.SH", "000858.SZ", "601318.SH", "600036.SH"],
            note="本研报由 UniQuant 量化研究平台自动化生成，不构成投资建议。",
        )
        print(f"[FeishuNotifier] 结果: {res}")
        return 0 if res.get("code") == 0 else 1

    print("请使用 --test 参数触发研报测试发送。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
