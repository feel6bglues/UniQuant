# rule6 LPS 判定重构 — 修复设计（符合 Wyckoff 方法论）

> 版本：v1（重写稿，替代原加权评分草案）
> 依据：`docs/analysis/WYCKOFF_P0_P1_FIX_ANALYSIS_20260802.md` P1 诊断 + Wyckoff 经典方法论
> 目标文件：`src/uniquant/brain/wyckoff/rules.py`（rule6）、`src/uniquant/brain/wyckoff/engine.py`（调用点）

---

## 一、设计原则（方法论约束）

本设计严格遵守 Wyckoff 经典原理，**不引入违背理论的评分补偿**：

| Wyckoff 原理 | 设计含义 |
|---|---|
| LPS 是结构事件，不是评分题 | 守位是**硬门槛**，不可被其他因素补偿 |
| 供给枯竭的参照是 SC/Spring 的卖出量 | 量能对比参照** spring 当日量**，而非后 spring 窗口峰值 |
| LPS 确认带后验性（随后的 SOS） | 反弹确认用**多根K线结构**，非单日收阳 |
| Phase C→D 渐进确认 | LPS 两档：测试中（观察）/ 确认（可做多） |

**明确禁止**：加权评分方案（如"守位30分+量缩40分+反弹30分，总分≥60"）——它允许跌破 spring 低点被高分补偿，违反 Wyckoff。

---

## 二、接口变更

### 2.1 `rule6_spring_validation` 签名变更（rules.py:146）

```python
# 旧签名（仅传 spring_low，无量参照，无测试K线识别）
@staticmethod
def rule6_spring_validation(
    spring_detected: bool,
    post_spring_df: pd.DataFrame,
    spring_low: float,
) -> Dict[str, Any]

# 新签名（增加 spring 当日量参照 + 可选 ATR 用于冲击阈值）
@staticmethod
def rule6_spring_validation(
    spring_detected: bool,
    post_spring_df: pd.DataFrame,
    spring_low: float,
    spring_volume: float = 0.0,     # spring 当日成交量（供给枯竭参照）
    atr: float = 0.0,               # 当前 ATR（冲击容忍阈值）
) -> Dict[str, Any]
```

### 2.2 返回结构扩展（保持向后兼容）

```python
{
    "lps_confirmed": bool,          # 硬门槛 + 全部确认证据 → True
    "quality": str,                 # "作废" | "一级(LPS确认)" | "二级(LPS测试中)" | "无"
    "desc": str,                    # 中文说明
    "spring_invalidated": bool,     # 作废标记（保持原语义）
    # —— 新增诊断字段 ——
    "lps_stage": str,               # "not_test" | "test_held" | "lps_confirmed" | "invalidated"
    "test_low": float,              # 测试K线最低价（守位判定用）
    "test_vol_ratio": float,        # 测试量 / spring量 比值
    "bounce_bars": int,             # 反弹确认的K线数
}
```

---

## 三、算法设计（分层判定）

### 3.1 总流程

```
rule6_spring_validation()
├─ 前置校验（无 spring / 数据不足）→ 原样返回
├─ 阶段1【作废检查】→ invalidated（保持原逻辑）
├─ 阶段2【测试K线识别】→ 找到 spring 后的"回落测试"K线
├─ 阶段3【硬门槛：守位】→ 测试低点 >= spring_low×(1-容忍) 否则 NOT_LPS
└─ 阶段4【确认证据】
     ├─ 量能：测试量 vs spring量 供给枯竭
     └─ 反弹：测试后多根K线结构
     → 两证都满足 = lps_confirmed=True
     → 仅量能 = lps_stage="test_held"（观察等待）
```

### 3.2 阶段2 — 测试K线识别（新）

Wyckoff LPS 是 spring 后**回落接近 spring 低点但未破位**的测试。识别算法：

