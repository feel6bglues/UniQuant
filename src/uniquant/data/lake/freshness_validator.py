"""
数据新鲜度评估与两级 SLA 审计器 (FreshnessValidator)
=============================================================================
核心职责:
1. 扫描数据湖日线 parquet 文件获取最大交易日 (lake_max_date)；
2. 扫描通达信本地 .day 数据目录获取最大交易日 (tdx_max_date)；
3. 评估 L1 (TDX 相对当前交易日) 与 L2 (湖相对 TDX) 的两级滞后天数与交易日滞后。
=============================================================================
"""

import datetime
import os
from pathlib import Path
import struct
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

import pandas as pd

from ...shared.logger_factory import get_logger

if TYPE_CHECKING:
    from .storage_manager import StorageManager

logger = get_logger("StorageManager")


def format_date_val(val: Any) -> Optional[str]:
    """格式化日期值为标准 YYYY-MM-DD 字符串"""
    if val is None or pd.isna(val):
        return None
    if isinstance(val, (datetime.date, datetime.datetime, pd.Timestamp)):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    try:
        dt = pd.to_datetime(s)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


class FreshnessValidator:
    """
    数据新鲜度验证器
    提供 parquet 高效元数据最大日期解析、本地通达信 .day 最大日期探测以及两级 SLA 评估
    """

    def __init__(self, storage_manager: "StorageManager"):
        self.storage_manager = storage_manager

    @property
    def daily_dir(self) -> Path:
        return self.storage_manager.daily_dir

    def read_parquet_max_date(self, file_path: Path) -> Optional[str]:
        """从 parquet 文件中高效提取最大交易日"""
        try:
            import pyarrow.parquet as pq

            pf = pq.ParquetFile(str(file_path))
            if pf.num_row_groups > 0:
                rg = pf.metadata.row_group(pf.num_row_groups - 1)
                for i in range(rg.num_columns):
                    col = rg.column(i)
                    if "date" in col.path_in_schema and col.statistics and col.statistics.has_min_max:
                        d_str = format_date_val(col.statistics.max)
                        if d_str:
                            return d_str
        except Exception:
            pass

        try:
            df = pd.read_parquet(file_path, columns=["date"])
            if not df.empty and "date" in df.columns:
                max_val = df["date"].dropna().max()
                return format_date_val(max_val)
        except Exception as e:
            logger.warning(f"读取 parquet 日期失败 {file_path}: {e}")
            raise
        return None

    def find_tdx_max_date(
        self, tdx_dir: Optional[Union[str, Path]] = None
    ) -> Tuple[Optional[str], Optional[Path]]:
        """从通达信本地 .day 目录提取最大交易日"""
        resolved_dir: Optional[Path] = None
        if tdx_dir:
            cand = Path(tdx_dir)
            if cand.exists():
                resolved_dir = cand
        else:
            candidates = []
            env_vipdoc = os.environ.get("TDX_VIPDOC_DIR")
            if env_vipdoc:
                candidates.append(Path(env_vipdoc))
            env_tdx = os.environ.get("TDX_PATH")
            if env_tdx:
                candidates.append(Path(env_tdx))
            try:
                from ...shared.config_loader import ConfigLoader

                cfg = ConfigLoader().load_config()
                cfg_tdx = cfg.get("tdx", {}).get("path")
                if cfg_tdx:
                    candidates.append(Path(cfg_tdx))
            except Exception:
                pass
            candidates.extend([
                Path.home() / ".local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday",
                Path.home() / ".local/share/tdxcfv/drive_c/tc/vipdoc",
            ])
            for c in candidates:
                if c.exists():
                    resolved_dir = c
                    break

        if not resolved_dir or not resolved_dir.exists():
            return None, None

        day_files: List[Path] = []
        if (resolved_dir / "sh" / "lday").exists():
            day_files.extend(list((resolved_dir / "sh" / "lday").glob("*.day")))
            if (resolved_dir / "sz" / "lday").exists():
                day_files.extend(list((resolved_dir / "sz" / "lday").glob("*.day")))
        elif resolved_dir.is_dir():
            day_files.extend(list(resolved_dir.glob("*.day")))

        if not day_files:
            return None, resolved_dir

        anchors = {"sh600519.day", "sh000001.day", "sz000001.day", "sz399001.day"}
        candidates_list = [f for f in day_files if f.name.lower() in anchors]
        newest = sorted(day_files, key=lambda f: f.stat().st_mtime, reverse=True)[:20]
        for f in newest:
            if f not in candidates_list:
                candidates_list.append(f)

        dates: List[str] = []
        for f in candidates_list:
            try:
                s = f.stat().st_size
                if s >= 32 and s % 32 == 0:
                    with open(f, "rb") as fp:
                        fp.seek(s - 32)
                        d_int = struct.unpack("<I", fp.read(4))[0]
                        d_str = str(d_int)
                        if len(d_str) == 8 and d_str.isdigit():
                            dates.append(f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:]}")
            except Exception:
                continue

        return (max(dates) if dates else None), resolved_dir

    def validate_freshness(
        self,
        max_lag_days: int = 7,
        tdx_dir: Optional[Union[str, Path]] = None,
        as_of_date: Optional[Union[str, datetime.date, pd.Timestamp]] = None,
        sample_size: int = 50,
        check_tdx: bool = True,
        require_l1_fresh: bool = False,
    ) -> Dict[str, Any]:
        """扫描数据湖日线数据最近日期，并与上游通达信数据比对评估两级新鲜度。

        两级 SLA 架构 (R10):
        - L1 SLA: TDX 相对当前交易日的滞后 (通达信盘后行情获取人工/脚本步)
        - L2 SLA: 湖相对 TDX 的滞后 (本地 TDX .day 到 Parquet 数据湖同步步)

        Args:
            max_lag_days: L2 滞后天数容忍阈值 (默认 7 天)
            tdx_dir: 通达信本地 vipdoc 或 lday 目录 (可选，未指定时尝试自动发现)
            as_of_date: 比对基准日期 (可选，默认使用当前时间提供者日期)
            sample_size: 湖文件扫描抽样数量 (<=0 表示全量扫描，默认 50)
            check_tdx: 是否比对本地 TDX 上游数据 (默认 True)
            require_l1_fresh: 判定整体 is_fresh 时是否要求 L1 也新鲜 (默认 False，仅考核 L2)

        Returns:
            Dict: {
                "is_fresh": bool,
                "lake_max_date": str,
                "tdx_max_date": Optional[str],
                "l2_lag_days": int,
                "details": dict
            }
        """
        # 1. 确定基准日期 as_of_date
        if as_of_date is None:
            try:
                from ...shared.time_provider import get_time_provider

                as_of_obj = get_time_provider().today()
            except Exception:
                as_of_obj = datetime.date.today()
        elif isinstance(as_of_date, str):
            as_of_obj = datetime.date.fromisoformat(as_of_date[:10])
        elif isinstance(as_of_date, (datetime.datetime, pd.Timestamp)):
            as_of_obj = as_of_date.date()
        elif isinstance(as_of_date, datetime.date):
            as_of_obj = as_of_date
        else:
            as_of_obj = datetime.date.today()
        as_of_str = as_of_obj.strftime("%Y-%m-%d")

        # 2. 扫描数据湖日线 parquet 文件获取 lake_max_date
        read_errors: List[str] = []
        parquet_files: List[Path] = []
        if self.daily_dir.exists():
            parquet_files = [
                f for f in self.daily_dir.glob("*.parquet") if f.is_file() or f.exists()
            ]

        lake_empty = len(parquet_files) == 0
        lake_max_date = ""
        lake_dates: List[str] = []
        scanned_count = 0

        if not lake_empty:
            anchors = {
                "600519.SH.parquet",
                "000001.SZ.parquet",
                "601398.SH.parquet",
                "000858.SZ.parquet",
            }
            candidates: List[Path] = [f for f in parquet_files if f.name in anchors]
            if sample_size <= 0 or sample_size >= len(parquet_files):
                candidates = list(parquet_files)
            else:
                newest = sorted(
                    parquet_files, key=lambda f: f.stat().st_mtime, reverse=True
                )[:sample_size]
                for f in newest:
                    if f not in candidates:
                        candidates.append(f)

            scanned_count = len(candidates)
            read_func = getattr(
                self.storage_manager, "_read_parquet_max_date", self.read_parquet_max_date
            )
            for f in candidates:
                try:
                    d_str = read_func(f)
                    if d_str:
                        lake_dates.append(d_str)
                except Exception as e:
                    read_errors.append(f"{f.name}: {e}")

            if lake_dates:
                lake_max_date = max(lake_dates)
            else:
                lake_empty = True

        # 3. 扫描通达信本地 .day 获取 tdx_max_date (可选)
        tdx_max_date: Optional[str] = None
        resolved_tdx_path: Optional[Path] = None
        if check_tdx:
            find_func = getattr(
                self.storage_manager, "_find_tdx_max_date", self.find_tdx_max_date
            )
            tdx_max_date, resolved_tdx_path = find_func(tdx_dir)

        # 4. 计算两级滞后天数
        l1_lag_days: Optional[int] = None
        l2_lag_days: int = -1
        stale_reasons: List[str] = []

        if tdx_max_date:
            tdx_d = datetime.date.fromisoformat(tdx_max_date)
            l1_lag_days = max(0, (as_of_obj - tdx_d).days)
            if l1_lag_days > 1:
                stale_reasons.append(f"L1_TDX_STALE_{l1_lag_days}D")
                logger.warning(
                    f"TDX 上游数据停更/滞后: l1_lag={l1_lag_days}天, "
                    f"tdx_max_date={tdx_max_date}, as_of_date={as_of_str}"
                )

        if lake_empty or not lake_max_date:
            l2_lag_days = -1
            is_fresh = False
            stale_reasons.append("L2_LAKE_EMPTY")
            logger.warning("数据湖日线数据为空，SLA 判定不新鲜 (lake_empty=True)")
        else:
            lake_d = datetime.date.fromisoformat(lake_max_date)
            if tdx_max_date:
                tdx_d = datetime.date.fromisoformat(tdx_max_date)
                l2_lag_days = max(0, (tdx_d - lake_d).days)
            else:
                l2_lag_days = max(0, (as_of_obj - lake_d).days)

            l2_is_fresh = l2_lag_days <= max_lag_days
            if not l2_is_fresh:
                stale_reasons.append(
                    f"L2_LAG_EXCEEDED_{l2_lag_days}D_GT_{max_lag_days}D"
                )
                logger.warning(
                    f"数据湖滞后超阈值: l2_lag={l2_lag_days}天 (阈值={max_lag_days}天), "
                    f"lake_max_date={lake_max_date}, tdx_max_date={tdx_max_date}"
                )

            if require_l1_fresh and l1_lag_days is not None and l1_lag_days > 1:
                is_fresh = False
            else:
                is_fresh = l2_is_fresh

        # 5. 计算交易日滞后天数 (增强细节)
        l1_lag_trading: Optional[int] = None
        l2_lag_trading: Optional[int] = None
        try:
            from ..managers.trade_calendar_manager import TradeCalendarManager

            tcm = TradeCalendarManager()
            if tdx_max_date and as_of_str > tdx_max_date:
                cal1 = tcm.get_trade_calendar(tdx_max_date, as_of_str)
                if cal1 is not None and not cal1.empty and "trade_date" in cal1.columns:
                    l1_lag_trading = max(
                        0,
                        len(
                            cal1[
                                pd.to_datetime(cal1["trade_date"])
                                > pd.to_datetime(tdx_max_date)
                            ]
                        ),
                    )
            if lake_max_date:
                ref_date = tdx_max_date or as_of_str
                if ref_date > lake_max_date:
                    cal2 = tcm.get_trade_calendar(lake_max_date, ref_date)
                    if (
                        cal2 is not None
                        and not cal2.empty
                        and "trade_date" in cal2.columns
                    ):
                        l2_lag_trading = max(
                            0,
                            len(
                                cal2[
                                    pd.to_datetime(cal2["trade_date"])
                                    > pd.to_datetime(lake_max_date)
                                ]
                            ),
                        )
        except Exception:
            pass

        details: Dict[str, Any] = {
            "as_of_date": as_of_str,
            "lake_empty": lake_empty,
            "lake_dir": str(self.daily_dir),
            "lake_max_date": lake_max_date,
            "scanned_files_count": scanned_count,
            "tdx_dir": str(resolved_tdx_path) if resolved_tdx_path else None,
            "tdx_max_date": tdx_max_date,
            "l1_lag_days": l1_lag_days,
            "l2_lag_days": l2_lag_days,
            "l1_lag_trading_days": l1_lag_trading,
            "l2_lag_trading_days": l2_lag_trading,
            "l1_is_fresh": (l1_lag_days is None or l1_lag_days <= 1),
            "l2_is_fresh": (
                not lake_empty and l2_lag_days >= 0 and l2_lag_days <= max_lag_days
            ),
            "max_lag_days": max_lag_days,
            "stale_reasons": stale_reasons,
            "read_errors": read_errors,
        }

        return {
            "is_fresh": is_fresh,
            "lake_max_date": lake_max_date,
            "tdx_max_date": tdx_max_date,
            "l2_lag_days": l2_lag_days,
            "details": details,
        }
