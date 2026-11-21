"""tdxdata 在线数据源 — 通达信 2026-09 新版行情协议客户端。

背景与替代关系: 旧协议客户端 (pytdx/mootdx/tdxpy) 的 bars/quotes 命令自
2026-09 起被通达信服务端拒绝 (响应被截断为短错误包, ``MootdxOnlineSource``
因此恒返回空表); ``tdxdata`` 是针对新协议的适配库。2026-11-20 实测: 本源
日线与数据湖 raw 口径逐位一致 (600519 全历史 6047 根至 2001-08-27 IPO,
6044 重叠交易日 close/amount 差为 0)。

口径约定:
- ``bars()`` 返回 raw 未复权价; 复权走 ``fetch_xdxr`` + 现有
  ``CorporateActionAdjuster`` 链路 (与湖/gbbq 同构)。
- tdxdata ``vol`` 单位为手, 本源统一 ×100 转为股 (湖契约 volume=股)。
- 主源默认主机 101.35.121.35 历史最全; connect.cfg 东证节点可用但
  2003-2007 老历史段缺 4 根且有 10 日 0.01-0.98 元偏差, 仅作备用。

边界: ``get_price`` 冻结契约 (sources=("lake","mootdx_local")) 本轮未动,
本源作为独立在线通道接入 config (data_sources.sources.tdxdata_online)。
"""

from typing import Optional

import pandas as pd
import threading

from .base import DataSource
from ...shared.logger_factory import get_logger

logger = get_logger("TdxDataOnlineSource")

# TDX K 线 category 码: 9 = 日线
DAY_CATEGORY = 9
# 单页最大根数 (服务端协议上限), 与翻页步长一致
PAGE_SIZE = 800
# 翻页上限护栏: 800×30 = 24,000 根 ≈ 95 年交易日, 防服务端异常导致的失控翻页
MAX_PAGES = 30
# tdxdata vol 单位为手; 湖契约 volume=股
LOT_TO_SHARE = 100.0

# fetch_daily 输出列契约 (与 GET_PRICE_LAKE_COLUMNS 对齐的子集, code 附后)
DAILY_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "code"]

# gbbq 八列契约 (与 data/fq/gbbq.parquet / Step2b 冻结契约一致)
GBBQ_CONTRACT_COLUMNS = [
    "code", "market", "date", "category", "cash_div", "split_ratio", "rights_ratio", "rights_price",
]

# 分钟频率 → TDX K 线 category 码 (服务端分钟 vol 单位=股, 与日线的手不同, 见 fetch_minute)
MINUTE_CATEGORY = {"1min": 7, "5min": 0, "15min": 1, "30min": 2, "60min": 3}
MINUTE_COLUMNS = ["datetime", "open", "high", "low", "close", "volume", "amount", "code"]

# 实时快照解析列 (第二十四轮修正): prices 为抽样序列且**首元素语义不普适**
# (600519=昨收 1460.21 ✓; 600959=89088.477 垃圾值, 昨收实为 3.02) → 只保留
# 全样本可验证的 last, 不解析 prev_close/open (第二十三轮基于单标的外推, 系
# 伪回归, 已回退)。极值不完整 → 不伪造 high/low (Rule 4)。
REALTIME_COLUMNS = ["code", "market", "last", "series_points", "compressed"]


