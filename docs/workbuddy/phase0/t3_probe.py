# -*- coding: utf-8 -*-
"""T3a 历史成分可行性探测: 找到 HS300 历史成分或退市股数据源
候选: 1) mootdx 是否含退市股/历史成分  2) 东财 datacenter 历史成分接口
      3) 中证官网成分历史  4) 市值代理可行性
"""
import sys, io, json, os, urllib.request, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import re

print("=== 探测1: mootdx 退市股/历史成分 ===", flush=True)
try:
    from mootdx.quotes import Quotes
    q = Quotes.factory(market="std", timeout=15)
    # 尝试退市板块
    for node in ("zq_zsts", "zq_tt", "delist"):
        try:
            df = q.stock_all()
            if df is not None:
                # 检查是否有退市标记
                codes = df["code"].astype(str).str.zfill(6)
                delist_cnt = codes[codes.str.startswith(("400", "420", "800"))].count()
                print(f"  stock_all: {len(df)} 行, 老三板类代码: {delist_cnt}", flush=True)
            break
        except Exception as e:
            print(f"  {node} 失败: {repr(e)[:80]}", flush=True)
except Exception as e:
    print(f"  mootdx 探测失败: {repr(e)[:100]}", flush=True)

print("\n=== 探测2: 东财历史成分接口 (HS300 历史成分) ===", flush=True)
try:
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get?"
           "reportName=RPT_INDEX_TS_COMPONENT&columns=SECURITY_CODE,SECURITY_NAME_ABBR,IN_DATE,OUT_DATE"
           "&filter=(INDEX_CODE%3D%22000300%22)&pageNumber=1&pageSize=10&source=WEB&client=WEB")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    d = json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8"))
    rows = (d.get("result") or {}).get("data") or []
    print(f"  返回 {len(rows)} 行", flush=True)
    if rows:
        print(f"  样例: {rows[0]}", flush=True)
        has_date = any("IN_DATE" in r or "OUT_DATE" in r for r in rows)
        print(f"  含进出日期字段: {has_date}  <== 若为True则支持历史成分重建!", flush=True)
except Exception as e:
    print(f"  东财探测失败: {repr(e)[:100]}", flush=True)

print("\n=== 探测3: 中证官网成分历史 ===", flush=True)
try:
    url = "https://www.csindex.com.cn/csindex-home/perf/index-perf?indexCode=000300"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", errors="ignore")
    print(f"  页面可访问: {len(raw)} 字节 (内容含成分下载入口?)", flush=True)
    print(f"  含 '成分' 关键词: {'成分' in raw}", flush=True)
except Exception as e:
    print(f"  中证官网探测失败: {repr(e)[:100]}", flush=True)

print("\n=== 探测4: 市值代理可行性 (当前成分+市值过滤近似历史大盘股) ===", flush=True)
try:
    import json as j
    import pandas as pd
    monthly = j.load(open("mx_fin_data/hs300_monthly.json"))
    # 用 2014 年末市值 top 300 近似当时的 HS300 (仅可行性评估)
    px_2014 = {code: {int(k): v for k, v in m.items()}.get(201412) for code, m in monthly.items()}
    from mootdx_client import MootdxClient
    c = MootdxClient()
    df = c.fetch_report("gpcw20141231.zip")
    shares = {}
    if len(df):
        df.index = df.index.astype(str).str.zfill(6)
        s = c._pick(df, "shares")
        shares = pd.to_numeric(s, errors="coerce").to_dict() if s is not None else {}
    mcaps = {code: px * shares.get(code, 0) for code, px in px_2014.items() if px and shares.get(code, 0)}
    import pandas as pd
    top300 = sorted(mcaps, key=mcaps.get, reverse=True)[:300]
    print(f"  2014 年末市值可算: {len(mcaps)} 只 (覆盖率 {len(mcaps)/len(px_2014)*100:.0f}%)", flush=True)
    print(f"  近似Top300 与当前HS300 交集: {len(set(top300) & set(j.load(open('mx_fin_data/hs300_codes.json'))))} 只", flush=True)
    print(f"  <== 市值代理可用性评估", flush=True)
except Exception as e:
    print(f"  市值代理探测失败: {repr(e)[:100]}", flush=True)

print("\n探测完成")
