# -*- coding: utf-8 -*-
"""T35v2 核心持仓池日线分页拉取 (修复: mootdx 单次日线上限 ~800 条)
分页 start=0,800,1600,2400 拼接 -> 覆盖 2014-2026
断点续传: 已有数据但最早日期 > 20140101 的股票补拉历史页
"""
import sys, io, json, os, time, threading
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from concurrent.futures import ThreadPoolExecutor, as_completed
from mootdx.quotes import Quotes

pool = json.load(open("mx_fin_data/core_pool_codes.json"))
OUT = "mx_fin_data/core_pool_daily.json"
data = json.load(open(OUT)) if os.path.exists(OUT) else {}
print(f"池 {len(pool)} 只 | 已有 {len(data)} 只", flush=True)

# 检查已有数据覆盖
need_pages = {}
for code, dd in data.items():
    if dd:
        earliest = min(dd.keys())
        need = 0 if earliest <= "20140101" else (4 if earliest > "20160501" else 2)
        if need > 0:
            need_pages[code] = need
todo = [c for c in pool if c not in data] + list(need_pages.keys())
print(f"待处理: {len(todo)} 只 (全新 {len([c for c in pool if c not in data])} + 补历史 {len(need_pages)})", flush=True)

_local = threading.local()
def get_qc():
    if not hasattr(_local, "qc"):
        _local.qc = Quotes.factory(market="std", timeout=20)
    return _local.qc

def pull_full(code):
    """分页拉全历史, 返回 {date: {o,h,l,c,v,a}}"""
    qc = get_qc()
    merged = {}
    for attempt in range(3):
        try:
            for start in (0, 800, 1600, 2400):
                df = qc.bars(symbol=code, frequency=9, start=start, offset=800)
                if df is None or len(df) == 0:
                    break
                for _, r in df.iterrows():
                    dt = str(r["datetime"]).replace("-", "")[:8]
                    if len(dt) != 8:
                        continue
                    merged[dt] = {"o": float(r["open"]), "h": float(r["high"]),
                                  "l": float(r["low"]), "c": float(r["close"]),
                                  "v": float(r["vol"]) if r["vol"] else 0.0,
                                  "a": float(r["amount"]) if r["amount"] else 0.0}
                if str(df.iloc[0]["datetime"])[:4] <= "2013":
                    break  # 已到 2013
                time.sleep(0.1)
            return code, merged
        except Exception:
            time.sleep(1.0 * (attempt + 1))
    return code, None

t0 = time.time()
with ThreadPoolExecutor(max_workers=12) as ex:
    futs = {ex.submit(pull_full, c): c for c in todo}
    for i, fut in enumerate(as_completed(futs)):
        code, out = fut.result()
        if out:
            data[code] = out
        if (i + 1) % 100 == 0:
            json.dump(data, open(OUT, "w"))
            el = (time.time() - t0) / 60
            n_rec = sum(len(dd) for dd in data.values())
            print(f"  [{i+1}/{len(todo)}] {len(data)} 只 | {n_rec/1e6:.1f}M 记录 | {el:.1f}min", flush=True)
json.dump(data, open(OUT, "w"))
# 覆盖核验
earliest = min((min(dd.keys()) for dd in data.values() if dd), default="none")
print(f"DONE: {len(data)} 只 | 最早日期 {earliest} | {(time.time()-t0)/60:.1f}min", flush=True)