class TdxDataOnlineSource(DataSource):
    """tdxdata 新协议在线源 — 日线/实时/财务/分红 (公司行为) 在线通道。"""

    def __init__(self, host: Optional[str] = None, port: int = 7709):
        self._host = host
        self._port = port
        self._client = None
        # fetch_stocks_daily 走 16 线程池 → _get_client 需防并发双建连接
        self._lock = threading.Lock()

    def _get_client(self):
        """延迟初始化 tdxdata 客户端 (连接建立于首次取数, 双检锁防并发重建)。"""
        if self._client is None:
            with self._lock:
                if self._client is None:
                    from tdxdata import TdxClient

                    if self._host:
                        self._client = TdxClient(host=self._host, port=self._port)
                    else:
                        self._client = TdxClient()
                    self._client.connect()
                    logger.info(f"tdxdata 新协议客户端初始化成功 ({self._host or '默认主机'})")
        return self._client

    @staticmethod
    def _split_code(symbol: str) -> str:
        """'600519.SH' -> '600519'; market 交由 tdxdata 自行判定 (market=None)。"""
        return symbol.split(".")[0]

    def _fetch_all_rows(self, category: int, code: str, start_day: str) -> list:
        """翻页拉取直至覆盖 start_day (按 datetime 前十位日期比较, 页未满即停)。"""
        rows: list = []
        start = 0
        for _ in range(MAX_PAGES):
            page = self._get_client().bars(category, code, start=start, count=PAGE_SIZE)
            if not page:
                break
            rows.extend(page)
            last_day = str(page[-1].get("datetime", ""))[:10]
            start += len(page)
            if len(page) < PAGE_SIZE or last_day <= start_day:
                break
        return rows

    def _fetch_all_daily_rows(self, code: str, start_date: str) -> list:
        """日线翻页 (委托通用翻页器)。"""
        return self._fetch_all_rows(DAY_CATEGORY, code, str(start_date))

    def fetch_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """拉取 [start_date, end_date] 区间 raw 日线 (volume 已转股)。"""
        try:
            code = self._split_code(symbol)
            rows = self._fetch_all_daily_rows(code, str(start_date))
            if not rows:
                logger.warning(f"未获取到 {symbol} 的日线数据")
                return pd.DataFrame()

            df = pd.DataFrame(rows).rename(columns={"datetime": "date"})
            df["volume"] = df["vol"].astype(float) * LOT_TO_SHARE
            df["date"] = pd.to_datetime(df["date"])
            df["code"] = symbol
            df = df[DAILY_COLUMNS].sort_values("date").drop_duplicates("date", keep="last")

            start = pd.to_datetime(start_date)
            end = pd.to_datetime(end_date)
            df = df[(df["date"] >= start) & (df["date"] <= end)].reset_index(drop=True)
            logger.info(f"成功获取 {symbol} 日线数据，共 {len(df)} 条")
            return df
        except Exception as e:
            logger.error(f"获取 {symbol} 日线数据失败: {e}")
            return pd.DataFrame()

    def fetch_minute(
        self,
        symbol: str,
        frequency: str = "5min",
        start_dt: Optional[str] = None,
        end_dt: Optional[str] = None,
    ) -> pd.DataFrame:
        """拉取分钟线 (1/5/15/30/60 分钟), 翻页语义与 fetch_daily 一致。

        ⚠️ 量纲实测 (2026-11-21): 服务端分钟 bar 的 ``vol`` 已是**股**
        (amount/(close*vol) 比值=1.00), 与日线的手(×100=股)不同 → 本方法
        **不做** ×100 换算。在线深度受服务端保留期限制 (5 分钟约 2 个月,
        1 分钟更短), 仅够近期增量, 历史分钟归档仍需湖快照。
        """
        category = MINUTE_CATEGORY.get(str(frequency).lower())
        if category is None:
            raise ValueError(f"未知分钟频率 {frequency!r}; 支持: {sorted(MINUTE_CATEGORY)}")
        try:
            code = self._split_code(symbol)
            start_day = str(start_dt)[:10] if start_dt else "1990-01-01"
            rows = self._fetch_all_rows(category, code, start_day)
            if not rows:
                logger.warning(f"未获取到 {symbol} 的 {frequency} 分钟数据")
                return pd.DataFrame()

            df = pd.DataFrame(rows)
            df["datetime"] = pd.to_datetime(df["datetime"])
            df["code"] = symbol
            # 服务端字段名 vol → volume; 分钟 vol 已是股, 仅改名不缩放
            df = df.rename(columns={"vol": "volume"})
            df = df[MINUTE_COLUMNS].sort_values("datetime").drop_duplicates("datetime", keep="last")

            start = pd.to_datetime(start_dt) if start_dt else None
            end = pd.to_datetime(end_dt) if end_dt else None
            if start is not None:
                df = df[df["datetime"] >= start]
            if end is not None:
                df = df[df["datetime"] <= end]
            df = df.reset_index(drop=True)
            logger.info(f"成功获取 {symbol} {frequency} 分钟数据，共 {len(df)} 条")
            return df
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"获取 {symbol} {frequency} 分钟数据失败: {e}")
            return pd.DataFrame()

    def fetch_real_time(self, symbol: Optional[str] = None) -> pd.DataFrame:
        """获取单标的实时快照并解析 (第二十四轮修正)。

        snap 原始结构实测: ``last`` = 最新价 (12/12 抽样标的与日线收盘逐位
        一致); ``prices`` 为抽样序列 (茅台一个交易日 62 点), **首元素语义不
        普适** — 600519 prices[0]=昨收 1460.21, 但 600959 prices[0]=89088.477
        (垃圾值, 昨收实为 3.02) → 第二十三轮 "prices[0]=昨收 / [1]=今开" 的
        语义外推系**伪回归**, 已回退: 本方法只输出 ``last``, 不解析
        prev_close/open, 不伪造 high/low (Rule 4)。``market`` 为新协议自带
        字段, 语义未定 → 原样透传不解释。
        """
        if not symbol:
            logger.warning("获取全市场实时数据暂不支持，请指定股票代码")
            return pd.DataFrame()
        try:
            snap = self._get_client().snap(self._split_code(symbol))
            if not snap:
                logger.warning(f"未获取到 {symbol} 的实时快照")
                return pd.DataFrame()
            row = {
                "code": symbol,
                "market": snap.get("market"),
                "last": snap.get("last"),
                "series_points": len(snap.get("prices") or []),
                "compressed": snap.get("compressed"),
            }
            df = pd.DataFrame([row], columns=REALTIME_COLUMNS)
            logger.info(f"成功获取实时数据: {symbol} last={row['last']}")
            return df
        except Exception as e:
            logger.error(f"获取实时数据失败: {e}")
            return pd.DataFrame()

    def fetch_market_cap(self, symbol: str) -> float:
        """总股本 (finance.zongguben, 股) × 最新收盘价; 失败返回 0.0。"""
        try:
            code = self._split_code(symbol)
            fin = self._get_client().finance(code)
            shares = float(fin.get("zongguben") or 0.0)
            page = self._get_client().bars(DAY_CATEGORY, code, start=0, count=1)
            if shares <= 0.0 or not page:
                logger.warning(f"{symbol} 市值要素缺失 (shares={shares})")
                return 0.0
            last_close = float(page[-1]["close"])
            return shares * last_close
        except Exception as e:
            logger.error(f"获取 {symbol} 市值失败: {e}")
            return 0.0

    def fetch_finance(self, symbol: str) -> dict:
        """最新报告期财务快照 (F10 式 40 字段, 含 zongguben/net_profit 等)。"""
        try:
            return self._get_client().finance(self._split_code(symbol))
        except Exception as e:
            logger.error(f"获取 {symbol} 财务数据失败: {e}")
            return {}

    def fetch_xdxr(self, symbol: str) -> list:
        """分红送配 (公司行为) 记录 — 在线替代本地 gbbq/xdxr 通道。"""
        try:
            return self._get_client().xdxr(self._split_code(symbol))
        except Exception as e:
            logger.error(f"获取 {symbol} 分红数据失败: {e}")
            return []

    def fetch_xdxr_as_gbbq(self, symbol: str) -> pd.DataFrame:
        """xdxr 记录 → gbbq 八列契约 (code/market/date/category/cash_div/
        split_ratio/rights_ratio/rights_price)。

        字段映射经 2026-11-20 逐位实测 (5 标的 170 事件, 全 category=1,
        fenhong/songzhuangu/peigu/peigujia 与 data/fq/gbbq.parquet 四字段
        差为 0, 单位同为每10股); 其余 category 同表同字段直通。
        """
        try:
            rows = self._get_client().xdxr(self._split_code(symbol))
            df = pd.DataFrame(
                [
                    {
                        "code": str(r.get("code", "")).zfill(6),
                        "market": r.get("market"),
                        "date": int(r.get("date")),
                        "category": r.get("category"),
                        "cash_div": float(r.get("fenhong") or 0.0),
                        "split_ratio": float(r.get("songzhuangu") or 0.0),
                        "rights_ratio": float(r.get("peigu") or 0.0),
                        "rights_price": float(r.get("peigujia") or 0.0),
                    }
                    for r in rows
                ],
                columns=GBBQ_CONTRACT_COLUMNS,
            )
            return df.sort_values("date").reset_index(drop=True)
        except Exception as e:
            logger.error(f"获取 {symbol} gbbq 契约数据失败: {e}")
            return pd.DataFrame(columns=GBBQ_CONTRACT_COLUMNS)

    def get_capabilities(self) -> dict:
        """返回数据源能力 (financial=最新快照; 历史逐季序列仍需湖)。"""
        return {
            "offline": False,
            "daily": True,
            "minute": False,
            "realtime": True,
            "financial": True,
        }

    def close(self):
        """关闭连接"""
        self._client = None
        logger.info("tdxdata 在线行情客户端已关闭")
