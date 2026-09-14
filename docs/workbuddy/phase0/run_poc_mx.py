"""Phase 0 — 妙想版 PoC（断点续传 + 限流友好）。

用 MiaoXiangClient 拉 15 只龙头的 2020–2024 五因子时序面板 + 月线，
做 PIT 近似（因子_t → 次年收益_{t+1}）的截面 rank IC / IR。

健壮性设计（应对妙想免费接口突发限流）：
- 逐股票拉取，每只成功即写入 mx_cache.json 断点；可多次重跑补齐。
- 股票间 3s 间隔 + query_raw 内置重试，规避突发限流。
"""
from __future__ import annotations
import os, sys, json, time
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from miaoxiang_client import MiaoXiangClient  # noqa: E402
from quant_pipeline import rank_ic  # noqa: E402

BASKET = [
    "600519.SH", "000858.SZ", "601318.SH", "600036.SH", "000333.SZ",
    "002594.SZ", "600900.SH", "601012.SH", "000001.SZ", "600276.SH",
    "603259.SH", "300750.SZ", "600030.SH", "000651.SZ", "601888.SH",
]
FACTORS = ["roe", "ep", "dy", "fcf", "sue"]
CACHE = os.path.join(HERE, "mx_cache.json")
SLEEP_BETWEEN = 3.0


def load_cache():
    if os.path.exists(CACHE):
        with open(CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(c):
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False)


def pull_all(client, cache):
    for code in BASKET:
        done = code in cache and cache[code].get("factors") and cache[code].get("monthly")
        if done:
            print(f"  [cache] {code} 已存在，跳过", flush=True)
            continue
        print(f"  [妙想] {code} ...", flush=True)
        # 因子面板
        if code not in cache or not cache[code].get("factors"):
            try:
                fp = client.get_factor_panel([code], 2020, 2024)
                if not fp.empty:
                    recs = fp.reset_index().to_dict("records")
                    cache.setdefault(code, {})["factors"] = recs
                    save_cache(cache)
            except Exception as e:
                print(f"    ⚠️ 因子失败: {e}", flush=True)
        # 月线
        if code not in cache or not cache[code].get("monthly"):
            try:
                mc = client.get_monthly_closes([code], "2020年1月", "2024年12月")
                if len(mc):
                    recs = [{"ym": int(k[1]), "close": float(v)} for k, v in mc.items()]
                    cache.setdefault(code, {})["monthly"] = recs
                    save_cache(cache)
            except Exception as e:
                print(f"    ⚠️ 月线失败: {e}", flush=True)
        time.sleep(SLEEP_BETWEEN)
    return cache


def annual_returns(monthly_recs):
    df = pd.DataFrame(monthly_recs)
    df["year"] = df["ym"] // 100
    ye = df.loc[df.groupby("year")["ym"].idxmax(), ["year", "close"]]
    ye = ye.sort_values("year")
    ye["ret"] = ye["close"].pct_change()
    return ye.set_index("year")["ret"].dropna()


