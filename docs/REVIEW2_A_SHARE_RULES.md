# 二次审查报告: OPTIMIZATION_A_SHARE_RULES_MODULE.md (v2)

**审查者**: Senior Quant Engineer / A-share Trader
**审查日期**: 2026-05-31
**基准文件**: `docs/OPTIMIZATION_A_SHARE_RULES_MODULE.md` (v2, corrected)
**对照**: `docs/REVIEW_A_SHARE_RULES_MODULE.md` (v1 review, 11 issues: 10 errors + 9 omissions)
**源码**: `limit_checker.py`, `market_rules.py`, `constants/market.py`, `classifiers.py:240-294`, `rules.py:25-45,59-102,312-352`, `models.py`

---

## 最终评分: 7.5/10 (v1 为 6.5/10, +1.0)

**判断**: v2 对 v1 审查的 10 个 Error 中的 **8 个进行了正确修正**。文档诊断准确、数据模型基本一致、代码示例可执行。但修正过程中引入了 **2 个新的不一致**, 且有 **3 个 v1 遗漏项未填补**。仍需一轮修正后方可执行。

---

## 一、V1 审查修正验证 (10 Errors)

| # | V1 问题 | 严重度 | V2 修正 | 判定 |
|---|---------|--------|---------|------|
| 1 | limit_checker "仅返回布尔状态" 事实错误 | 严重 | 改为 "返回 LimitStatus dataclass (8字段)" | ✅ 正确 |
| 2 | Section 3.1 `auto()` vs Section 4.1 字符串值矛盾 | 严重 | 删除 Section 3.1 的 `BoardType` 定义, 统一为 Section 4.1 字符串版本 | ✅ 正确 |
| 3 | limits.py 迁移代码传 `BoardType.ST` 枚举而非 `"st"` 字符串 | 严重 | 改为 `board_type = "st" if is_st else None` | ✅ 正确 |
| 4 | `limit_pct` 字段名与 `market_rules.py` 的 `price_limit_pct` 不一致 | 中 | 统一为 `price_limit_pct` | ✅ 正确 |
| 5 | 创业板 `"302"` 前缀遗漏 | 中 | Section 5.1 `detect_board` 加入 `"302"`, Section 9 速查表更新 | ✅ 正确 |
| 6 | 科创板 `"689"` 在 MarketConstants 中缺失 | 中 | `detect_board` 已加 `"689"`, 但标注 MarketConstants 仍缺 | ⚠️ 半修正 |
| 7 | `PRICE_TOLERANCE` 硬编码 | 低 | 改为 `MarketConstants.PRICE_TOLERANCE` | ✅ 正确 |
| 8 | `0.005` 魔法数字 | 低 | 提升为 `BREAK_THRESHOLD_BUFFER = 0.005` 命名常量 | ✅ 正确 |
| 9 | `frozen=True` 破坏性变更未标注 | 低 | Section 10 待决事项 #6 已标注 | ⚠️ 已标注, 未解决 |
| 10 | 跌停 threshold 方向问题 | 低 | 改用 `price_ratio <= down_limit_ratio + tolerance` | ✅ 正确 |

**修正率: 8/10 完全修正, 2/10 部分修正。**

### 修正 6 详情: `"689"` 前缀

`detect_board()` 正确加入了 `"689"`:
```python
if code.startswith(("688", "689")):  # 注意: MarketConstants.BOARD_PREFIX 缺少 "689"
    return BoardType.STAR
```
但注释仅标注了问题, 未给出 `MarketConstants` 的修改方案。`constants/market.py:68` 仍为:
```python
"sci_tech": ["688"],  # 缺少 "689"
```
Phase 0 实现时必须同步修改, 否则 `limit_checker.get_board_type()` 对 `689xxx` 股票会误判为主板 (±10% 而非 ±20%)。**这在实盘中是资金风险级别的 bug**。

### 修正 9 详情: `frozen=True`