```python
def _find_test_bar(post_spring_df, spring_low):
    """找到 spring 后最近一次"回落测试"K线。
    条件：K线 low 接近 spring_low（0.99~1.05 倍区间内），
    且该K线是"回落"性质（open >= low 附近，即非跳空高开的长阳）。
    返回该K线在 post_spring_df 中的位置（最后满足者优先）。
    """
    test_idx = None
    for i in range(len(post_spring_df)):
        r = post_spring_df.iloc[i]
        # 接近 spring 低点（测试）
        if spring_low * 0.99 <= r["low"] <= spring_low * 1.05:
            # 回落性质：open 不在测试低点上方过远处（非强突破K线）
            if r["open"] <= spring_low * 1.03:
                test_idx = i
    return test_idx  # 返回最后一个测试K线位置（最近的测试）
```

**方法论依据**：LPS 是多次测试中的最后一次守位。取"最后满足测试条件"的K线，天然对应 Wyckoff"最后一次支撑点"。

### 3.3 阶段3 — 硬门槛：守位（不可补偿）

```python
# 测试K线低点（含其后的窗口，容忍 ATR 比例的下影线噪声）
tolerance = max(atr * 0.25, spring_low * 0.005)   # 至少 0.5%，或用 0.25×ATR
price_held = test_bar_low >= spring_low - tolerance
if not price_held:
    return lps_stage="not_test" / 或作废   # 硬否决，不给任何补偿
```

**方法论依据**：守位是 LPS 的定义性特征。跌破 spring 低点 = 测试失败，无论量能多缩、反弹多强都不是 LPS。

**宽容度说明**：原实现用"窗口内 min(low)"，任何一根瞬时下影线跌破即作废，过严。改为"测试K线 low + ATR 比例容忍"，区分结构破位与噪声下影线。

### 3.4 阶段4 — 确认证据（分级）

**证据1：量能供给枯竭**（修正参照系）

```python
# 旧：recent_vol < max(post_spring_vol) × 0.3   ← 参照系错误
# 新：测试K线量 vs spring 当日量
if spring_volume > 0:
    test_vol_ratio = test_bar_volume / spring_volume
    supply_dry = test_vol_ratio <= 1.0    # 测试量不超过 spring 量（供给未放大）
else:
    test_vol_ratio = None
    supply_dry = True                      # 无量参照时弱化该证据（不卡死）
```

**方法论依据**：Wyckoff 的供给枯竭是"测试时的卖压小于 spring/SC 时的卖压"。参照 spring 当日量是正确口径。

**证据2：反弹冲动（多根K线结构，替代单日收阳）**

```python
# 测试K线之后 N=5 根内（或到数据末尾）：
# 反弹确认 = 出现一根收盘站上"测试K线高点 + 0.5×ATR" 或
#            连续K线累计上涨 >= 1.0×ATR
bounce_bars = 0
test_high = test_bar["high"]
target = test_high + atr * 0.5
for j in range(test_idx+1, min(test_idx+1+N, len(post_spring_df))):
    if post_spring_df.iloc[j]["close"] >= target:
        bounce_bars = j - test_idx
        break
```

**方法论依据**：LPS 确认带后验性——真正的 LPS 以随后的 SOS/上涨确认。多根窗口比"最后一根收阳"稳健，且不被扫描日单日噪声否决。

### 3.5 判定汇总

| 阶段组合 | lps_stage | lps_confirmed | quality | 下游方向 |
|---|---|---|---|---|
| 作废 | invalidated | False | 作废 | 空仓观望 |
| 测试跌破守位 | not_test | False | 二级(需ST) | 空仓观望 |
| 守位 + 仅量缩 | test_held | **False** | 二级(LPS测试中) | **观察等待** |
| 守位 + 量缩 + 反弹 | lps_confirmed | **True** | 一级(LPS确认) | **可做多** |

**下游联动**（engine.py:1283-1289 ACCUMULATION 分支）：
- `lps_confirmed=True` → 保持现有"做多/轻仓试探"逻辑
- `lps_confirmed=False` + `spring_detected=True` → 当前已正确走"观察等待"

---

## 四、调用点变更（engine.py:969-979）

