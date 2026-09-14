# -*- coding: utf-8 -*-
"""MootdxClient: 基于 mootdx 的确定性批量数据源。
行情: Quotes.factory()->StdQuotes.bars (frequency=9日线/6月线)
财报: Financial 下载 gpcwYYYYMMDD.zip (全 A 单期) -> Financial.to_df (中文表头)

对齐 NeoDataClient/MiaoXiangClient 的因子接口, 供 quant_pipeline IC/IR 引擎直接使用。
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd


class MootdxClient:
    """mootdx 封装: 月线行情 + 全 A 财报因子。"""

    FREQ_DAY = 9
    FREQ_MON = 6

    # gpcw 字段名 -> 因子 (字段在财报包中可能有多处, 用子串匹配取第一个命中)
    FIELD = {
        "roe": "加权净资产收益率(每股指标)",          # 茅台 36.02 与妙想一致
        "np": "归属于母公司所有者的净利润",           # 净利润 (元)
        "np_prev": "归属于母公司所有者的净利润",      # 同比计算用
        "ocf": "经营活动产生的现金流量净额",          # 经营现金流 (元)
        "capex": "购建固定资产、无形资产和其他长期资产支付的现金",  # 资本支出 (元)
        "fcf_ps": "每股企业自由现金流",                # 企业自由现金流/股
        "eps": "基本每股收益",                        # EP 分子
        "shares": "总股本",                           # 股本 (股)
        "np_gr": "净利润增长率(%)",                    # SUE 参考
        "equity": "所有者权益（或股东权益）合计",       # 净资产 (元)
        "assets": "总资产",                           # 总资产 (元)
        "sales": "营业收入",                          # 营收 (元)
        "dividend_paid": "分配股利、利润或偿付利息支付的现金",  # 分红近似 (元)
    }

    def __init__(self, fin_dir: str = "mx_fin_data", timeout: int = 20):
        self.fin_dir = Path(fin_dir)
        self.fin_dir.mkdir(exist_ok=True)
        self._quotes = None
        self._financial = None
        self.timeout = timeout

    # ---------- 行情 ----------
    def quotes(self):
        if self._quotes is None:
            from mootdx.quotes import Quotes
            self._quotes = Quotes.factory(market="std", timeout=self.timeout)
        return self._quotes

    def monthly_closes(self, symbol: str, start: int = 0, offset: int = 300) -> dict:
        """月线收盘价 -> {YYYYMM: close}。symbol 如 '600519' (6位数字)。"""
        out = {}
        for attempt in range(3):
            try:
                df = self.quotes().bars(symbol=symbol, frequency=self.FREQ_MON, start=start, offset=offset)
                if df is not None and len(df):
                    for _, r in df.iterrows():
                        dt = r.get("datetime")
                        if dt is None:
                            continue
                        ym = re.sub(r"\D", "", str(dt))[:6]
                        if len(ym) == 6:
                            out[int(ym)] = float(r["close"])
                    return out
            except Exception as e:
                if attempt == 2:
                    print(f"    ⚠️ {symbol} 月线失败: {e}", flush=True)
                time.sleep(1.5)
        return out

    # ---------- 财报 ----------
    def financial(self):
        if self._financial is None:
            from mootdx.financial.financial import Financial
            self._financial = Financial()
        return self._financial

    def list_reports(self) -> list:
        """财报目录: [{filename, hash, filesize}, ...] 按文件名倒序。"""
        from mootdx.financial.financial import FinancialList
        fl = FinancialList()
        files = fl.fetch_and_parse()
        return sorted(files, key=lambda x: x["filename"], reverse=True)

    def download_report(self, filename: str) -> Path:
        """下载单期财报 zip 到 fin_dir (若已存在则跳过)。"""
        target = self.fin_dir / filename
        if target.exists() and target.stat().st_size > 1000:
            return target
        self.financial().content(filename=filename, downdir=str(self.fin_dir))
        return target

    def parse_report(self, filename: str) -> pd.DataFrame:
        """解析单期财报 zip -> DataFrame (index=code字符串, 585列中文)。"""
        target = self.download_report(filename)
        if target.exists() and target.stat().st_size > 1000:
            from mootdx.financial.financial import FinancialReader
            df = FinancialReader.to_data(str(target), header="zh")
            df.index = df.index.astype(str)
            return df
        return pd.DataFrame()

    def fetch_report(self, filename: str) -> pd.DataFrame:
        """下载+解析一步到位 (带本地缓存)。"""
        cache = self.fin_dir / (filename.replace(".zip", ".csv"))
        if cache.exists():
            df = pd.read_csv(cache, index_col=0, dtype=str)
            return df
        df = self.parse_report(filename)
        if len(df):
            df.to_csv(cache, encoding="utf-8-sig")
        return df

    # ---------- 因子构建 ----------
    def _pick(self, df: pd.DataFrame, key: str):
        """取字段列: 优先精确名, 否则子串匹配。返回 Series 或 None。
        注意 gpcw 存在重复列名 -> df[name] 返回 DataFrame, 取第一列。"""
        cols = list(df.columns)
        name = self.FIELD.get(key)
        if name is None:
            return None

        def _first(s):
            if s is None:
                return None
            if isinstance(s, pd.DataFrame):
                s = s.iloc[:, 0]
            return s

        if name in cols:
            return _first(df[name])
        for c in cols:
            if name in c:
                return _first(df[c])
        return None

    def factor_snapshot(self, df: pd.DataFrame, prices: dict | None = None) -> pd.DataFrame:
        """单期财报 DataFrame -> 因子截面 (index=code)。
        roe: 加权净资产收益率(每股指标)
        ep:  eps / 期未价格 (需 prices: {code: close})
        sue: 净利润同比 -> 截面标准化 (此处先给原值, 标准化由引擎做)
        fcf: 经营现金流 - 资本支出, /总市值(用价格*股本) -> FCF yield
        dy:  分红近似 / 总市值
        """
        out = pd.DataFrame(index=df.index)
        for fk in ["roe", "np", "ocf", "capex", "fcf_ps", "eps", "shares", "np_gr", "equity", "assets", "sales", "dividend_paid"]:
            s = self._pick(df, fk)
            out[fk] = pd.to_numeric(s, errors="coerce") if s is not None else np.nan
        # 派生因子
        eps = out["eps"]
        shares = out["shares"]
        np_ = out["np"]
        ocf = out["ocf"]
        capex = out["capex"]
        div_paid = out["dividend_paid"]
        out["fcf"] = ocf - capex.fillna(0)          # 绝对 FCF (元)
        out["fcf_ps2"] = out["fcf"] / shares.replace(0, np.nan)  # FCF/股
        if prices:
            px = pd.Series(prices, dtype=float)
            px = px.reindex(out.index)
            mcap = shares * px
            out["ep"] = eps / px                     # 盈利收益率
            out["fcfy"] = out["fcf"] / mcap.replace(0, np.nan)   # FCF yield
            out["dy"] = div_paid / mcap.replace(0, np.nan)        # 分红收益率(近似)
            out["bp"] = out["equity"] / mcap.replace(0, np.nan)   # 账面市值比
        return out

    def factor_panel(self, periods: list[str], prices_map: dict | None = None,
                     codes: list | None = None) -> pd.DataFrame:
        """多期因子面板: index=[code, period], 列=因子。periods 如 ['20101231', '20111231', ...]"""
        frames = []
        for p in periods:
            fn = f"gpcw{p}.zip"
            print(f"  拉取 {fn} ...", flush=True)
            df = self.fetch_report(fn)
            if not len(df):
                print(f"    ⚠️ {fn} 无数据", flush=True)
                continue
            px = {}
            if prices_map:
                px = {c: prices_map.get(c, {}).get(int(p[:4])) for c in df.index}
                px = {k: v for k, v in px.items() if v}
            snap = self.factor_snapshot(df, px)
            snap["period"] = p
            frames.append(snap)
        panel = pd.concat(frames)
        if codes:
            panel = panel[panel.index.isin(codes)]
        return panel


if __name__ == "__main__":
    c = MootdxClient()
    # 快速自检: 拉一期 + 因子
    df = c.fetch_report("gpcw20231231.zip")
    print("2023 年报:", df.shape)
    snap = c.factor_snapshot(df, {"600519": 1600.0, "000858": 130.0})
    print(snap.loc[["600519", "000858"], ["roe", "np", "fcf", "eps", "shares", "ep", "fcfy", "dy", "bp"]])
