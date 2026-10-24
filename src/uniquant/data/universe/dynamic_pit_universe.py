"""
动态点在时 (Point-in-Time, PIT) 股票池构建与合规初筛引擎 (Dynamic PIT Universe)
=============================================================================
核心职责 (消除回测幸存者偏差与未来函数):
1. 彻底拔除静态 105 股面板固化名单，建立动态、客观的 A 股全历史点在时股票池;
2. 依据权威 SSOT (data/all_stock_codes.csv) 对任意回测调仓日 (as_of_date) 精准筛选:
   - 上市有效性: ipoDate <= as_of_date < outDate (若 outDate 为空则仍未退市);
   - 排除次新股: 上市自然日满 min_listing_days (默认 365 天), 消除 IPO 炒作扰动;
   - 排除 ST/高风险警示标的: 剔除 *ST、ST、PT、退市前缀或标记标的;
   - 支持流动性初筛: 对接日均成交额 ADV 门禁;
3. 严格遵循只读原则，严禁写入或污染 data/all_stock_codes.csv。
=============================================================================
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd

from uniquant.shared.constants.path import STOCK_LIST_FILE
from uniquant.shared.logger_factory import get_logger

logger = get_logger("data.universe.dynamic_pit_universe")


class DynamicPointInTimeUniverse:
    """
    点在时动态股票池候选构建器
    """

    def __init__(
        self,
        metadata_path: Optional[str | Path] = None,
        default_min_listing_days: int = 365,
    ):
        self.metadata_path = Path(metadata_path) if metadata_path else STOCK_LIST_FILE
        self.default_min_listing_days = int(default_min_listing_days)
        self._df_meta: Optional[pd.DataFrame] = None
        self._load_metadata()

    def _normalize_symbol(self, raw_code: str) -> str:
        """归一化股票代码格式为 XXXXXX.SH / XXXXXX.SZ"""
        s = str(raw_code).strip()
        if "." in s:
            parts = s.split(".")
            if parts[0].lower() in ["sh", "sz"]:
                return f"{parts[1].zfill(6)}.{parts[0].upper()}"
            elif parts[1].lower() in ["sh", "sz"]:
                return f"{parts[0].zfill(6)}.{parts[1].upper()}"
        code_digits = "".join(ch for ch in s if ch.isdigit()).zfill(6)
        if code_digits.startswith(("6", "9")):
            return f"{code_digits}.SH"
        elif code_digits.startswith(("0", "2", "3")):
            return f"{code_digits}.SZ"
        elif code_digits.startswith(("4", "8")):
            return f"{code_digits}.BJ"
        return f"{code_digits}.SH"

    def _load_metadata(self) -> None:
        """加载全量股票元数据 SSOT 并完成类型与日期解析"""
        if not self.metadata_path.exists():
            raise FileNotFoundError(f"股票元数据真源文件不存在: {self.metadata_path}")

        # 只读方式读取，杜绝写操作
        df = pd.read_csv(self.metadata_path, encoding="utf-8")
        # 仅保留 A 股普通股票 (type == 1)
        df_stocks = df[df["type"] == 1].copy()

        df_stocks["symbol"] = df_stocks["code"].apply(self._normalize_symbol)
        df_stocks["code_digits"] = df_stocks["代码"].astype(str).str.zfill(6)
        df_stocks["name"] = df_stocks["name"].astype(str)
        df_stocks["ipo_dt"] = pd.to_datetime(df_stocks["ipoDate"], errors="coerce")
        df_stocks["out_dt"] = pd.to_datetime(df_stocks["outDate"], errors="coerce")
        df_stocks["status"] = pd.to_numeric(df_stocks["status"], errors="coerce").fillna(1).astype(int)

        self._df_meta = df_stocks
        logger.info(
            f"DynamicPointInTimeUniverse 已加载 {len(self._df_meta)} 只 A 股全历史标的元数据 "
            f"(在市: {sum(self._df_meta['status'] == 1)}, 历史退市: {sum(self._df_meta['status'] == 0)})"
        )

    def get_eligible_universe(
        self,
        as_of_date: str | pd.Timestamp,
        min_listing_days: Optional[int] = None,
        exclude_st: bool = True,
        adv_map: Optional[Dict[str, float]] = None,
        min_adv: float = 0.0,
    ) -> List[str]:
        """
        获取 as_of_date 当日客观合规的交易标的候选池
        
        Args:
            as_of_date: 点在时评估日期 (YYYY-MM-DD)
            min_listing_days: 排除次新股最小自然日要求 (默认 365 天)
            exclude_st: 是否剔除 *ST / ST / PT 风险警示标的
            adv_map: 标的 20 日日均成交额映射 (可选)
            min_adv: 最小日均成交额门槛 (元, 默认 0.0)
            
        Returns:
            List[str]: 格式为 ['000001.SZ', '600000.SH', ...] 的合规候选池
        """
        if self._df_meta is None:
            self._load_metadata()

        as_of_dt = pd.to_datetime(as_of_date)
        req_listing_days = min_listing_days if min_listing_days is not None else self.default_min_listing_days

        df = self._df_meta
        assert df is not None

        # 1. 上市状态判定: ipoDate <= as_of_date < outDate
        cond_listed = (df["ipo_dt"] <= as_of_dt) & (df["out_dt"].isna() | (df["out_dt"] > as_of_dt))

        # 2. 次新股过滤: as_of_date - ipoDate >= min_listing_days
        days_listed = (as_of_dt - df["ipo_dt"]).dt.days
        cond_seasoned = days_listed >= req_listing_days

        # 3. 风险警示 ST/退市过滤
        if exclude_st:
            cond_not_st = ~df["name"].str.contains(r"\*ST|ST|PT|退市|退", case=False, regex=True)
        else:
            cond_not_st = pd.Series(True, index=df.index)

        # 综合掩码
        mask = cond_listed & cond_seasoned & cond_not_st
        candidates = df.loc[mask, "symbol"].tolist()

        # 4. 流动性初筛 (若提供 ADV 数据)
        if adv_map and min_adv > 0:
            candidates = [sym for sym in candidates if adv_map.get(sym, 0.0) >= min_adv]

        return sorted(list(set(candidates)))

    def get_delisted_stocks_as_of(self, as_of_date: str | pd.Timestamp) -> List[str]:
        """获取截至 as_of_date 已经退市的股票列表"""
        if self._df_meta is None:
            self._load_metadata()
        as_of_dt = pd.to_datetime(as_of_date)
        df = self._df_meta
        assert df is not None
        mask = df["out_dt"].notna() & (df["out_dt"] <= as_of_dt)
        return sorted(df.loc[mask, "symbol"].tolist())

    def is_stock_eligible(
        self,
        symbol: str,
        as_of_date: str | pd.Timestamp,
        min_listing_days: Optional[int] = None,
        exclude_st: bool = True,
    ) -> bool:
        """单票点在时资格判定"""
        norm_sym = self._normalize_symbol(symbol)
        pool = set(
            self.get_eligible_universe(
                as_of_date=as_of_date,
                min_listing_days=min_listing_days,
                exclude_st=exclude_st,
            )
        )
        return norm_sym in pool

    def get_point_in_time_snapshot_stats(
        self,
        dates: List[str],
    ) -> pd.DataFrame:
        """
        生成多时期点在时股票池规模演化统计报表
        """
        records = []
        for d in dates:
            as_of_dt = pd.to_datetime(d)
            df = self._df_meta
            assert df is not None

            # 当日合法存续上市公司总数 (含次新与ST)
            total_active = sum((df["ipo_dt"] <= as_of_dt) & (df["out_dt"].isna() | (df["out_dt"] > as_of_dt)))
            # 累计已退市数量
            total_delisted = sum(df["out_dt"].notna() & (df["out_dt"] <= as_of_dt))
            # 最终合格投资池
            eligible = len(self.get_eligible_universe(d, min_listing_days=365, exclude_st=True))
            # 次新股拦截数
            sub_new = sum(
                (df["ipo_dt"] <= as_of_dt)
                & (df["out_dt"].isna() | (df["out_dt"] > as_of_dt))
                & ((as_of_dt - df["ipo_dt"]).dt.days < 365)
            )
            # ST 拦截数
            st_count = sum(
                (df["ipo_dt"] <= as_of_dt)
                & (df["out_dt"].isna() | (df["out_dt"] > as_of_dt))
                & df["name"].str.contains(r"\*ST|ST|PT|退市", case=False, regex=True)
            )

            records.append({
                "as_of_date": d,
                "total_listed_companies": total_active,
                "eligible_universe_size": eligible,
                "sub_new_excluded": sub_new,
                "st_risk_excluded": st_count,
                "cum_delisted_count": total_delisted,
            })

        return pd.DataFrame(records)