Section 10 将其列为待决事项, 但未给出迁移策略。现有 `limit_checker.LimitStatus` 是普通 `@dataclass`, `rules.py` 的 `StopLossResult` 也是普通 `@dataclass`。如果 `a_share_rules` 使用 `frozen=True`, 任何修改字段的代码 (如 `result.can_buy = False`) 会抛 `FrozenInstanceError`。建议在 Phase 0 的测试中加入 mutation 测试用例。

---

## 二、V2 修正过程中引入的新问题

### 新问题 A [中]: `LimitMove.volume_level` 类型注解不一致

**位置**: Section 3.2 签名 vs Section 4.1 数据模型

**Section 3.2** (`detect_limit_moves` 返回类型):
```python
def detect_limit_moves(...) -> list[LimitMove]:
```
其中 `LimitMove` 的 `volume_level` 在 Section 3.2 的 inline 定义中注解为 `str`:
```python
volume_level: str          # 量能等级
```

**Section 4.1** (完整数据模型):
```python
@dataclass(frozen=True)
class LimitMove:
    volume_level: VolumeLevel   # ← 枚举类型
```

**源码** (`models.py:212`):
```python
volume_level: VolumeLevel   # 枚举类型
```

**问题**: Section 3.2 的 inline `LimitMove` 定义使用 `str`, Section 4.1 使用 `VolumeLevel`。如果开发者按 Section 3.2 的签名实现, 返回 `str` 会导致 `m.value` 属性访问在 Section 6.3 示例中崩溃。

**修正建议**: Section 3.2 的 `LimitMove` inline 定义应改为 `volume_level: VolumeLevel`。

---

### 新问题 B [中]: `classify_limit_move` docstring 对跌停判定逻辑描述不准确

**位置**: Section 5.2, docstring 第 265 行附近

**Docstring 声称**:
```
3. 若收盘未触及，判断盘中是否触及（high/low）
```

**实际代码** (Section 5.2):
```python
# 涨停判定
if up_ratio >= limit_pct - tolerance:
    return LimitMoveType.LIMIT_UP                    # 收盘封住涨停
if high_ratio >= threshold:
    return LimitMoveType.BREAK_LIMIT_UP              # 盘中触及涨停但未封住

# 跌停判定
if price_ratio <= down_limit_ratio + tolerance:
    return LimitMoveType.LIMIT_DOWN                  # 收盘封住跌停
if low_ratio <= -(limit_pct - BREAK_THRESHOLD_BUFFER):
    return LimitMoveType.BREAK_LIMIT_DOWN            # 盘中触及跌停但未封住
```

涨停判定: `up_ratio` (收盘涨幅) vs `high_ratio` (盘中最高涨幅) — 正确。
跌停判定: `price_ratio` (收盘价/前收盘价) vs `low_ratio` (盘中最低跌幅/前收盘价 - 1) — 正确, 但 docstring 应说明:
- 涨停用 `up_ratio` (收盘涨幅) 和 `high_ratio` (盘中最高涨幅)
- 跌停用 `price_ratio` (收盘价比) 和 `low_ratio` (盘中最低跌幅)

两者使用不同的比较基准 (`up_ratio` 是涨幅, `price_ratio` 是绝对比例), 这是因为跌停 `down_limit_ratio = 1.0 - limit_pct` 天然是绝对比例。代码逻辑正确, 但注释 `# 跌停判定（使用 price_ratio 而非 up_ratio，避免 threshold 方向问题）` 不够清晰。

**建议**: 统一 docstring, 明确说明涨停用涨幅 (`up_ratio`), 跌停用绝对比例 (`price_ratio`)。

---

## 三、V1 遗漏项验证 (9 Omissions)

