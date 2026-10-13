#!/usr/bin/env python3
"""
UniQuant 数据湖新鲜度 SLA 巡检与告警通道 — check_freshness_sla.py

由 crontab 每日 18:00 自动触发，或供运维人员手动执行。
在检测到 L1/L2 滞后或数据湖异常时，除输出日志外，主动触发以下多级告警通道:
1. 结构化高危告警日志 (logs/sla_alerts.log)
2. Linux 桌面通知 (notify-send, 若桌面会话可用)
3. 操作系统 syslog 核心告警 (syslog.LOG_CRIT)
4. 返回非零退出码 (L1 异常 exit 1, L2/数据湖异常 exit 2)

用法:
  python3 scripts/maintenance/check_freshness_sla.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import syslog
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from uniquant.data.lake.storage_manager import StorageManager


def _send_desktop_notification(title: str, message: str) -> None:
    """尝试向当前活动桌面发送系统告警通知 (notify-send)。"""
    notify_bin = shutil.which("notify-send")
    if not notify_bin:
        return

    # 若 crontab 执行，环境变量可能缺失 DISPLAY 或 DBUS_SESSION_BUS_ADDRESS
    env = os.environ.copy()
    if "DISPLAY" not in env:
        env["DISPLAY"] = ":0"
    if "DBUS_SESSION_BUS_ADDRESS" not in env:
        # 尝试自动定位当前用户的 dbus 地址
        uid = os.getuid()
        runtime_bus = f"/run/user/{uid}/bus"
        if os.path.exists(runtime_bus):
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime_bus}"

    try:
        subprocess.run(
            [notify_bin, "-u", "critical", "-t", "10000", title, message],
            env=env,
            timeout=5,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        pass


def _log_critical_alert(alert_type: str, details: dict, log_dir: Path) -> None:
    """记录结构化高危告警到专门文件与系统 syslog。"""
    log_dir.mkdir(parents=True, exist_ok=True)
    alert_file = log_dir / "sla_alerts.log"
    now_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")

    alert_entry = {
        "timestamp": now_str,
        "alert_type": alert_type,
        "is_fresh": details.get("is_fresh"),
        "lake_max_date": details.get("lake_max_date"),
        "tdx_max_date": details.get("tdx_max_date"),
        "l1_lag_days": details.get("details", {}).get("l1_lag_days"),
        "l2_lag_days": details.get("l2_lag_days"),
        "stale_reasons": details.get("details", {}).get("stale_reasons", []),
    }

    alert_line = f"[{now_str}] [{alert_type}] {json.dumps(alert_entry, ensure_ascii=False)}\n"
    with open(alert_file, "a", encoding="utf-8") as f:
        f.write(alert_line)

    # 写入系统日志
    try:
        syslog.openlog(ident="uniquant-sla", facility=syslog.LOG_LOCAL0)
        syslog.syslog(
            syslog.LOG_CRIT,
            f"UniQuant SLA Alert: {alert_type} | Lake={details.get('lake_max_date')} | "
            f"TDX={details.get('tdx_max_date')} | L2_Lag={details.get('l2_lag_days')}d | "
            f"Reasons={details.get('details', {}).get('stale_reasons', [])}",
        )
        syslog.closelog()
    except Exception:
        pass


def main() -> int:
    sm = StorageManager()
    res = sm.validate_freshness(check_tdx=True)

    # 1. 打印结构化 JSON 报告到 stdout (被 crontab 日志捕获)
    print(json.dumps(res, indent=2, ensure_ascii=False))

    is_fresh = res.get("is_fresh", False)
    details = res.get("details", {})
    l1_fresh = details.get("l1_is_fresh", True)
    l2_fresh = details.get("l2_is_fresh", True)

    log_dir = PROJECT_ROOT / "logs"

    # 2. 判断是否正常
    if is_fresh and l1_fresh and l2_fresh:
        return 0

    # 3. 触发异常告警
    if not is_fresh or not l2_fresh:
        alert_type = "L2_LAKE_STALE_CRITICAL"
        reasons = ", ".join(details.get("stale_reasons", [])) or "数据湖滞后超标"
        msg = (
            f"数据湖滞后告警！\n"
            f"湖最大日期: {res.get('lake_max_date')}, TDX 最大日期: {res.get('tdx_max_date')}\n"
            f"L2 滞后: {res.get('l2_lag_days')} 天\n"
            f"原因: {reasons}\n"
            f"请执行 SOP: python3 scripts/maintenance/sync_local_tdx_day.py"
        )
        _log_critical_alert(alert_type, res, log_dir)
        _send_desktop_notification("UniQuant 数据湖 SLA 异常", msg)
        print(f"\n[ALERT] 触发 {alert_type}: {reasons}", file=sys.stderr)
        return 2

    if not l1_fresh:
        alert_type = "L1_TDX_UPSTREAM_STALE_WARNING"
        l1_lag = details.get("l1_lag_days", "未知")
        msg = (
            f"通达信上游滞后提醒！\n"
            f"TDX 最大日期: {res.get('tdx_max_date')} (滞后 {l1_lag} 天)\n"
            f"请打开 Wine 通达信执行「系统 -> 盘后数据下载」"
        )
        _log_critical_alert(alert_type, res, log_dir)
        _send_desktop_notification("UniQuant 上游数据未更新", msg)
        print(f"\n[ALERT] 触发 {alert_type}: TDX 滞后 {l1_lag} 天", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
