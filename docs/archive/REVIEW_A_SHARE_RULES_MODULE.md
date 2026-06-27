# 代码审查报告: OPTIMIZATION_A_SHARE_RULES_MODULE.md

**审查者**: AI — quant finance / Python / A-share specialist
**审查日期**: 2026-05-31
**基准文件**: `docs/OPTIMIZATION_A_SHARE_RULES_MODULE.md` (v1.0)
**审查范围**: `limit_checker.py`, `market_rules.py`, `classifiers.py` (L240-294), `rules.py` (L25-45, L59-102, L312-352), `constants/market.py`, `models.py`

---

## 总体评分: 6.5/10

**判断**: 文档的**问题诊断基本正确** (三套涨跌停逻辑确实存在不一致), **但代码示例质量差、存在多处事实性错误、数据结构定义自相矛盾、迁移计划关键细节遗漏**。建议重大修改后执行, 而非直接按此实施。

---

## 一、Verified Claims — 文档说对的

### 1.1 三套逻辑不一致的诊断 ✅
文档正确地指出现存三个问题:
- `limit_checker.py` 返回 `board_type: str` (`"main"`, `"sci_tech"`, `"gem"`, `"st"`, `"beijing"`)
- `market_rules.py` 使用 `BoardType` 枚举 (`MAIN_SH`, `STAR`, `GEM`, `ST`, `BEIJING`)
- `classifiers.py:detect_limit_moves()` 硬编码涨跌停比例, 不依赖统一常量

三者的代码前缀逻辑、板块命名、涨跌停比例来源确实不同, 统一是正确方向。

### 1.2 板块规则映射表 (Section 4.2) ✅
`BOARD_RULES` 中的 `lot_size`, `limit_pct`, `price_collar_pct` 数值全部正确:
- 科创板 `lot_size=200` ✅
- 北交所 `limit_pct=0.30` ±30% ✅
- ST `limit_pct=0.05` ±5% ✅
- 价格笼子比例与 `market_rules.py` 一致 ✅

### 1.3 板块识别优先级 (Section 5.1) ✅
ST → 交易所后缀 → 代码前缀 → 无后缀降级, 这一顺序是正确的。

### 1.4 T+1 风险评估逻辑 (Section 5.4) ✅
回撤计算和风险分级 (`<3%` SAFE, `3-5%` THIN, `>5%` EXCEEDED) 与 `rules.py:rule3_t1_risk_test()` 逻辑一致。

### 1.5 智能止损逻辑 (Section 5.5) ✅
`stop_loss_price = key_low * 0.995`, 精度检查 `<1.5%`, 流动性警告 ±3%, 与 `rules.py:rule10_stop_loss()` 一致。

### 1.6 量能分类阈值 (Section 5.3) ✅
`2.0 / 1.3 / 0.7 / 0.4` 阈值与 `rules.py:rule1_relative_volume()` 一致。

### 1.7 待决事项 (Section 10) ✅
五个待决事项均属合理关切, 特别是:
- 第3项 "北交所代码前缀 8/4 可能误匹配" — 确实需要长度校验
- 第4项 "classifiers.py:246 硬编码前缀是否扩展" — 确实应统一

---

## 二、Errors Found — 文档错误

### 错误 1 [严重]: `limit_checker.py` "仅返回布尔状态" — 事实错误

**位置**: Section 1.1, 表格第1行
**原文**: `shared/limit_checker.py` → 职责: "基础涨跌停检查" → 问题: "仅返回布尔状态，不区分封板/炸板"

**事实**: `limit_checker.py:check_limit_status()` 返回的是完整的 `LimitStatus` dataclass, 包含 **8 个字段**:
```python
@dataclass
class LimitStatus:
    is_limit_up: bool
    is_limit_down: bool
    can_buy: bool
    can_sell: bool
    board_type: str
    up_limit_price: float
    down_limit_price: float
    price_ratio: float
```

它不"仅返回布尔"。它**确实没有**封板/炸板分类 (那是 `classifiers.py` 的职责), 但说它"仅返回布尔"是严重失实。`limit_checker.py` 是一个相当完善的基础涨跌停检测模块。

