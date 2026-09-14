"""Phase 0 — 缩小版 PoC：15 只龙头 × NeoData 可靠字段，跑通完整 IC/IR 引擎。

目的（用户选择"先跑缩小版 PoC"）：
- 用 NeoData 真实返回的字段（ROE/EP/PE分位，偶有 FCF/成长/股息率）构建因子截面；
- 拉 2025-01 → 2026-08 月线算次月收益，逐月算五因子截面 rank IC；
- 聚合 mean IC / IC std / IR，证明 IC/IR 引擎在真实数据上可用。
- 明确标注：非全样本、因子为"当前快照"而非 PIT 时变，属方法论演示，不等同 WS1。

仅依赖 pandas / numpy（managed venv）。
"""
from __future__ import annotations
import os
import sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
VENV_PY = r"C:\Users\VMW\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
QUERY_PY = r"C:\Users\VMW\.workbuddy\skills\neodata-financial-search\scripts\query.py"

sys.path.insert(0, HERE)
from quant_pipeline import (  # noqa: E402
    NeoDataClient, FactorFrame, build_factor_frame,
    rank_ic, rolling_ir, evaluate_factors,
)

# 15 只跨风格龙头（与 Phase0 PoC 一致）
BASKET = [
    "600519.SH", "000858.SZ", "601318.SH", "600036.SH", "000333.SZ",
    "002594.SZ", "600900.SH", "601012.SH", "000001.SZ", "600276.SH",
    "603259.SH", "300750.SZ", "600030.SH", "000651.SZ", "601888.SH",
]
START, END = "2025年1月", "2026年8月"


def main():
    client = NeoDataClient(QUERY_PY, VENV_PY)

    print("[1/4] 构建因子截面（ROE/EP/PE分位 ...）...", flush=True)
    ff = build_factor_frame(client, BASKET)
    fac = ff.to_frame()  # index=code, cols=ROE/EP/SUE_proxy/FCF_yield/DY/PE_pct
    fac.to_csv(os.path.join(HERE, "factor_frame_reduced.csv"))
    print(f"     因子覆盖：\n{fac.notna().sum().to_string()}", flush=True)

    print("[2/4] 拉月线（2025-01 → 2026-08）算次月收益...", flush=True)
    closes = {}
    for c in BASKET:
        s = client.monthly_close(c, START, END)
        if len(s):
            closes[c] = s
        else:
            print(f"     ⚠️ {c} 月线为空，剔除", flush=True)
    close_df = pd.DataFrame(closes).sort_index()           # index=YYYYMM
    ret = close_df.pct_change()                            # 当月收益 = close[t]/close[t-1]-1
    fwd = ret.shift(-1)                                    # 次月收益（因子在 t 已知，收益 t→t+1）
    fwd.to_csv(os.path.join(HERE, "monthly_fwd_returns.csv"))
    n_months = len(fwd.dropna(how="all"))
    print(f"     月线覆盖 {close_df.shape[1]}/{len(BASKET)} 只，有效月 {n_months} 个", flush=True)

    print("[3/4] 逐月算五因子截面 rank IC...", flush=True)
    factors = ["ROE", "EP", "SUE_proxy", "FCF_yield", "DY"]
    ic_records = []
    for m, row in fwd.iterrows():
        fwd_ret = row.dropna()
        if fwd_ret.notna().sum() < 5:
            continue
        rec = {"month": int(m)}
        for f in factors:
            fac_vec = fac[f].dropna()
            common = fac_vec.index.intersection(fwd_ret.index)
            if len(common) < 5:
                rec[f] = np.nan
            else:
                rec[f] = rank_ic(fac[f], fwd_ret)
        ic_records.append(rec)
    ic_df = pd.DataFrame(ic_records).set_index("month")
    ic_df.to_csv(os.path.join(HERE, "ic_matrix_reduced.csv"))

    # 聚合 IC / IR
    summary = []
    for f in factors:
        s = ic_df[f].dropna()
        if len(s) >= 2:
            mean_ic = s.mean()
            ic_std = s.std(ddof=1)
            ir = mean_ic / ic_std if ic_std > 0 else np.nan
            summary.append({
                "factor": f,
                "meanIC": round(mean_ic, 4),
                "IC_std": round(ic_std, 4),
                "IR": round(ir, 3) if not np.isnan(ir) else np.nan,
                "n_obs": int(len(s)),
                "verdict": "✅>0.03" if abs(mean_ic) > 0.03 else "⚠️弱/样本小",
            })
        else:
            summary.append({"factor": f, "meanIC": np.nan, "IC_std": np.nan,
                            "IR": np.nan, "n_obs": int(len(s)), "verdict": "⚠️样本不足"})

    # 复合因子（可用因子等权 z-score）预览 WS2 核心
    zparts = []
    for f in factors:
        v = fac[f].dropna()
        if v.notna().sum() >= 5:
            zparts.append((f, (v - v.mean()) / v.std(ddof=0)))
    if zparts:
        comp = pd.concat([p[1] for p in zparts], axis=1).mean(axis=1)
        comp_ic = [rank_ic(comp, fwd.loc[m].dropna()) if fwd.loc[m].notna().sum() >= 5 else np.nan
                   for m in ic_df.index]
        comp_series = pd.Series(comp_ic, index=ic_df.index).dropna()
        if len(comp_series) >= 2:
            summary.append({
                "factor": "COMPOSITE(等权z)",
                "meanIC": round(comp_series.mean(), 4),
                "IC_std": round(comp_series.std(ddof=1), 4),
                "IR": round(comp_series.mean() / comp_series.std(ddof=1), 3),
                "n_obs": int(len(comp_series)),
                "verdict": "✅预览 WS2 核心",
            })
    summ_df = pd.DataFrame(summary)
    summ_df.to_csv(os.path.join(HERE, "ic_summary_reduced.csv"), index=False)

    print("[4/4] 生成 HTML 报告...", flush=True)
    html = build_html(fac, close_df, ic_df, summ_df, n_months)
    out = os.path.join(HERE, "Phase0_缩小版PoC_ICIR演示.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ 完成 → {out}", flush=True)
    print(summ_df.to_string(index=False), flush=True)