| # | V1 遗漏 | 严重度 | V2 是否填补 | 说明 |
|---|---------|--------|------------|------|
| 1 | 价格笼子和 tick size 缺失 | 严重 | ✅ 新增 Section 5.6 | 见下方详细审查 |
| 2 | 日内多次封板/炸板无法处理 | 高 | ❌ 未填补 | 文档未声明 `classify_limit_move` 仅适用于回测 |
| 3 | T+1 评估缺少日内浮亏维度 | 高 | ❌ 未填补 | 仍仅计算入场价到支撑位回撤 |
| 4 | limits.py 现状被忽视 | 中 | ❌ 未填补 | 现状仍是 9 行 re-export, 迁移方案未评估成本 |
| 5 | WyckoffEngine._detect_limit_moves 迁移路径 | 中 | ❌ 未填补 | 未提及引擎内部调用链 |
| 6 | 北交所 `4xx` 前缀问题 | 中 | ⚠️ 标注但未修正 | Section 10 #3 标注, 但 Section 5.1 代码未加长度校验 |
| 7 | validate_trade_action 迁移路径 | 中 | ⚠️ 标注但未解决 | Section 10 #2 标注 |
| 8 | can_buy/can_sell 过于简化 | 低 | ❌ 未填补 | 仍为 `not is_limit_up` / `not is_limit_down` |
| 9 | 测试未覆盖边界 | 低 | ❌ 未填补 | 未增加空字符串、小写后缀等边界测试 |

**填补率: 1/9 完全填补, 2/9 标注待确认, 6/9 未填补。**

V1 遗漏项的填补率低, 但这些大多是"应该在实施前补充"的建议, 不是阻塞性问题。最关键的是遗漏 2 (应声明回测限定) 和遗漏 3 (日内浮亏维度)。

---

## 四、Section 5.6 (价格笼子/Tick Size) 详细审查

### 4.1 `round_price()` — 简化但有边界风险

```python
def round_price(price: float) -> float:
    return round(price, 2)
```

**对源码的声称**: 文档称 "A 股最小变动价位: ¥0.01" — **正确**。