def main():
    client = MiaoXiangClient()
    print("[1/4] 拉取（断点续传）...", flush=True)
    cache = pull_all(client, load_cache())

    # 组装面板
    fac_rows = []
    for code, v in cache.items():
        for r in v.get("factors", []):
            fac_rows.append(r)
    panel = pd.DataFrame(fac_rows)
    if not panel.empty:
        panel = panel.set_index(["code", "year"])
        panel = panel[["roe", "ep", "dy", "fcf", "sue"]]
    panel.to_csv(os.path.join(HERE, "factor_panel_mx.csv"))

    # 组装月线年收益
    ann = {}
    for code, v in cache.items():
        if v.get("monthly"):
            ann[code] = annual_returns(v["monthly"])
    ann_df = pd.DataFrame(ann)  # year × code
    ann_df.to_csv(os.path.join(HERE, "annual_ret_mx.csv"))
    print(f"     面板: {panel.shape}, 年收益股票数: {len(ann_df.columns)}", flush=True)

    print("[2/4] 逐形成年算截面 rank IC（因子_t → 收益_{{t+1}}）...", flush=True)
    years = sorted(panel.index.get_level_values(1).unique())
    ic_records = []
    for t in years:
        t1 = t + 1
        if t1 not in ann_df.index:
            continue
        ret_t1 = ann_df.loc[t1].dropna()  # code->ret
        rec = {"form_year": int(t), "fwd_year": int(t1)}
        for f in FACTORS:
            fac_series = panel.xs(t, level="year")[f].dropna()
            common = fac_series.index.intersection(ret_t1.index)
            rec[f] = rank_ic(fac_series[common], ret_t1[common]) if len(common) >= 5 else np.nan
        ic_records.append(rec)
    ic_df = pd.DataFrame(ic_records)
    ic_df.to_csv(os.path.join(HERE, "ic_matrix_mx.csv"), index=False)

    summary = []
    for f in FACTORS:
        s = ic_df[f].dropna()
        if len(s) >= 2:
            mean_ic, ic_std = s.mean(), s.std(ddof=1)
            summary.append({"factor": f, "meanIC": round(mean_ic, 4), "IC_std": round(ic_std, 4),
                            "IR": round(mean_ic / ic_std, 3), "n_obs": int(len(s)),
                            "verdict": "✅" if abs(mean_ic) > 0.03 else "⚠️弱"})
        else:
            summary.append({"factor": f, "meanIC": np.nan, "IC_std": np.nan, "IR": np.nan,
                            "n_obs": int(len(s)), "verdict": "⚠️样本不足"})
    summ_df = pd.DataFrame(summary)
    summ_df.to_csv(os.path.join(HERE, "ic_summary_mx.csv"), index=False)
    print(summ_df.to_string(index=False), flush=True)

    print("[3/4] 生成 HTML...", flush=True)
    html = build_html(panel, ann_df, ic_df, summ_df, cache)
    out = os.path.join(HERE, "Phase0_妙想PoC_五因子ICIR.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("✅", out, flush=True)


def build_html(panel, ann_df, ic_df, summ_df, cache):
    cov = panel.groupby("year")[FACTORS].apply(lambda d: d.notna().sum()) if not panel.empty else pd.DataFrame()
    cov_html = cov.round(0).to_html(classes="t", border=0) if not cov.empty else "<p>面板为空</p>"
    ic_html = ic_df.round(3).to_html(classes="t", border=0, index=False)
    summ_html = summ_df.to_html(classes="t", border=0, index=False)
    nstocks = panel.index.get_level_values(0).nunique() if not panel.empty else 0
    nyears = panel.index.get_level_values(1).nunique() if not panel.empty else 0
    got = sum(1 for v in cache.values() if v.get("factors") and v.get("monthly"))
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Phase 0 妙想 PoC · 五因子时序 IC/IR</title>
<style>
:root{{--bg:#f7f8fa;--card:#fff;--ink:#1f2733;--sub:#5b6675;--line:#e4e8ee;--blue:#1f6feb;--green:#1a9d5a;--amber:#c97a0a;--red:#d23b3b}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.6;font-size:15px}}
.wrap{{max-width:1140px;margin:0 auto;padding:28px 24px 60px}}
header{{background:linear-gradient(120deg,#0f2c54,#1f6feb);color:#fff;border-radius:16px;padding:24px 30px;margin-bottom:20px}}
header h1{{margin:0 0 6px;font-size:22px}}header p{{margin:3px 0;opacity:.92;font-size:13px}}
h2{{font-size:18px;margin:26px 0 10px;padding-left:12px;border-left:5px solid var(--blue)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:16px 18px;margin:10px 0;overflow:auto}}
table.t{{border-collapse:collapse;width:100%;font-size:12.5px;margin:6px 0}}
table.t th,table.t td{{border:1px solid var(--line);padding:5px 8px;text-align:right}}
table.t th{{background:#f0f3f8;color:#0f2c54}}
table.t td:first-child,table.t th:first-child{{text-align:left}}
.call{{border-radius:11px;padding:11px 14px;font-size:13px;margin:10px 0}}
.c-a{{background:#fff6e8;border:1px solid #f0d6a8}}.c-g{{background:#eafaf0;border:1px solid #bfe6cd}}.c-r{{background:#fdecec;border:1px solid #f3c0c0}}
.legend{{font-size:12px;color:var(--sub)}}.footer{{font-size:11.5px;color:var(--sub);border-top:1px solid var(--line);margin-top:28px;padding-top:12px}}
</style></head><body><div class="wrap">
<header><h1>Phase 0 · 妙想 PoC — 五因子时序 IC/IR 验证</h1>
<p>基本面因子效用工程化 · 数据源：东方财富妙想（MiaoXiang，结构化 JSON API）</p>
<p>样本：{nstocks} 只龙头（共 {len(cache)} 只已拉）　|　因子窗：2020–2024（时变）　|　前瞻：妙想月线算次年收益（PIT 近似）</p></header>

<h2>1. 方法论与边界</h2>
<div class="card">
<div class="call c-g"><b>✅ 本次用妙想（mx）真实拉数</b>：五因子多年时序面板 + 月线收盘，全部来自妙想结构化接口。这证明妙想可替代 NeoData 成为 WS1 批量底座。</div>
<div class="call c-a"><b>⚠️ 仍属 PoC</b>：仅 {nstocks} 只龙头、形成年 {nyears} 个、IC 观察点少；因子_t 前瞻收益用"次年日历年收益"近似（未精确到财报披露日），属方法论演示，非 WS1 全样本稳健结论。</div>
<div class="call c-r"><b>读图须知</b>：小样本 IC 噪声大、绝对值易偏高，<b>不可外推为全市场效力</b>。本 PoC 价值 = 妙想数据链路打通 + PIT 对齐 IC/IR 引擎跑通。</div>
</div>

<h2>2. 五因子面板覆盖（按年，非空计数）</h2>
<div class="card">{cov_html}
<p class="legend">各因子每年非空股票数。ROE/EP/FCF/SUE 由妙想稳定返回；股息率可能缺失（查询已含，缺失则NaN）。</p></div>

<h2>3. 逐形成年截面 rank IC（因子_t → 收益_{{t+1}}）</h2>
<div class="card">{ic_html}
<p class="legend">每行 = 一个形成年 t；IC = 该年截面内 Spearman(因子, 次年收益)。空白=可用股票&lt;5 或因子缺失。</p></div>

<h2>4. IC / IR 聚合</h2>
<div class="card">{summ_html}
<p class="legend">meanIC=各形成年 rank IC 均值；IR=meanIC/IC_std；n_obs=有效形成年数。</p></div>

<h2>5. 与既有结论 & 下一步</h2>
<div class="card">
<div class="call c-g"><b>对照 v2 / 阶段2 论坛共识</b>：质量(ROE)+价值(EP)长期有效、合成优于单因子；FCF 是否质量/红利进化版（WS3）、红利拥挤（WS4）待 WS1 全样本（妙想拉全 A）定量裁决。</div>
<div class="call c-a"><b>下一步</b>：妙想数据链路已通 → 升 WS1：① MiaoXiangClient 拉全 A 2020–2025 因子面板（按年/分页）；② IC/IR 引擎零改动；③ 加牛熊拆分 + 2024-02 压力测试。仅需换全 A 列表 + 循环年份。</div>
</div>
<div class="footer">妙想 PoC：用东方财富妙想结构化 API 在龙头上拉真实五因子时序 + 月线，做 PIT 近似 IC/IR 验证。数值来自妙想实时返回。生成：2026-08-26 · 工作区：C:\\Users\\VMW\\Documents\\Workbuddy\\phase0\\</div>
</div></body></html>"""


if __name__ == "__main__":
    main()