---

### 错误 2 [严重]: `BoardType` 定义自相矛盾

**位置**: Section 3.1 vs Section 4.1

Section 3.1 用 `auto()`:
```python
class BoardType(Enum):
    MAIN_SH = auto()
    MAIN_SZ = auto()
    ...
```

Section 4.1 用字符串字面量:
```python
class BoardType(Enum):
    MAIN_SH = "main_sh"
    MAIN_SZ = "main_sz"
    ...
```

**问题**: 同一个模块中定义了两个完全不同的 `BoardType`。使用 `auto()` 则 `.value` 为 `1`; 使用字符串则为 `"main_sh"`。字符串版本更适合序列化, 应统一使用 Section 4.1 的版本, 删除 3.1 的 `auto()` 版本。

---

### 错误 3 [严重]: `limits.py` 改写代码传入错误参数类型 (会导致运行时崩溃)

**位置**: Section 7.2

文档的 `limits.py` 改写后代码:
```python
board_type = BoardType.ST if is_st else None
result = check_limit_status(price, prev_close, code_prefix, board_type=board_type)
```

**两个类型错误**:
1. `board_type=BoardType.ST` — 传入枚举对象, 但 `check_limit_status` 的签名是 `board_type: Optional[str]`。`MarketConstants.LIMIT_RATIO.get(board_type)` 在收到枚举对象时会返回 `None`, 导致崩溃。
2. `symbol=code_prefix` — 传入 `"000"` 而不是 `"000001.SZ"`, `detect_board` 无法正确识别板块。

现有 `limit_checker.py` 的正确实现已经是:
```python
board_type = "st" if is_st else None
result = check_limit_status(price, prev_close, code_prefix, board_type=board_type)
```

---

### 错误 4 [中]: `BoardRule` 字段名与现有代码不一致

**位置**: Section 3.1

文档: `limit_pct: float`  
现有 `market_rules.py`: `price_limit_pct: float`

迁移需要修改所有引用 `BoardRule.price_limit_pct` 的代码, 文档未标注此为破坏性变更。建议保留 `price_limit_pct` 字段名以减少改动范围。

---

### 错误 5 [中]: 创业板 `302` 代码前缀被遗漏

**位置**: Section 9 (速查表), Section 4.2 (BOARD_RULES), Section 5.1 (detect_board)

**现有 `classifiers.py:246`**:
```python
code_prefix in {"688", "689", "300", "301", "302"}
```

`"302"` 是创业板代码前缀, 但现有 `MarketConstants.BOARD_PREFIX["gem"] = ["300", "301"]` 和文档均遗漏此前缀。文档批评了硬编码问题, 但自己没有发现或修复这个现有 bug。

---

### 错误 6 [中]: 科创板 `689` 前缀在 MarketConstants 中缺失

**位置**: Section 5.1, Section 9

`MarketConstants.BOARD_PREFIX["sci_tech"] = ["688"]` 缺少 `"689"`。`classifiers.py:246` 正确检查了 `"689"`, 但文档未指出 `MarketConstants` 需要同步补齐。

---

### 错误 7 [低]: `PRICE_TOLERANCE` 硬编码而非引用常量

**位置**: Section 5.2

```python
tolerance = 0.001  # ← 应使用 MarketConstants.PRICE_TOLERANCE
```

`MarketConstants.PRICE_TOLERANCE = 0.001` 已存在。文档自己批评硬编码, 但重犯了同样的问题。

---

### 错误 8 [低]: 封板阈值 `0.005` 仍然是硬编码魔法数字

**位置**: Section 5.2

```python
threshold = limit_pct - 0.005
```

与 `classifiers.py:246` 的硬编码值相同, 文档未将其提升为命名常量。

---

### 错误 9 [低]: `LimitStatus` 的 `frozen=True` 是破坏性变更

**位置**: Section 4.1

