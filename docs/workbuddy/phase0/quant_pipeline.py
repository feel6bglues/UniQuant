"""Phase 0 — 基本面因子效用实证化管线（可复用核心）。

设计目标（承接《基本面因子效用工程化工作计划》）：
- 复用 wb-finance-skill 的截面 Z-score 思路（factor_multi.zscore_cross_section），
  但 IC/IR、行业中性化、PIT、牛熊拆分、压力测试均在此自实现（factor_multi.py 不含这些）。
- 数据源：NeoData（自然语言金融搜索，自带凭证，实时）。
  财务(ROE/FCF/成长)来自「综合财务指标」；估值(PE/PB/EV/股息率+历史序列)来自「统一估值查询」；
  分红来自「分红派息详细」；价格序列来自「历史K线」。
- 注意：本模块对单只股票按"最新已公告"取值，严格 PIT（按发布日期对齐）需接入历史财报
  接口或 Tushare；PoC 阶段以"最新公告"近似，已在报告中标注。

仅依赖 pandas / numpy（managed venv）。
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------
# 1. NeoData 连接器（解析 markdown 表格 -> 结构化）
# ----------------------------------------------------------------------------

class NeoDataClient:
    def __init__(self, query_py: str, python_exe: str):
        self.query_py = query_py
        self.python_exe = python_exe

    def _run(self, nl: str, data_type: Optional[str] = None, retries: int = 3) -> Optional[dict]:
        import time
        last = None
        for attempt in range(retries):
            cmd = [self.python_exe, self.query_py, "--query", nl]
            if data_type:
                cmd += ["--data-type", data_type]
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            except Exception as e:  # noqa
                print(f"  [NeoData] 调用失败: {e}")
                return None
            txt = out.stdout
            s, e2 = txt.find("{"), txt.rfind("}")
            if s != -1 and e2 != -1:
                try:
                    last = json.loads(txt[s:e2 + 1])
                    if last and last.get("code") == "200" and last.get("suc"):
                        return last
                except Exception:
                    last = None
            if attempt < retries - 1:
                time.sleep(1.5)
        return last

    @staticmethod
    def _api_contents(resp: Optional[dict]) -> List[str]:
        if not resp:
            return []
        try:
            recalls = resp["data"]["apiData"]["apiRecall"]
            return [r.get("content", "") for r in recalls]
        except Exception:
            return []

    # ---- 财务指标 ----
    def financials(self, code: str) -> Dict[str, float]:
        """综合财务指标 -> {roe, fcf(元), fcf_yield_ev, growth_yoy(%)}。

        注：用 'ROE 和 市盈率 和 股息率' 这一验证可用措辞，能完整召回
        资产负债/现金流/盈利/运营/成长 五张表（'综合财务指标' 措辞子表不全）。
        """
        resp = self._run(f"{code} 2024年 ROE 和 市盈率 和 股息率", data_type="api")
        out = {"roe": np.nan, "fcf": np.nan, "fcf_yield_ev": np.nan, "growth_yoy": np.nan}
        for md in self._api_contents(resp):
            tables = _extract_tables(md)
            for hdr, rows in tables:
                if "加权净资产收益率ROE" in hdr:
                    out["roe"] = _cell(hdr, rows, "加权净资产收益率ROE")
                if "自由现金流量" in hdr:
                    out["fcf"] = _cell(hdr, rows, "自由现金流量")
                if "归母净利润同比" in hdr:
                    out["growth_yoy"] = _cell(hdr, rows, "归母净利润同比", pct=True)
        # FCF/EV 需要 EV：从估值拿
        val = self.valuation(code)
        ev_yi = val.get("ev_yi", np.nan)  # 亿元
        if not np.isnan(out["fcf"]) and not np.isnan(ev_yi) and ev_yi > 0:
            out["fcf_yield_ev"] = (out["fcf"] / 1e8) / ev_yi  # 自由现金流(元)/EV(亿元)
        return out

    # ---- 估值（含历史序列） ----
    def valuation(self, code: str) -> Dict[str, float]:
        """统一估值查询 -> {pe, pe_pct, pb, ev_yi, dy, hist_pe(list)}"""
        resp = self._run(f"{code} 当前滚动市盈率PE 市净率PB", data_type="api")
        out = {"pe": np.nan, "pe_pct": np.nan, "pb": np.nan,
               "ev_yi": np.nan, "dy": np.nan, "hist_pe": []}
        for md in self._api_contents(resp):
            tables = _extract_tables(md)
            for hdr, rows in tables:
                if "估值日期" in hdr and "扣非后滚动市盈率" in hdr:
                    for r in rows:
                        # 估值日期 | 静态PE | 动态PE | 扣非滚动PE | ... | 滚动股息率 | 企业价值(亿元) | PEG
                        pe = _col(r, hdr, "扣非后滚动市盈率（倍）")
                        dy = _col(r, hdr, "滚动股息率（%）")
                        ev = _col(r, hdr, "企业价值（亿元）")
                        if not np.isnan(pe):
                            out["hist_pe"].append(pe)
                        if not np.isnan(dy):
                            out["dy"] = dy
                        if not np.isnan(ev):
                            out["ev_yi"] = ev
                # 顶部摘要字段（PE 历史分位/ PB）
                m = re.search(r"\*\*滚动市盈率（倍）\*\*:\s*([\d.]+)", md)
                if m and np.isnan(out["pe"]):
                    out["pe"] = float(m.group(1))
                m2 = re.search(r"\*\*市盈率历史分位数（%）\*\*:\s*([\d.]+)", md)
                if m2:
                    out["pe_pct"] = float(m2.group(1))
                m3 = re.search(r"\*\*市净率（倍）\*\*:\s*([\d.]+)", md)
                if m3:
                    out["pb"] = float(m3.group(1))
        # 若历史序列非空，用最新 PE 覆盖摘要
        if out["hist_pe"]:
            out["pe"] = out["hist_pe"][0]
        return out

    # ---- 分红 ----
    def dividend(self, code: str) -> Dict[str, float]:
        """分红派息详细 -> {per10_latest(元)}"""
        resp = self._run(f"{code} 股息率 近一年分红", data_type="api")
        out = {"per10_latest": np.nan}
        for md in self._api_contents(resp):
            m = re.search(r"每10股派息\(元\)\s*\|\s*([\d.]+)", md)
            if m:
                out["per10_latest"] = float(m.group(1))
                break
        return out

    # ---- 月线价格 ----
    def monthly_close(self, code: str, start: str, end: str) -> pd.Series:
        """历史K线（月）-> 月末收盘 Series（index=YYYYMM）。主问法失败则尝试备用问法。"""
        def _parse(resp):
            closes = {}
            for md in self._api_contents(resp):
                tables = _extract_tables(md)
                for hdr, rows in tables:
                    if not any(k in hdr for k in ["K线归属时点", "交易日期", "日期", "收盘价"]):
                        continue
                    # 用子串定位列下标（避免 _num 对日期串 float 失败）
                    dt_idx = next((i for i, h in enumerate(hdr)
                                   if any(k in h for k in ["K线归属时点", "交易日期", "日期"])), None)
                    cl_idx = next((i for i, h in enumerate(hdr)
                                   if "收盘价" in h or "收盘" in h), None)
                    if dt_idx is None or cl_idx is None:
                        continue
                    for r in rows:
                        if dt_idx >= len(r) or cl_idx >= len(r):
                            continue
                        cl = _num(r[cl_idx])
                        ym = re.sub(r"\D", "", str(r[dt_idx]))[:6]
                        if len(ym) == 6 and not np.isnan(cl):
                            closes[int(ym)] = cl
            return closes
        resp = self._run(f"{code} {start}至{end} 月K线", data_type="api")
        closes = _parse(resp)
        if not closes:  # 备用问法
            resp2 = self._run(f"{code} 2025年至今 月线 不复权", data_type="api")
            closes = _parse(resp2)
        s = pd.Series(closes, name=code)
        s.index = s.index.astype(int)
        return s.sort_index()


# ----------------------------------------------------------------------------
# 2. markdown 表格解析工具
# ----------------------------------------------------------------------------

def _extract_tables(md: str) -> List[Tuple[List[str], List[List[str]]]]:
    """解析 markdown 表格，返回 [(header, [row, ...]), ...]。

    多表场景（同一 content 内被 '### 章节' 等非 | 行分隔的若干表）也能正确切分：
    遇到非表格行且有已收集数据行时，先结束当前表。
    """
    lines = md.splitlines()
    tables = []
    cur_h, cur_rows = None, []
    for ln in lines:
        s = ln.strip()
        if not s.startswith("|"):
            if cur_h is not None and cur_rows:
                tables.append((cur_h, cur_rows))
                cur_h, cur_rows = None, []
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        nonempty = [c for c in cells if c != ""]
        is_sep = len(nonempty) > 0 and all(re.fullmatch(r":?-+:?", c) for c in nonempty)
        if is_sep:
            continue
        if cur_h is None:
            cur_h = cells
        else:
            cur_rows.append(cells)
    if cur_h is not None and cur_rows:
        tables.append((cur_h, cur_rows))
    return tables


def _cell(header: List[str], rows: List[List[str]], key: str, pct: bool = False):
    """在表头找到含 key 的列（子串匹配，兼容'归母净利润同比' vs '归母净利润同比增长'），
    返回数据行该列数值（去逗号/百分号）。"""
    matches = [i for i, h in enumerate(header) if key in h]
    if not matches or not rows:
        return np.nan
    idx = matches[0]
    val = rows[0][idx] if idx < len(rows[0]) else ""
    return _num(val, pct)


def _col(row: List[str], header: List[str], key: str):
    matches = [i for i, h in enumerate(header) if key in h]
    if not matches:
        return np.nan
    idx = matches[0]
    return _num(row[idx]) if idx < len(row) else np.nan


def _num(s, pct: bool = False):
    if s is None:
        return np.nan
    s = str(s).replace(",", "").replace("%", "").replace("+", "").strip()
    if s in ("", "--", "暂无数据", "None", "nan"):
        return np.nan
    try:
        v = float(s)
        return v / 100.0 if pct else v
    except Exception:
        return np.nan


# ----------------------------------------------------------------------------
# 3. 因子计算
# ----------------------------------------------------------------------------

@dataclass
class FactorFrame:
    codes: List[str]
    roe: Dict[str, float] = field(default_factory=dict)
    ep: Dict[str, float] = field(default_factory=dict)        # 1/PE
    sue_proxy: Dict[str, float] = field(default_factory=dict)  # 归母净利润同比(%)
    fcf_yield: Dict[str, float] = field(default_factory=dict)  # FCF/EV
    dy: Dict[str, float] = field(default_factory=dict)          # 股息率(%)
    pe_pct: Dict[str, float] = field(default_factory=dict)      # 估值分位(%)

    def to_frame(self) -> pd.DataFrame:
        d = {
            "ROE": self.roe, "EP": self.ep, "SUE_proxy": self.sue_proxy,
            "FCF_yield": self.fcf_yield, "DY": self.dy, "PE_pct": self.pe_pct,
        }
        return pd.DataFrame(d)


def build_factor_frame(client: NeoDataClient, codes: List[str]) -> FactorFrame:
    ff = FactorFrame(codes=list(codes))
    for c in codes:
        print(f"  拉取 {c} ...", flush=True)
        fin = client.financials(c)
        val = client.valuation(c)
        div = client.dividend(c)
        ff.roe[c] = fin["roe"]
        ff.ep[c] = (1.0 / val["pe"]) if not np.isnan(val["pe"]) and val["pe"] > 0 else np.nan
        ff.sue_proxy[c] = fin["growth_yoy"]
        ff.fcf_yield[c] = fin["fcf_yield_ev"]
        # 股息率：优先滚动股息率；否则 每股分红/价格近似（价格用 PE×EPS 难取，用 EV 反推不稳健，留 NaN）
        ff.dy[c] = val["dy"] if not np.isnan(val["dy"]) else np.nan
        ff.pe_pct[c] = val["pe_pct"]
    return ff


# ----------------------------------------------------------------------------
# 4. IC / IR 引擎（自实现；factor_multi.py 不含）
# ----------------------------------------------------------------------------

def rank_ic(factor: pd.Series, fwd_ret: pd.Series) -> float:
    """截面 rank IC（因子值与前瞻收益的 Spearman 相关）。"""
    df = pd.concat([factor, fwd_ret], axis=1).dropna()
    if len(df) < 5:
        return np.nan
    return df.iloc[:, 0].rank().corr(df.iloc[:, 1].rank())


def zscore(series: pd.Series) -> pd.Series:
    s = series.astype(float)
    mu, sd = s.mean(), s.std()
    return (s - mu) / sd if sd and sd == sd and sd > 0 else s * 0.0


def rolling_ir(ic_series: pd.Series, window: int = 12) -> pd.Series:
    """滚动 IR = 窗口内 IC 均值 / IC 标准差。"""
    return ic_series.rolling(window).apply(
        lambda x: x.mean() / x.std(ddof=1) if x.std(ddof=1) > 0 else np.nan, raw=True
    )


def evaluate_factors(ff: FactorFrame, fwd_ret: pd.Series) -> pd.DataFrame:
    """对截面算各因子 rank IC，返回汇总。"""
    fac = ff.to_frame()
    rows = []
    for col in ["ROE", "EP", "SUE_proxy", "FCF_yield", "DY"]:
        ic = rank_ic(fac[col], fwd_ret)
        rows.append({
            "factor": col,
            "rankIC": round(ic, 4) if not np.isnan(ic) else np.nan,
            "effective": "✅" if (not np.isnan(ic) and abs(ic) > 0.03) else "⚠️样本不足/弱",
        })
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# 5. 牛熊状态 & 压力测试（框架，供 WS1 扩展）
# ----------------------------------------------------------------------------

def regime_label(index_close: pd.Series) -> str:
    """极简牛熊判定：20MA vs 250MA + 12M 收益。"""
    if len(index_close) < 250:
        return "⚪样本不足"
    ma20 = index_close.rolling(20).mean().iloc[-1]
    ma250 = index_close.rolling(250).mean().iloc[-1]
    ret12m = index_close.iloc[-1] / index_close.iloc[-250] - 1
    if ma20 > ma250 and ret12m > 0:
        return "🟢牛市"
    if ma20 < ma250 and ret12m < 0:
        return "🔴熊市"
    return "⚪震荡"


# 暴露给外部
__all__ = ["NeoDataClient", "FactorFrame", "build_factor_frame",
           "rank_ic", "zscore", "rolling_ir", "evaluate_factors",
           "regime_label", "_extract_tables"]