**与交易所规则的差异**:
- 交易所涨跌停价: `floor(pre_close × (1 + limit_pct) × 100 + 0.5) / 100` (四舍五入到分)
- 文档简化: `round(price, 2)` (Python 的 banker's rounding)

在大部分价格区间两者等价。边界案例如 `pre_close=10.025, limit_pct=0.10`:
- 交易所: `floor(10.025 × 1.10 × 100 + 0.5) / 100 = floor(1102.75 + 0.5) / 100 = 1103 / 100 = 11.03`
- `round(10.025 × 1.10, 2) = round(11.0275, 2) = 11.02` (banker's rounding, 偶数优先)

差 ¥0.01。对回测影响微小, 但对实盘挂单可能决定是否触发涨跌停。文档的 docstring 提到了 floor 规则但未实现, 仅用 `round` 简化。**建议在实现时使用 `Decimal` 或显式 `floor(x * 100 + 0.5) / 100`**。

### 4.2 `check_price_collar()` — 逻辑正确

```python
def check_price_collar(order_price, base_price, collar_pct, is_buy):
    if is_buy:
        limit_price = round_price(base_price * (1.0 + collar_pct))
        return order_price <= limit_price
    else:
        limit_price = round_price(base_price * (1.0 - collar_pct))
        return order_price >= limit_price
```

**与 `market_rules.py` 对照**:
- 主板 `price_collar_pct=0.02` (±2%) ✅
- 科创/创业板 `price_collar_pct=0.01` (±1%) ✅
- 北交所 `price_collar_pct=0.01` (±1%) ✅
- ST `price_collar_pct=0.01` (±1%) ✅

**实现正确**, 但应注意: 价格笼子在 2023 年全面注册制后有调整 (主板从 ±2% 改为 ±2%, 科创/创业板从 ±2% 改为 ±1%), 文档数值与当前规则一致。

### 4.3 `compute_limit_prices()` — 正确

```python
def compute_limit_prices(pre_close, limit_pct):
    up_limit = round_price(pre_close * (1.0 + limit_pct))
    down_limit = round_price(pre_close * (1.0 - limit_pct))
    return up_limit, down_limit
```

示例 `compute_limit_prices(10.0, 0.10)` → `(11.0, 9.0)` — 正确。
示例 `compute_limit_prices(18.52, 0.20)` → `(22.22, 14.82)` — 正确 (`round(22.224, 2) = 22.22`, `round(14.816, 2) = 14.82`)。

---

## 五、"302" 前缀与 classifiers.py 源码对照

### 源码事实 (`classifiers.py:246`):
```python
limit_pct = 0.05 if is_st else (0.20 if code_prefix in {"688", "689", "300", "301", "302"} else 0.10)
```

### V2 文档 (`detect_board` Section 5.1):
```python
if code.startswith(("300", "301", "302")):
    return BoardType.GEM
```

**判定**: ✅ 正确。`"302"` 已加入, 与 `classifiers.py` 的硬编码集合一致。

### 与 `market_rules.py` 和 `constants/market.py` 的差异:
- `market_rules.py:45`: `code.startswith(("300", "301"))` — **缺少 `"302"`**
- `constants/market.py:69`: `"gem": ["300", "301"]` — **缺少 `"302"`**

文档正确指出 `classifiers.py` 有 `"302"` 但 `MarketConstants` 没有。但文档自身在 Section 1.1 表格中写道:
> `classifiers.py` 直接用代码前缀 `"688"/"300"` 硬编码判断涨跌停比例

这**遗漏了 `"301"`, `"302"`, `"689"`**, 与 `classifiers.py:246` 的实际内容不符。应改为 `"688"/"689"/"300"/"301"/"302"`。

---

## 六、内部一致性审查

### 6.1 `LimitStatus` 字段数: 旧 8 → 新 9

| 字段 | `limit_checker.py` (旧) | `a_share_rules.py` (新) |
|------|------------------------|------------------------|
| `is_limit_up` | ✅ | ✅ |
| `is_limit_down` | ✅ | ✅ |
| `can_buy` | ✅ | ✅ |
| `can_sell` | ✅ | ✅ |
| `board_type` | `str` | `BoardType` ⚠️ |
| `up_limit_price` | ✅ | ✅ |
| `down_limit_price` | ✅ | ✅ |
| `price_ratio` | ✅ | ✅ |
| `limit_pct` | ❌ 不存在 | ✅ 新增 |

**两处破坏性变更未充分标注**:
1. `board_type` 从 `str` 改为 `BoardType` 枚举 — 所有 `status.board_type == "main"` 的比较会失败
2. 新增 `limit_pct` 字段 — 序列化/反序列化可能受影响

Section 10 仅标注了 `frozen=True`, 未标注这两个字段级变更。

### 6.2 `LimitMove` 字段: 旧 5 → 新 8

| 字段 | `models.py` (旧) | `a_share_rules.py` (新) |
|------|-----------------|------------------------|
| `date` | ✅ | ✅ |
| `move_type` | ✅ | ✅ |
| `price` | ✅ | ✅ |
| `volume_level` | `VolumeLevel` | `VolumeLevel` ✅ |
| `is_broken` | ✅ | ✅ |
| `high` | ❌ | ✅ 新增 |
| `low` | ❌ | ✅ 新增 |
| `pre_close` | ❌ | ✅ 新增 |

新增 3 个字段, 但旧代码 `classifiers.py:283-290` 构造 `LimitMove` 时仅传 5 个参数。迁移时必须更新构造调用。

### 6.3 Section 6 示例使用的字段名与 Section 4 数据模型

| 示例 | 字段访问 | Section 4 定义 | 一致性 |
|------|---------|---------------|--------|
| 6.2 `status.limit_pct` | `limit_pct` | `LimitStatus.limit_pct` | ✅ |
| 6.3 `m.move_type.value` | `move_type` | `LimitMove.move_type: LimitMoveType` | ✅ |
| 6.3 `m.volume_level.value` | `volume_level` | `LimitMove.volume_level: VolumeLevel` | ✅ (但与 Section 3.2 inline 定义 `str` 矛盾) |
| 6.5 `result.risk_level` | `risk_level` | `T1RiskResult.risk_level` | ✅ |
| 6.6 `result.stop_loss_price` | `stop_loss_price` | `StopLossResult.stop_loss_price` | ✅ |
| 6.6 `result.stop_logic` | `stop_logic` | `StopLossResult.stop_logic` | ✅ |

**结论**: Section 6 示例与 Section 4 数据模型一致。唯一问题是 Section 3.2 inline 的 `LimitMove` 定义中 `volume_level: str` 与 Section 4.1 的 `VolumeLevel` 不匹配。

---

## 七、limits.py 迁移代码编译验证 (Section 7.2)

```python
# limits.py 改写后
from .a_share_rules import (
    check_limit_status,
    LimitStatus,
    LimitMoveType,
    LimitMove,
)

def is_limit_up(data, prev_close, symbol, is_st=False):
    price = data.get("close", 0) if isinstance(data, dict) else getattr(data, "close", 0)
    board_type = "st" if is_st else None
    result = check_limit_status(price, prev_close, symbol, board_type=board_type)
    return result.is_limit_up

def is_limit_down(data, prev_close, symbol, is_st=False):
    price = data.get("close", 0) if isinstance(data, dict) else getattr(data, "close", 0)
    board_type = "st" if is_st else None
    result = check_limit_status(price, prev_close, symbol, board_type=board_type)
    return result.is_limit_down
```

**编译检查**:
- `check_limit_status` 签名: `(current_price, pre_close, symbol, name, board_type)` — `board_type` 参数类型为 `Optional[BoardType]`
- 调用: `check_limit_status(price, prev_close, symbol, board_type=board_type)` — 传入 `str` 或 `None`

**⚠️ 类型问题**: `board_type` 参数接受 `Optional[BoardType]`, 但迁移代码传入 `str` ("st") 或 `None`。如果 `check_limit_status` 内部用 `BOARD_RULES[board_type]` 查找, 传入 `"st"` 字符串会导致 `KeyError`。

**两种修复方案**:
1. `check_limit_status` 接受 `Optional[Union[BoardType, str]]`, 内部处理字符串→枚举转换
2. 迁移代码改为 `board_type = BoardType.ST if is_st else None`

文档的方案 1 (传字符串) 与现有 `limit_checker.py` 的行为一致 (现有代码用 `board_type="st"` 查 `MarketConstants.LIMIT_RATIO["st"]`), 但与新模块的 `BOARD_RULES: dict[BoardType, BoardRule]` 不兼容。**这是 v2 最严重的内部不一致之一**。

### 与现有 `limit_checker.py` 旧接口的签名对比

现有 `limit_checker.py:219-256` 的 `is_limit_down` / `is_limit_up`:
```python
def is_limit_down(data, prev_close: float, code_prefix: str, is_st: bool = False) -> bool:
```

V2 迁移版:
```python
def is_limit_down(data, prev_close, symbol, is_st=False):
```

参数名从 `code_prefix` 改为 `symbol`。如果调用方传入 `"000"` (code_prefix), `detect_board("000")` 会走降级模式返回 `BoardType.MAIN_SZ`。现有代码传 `code_prefix` 给 `check_limit_status`, 内部 `get_board_type` 会尝试从 3 位前缀推断板块 — 大部分情况能工作, 但不精确。

**结论**: 迁移代码基本可编译, 但 `board_type` 参数的类型不一致是运行时隐患。

---

## 八、其他细节问题

### 8.1 Section 1.1 表格中 classifiers.py 前缀描述不完整

**文档**: `"688"/"300"`
**实际**: `"688", "689", "300", "301", "302"`

### 8.2 Section 5.1 注释提到 MarketConstants 但未给出修改方案

```python
if code.startswith(("688", "689")):  # 注意: MarketConstants.BOARD_PREFIX 缺少 "689"
```

注释很好, 但应在 Phase 0 迁移计划中明确列出 `constants/market.py` 的修改项。

### 8.3 `VolumeLevel` 分类中 `classify_volume` 的 `window` 参数与 `rules.py` 不完全匹配

`rules.py:30`: `volume_series.rolling(window=30, min_periods=10)` — 硬编码 30
`a_share_rules.py` Section 5.3: `volume_series.rolling(window=window, min_periods=10)` — 参数化

这是改进, 不是问题。但 `min_periods=10` 仍为硬编码, 当 `volume_series` 长度 < 10 时全部返回 `NaN` → `AVERAGE`。应文档化此行为。

### 8.4 文档版本号未更新

文档底部: `文档版本: v1.0` — 应改为 `v2.0` 或更高。

---

## 九、A 股实盘视角补充

### 9.1 涨跌停价 rounding 是回测与实盘差异的常见来源

文档 Section 5.6 的 `round_price()` 使用 Python `round()` (banker's rounding)。A 股交易所使用 "四舍五入" (mathematical rounding)。在 `××.××5` 边界上:
- Python `round(10.025, 2)` = `10.02` (向偶数舍入)
- 交易所 `floor(10.025 * 100 + 0.5) / 100` = `10.03`

差异 ¥0.01, 对回测中的涨跌停判定可能产生级联影响 (如 10.03 vs 10.02 是否触发涨停)。建议实现时使用 `math.floor(x * 100 + 0.5) / 100`。

### 9.2 `classify_limit_move` 基于日线 OHLC 的局限性

文档未声明此方法仅适用于回测分析。日线 OHLC 无法区分:
- 开盘秒封 (强势, 不可买入) vs 尾盘偷板 (弱势, 次日低开概率高)
- 盘中多次开板又回封 vs 一次封死
- 集合竞价涨停 vs 连续竞价涨停

建议在 Section 5.2 加入 "适用范围" 声明。

### 9.3 `compute_stop_loss` 的 `stop_pct` 硬编码为 0.5%

`rules.py:325`: `stop_pct = 0.5  # 固定0.5%`

这不是算法计算出来的值, 而是 `key_low * 0.995` 的固定结果。文档如实反映了这一点, 但应说明: 止损幅度固定为 0.5%, 精度警告 (`precision_warning`) 因此**永远为 True**。这个字段在当前实现中没有实际区分意义。

---

## 十、总结

### 做得好的地方
1. `BoardType` 统一为字符串枚举, 消除了 `auto()` 矛盾 ✅
2. `price_limit_pct` 字段名与现有代码一致 ✅
3. `PRICE_TOLERANCE` 和 `BREAK_THRESHOLD_BUFFER` 提升为命名常量 ✅
4. `limits.py` 迁移代码修正了类型错误 ✅
5. 新增 Section 5.6 价格笼子/tick size, 填补了 v1 最严重的遗漏 ✅
6. 数据模型 (Section 4) 与函数签名 (Section 3) 基本一致 ✅

### 仍需修正的问题
1. `check_limit_status` 的 `board_type` 参数类型: `Optional[BoardType]` vs 迁移代码传入 `str` — **运行时 KeyError 风险**
2. `LimitMove.volume_level` Section 3.2 注解为 `str` vs Section 4.1 为 `VolumeLevel` — **实现混淆**
3. `LimitStatus.board_type` 从 `str` 改为 `BoardType` 枚举 — **破坏性变更未标注**
4. `constants/market.py` 的 `BOARD_PREFIX` 缺少 `"689"` 和 `"302"` — **实盘风险**
5. `round_price()` 使用 banker's rounding — **与交易所有 ¥0.01 边界差异**
6. 文档版本号未更新 (仍为 v1.0)

### 建议的下一步

1. **统一 `board_type` 参数策略**: `check_limit_status` 应接受 `Union[BoardType, str, None]`, 内部归一化
2. **修正 Section 3.2 的 `LimitMove` inline 定义**: `volume_level: VolumeLevel`
3. **在 Section 10 增加**: `board_type` 类型变更 (`str` → `BoardType`) 和 `limit_pct` 新增字段的破坏性变更标注
4. **Phase 0 前修改 `constants/market.py`**: `"sci_tech": ["688", "689"]`, `"gem": ["300", "301", "302"]`
5. **`round_price` 实现**: 使用 `math.floor(x * 100 + 0.5) / 100` 或 `Decimal`
6. **更新版本号**: `v2.0`

---

*文档版本: v2.0 review | 审查基于 limit_checker.py, market_rules.py, constants/market.py, classifiers.py, rules.py, models.py 源码*