文档使用 `frozen=True`, 现有 `limit_checker.py` 使用普通 `@dataclass`。如有代码修改 `LimitStatus` 字段, 会引发 `FrozenInstanceError`。文档未标注此变更。

---

### 错误 10 [低]: `classify_limit_move` 对 ST 的跌停 threshold 方向问题

**位置**: Section 5.2

```python
if up_ratio <= -(limit_pct - tolerance):  # 对 ST: up_ratio <= -0.049
```

ST 跌停实际为 -5.0%。-4.9% 的 threshold 比 -5.0% 更"严格", 可能将 -4.95% 的正常下跌误判为跌停。现有 `limit_checker.py` 使用 `price_ratio <= down_limit_ratio + tolerance` (即 `≤ 0.951`), 两者不等价。需要统一 threshold 逻辑。

---

## 三、Omissions — 文档遗漏的关键问题

### 遗漏 1 [严重]: 价格笼子和 tick size 实现逻辑完全缺失

文档定义了 `price_collar_pct` 字段, 但**完全没有实现**价格笼子的核心逻辑:
- 买入申报价 ≤ 基准价 × (1 + 价格笼子%)
- 卖出申报价 ≥ 基准价 × (1 - 价格笼子%)

也没有涉及 A 股的最小变动价位 (tick size = ¥0.01 对大部分股票) 和涨跌停价的 round 规则 (`floor`/`ceil` vs `round`)。错误的 rounding 会导致回测信号和实盘不一致。

### 遗漏 2 [高]: 日内多次封板/炸板无法处理

文档的 `classify_limit_move` 仅基于日线 OHLC, 无法区分"开盘秒封"(强势) vs "尾盘偷板"(弱势)。文档应说明此方法**仅适用于回测分析, 不适用于实盘决策**。

### 遗漏 3 [高]: T+1 风险评估缺少日内浮亏维度

文档只考虑入场价到支撑位的回撤, 但 T+1 当日最致命的是"买入后尾盘跳水, 当天无法卖出"。应增加 `(entry_price - day_low) / entry_price` 的日内浮亏评估。

### 遗漏 4 [中]: `limits.py` 现状被忽视

`limits.py` 当前仅 6 行, 从 `limit_checker.py` 直接 re-export。文档 Phase 1 方案 "改写 limits.py" 会产生额外的适配层代码 — 应评估是否应直接修改 `classifiers.py` 的 import 路径。

### 遗漏 5 [中]: `WyckoffEngine._detect_limit_moves()` 的迁移路径

引擎有自己的 `_detect_limit_moves()` 方法调用 `classifiers.detect_limit_moves()`。文档未提及引擎内部的调用链。

### 遗漏 6 [中]: 北交所 `4xx` 前缀的问题

`startswith(("8", "4"))` 过于宽泛。`4xxx` 主要是退市整理期/老三板股票, 与北京证券交易所 (`8xx`) 的涨跌停规则不同。应仅匹配 `8xx` 为北交所, `4xx` 单独处理或归为 UNKNOWN。

### 遗漏 7 [中]: `validate_trade_action` 的迁移路径不明确

此函数被 `services` 层直接调用。如果不迁移, services 层继续依赖 `limit_checker`, 统一目标无法达成。文档标记为"待确认"但未给出解决方案。

### 遗漏 8 [低]: `can_buy`/`can_sell` 过于简化

现有 `can_buy = not is_limit_up` 没有考虑盘中停牌、集合竞价时段等 A 股特殊情况。

### 遗漏 9 [低]: 测试未覆盖板块识别边界

- 空字符串 `detect_board("")`
- 小写后缀 `detect_board("000001.sh")`
- 不合法代码 `detect_board("XXXXXX")`
- 6 位无后缀但前缀为 `"8"` 或 `"4"` 的误匹配

---

## 四、Practical Trading Insights — A 股实盘视角

### 涨跌停价 round 规则是回测精度的关键

A 股的涨跌停价不是 `pre_close * 1.10`, 而是四舍五入到分:
- 涨停价 = `round(pre_close * 1.10 / 0.01) * 0.01`
- 但 actual SSE/SZSE rule: `floor(pre_close * 1.10 * 100 + 0.5) / 100`