def build_html(fac, close_df, ic_df, summ_df, n_months):
    fac_tbl = fac.round(4).to_html(classes="t", border=0)
    ic_tbl = ic_df.round(3).to_html(classes="t", border=0)
    summ_tbl = summ_df.to_html(classes="t", border=0, index=False)
    cov = fac.notna().sum()
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Phase 0 缩小版 PoC · 五因子 IC/IR 引擎演示</title>
<style>
:root{{--bg:#f7f8fa;--card:#fff;--ink:#1f2733;--sub:#5b6675;--line:#e4e8ee;--blue:#1f6feb;--green:#1a9d5a;--amber:#c97a0a;--red:#d23b3b}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.6;font-size:15px}}
.wrap{{max-width:1120px;margin:0 auto;padding:28px 24px 60px}}
header{{background:linear-gradient(120deg,#0f2c54,#1f6feb);color:#fff;border-radius:16px;padding:24px 30px;margin-bottom:20px}}
header h1{{margin:0 0 6px;font-size:22px}}header p{{margin:3px 0;opacity:.92;font-size:13px}}
h2{{font-size:18px;margin:26px 0 10px;padding-left:12px;border-left:5px solid var(--blue)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:16px 18px;margin:10px 0;overflow:auto}}
table.t{{border-collapse:collapse;width:100%;font-size:12.5px;margin:6px 0}}
table.t th,table.t td{{border:1px solid var(--line);padding:5px 8px;text-align:right}}
table.t th{{background:#f0f3f8;color:#0f2c54;position:sticky;top:0}}
table.t td:first-child,table.t th:first-child{{text-align:left}}
.call{{border-radius:11px;padding:11px 14px;font-size:13px;margin:10px 0}}
.c-a{{background:#fff6e8;border:1px solid #f0d6a8}}.c-g{{background:#eafaf0;border:1px solid #bfe6cd}}.c-r{{background:#fdecec;border:1px solid #f3c0c0}}
code{{background:#eef1f5;padding:1px 5px;border-radius:5px;font-size:12px}}
.legend{{font-size:12px;color:var(--sub)}}
.footer{{font-size:11.5px;color:var(--sub);border-top:1px solid var(--line);margin-top:28px;padding-top:12px}}
</style></head><body><div class="wrap">
<header><h1>Phase 0 · 缩小版 PoC — 五因子 IC/IR 引擎演示</h1>
<p>基本面因子效用工程化工作计划 · 用户选择"先跑缩小版 PoC"</p>
<p>样本：15 只跨风格龙头　|　数据：NeoData（真实返回字段）　|　收益窗：2025-01 → 2026-08 月线次月收益</p></header>

<h2>1. 方法论与边界（必读）</h2>
<div class="card">
<div class="call c-a"><b>⚠️ 这是"方法论演示"，不是 WS1 全样本实证。</b>
<ul style="margin:6px 0;padding-left:20px">
<li><b>样本小</b>：仅 15 只龙头，非全 A；月度 IC 观察点 ≈ {n_months} 个，IR 统计意义有限。</li>
<li><b>因子为"当前快照"</b>：ROE/EP/PE分位取最新已公告值，不是按月 PIT 时变因子。WS1 需 Tushare/妙想 提供历史财报时点。</li>
<li><b>前瞻收益</b>：用月线次月收益（close[t+1]/close[t]-1）作为因子在 t 时刻的"前瞻收益"，截面 rank IC = Spearman(因子, 次月收益)。</li>
<li><b>字段可用性</b>：ROE/EP/PE分位稳定返回；FCF/成长/股息率随调用波动（NeoData 结构不确定）。下方覆盖数见因子表。</li>
</ul></div>
<div class="call c-g"><b>✅ 本 PoC 证明</b>：IC/IR 引擎（rank_ic / rolling_ir / evaluate_factors）在真实数据上可运行，解析链路正确；一旦换上 TushareClient，<b>同一引擎零改动</b>即可升至 WS1 全样本（2010–2025，180+ 月，PIT 时变因子，牛熊拆分 + 2024-02 压力测试）。</div>
</div>

<h2>2. 因子截面（15 只龙头，真实值）</h2>
<div class="card">
{fac_tbl}
<p class="legend">各列非空计数 — ROE:{int(cov['ROE'])} / EP:{int(cov['EP'])} / SUE_proxy:{int(cov['SUE_proxy'])} / FCF_yield:{int(cov['FCF_yield'])} / DY:{int(cov['DY'])} / PE_pct:{int(cov['PE_pct'])}（共 {len(fac)} 只）。EP=1/PE；SUE_proxy=归母净利润同比(%)；FCF_yield=FCF/EV；DY=滚动股息率(%)。</p>
</div>

<h2>3. 逐月截面 rank IC（因子 × 月份）</h2>
<div class="card">
{ic_tbl}
<p class="legend">每个单元格 = 该月截面内 Spearman(因子快照, 次月收益)。空白=该月可用股票&lt;5 只或因子缺失。</p>
</div>

<h2>4. IC / IR 聚合汇总</h2>
<div class="card">
{summ_tbl}
<p class="legend">meanIC=各月 rank IC 均值；IC_std=标准差；IR=meanIC/IC_std；n_obs=有效月点数。判定阈值 |meanIC|&gt;0.03 为弱有效（小样本仅作方向参考）。COMPOSITE=可用因子等权 z-score 合成，预览 WS2 "核心"组合思路。</p>
</div>

<h2>5. 与既有结论的对照</h2>
<div class="card">
<div class="call c-r"><b>读图须知</b>：小样本 IC 可能正负交替、绝对值偏大（15 只股票截面噪声高），<b>不应直接外推为全市场效力</b>。本 PoC 价值在于"引擎跑通 + 流程可复现"，而非给出稳健的因子效力数字。</div>
<div class="call c-g"><b>对照 v2 / 阶段2 论坛共识</b>：质量(ROE)与价值(EP)在长期有效但周期巨震；红利(股息率)2025 拥挤；FCF 是否为质量/红利进化版需 WS3 独立验证；这些命题的<b>定量裁决</b>仍须待 WS1 全样本（Tushare/妙想解锁后）。</div>
</div>

<h2>6. 下一步</h2>
<div class="card">
<ol style="margin:6px 0;padding-left:20px">
<li><b>解锁批量数据源</b>（Tushare 或 妙想 MCP）→ 升 WS1 全样本。</li>
<li>复用本 PoC 的 IC/IR 引擎，仅替换数据客户端（TushareClient 接口同 NeoDataClient）。</li>
<li>WS2 多策略回测 / WS3 FCF 正交 / WS4 拥挤度熔断 顺序推进。</li>
</ol>
</div>

<div class="footer">缩小版 PoC：用 NeoData 真实返回字段在 15 只龙头上跑通五因子 IC/IR 引擎，作为 WS1 全样本前的可行性验证。所有数值来自 NeoData 实时返回；方法论边界已明确标注。生成：2026-08-26 · 工作区：C:\\Users\\VMW\\Documents\\Workbuddy\\phase0\\</div>
</div></body></html>"""


if __name__ == "__main__":
    main()