```python
# 旧：仅传 spring_low
lps_result = self.rules.rule6_spring_validation(
    True, post_spring_df, spring_low_price
)

# 新：补充 spring 当日量 + ATR
spring_vol = float(df["volume"].iloc[spring_found["pos"]])   # spring 当日量
lps_result = self.rules.rule6_spring_validation(
    True, post_spring_df, spring_low_price,
    spring_volume=spring_vol,
    atr=current_atr,          # 需提前计算（见下方重构顺序）
)
```

**注意**：当前 `current_atr` 在 rule6 调用之后才计算（engine.py:1018）。需将 ATR 计算上移至 spring 检测之前，或让 rule6 自行计算。

---

## 五、Step3Result 扩展（models.py:444）

新增字段用于报告透传（可选，默认值保持向后兼容）：

```python
@dataclass
class Step3Result:
    ...
    lps_confirmed: bool = False
    lps_stage: str = "not_test"      # 新增：测试阶段标记
    test_low: Optional[float] = None # 新增：测试K线低点
```

---

## 六、参数标定与测试策略

### 6.1 参数默认值（首次标定）

| 参数 | 默认值 | 依据 |
|---|---|---|
| 测试识别区间 | low ∈ [0.99, 1.05]×spring_low | spring 低点附近 ± |
| 守位容忍 | max(0.25×ATR, 0.5%) | 噪声下影线 vs 结构破位 |
| 量能参照 | 测试量 ≤ spring量×1.0 | 供给未放大 |
| 反弹窗口 | 测试后 5 根K线 | 非单日噪声 |
| 反弹阈值 | 收盘 ≥ 测试K线高 + 0.5×ATR | 向上冲动确认 |

### 6.2 测试用例（TDD，新增 `tests/classic_wyckoff/test_lps_refactor.py`）

| 用例 | 场景 | 预期 |
|---|---|---|
| T1 | spring 后回落测试守位 + 缩量 + 反弹 | lps_confirmed=True |
| T2 | spring 后测试**跌破** spring 低点（无反弹） | lps_confirmed=False, lps_stage=not_test |
| T3 | 守位 + 缩量但**无反弹** | lps_confirmed=False, lps_stage=test_held |
| T4 | spring 后放量再创新低 | 作废 invalidated |
| T5 | 测试量**放大**（供给未枯竭） | 确认证据缺失 |
| T6 | 单日收阴但 5 根窗口内反弹（旧实现误否决场景） | lps_confirmed=True（修复单日噪声） |
| T7 | 下影线瞬时破位但收盘守位（ATR 容忍） | 不误判作废 |
| T8 | 真实数据回归：全量扫描 spring 标的 lps_confirmed 率 > 30% | 传导率修复验证 |

### 6.3 回归测试

- `tests/test_wyckoff.py`（spring_freeze 等）
- `tests/test_wyckoff_new_features.py`（Step3Result 构造 4 处，需兼容新字段）
- `tests/classic_wyckoff/` 全套（62 测试基线）
- 全量扫描重跑（spring 传导率对比）

---

## 七、验收标准

1. **方法论合规**：守位是硬门槛，无评分补偿；量能参照 spring 量；反弹多根窗口
2. **功能正确**：T1-T7 全部通过
3. **传导率修复**：全量扫描 spring 标的 lps_confirmed 率从 0% → >30%
4. **无回归**：classic_wyckoff 62 测试全过；ruff clean
5. **向后兼容**：旧字段（lps_confirmed 等）语义不变，新增字段默认值安全

---

## 八、实施顺序

1. 改 `rule6_spring_validation`（rules.py）→ 分层判定
2. 改调用点（engine.py）→ 传 spring_vol + ATR；ATR 计算上移
3. 扩展 `Step3Result`（models.py）
4. 写 T1-T7 测试（先 RED）
5. 跑 T1-T7 + classic_wyckoff 回归（GREEN）
6. 全量扫描重跑，验证传导率
7. 更新 `docs/analysis/WYCKOFF_P0_P1_FIX_ANALYSIS_20260802.md` 的 P1 部分 + AGENTS.md

> **底线**：若重构后 lps_confirmed 率仍为 0%，优先检查"测试K线识别"是否在真实数据上找到守位测试——宁可在识别层找原因，也不要在判定层放宽守位门槛（守住 Wyckoff 底线）。