`limit_checker.py` 目前用 `round(up_limit_price, 2)`, 这在边界条件下可能与交易所规则有 0.01 元的偏差。文档完全没有提及这一点。

### 日线 OHLC 辨封板/炸板仅供参考

"最高价触板但收盘未封"≠"炸板"。真正的炸板是:开板→回封→再开板。日线数据无法捕捉这种微观结构。文档应声明 `classify_limit_move` 的输出仅供回测统计, 不能作为实盘信号。

### 流动性警告的 3% 阈值应动态化

`abs(move_price - stop_price) / stop_price < 0.03` 这个硬阈值对低价股 (如 ¥2 股票, 3% = ¥0.06) 过于严格, 对高价股 (如 ¥500 股票, 3% = ¥15) 几乎从不触发。应改用 `ATR * 0.5` 或基于溢价的动态阈值。

---

## 五、Code Quality Review — 代码审查

| 问题 | 位置 | 说明 |
|------|------|------|
| 浮点比较 | Section 5.2 | `up_ratio >= limit_pct - tolerance` 应使用 `math.isclose` |
| 无效输入返回 | Section 5.4 | `entry_price <= 0` 返回 `T1RiskLevel.EXCEEDED` — 合理 |
| `classify_volume` 的 `window` 参数 | Section 5.3 | 当 `volume_series` 长度 < `window` 时, 会返回 `NaN` |
| `detect_limit_moves` 函数 | Section 3.2 | 签名定义但无实现体代码 (文档中为空壳) |
| `pd.read_parquet` 路径 | Section 6.3 | 与模块职责无关, 属于使用示例问题 |

### 设计问题: `get_limit_ratio()` 与 `get_board_rule()` 功能重叠

两个函数都提供"获取涨跌停比例"的能力但格式不同:
- `get_limit_ratio()` 返回 `tuple[float, float]` 如 `(1.10, 0.90)`
- `BoardRule.limit_pct` (文档) 或 `price_limit_pct` (现有) 是单个 `float` 如 `0.10`

建议只保留 `BoardRule` + `get_board_rule()` 方式, 删除 `get_limit_ratio()`。

---

## 六、Recommendation — 建议

**结论: 6.5/10。不应直接执行, 需先修正以下问题。**

### 必须修正的 Blocker

1. 统一 `BoardType` 定义 — 使用 Section 4.1 的字符串版本, 删除 `auto()` 版本
2. 修正 `limits.py` 迁移代码: 传字符串 `"st"` 而非 `BoardType.ST`, 传完整 symbol 而非 code_prefix
3. 补充 `"302"` (创业板) 和 `"689"` (科创板) 到 `BOARD_PREFIX` 和 `detect_board`
4. 保留 `price_limit_pct` 字段名 (或全局替换并标注破坏性变更)
5. 删除 `get_limit_ratio()`, 统一使用 `BoardRule.limit_pct`

### 建议在 Phase 0 前补充

6. 增加涨跌停价 round 规则 (`floor`/`ceil` 选择)
7. 将 `0.005` 魔法数字提升为 `BREAK_THRESHOLD_BUFFER = 0.005`
8. 明确 `LimitStatus` 的 `frozen` 策略
9. 增加 `30x` (创业板) 和 `68x/689` (科创板) 的完整前缀映射

### 修改后的 Phase 执行路径

```
Phase 0: 创建 a_share_rules.py (修正以上所有问题)
Phase 1:
  1a. limit_checker.py 增加内部代理调用 a_share_rules
  1b. market_rules.BoardType 改为 from a_share_rules import BoardType
Phase 2:
  2a. classifiers.detect_limit_moves 委托 a_share_rules
  2b. rules.rule3/rule10 委托 a_share_rules
  2c. engine._detect_limit_moves 同步更新
Phase 3:
  3a. 删除 limit_checker 中已迁移逻辑 (保留 validate_trade_action)
  3b. 新旧接口并行测试确保零破坏
```
