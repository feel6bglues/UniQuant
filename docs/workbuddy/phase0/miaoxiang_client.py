"""Phase 0 — 妙想(MiaoXiang / 东方财富) 数据客户端。

取代 NeoData 作为批量结构化数据底座：
- 妙想返回结构化指标表（dataTableDTOList: 指标编码/名称/数值/日期/单位），
  不是 NeoData 那种易变的 markdown，因此可作为 WS1 全样本快照的可靠源。
- 接口刻意与 NeoDataClient 对齐（financials/valuation/dividend/monthly_close），
  但新增更贴合批量的 get_factor_panel / get_monthly_closes。

依赖：仅标准库 urllib（受管 venv 无需额外装包）。鉴权用环境变量 MX_APIKEY（header: apikey）。
"""
from __future__ import annotations
import os
import json
import time
import re
import urllib.request
import numpy as np
import pandas as pd

MX_API = "https://mkapi2.dfcfs.com/finskillshub/api/claw/query"


class MiaoXiangClient:
    def __init__(self, apikey: str | None = None, api: str = MX_API):
        self.apikey = apikey or os.environ.get("MX_APIKEY", "")
        if not self.apikey:
            raise RuntimeError("MX_APIKEY 未设置：请在环境变量或参数中提供妙想 API Key")
        self.api = api

    # ---------- 底层 ----------
    def query_raw(self, q: str, retries: int = 3) -> list:
        """单次自然语言查询 -> 解析后的表列表（每个表是一个 dict）。

        妙想免费接口在连续请求时偶发返回非正常结构（限流/瞬断），故加重试与间隔。
        """
        body = json.dumps({"toolQuery": q}).encode("utf-8")
        last_err = None
        for attempt in range(retries):
            try:
                req = urllib.request.Request(self.api, data=body, method="POST")
                req.add_header("Content-Type", "application/json")
                req.add_header("apikey", self.apikey)
                with urllib.request.urlopen(req, timeout=90) as r:
                    resp = json.loads(r.read().decode("utf-8"))
                data = (resp or {}).get("data") or {}
                dto = data.get("data") or {}
                tbl = dto.get("dataTableDTOList")
                if tbl is None:
                    # 结构异常（如限流），重试
                    last_err = "searchDataResultDTO 为空"
                    time.sleep(2.0 * (attempt + 1))
                    continue
                return json.loads(tbl) if isinstance(tbl, str) else (tbl or [])
            except Exception as e:  # noqa
                last_err = repr(e)
                time.sleep(2.0 * (attempt + 1))
        print(f"    ⚠️ query_raw 重试失败: {last_err}", flush=True)
        return []

    @staticmethod
    def _year_of(label: str) -> int | None:
        m = re.search(r"(\d{4})", str(label))
        return int(m.group(1)) if m else None

    @staticmethod
    def _norm_indicator(name: str) -> str | None:
        n = name or ""
        if "净资产收益率" in n or re.search(r"\bROE\b", n, re.I):
            return "roe"
        if "市盈率" in n or re.search(r"\bPE\b", n, re.I):
            return "pe"
        if "股息率" in n:
            return "dy"
        if "自由现金" in n:
            return "fcf"
        if "归母净利润同比" in n or "净利润同比" in n:
            return "sue"
        return None

    # ---------- 因子面板（多年，多指标） ----------
    def get_factor_panel(self, codes: list, start: int = 2020, end: int = 2024) -> pd.DataFrame:
        """对每只股票查询多年五因子，返回 (code, year) 多层索引 DataFrame：
        columns = roe, ep, dy, fcf, sue（缺失为 NaN）。"""
        records = []
        for code in codes:
            print(f"  [妙想] 因子面板 {code} ...", flush=True)
            q = (f"{code} {start}年至{end}年 每年 "
                 f"净资产收益率ROE 市盈率PE 股息率 企业自由现金流量 归母净利润同比增长率")
            try:
                tables = self.query_raw(q)
            except Exception as e:
                print(f"    ⚠️ 查询失败: {e}", flush=True)
                time.sleep(1.5)
                continue
            time.sleep(1.2)  # 避免连续请求限流
            # 仅取目标证券的表（跳过母公司等 1000xxxx.FXR）
            for tb in tables:
                if tb.get("code") != code:
                    continue
                rawT = tb.get("rawTable", {})
                nm = tb.get("nameMap", {})
                head = rawT.get("headName", [])
                for ind_code, vals in rawT.items():
                    if ind_code == "headName" or not isinstance(vals, list):
                        continue
                    fkey = self._norm_indicator(nm.get(ind_code, ind_code))
                    if fkey is None:
                        continue
                    for j, label in enumerate(head):
                        if j >= len(vals):
                            break
                        yr = self._year_of(label)
                        v = self._num(vals[j])
                        if yr is None or np.isnan(v):
                            continue
                        records.append({"code": code, "year": yr, "factor": fkey, "value": v})
        df = pd.DataFrame(records)
        if df.empty:
            return pd.DataFrame(columns=["roe", "ep", "dy", "fcf", "sue"])
        # 透视：code×year × factor → value
        panel = df.pivot_table(index=["code", "year"], columns="factor", values="value")
        # ep = 1/pe
        if "pe" in panel.columns:
            panel["ep"] = panel["pe"].apply(lambda x: 1.0 / x if pd.notna(x) and x > 0 else np.nan)
        for c in ["roe", "ep", "dy", "fcf", "sue"]:
            if c not in panel.columns:
                panel[c] = np.nan
        return panel[["roe", "ep", "dy", "fcf", "sue"]]

    # ---------- 月线收盘（用于前瞻收益） ----------
    def get_monthly_closes(self, codes: list, start: str = "2020年1月", end: str = "2025年12月") -> pd.DataFrame:
        """返回 (code, yyyymm) 多层索引的月末收盘 DataFrame。"""
        rows = []
        for code in codes:
            print(f"  [妙想] 月线 {code} ...", flush=True)
            q = f"{code} {start}至{end} 月线 收盘价"
            try:
                tables = self.query_raw(q)
            except Exception as e:
                print(f"    ⚠️ 查询失败: {e}", flush=True)
                time.sleep(1.5)
                continue
            time.sleep(1.2)  # 避免连续请求限流
            for tb in tables:
                if tb.get("code") != code:
                    continue
                rawT = tb.get("rawTable", {})
                nm = tb.get("nameMap", {})
                head = rawT.get("headName", [])
                # 找收盘价列
                ind_code = None
                for k in rawT:
                    if k == "headName":
                        continue
                    if "收盘" in nm.get(k, k):
                        ind_code = k
                        break
                if ind_code is None:
                    continue
                vals = rawT[ind_code]
                for j, label in enumerate(head):
                    if j >= len(vals):
                        break
                    ym = self._yyyymm(label)
                    v = self._num(vals[j])
                    if ym is None or np.isnan(v):
                        continue
                    rows.append({"code": code, "ym": ym, "close": v})
        df = pd.DataFrame(rows)
        if df.empty:
            return pd.DataFrame(columns=["close"])
        return df.set_index(["code", "ym"])["close"].sort_index()

    @staticmethod
    def _yyyymm(label: str) -> int | None:
        digits = re.sub(r"\D", "", str(label))
        if len(digits) >= 6:
            return int(digits[:6])
        return None

    @staticmethod
    def _num(s) -> float:
        if s is None:
            return np.nan
        s = str(s).replace(",", "").replace("%", "").replace("+", "").strip()
        if s in ("", "-", "--", "暂无数据", "None", "nan"):
            return np.nan
        try:
            return float(s)
        except Exception:
            return np.nan


# 暴露给外部
__all__ = ["MiaoXiangClient"]
