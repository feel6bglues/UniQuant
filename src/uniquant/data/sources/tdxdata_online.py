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

    def _fetch_all_daily_rows(self, code: str, start_date: str) -> list:
        """翻页拉取直至覆盖 start_date (页未满或已越过起点即停)。"""
        rows: list = []
        start = 0
        for _ in range(MAX_PAGES):
            page = self._get_client().bars(DAY_CATEGORY, code, start=start, count=PAGE_SIZE)
            if not page:
                break
            rows.extend(page)
            last_day = str(page[-1].get("datetime", ""))[:10]
            start += len(page)
            if len(page) < PAGE_SIZE or last_day <= start_date:
                break
        return rows

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

    def fetch_real_time(self, symbol: Optional[str] = None) -> pd.DataFrame:
        """获取单标的实时快照 (snap); 全市场扫描暂不支持。"""
        if not symbol:
            logger.warning("获取全市场实时数据暂不支持，请指定股票代码")
            return pd.DataFrame()
        try:
            snap = self._get_client().snap(self._split_code(symbol))
            if not snap:
                logger.warning(f"未获取到 {symbol} 的实时快照")
                return pd.DataFrame()
            df = pd.DataFrame([snap])
            df["code"] = symbol
            logger.info(f"成功获取实时数据，共 {len(df)} 条")
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
