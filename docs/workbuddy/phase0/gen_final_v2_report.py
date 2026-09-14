# -*- coding: utf-8 -*-
"""T27 生成 V2 完整报告 (HTML): 季频升级 + 真实DY + 全A拥挤度 + CANSLIM/LPPL"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import numpy as np

# 核心指标汇总
METRICS = {
    # (年化, 夏普, 回撤, Calmar, 净值)
    "HS300 年频核心(无ROE, 真实DY)": (12.8, 0.465, -40.3, 0.317, 4.31),
    "HS300 季频核心(无ROE, TTM)":   (12.3, 0.494, -28.4, 0.432, 3.71),
    "全A 年频核心(近似DY 30%)":     (12.2, 0.398, -52.3, 0.233, 4.05),
    "全A 年频核心(真实DY)":         (9.1, 0.312, -49.2, 0.185, 2.85),
    "全A 季频核心(真实DY)":         (8.8, 0.297, -47.8, 0.185, 2.61),
    "全A 季频+熔断方案A":           (9.9, 0.347, -45.0, 0.219, 3.13),
    "CANSLIM 五因子(HS300)":        (10.9, 0.307, -63.4, 0.172, 3.14),
    "基准 HS300等权":               (11.7, 0.448, -39.6, 0.294, 4.01),
    "基准 全A等权":                 (7.2, 0.194, -58.8, 0.122, 2.39),
}

def row(k, hl=False):
    ar, sh, dd, cm, nv = METRICS[k]
    cls = ' class="hl"' if hl else ''
    scls = ' class="pos"' if sh > 0.4 else (' class="neg"' if sh < 0.15 else '')
    return (f'<tr{cls}><td style="text-align:left"><b>{k}</b></td><td>{ar:.1f}%</td>'
            f'<td{scls}>{sh:.3f}</td><td class="neg">{dd:.1f}%</td><td>{cm:.3f}</td><td>{nv:.2f}</td></tr>')

rows_hs300 = row("HS300 年频核心(无ROE, 真实DY)") + row("HS300 季频核心(无ROE, TTM)", True)
rows_alla = row("全A 年频核心(近似DY 30%)") + row("全A 年频核心(真实DY)") + row("全A 季频核心(真实DY)") + row("全A 季频+熔断方案A", True)
rows_sat = row("CANSLIM 五因子(HS300)") + row("基准 HS300等权") + row("基准 全A等权")

html = f'''<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><title>基本面因子工程化 V2 完整报告</title>
<style>
body{{font-family:system-ui;max-width:1060px;margin:24px auto;padding:0 16px;color:#222;line-height:1.65}}
h1{{color:#0b3d91;font-size:24px}}h2{{color:#0b3d91;border-left:4px solid #0b3d91;padding-left:8px;margin-top:36px}}
table{{border-collapse:collapse;width:100%;margin:12px 0;font-size:13.5px}}
th,td{{border:1px solid #ccc;padding:6px 9px;text-align:right}}th{{background:#f0f4fa;text-align:center}}
td:first-child{{text-align:left}}th:first-child{{text-align:left}}
.pos{{color:#c0392b;font-weight:bold}}.neg{{color:#27ae60}}
.box{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:13px 17px;margin:13px 0}}
.warn{{background:#fff8e6;border:1px solid #f0d9a8;border-radius:8px;padding:12px 16px;margin:13px 0}}
.hl{{background:#fff4e6}}.hl2{{background:#e8f4ec}}
code{{background:#f1f5f9;padding:2px 6px;border-radius:4px}}
.tag{{display:inline-block;background:#e6f1fb;color:#0c447c;border-radius:4px;padding:1px 8px;font-size:12px;margin-right:6px}}
</style></head><body>
<h1>基本面因子效用工程化 · V2 完整报告</h1>
<p>样本：沪深300(300只) + 全A(5328只) · mootdx 真实数据 · 2026-08-27<br>
数据升级：<span class="tag">全A xdxr 真实分红 5115只</span><span class="tag">全A OHLCV 5211只(含成交额)</span><span class="tag">45期季报 gpcw</span></p>

<h2>一、核心方法论升级：年频 → 季频（TTM 因子 + 5/9/11 月调仓）</h2>
<table><tr><th>策略</th><th>年化</th><th>夏普</th><th>最大回撤</th><th>Calmar</th><th>期末净值</th></tr>
{rows_hs300}</table>
<div class="box"><b>✓ 季频升级验证成功（HS300）</b>：夏普 0.465→<b>0.494</b>，回撤 -40.3%→<b>-28.4%</b>（改善 11.9pp），Calmar 0.317→<b>0.432</b>。
季频+TTM 的核心价值是<b>回撤控制</b>——9 月/11 月调仓用最新财报，规避了年报滞后 8 个月的信号衰减。</div>

<h2>二、全 A 真实 DY 重跑：近似 DY 的"盈利暴露"幻觉</h2>
<table><tr><th>策略</th><th>年化</th><th>夏普</th><th>最大回撤</th><th>Calmar</th><th>期末净值</th></tr>
{rows_alla}</table>
<div class="warn"><b>⚠️ 颠覆性发现（全 A）</b>：真实 DY 替换近似 DY 后，全 A 年频核心夏普 <b>0.398 → 0.312</b>（-0.086）。
<b>近似 DY（=净利润×30%/市值）实为盈利因子（EP）的代理</b>——它给所有盈利股一个名义分红率，旧版红利组的超额大部分来自"高盈利"暴露而非真实分红。
HS300 上真实 DY 增强（大盘分红率接近 30%，近似失真小）；全 A 上中小盘分红差异巨大，真实 DY 将红利组收敛到银行/煤炭/公用事业（样本期跑输）。
<b>结论：全 A 必须用真实 DY，且红利 alpha 弱于此前估计——需重新审视红利核心在全 A 的权重。</b></div>

<h2>三、全 A 拥挤度重标定 + 熔断（口径依赖）</h2>
<table><tr><th>策略</th><th>年化</th><th>夏普</th><th>最大回撤</th><th>Calmar</th><th>期末净值</th></tr>
{rows_alla[2]}{rows_alla[3]}</table>
<div class="box"><b>✓ 方案A（合成≥75减半/≥85清仓）有效</b>：全A 季频核心 0.297→<b>0.347</b>，回撤 -47.8%→-45.0%，Calmar 0.185→0.219。
<b>方案B（任一维度≥90）在全 A 过度防御</b>（触发 47 个月，夏普反降至 0.241）——全 A 口径需用合成阈值，与 HS300 相反。</div>
<div class="warn"><b>⚠️ 口径依赖发现</b>：全 A 红利组合 2026-04 估值拥挤仅 <b>33 分位</b>（vs HS300 口径 <b>100 分位历史极值</b>）。
两个口径的红利篮不同（全A 红利股分布更广），<b>拥挤度监控必须以实际投资篮为准</b>——HS300 红利组合正处历史最贵，全 A 红利篮并不拥挤。</div>
<div class="box"><b>预测力</b>：全A 拥挤度 vs 未来12月红利收益 rankIC = <b>-0.281</b>（HS300 为 -0.232，更强）。
拥挤≥75 时未来12月红利收益 <b>-32.1%</b> vs <75 时 <b>+6.1%</b>——风险开关有效性确认。</div>

<h2>四、卫星策略检验：CANSLIM 否证 + LPPL 预警</h2>
<table><tr><th>策略</th><th>年化</th><th>夏普</th><th>最大回撤</th><th>Calmar</th><th>期末净值</th></tr>
{rows_sat}</table>
<div class="box"><b>✗ CANSLIM（C+A+N+S+L 五因子，含真实季报 C）在 HS300 被否证</b>：夏普 0.307 跑输基准 0.448，
与动量相关性 <b>0.817</b>、与核心组合 <b>0.748</b>——无正交增量，回撤 -63.4% 反而最差。A 股大盘篮子里成长型打法水土不服。<br>
<b>✓ LPPL 泡沫监测验证通过</b>：历史回溯正确标记 2015 杠杆牛（评分 75+）、2020-21 抱团牛（74-77）；
<b>当前 2026-08 评分 75/100、m=0.06（超指数加速），处于泡沫加速期</b>——与 WS4 拥挤度"HS300 红利历史极值"信号共振。<b>双重风控信号齐亮，组合级减仓警告生效。</b></div>

<h2>五、最终推荐架构（V2）</h2>
<div class="box hl2"><b>投资篮：HS300（真实 DY 有增益、季频回撤改善最大）</b><br>
核心：季频 TTM 无ROE 核心（DY真实 + FCFY + 现金含量，Top30，5/9/11月调仓）夏普 0.494<br>
卫星：动量 25% + 低波 25%（低相关分散）<br>
风控：① 拥挤度熔断方案A（HS300口径，任一维度极端触发）② LPPL 泡沫评分≥75 时组合降杠杆 ③ 当前 2026-08 双重风控齐亮 → 建议维持熔断监视、降低核心仓位<br>
<b>全 A 口径定位</b>：真实 DY 下红利 alpha 大幅缩水（0.312），全 A 核心建议用"现金含量 + FCFY + EP"（剔除被证伪的红利权重）</div>

<h2>六、边界披露</h2>
<ul>
<li>幸存者偏差：成分/上市列表为当前时点，未做历史成分调整</li>
<li>季频 TTM：gpcw 累计值差分近似，未处理股本变动/增发稀释</li>
<li>LPPL 临界时间 tc 估计不稳定（m→0 退化），仅作定性"加速/非加速"判断</li>
<li>未计交易成本（季频换手提高，成本影响大于年频，预计 0.5-1pp/年）</li>
<li>CANSLIM 的 I(机构持股) 因子缺数据未纳入；S 用总股本代理流通盘</li>
</ul>
</body></html>'''
open("基本面因子效用工程化_V2完整报告.html", "w", encoding="utf-8").write(html)
print("HTML OK")
