# A 股特异性规则统一模块设计文档

> **目标模块**: `src/uniquant/shared/a_share_rules.py`
> **创建日期**: 2026-05-31
> **状态**: 设计阶段
> **依赖**: 无外部新增依赖，仅整合现有逻辑

---

## 1. 问题分析

### 1.1 三套涨跌停逻辑现状

当前系统中存在三套独立的涨跌停识别逻辑，存在重复代码、行为不一致、维护成本高等问题：

| 来源文件 | 职责 | 问题 |
|----------|------|------|
| `shared/limit_checker.py` | 基础涨跌停检查 | 返回 LimitStatus dataclass (8字段: is_limit_up, is_limit_down, can_buy, can_sell, board_type, up_limit_price, down_limit_price, price_ratio)，但不区分封板/炸板 |
| `shared/market_rules.py` | 板块规则 | 独立的 `BoardType` 枚举，与 `limit_checker` 的 `get_board_type` 字符串不兼容 |
| `brain/wyckoff/classifiers.py:240-294` | Wyckoff 涨跌停检测 | 硬编码涨跌停比例，依赖 `limits.py` 兼容层，耦合 Wyckoff 模型 |

**核心矛盾**:
- `limit_checker.py` 用字符串 `"main"/"sci_tech"/"gem"/"st"/"beijing"` 标识板块
- `market_rules.py` 用枚举 `BoardType.MAIN_SH/STAR/GEM/ST/BEIJING` 标识板块
- `classifiers.py` 直接用代码前缀 `"688"/"300"` 硬编码判断涨跌停比例

### 1.2 需要整合的逻辑清单

| 逻辑 | 原始位置 | 目标位置 |
|------|----------|----------|
| 板块识别 | `limit_checker.py:28-66` + `market_rules.py:34-48` | `a_share_rules.py: detect_board()` |
| 涨跌停比例 | `constants/market.py:76-82` + `classifiers.py:246` | `a_share_rules.py: get_limit_ratio()` |
| 涨跌停检测 | `limit_checker.py:69-135` | `a_share_rules.py: check_limit_status()` |
| 封板/炸板分类 | `classifiers.py:240-294` | `a_share_rules.py: classify_limit_move()` |
| 量能分类 | `rules.py:24-45` | `a_share_rules.py: classify_volume()` |
| T+1 风险评估 | `rules.py:59-102` | `a_share_rules.py: assess_t1_risk()` |
| 智能止损 | `rules.py:312-352` | `a_share_rules.py: compute_stop_loss()` |

---

## 2. 模块架构

### 2.1 与现有模块的关系图

```
┌─────────────────────────────────────────────────────────────┐
│                    src/uniquant/shared/                       │
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐   │
│  │  constants/   │    │ limit_checker│    │ market_rules  │   │
│  │  market.py    │───▶│   (保留)     │    │   (保留)      │   │
│  │  LIMIT_RATIO  │    │  兼容旧接口  │    │  BoardRule    │   │
│  │  BOARD_PREFIX │    └──────┬───────┘    └──────┬───────┘   │
│  └──────┬───────┘           │                   │            │
│         │                   ▼                   ▼            │
│         │           ┌──────────────────────────────┐         │
│         └──────────▶│     a_share_rules.py (新)     │◀────────┘
│                     │                              │         │
│                     │  detect_board()      ← 统一  │         │
│                     │  get_limit_ratio()   ← 统一  │         │
│                     │  check_limit_status()← 统一  │         │
│                     │  classify_limit_move()← 新增 │         │
│                     │  classify_volume()   ← 新增  │         │
│                     │  assess_t1_risk()    ← 新增  │         │
│                     │  compute_stop_loss() ← 新增  │         │
│                     └──────────────┬───────────────┘         │
│                                    │                         │
│  ┌──────────────┐                  │                         │
│  │   limits.py   │◀─── 兼容层 ─────┘                         │
│  │  (保留/改写)  │                                           │
│  └──────────────┘                                            │
└─────────────────────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
┌─────────────────────┐    ┌──────────────────────────┐
│ brain/wyckoff/       │    │ risk/                     │
│ classifiers.py       │    │ drawdown_analyzer.py      │
│ rules.py             │    │ (未来扩展)                │
│ (迁移后简化)         │    └──────────────────────────┘
└─────────────────────┘
```

### 2.2 依赖方向

```
a_share_rules.py
    ├── constants/market.py   (MarketConstants: BOARD_PREFIX, LIMIT_RATIO, PRICE_TOLERANCE)
    ├── logger_factory.py     (日志)
    └── (无其他依赖)

limit_checker.py  →  a_share_rules.py  (改写为调用统一模块)
limits.py         →  a_share_rules.py  (兼容层指向统一模块)
classifiers.py    →  a_share_rules.py  (迁移 detect_limit_moves)
rules.py          →  a_share_rules.py  (迁移 rule3, rule10)
```

---

## 3. 接口设计

### 3.1 板块识别

> `BoardType` 枚举定义见 [4.1 核心数据类](#41-核心数据类)（字符串值版本，如 `"main_sh"`、`"gem"`）。

```python
from dataclasses import dataclass
from typing import Optional, Union


@dataclass(frozen=True)
class BoardRule:
    """板块交易规则"""
    board_type: BoardType
    lot_size: int
    price_limit_pct: float
    price_collar_pct: float
    display_name: str


def detect_board(symbol: str, name: Optional[str] = None) -> BoardType:
    """
    统一板块识别

    Args:
        symbol: 股票代码，如 "000001.SZ", "688001.SH"
        name: 股票名称（可选，用于 ST 识别）

    Returns:
        BoardType: 板块枚举值

    示例:
        >>> detect_board("000001.SZ")
        BoardType.MAIN_SZ
        >>> detect_board("688001.SH")
        BoardType.STAR
        >>> detect_board("000001.SZ", "*ST 新海")
        BoardType.ST
    """
    ...


def get_board_rule(board_type: BoardType) -> BoardRule:
    """获取板块完整交易规则"""
    ...
```

### 3.2 涨跌停检测系统

```python
class LimitMoveType(Enum):
    """涨跌停事件类型"""
    LIMIT_UP = "涨停"           # 收盘封住涨停
    BREAK_LIMIT_UP = "炸板"     # 盘中触及涨停但收盘未封住
    LIMIT_DOWN = "跌停"         # 收盘封住跌停
    BREAK_LIMIT_DOWN = "撬板"   # 盘中触及跌停但收盘未封住
    NONE = "无"


@dataclass(frozen=True)
class LimitStatus:
    """涨跌停状态（增强版）"""
    is_limit_up: bool          # 是否涨停
    is_limit_down: bool        # 是否跌停
    can_buy: bool              # 是否可买入
    can_sell: bool             # 是否可卖出
    board_type: BoardType      # 板块类型（枚举）
    up_limit_price: float      # 涨停价
    down_limit_price: float    # 跌停价
    price_ratio: float         # 当前价/前收盘价
    limit_pct: float           # 涨跌停比例 (如 0.10)


@dataclass(frozen=True)
class LimitMove:
    """涨跌停事件详情"""
    date: str
    move_type: LimitMoveType
    price: float               # 收盘价
    volume_level: str          # 量能等级
    is_broken: bool            # 是否炸板/撬板
    high: float = 0.0          # 最高价（用于区分封板/炸板）
    low: float = 0.0           # 最低价（用于区分跌停/撬板）
    pre_close: float = 0.0     # 前收盘价


def check_limit_status(
    current_price: float,
    pre_close: float,
    symbol: str = "",
    name: Optional[str] = None,
    board_type: Optional[Union[BoardType, str]] = None,
) -> LimitStatus:
    """
    检查涨跌停状态

    Args:
        current_price: 当前价格（收盘价或实时价）
        pre_close: 前收盘价
        symbol: 股票代码
        name: 股票名称（可选，用于 ST 识别）
        board_type: 板块类型（可选，自动识别）。
            接受 BoardType 枚举或字符串 ("st"/"main"/"sci_tech"/"gem"/"beijing")。
            字符串输入会被内部归一化为 BoardType 枚举。

    Returns:
        LimitStatus: 涨跌停状态对象
    """
    # 字符串→枚举归一化
    if isinstance(board_type, str):
        _STR_TO_BOARD = {
            "st": BoardType.ST,
            "main": BoardType.MAIN_SH,
            "main_sh": BoardType.MAIN_SH,
            "main_sz": BoardType.MAIN_SZ,
            "sci_tech": BoardType.STAR,
            "gem": BoardType.GEM,
            "beijing": BoardType.BEIJING,
        }
        board_type = _STR_TO_BOARD.get(board_type.lower(), None)

    if board_type is None:
        board_type = detect_board(symbol, name)

    rule = BOARD_RULES.get(board_type, BOARD_RULES[BoardType.UNKNOWN])
    ...


def classify_limit_move(
    open_price: float,
    close_price: float,
    high_price: float,
    low_price: float,
    pre_close: float,
    volume: float,
    avg_volume: float,
    symbol: str = "",
    name: Optional[str] = None,
) -> LimitMoveType:
    """
    涨跌停分类（区分封板/炸板/跌停/撬板）

    判定逻辑：
    - 收盘价触及涨停价 → LIMIT_UP（封板）
    - 最高价触及涨停价但收盘未封住 → BREAK_LIMIT_UP（炸板）
    - 收盘价触及跌停价 → LIMIT_DOWN（跌停）
    - 最低价触及跌停价但收盘未封住 → BREAK_LIMIT_DOWN（撬板）

    Args:
        open_price: 开盘价
        close_price: 收盘价
        high_price: 最高价
        low_price: 最低价
        pre_close: 前收盘价
        volume: 当日成交量
        avg_volume: 近 30 日均量
        symbol: 股票代码
        name: 股票名称

    Returns:
        LimitMoveType: 涨跌停类型
    """
    ...


def detect_limit_moves(
    df: "pd.DataFrame",
    symbol: str,
    name: Optional[str] = None,
    lookback: int = 20,
) -> list[LimitMove]:
    """
    批量检测涨跌停事件（从 DataFrame 中提取）

    Args:
        df: 包含 date/open/close/high/low/volume 列的 DataFrame
        symbol: 股票代码
        name: 股票名称
        lookback: 回溯天数

    Returns:
        list[LimitMove]: 涨跌停事件列表
    """
    ...
```

### 3.3 量能分类

```python
class VolumeLevel(Enum):
    """量能等级（5 级分类）"""
    EXTREME_HIGH = "天量/爆量"   # ≥ 2.0 倍均量
    HIGH = "高于平均"            # ≥ 1.3 倍均量
    AVERAGE = "平均"             # ≥ 0.7 倍均量
    LOW = "萎缩"                # ≥ 0.4 倍均量
    EXTREME_LOW = "地量"         # < 0.4 倍均量


def classify_volume(
    volume: float,
    volume_series: "pd.Series",
    window: int = 30,
) -> VolumeLevel:
    """
    相对量能分类

    基准: 滚动 window 日均量（默认 30 日）
    阈值: 2.0 / 1.3 / 0.7 / 0.4

    Args:
        volume: 当日成交量
        volume_series: 历史成交量序列
        window: 均量计算窗口（默认 30）

    Returns:
        VolumeLevel: 量能等级

    示例:
        >>> classify_volume(5000, pd.Series([2000]*30))
        VolumeLevel.HIGH  # 5000/2000 = 2.5 → 天量
    """
    ...
```

### 3.4 T+1 风险评估

```python
class T1RiskLevel(Enum):
    """T+1 风险等级"""
    SAFE = "安全"       # 极限回撤 < 3%
    THIN = "偏薄"       # 极限回撤 3% ~ 5%
    EXCEEDED = "超限"   # 极限回撤 > 5%


@dataclass(frozen=True)
class T1RiskResult:
    """T+1 风险评估结果"""
    risk_level: T1RiskLevel
    max_drawdown_pct: float     # 极限回撤百分比
    description: str            # 中文描述
    liquidity_warning: str      # 流动性风险警告（空字符串表示无警告）
    stop_price: float           # 止损价 (support_low × 0.995)


def assess_t1_risk(
    entry_price: float,
    support_low: float,
    recent_limit_moves: Optional[list[dict]] = None,
) -> T1RiskResult:
    """
    T+1 极限回撤测试（含涨跌停流动性警告）

    计算逻辑:
        max_drawdown = (entry_price - support_low) / entry_price × 100

    风险等级:
        - < 3%: 安全（绿灯，安全垫充足）
        - 3% ~ 5%: 偏薄（黄灯，限 50% 半仓）
        - > 5%: 超限（红灯，强制禁止做多）

    流动性警告:
        检查止损位 (support_low × 0.995) 附近 ±3% 是否有涨跌停记录。
        若有，提示止损单可能无法按预期价格成交。

    Args:
        entry_price: 入场价格
        support_low: 支撑低点
        recent_limit_moves: 近期涨跌停事件列表（可选）
            每个元素包含 {"price": float, "type": "涨停"/"跌停"}

    Returns:
        T1RiskResult: 风险评估结果

    示例:
        >>> assess_t1_risk(10.0, 9.7)
        T1RiskResult(risk_level=T1RiskLevel.SAFE, max_drawdown_pct=3.0, ...)
        >>> assess_t1_risk(10.0, 9.0)
        T1RiskResult(risk_level=T1RiskLevel.EXCEEDED, max_drawdown_pct=10.0, ...)
    """
    ...
```

### 3.5 智能止损

```python
@dataclass(frozen=True)
class StopLossResult:
    """止损计算结果"""
    entry_price: float          # 入场价（关键低点）
    stop_loss_price: float      # 止损价 (key_low × 0.995)
    stop_pct: float             # 止损幅度百分比
    precision_warning: bool     # 止损区间是否过窄 (< 1.5%)
    liquidity_risk_warning: str # 流动性风险警告
    stop_logic: str             # 止损逻辑描述


def compute_stop_loss(
    key_low: float,
    recent_limit_moves: Optional[list[dict]] = None,
) -> StopLossResult:
    """
    智能止损计算

    计算逻辑:
        stop_loss_price = key_low × 0.995

    精度警告:
        若止损幅度 < 1.5%，标记 precision_warning = True

    流动性警告:
        检查止损位附近 ±3% 是否有涨跌停记录

    Args:
        key_low: 关键低点价格
        recent_limit_moves: 近期涨跌停事件（可选）
            每个元素包含 {"price": float, "type": "涨停"/"跌停"}

    Returns:
        StopLossResult: 止损计算结果

    示例:
        >>> compute_stop_loss(9.50)
        StopLossResult(
            entry_price=9.50,
            stop_loss_price=9.452,
            stop_pct=0.5,
            precision_warning=True,
            liquidity_risk_warning="止损区间窄，注意流动性",
            stop_logic="关键低点9.50×0.995=9.45"
        )
    """
    ...
```

---

## 4. 数据模型

### 4.1 核心数据类

```python
# ============================================================
# 完整数据模型定义
# ============================================================

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Union


# ---------- 枚举类型 ----------

class BoardType(Enum):
    """A 股板块类型"""
    MAIN_SH = "main_sh"
    MAIN_SZ = "main_sz"
    GEM = "gem"
    STAR = "star"
    BEIJING = "beijing"
    ST = "st"
    UNKNOWN = "unknown"


class LimitMoveType(Enum):
    """涨跌停事件类型"""
    LIMIT_UP = "涨停"
    LIMIT_DOWN = "跌停"
    BREAK_LIMIT_UP = "炸板"
    BREAK_LIMIT_DOWN = "撬板"
    NONE = "无"


class VolumeLevel(Enum):
    """量能等级"""
    EXTREME_HIGH = "天量/爆量"
    HIGH = "高于平均"
    AVERAGE = "平均"
    LOW = "萎缩"
    EXTREME_LOW = "地量"


class T1RiskLevel(Enum):
    """T+1 风险等级"""
    SAFE = "安全"
    THIN = "偏薄"
    EXCEEDED = "超限"


# ---------- 数据载体 ----------

@dataclass(frozen=True)
class BoardRule:
    """板块交易规则"""
    board_type: BoardType
    lot_size: int
    price_limit_pct: float
    price_collar_pct: float
    display_name: str


@dataclass(frozen=True)
class LimitStatus:
    """涨跌停状态"""
    is_limit_up: bool
    is_limit_down: bool
    can_buy: bool
    can_sell: bool
    board_type: BoardType
    up_limit_price: float
    down_limit_price: float
    price_ratio: float
    limit_pct: float


@dataclass(frozen=True)
class LimitMove:
    """涨跌停事件"""
    date: str
    move_type: LimitMoveType
    price: float
    volume_level: VolumeLevel
    is_broken: bool
    high: float = 0.0
    low: float = 0.0
    pre_close: float = 0.0


@dataclass(frozen=True)
class T1RiskResult:
    """T+1 风险评估结果"""
    risk_level: T1RiskLevel
    max_drawdown_pct: float
    description: str
    liquidity_warning: str
    stop_price: float


@dataclass(frozen=True)
class StopLossResult:
    """止损计算结果"""
    entry_price: float
    stop_loss_price: float
    stop_pct: float
    precision_warning: bool
    liquidity_risk_warning: str
    stop_logic: str
```

### 4.2 板块规则映射表

```python
BOARD_RULES: dict[BoardType, BoardRule] = {
    BoardType.MAIN_SH: BoardRule(
        board_type=BoardType.MAIN_SH,
        lot_size=100,
        price_limit_pct=0.10,
        price_collar_pct=0.02,
        display_name="上交所主板",
    ),
    BoardType.MAIN_SZ: BoardRule(
        board_type=BoardType.MAIN_SZ,
        lot_size=100,
        price_limit_pct=0.10,
        price_collar_pct=0.02,
        display_name="深交所主板",
    ),
    BoardType.GEM: BoardRule(
        board_type=BoardType.GEM,
        lot_size=100,
        price_limit_pct=0.20,
        price_collar_pct=0.01,
        display_name="创业板",
    ),
    BoardType.STAR: BoardRule(
        board_type=BoardType.STAR,
        lot_size=200,
        price_limit_pct=0.20,
        price_collar_pct=0.01,
        display_name="科创板",
    ),
    BoardType.BEIJING: BoardRule(
        board_type=BoardType.BEIJING,
        lot_size=100,
        price_limit_pct=0.30,
        price_collar_pct=0.01,
        display_name="北交所",
    ),
    BoardType.ST: BoardRule(
        board_type=BoardType.ST,
        lot_size=100,
        price_limit_pct=0.05,
        price_collar_pct=0.01,
        display_name="ST 股",
    ),
}
```

---

## 5. 实现细节

### 5.1 板块识别统一算法

```python
def detect_board(symbol: str, name: Optional[str] = None) -> BoardType:
    """统一板块识别，合并 limit_checker.get_board_type 和 market_rules.detect_board"""
    if not symbol:
        return BoardType.UNKNOWN

    upper = symbol.upper()
    code = upper.split(".")[0] if "." in upper else upper

    # 1. ST 检查（优先级最高，依赖名称）
    if name:
        name_upper = name.upper().strip()
        if name_upper.startswith(("ST", "*ST")):
            return BoardType.ST

    # 2. 按交易所后缀 + 代码前缀判断
    if upper.endswith(".SH"):
        if code.startswith(("688", "689")):
            return BoardType.STAR
        return BoardType.MAIN_SH

    if upper.endswith(".SZ"):
        if code.startswith(("300", "301", "302")):
            return BoardType.GEM
        return BoardType.MAIN_SZ

    if upper.endswith(".BJ"):
        return BoardType.BEIJING

    # 3. 无后缀时按代码前缀推断（降级模式）
    if code.startswith(("688", "689")):  # 注意: MarketConstants.BOARD_PREFIX 缺少 "689"
        return BoardType.STAR
    if code.startswith(("300", "301", "302")):
        return BoardType.GEM
    if code.startswith("8") and len(code) == 6:
        return BoardType.BEIJING
    # 4xx 为退市整理期/老三板股票，归为 UNKNOWN
    if code.startswith(("600", "601", "603", "605")):
        return BoardType.MAIN_SH
    if code.startswith(("000", "001", "002")):
        return BoardType.MAIN_SZ

    return BoardType.UNKNOWN
```

### 5.2 封板/炸板判定逻辑

```python
from uniquant.shared.constants import MarketConstants


BREAK_THRESHOLD_BUFFER = 0.005  # 封板/炸板判定缓冲阈值


def classify_limit_move(
    open_price: float,
    close_price: float,
    high_price: float,
    low_price: float,
    pre_close: float,
    volume: float,
    avg_volume: float,
    symbol: str = "",
    name: Optional[str] = None,
) -> LimitMoveType:
    """
    判定逻辑（源自 classifiers.py:266-279，增强为区分封板/炸板）:

    1. 计算涨跌停比例和阈值
    2. 判断收盘价是否触及涨/跌停
    3. 若收盘未触及，判断盘中是否触及（high/low）

    炸板阈值: limit_pct - BREAK_THRESHOLD_BUFFER（如主板 10% 涨停 → 阈值 9.5%）
    容差: MarketConstants.PRICE_TOLERANCE = 0.001
    """
    board = detect_board(symbol, name)
    rule = BOARD_RULES[board]
    limit_pct = rule.price_limit_pct
    tolerance = MarketConstants.PRICE_TOLERANCE
    threshold = limit_pct - BREAK_THRESHOLD_BUFFER

    price_ratio = close_price / pre_close                # 收盘价比例
    up_ratio = price_ratio - 1.0                         # 收盘涨幅
    high_ratio = high_price / pre_close - 1.0            # 盘中最高涨幅
    low_ratio = low_price / pre_close - 1.0              # 盘中最低跌幅
    down_limit_ratio = 1.0 - limit_pct                   # 跌停价比例

    # 涨停判定
    if up_ratio >= limit_pct - tolerance:
        return LimitMoveType.LIMIT_UP                    # 收盘封住涨停
    if high_ratio >= threshold:
        return LimitMoveType.BREAK_LIMIT_UP              # 盘中触及涨停但未封住（炸板）

    # 跌停判定（使用 price_ratio 而非 up_ratio，避免 threshold 方向问题）
    if price_ratio <= down_limit_ratio + tolerance:
        return LimitMoveType.LIMIT_DOWN                  # 收盘封住跌停
    if low_ratio <= -(limit_pct - BREAK_THRESHOLD_BUFFER):
        return LimitMoveType.BREAK_LIMIT_DOWN            # 盘中触及跌停但未封住（撬板）

    return LimitMoveType.NONE
```

### 5.3 量能分类算法

```python
def classify_volume(
    volume: float,
    volume_series: "pd.Series",
    window: int = 30,
) -> VolumeLevel:
    """
    滚动均量基准分类

    阈值（源自 rules.py:36-45）:
        ratio >= 2.0  → EXTREME_HIGH (天量)
        ratio >= 1.3  → HIGH (高于平均)
        ratio >= 0.7  → AVERAGE (平均)
        ratio >= 0.4  → LOW (萎缩)
        ratio <  0.4  → EXTREME_LOW (地量)
    """
    import pandas as pd

    if volume_series.empty or volume <= 0:
        return VolumeLevel.AVERAGE

    avg_vol = volume_series.rolling(window=window, min_periods=10).mean().iloc[-1]
    if pd.isna(avg_vol) or avg_vol <= 0:
        return VolumeLevel.AVERAGE

    ratio = volume / avg_vol

    if ratio >= 2.0:
        return VolumeLevel.EXTREME_HIGH
    elif ratio >= 1.3:
        return VolumeLevel.HIGH
    elif ratio >= 0.7:
        return VolumeLevel.AVERAGE
    elif ratio >= 0.4:
        return VolumeLevel.LOW
    else:
        return VolumeLevel.EXTREME_LOW
```

### 5.4 T+1 风险评估算法

```python
def assess_t1_risk(
    entry_price: float,
    support_low: float,
    recent_limit_moves: Optional[list[dict]] = None,
) -> T1RiskResult:
    """
    算法（源自 rules.py:59-102）:

    1. 计算极限回撤: (entry_price - support_low) / entry_price × 100
    2. 按阈值分级: <3% 安全, 3-5% 偏薄, >5% 超限
    3. 检查止损位附近流动性风险
    """
    if entry_price <= 0 or support_low <= 0:
        return T1RiskResult(
            risk_level=T1RiskLevel.EXCEEDED,
            max_drawdown_pct=100.0,
            description="无效价格",
            liquidity_warning="",
            stop_price=0.0,
        )

    max_drawdown_pct = (entry_price - support_low) / entry_price * 100
    stop_price = support_low * 0.995

    # 流动性警告检查
    liquidity_warning = _check_liquidity_risk(stop_price, recent_limit_moves)

    # 风险分级
    if max_drawdown_pct < 3.0:
        level = T1RiskLevel.SAFE
        desc = f"极限回撤{max_drawdown_pct:.1f}%，安全"
    elif max_drawdown_pct < 5.0:
        level = T1RiskLevel.THIN
        desc = f"极限回撤{max_drawdown_pct:.1f}%，偏薄"
    else:
        level = T1RiskLevel.EXCEEDED
        desc = f"极限回撤{max_drawdown_pct:.1f}%，超限"

    return T1RiskResult(
        risk_level=level,
        max_drawdown_pct=round(max_drawdown_pct, 2),
        description=desc,
        liquidity_warning=liquidity_warning,
        stop_price=round(stop_price, 3),
    )
```

### 5.5 流动性风险检查（内部函数）

```python
def _check_liquidity_risk(
    stop_price: float,
    recent_limit_moves: Optional[list[dict]],
) -> str:
    """
    检查止损位附近是否有涨跌停记录

    范围: 止损价 ±3%
    来源: rules.py:70-79, rules.py:330-339

    注意: 3% 固定阈值对低价股（如 ¥2 股票，3% = ¥0.06）过于严格，
          对高价股（如 ¥500 股票，3% = ¥15）几乎从不触发。
          生产环境建议改用 ATR × 0.5 的动态阈值。
    """
    if not recent_limit_moves:
        return ""

    for move in recent_limit_moves:
        move_price = move.get("price", 0)
        if move_price <= 0:
            continue
        if abs(move_price - stop_price) / stop_price < 0.03:
            move_type = move.get("type", "")
            if move_type in ("涨停", "跌停"):
                return (
                    f"流动性风险警告：止损位附近有{move_type}记录，"
                    f"止损单可能无法按预期价格成交"
                )
    return ""
```

### 5.6 价格笼子与 tick size 校验

```python
from typing import Tuple
import math


def round_price(price: float) -> float:
    """
    A 股最小变动价位: ¥0.01（大部分股票）

    round(price, 2) 对大部分股票足够，但涨跌停价需使用交易所的 floor 规则：
    涨停价 = floor(pre_close × (1 + limit_pct) × 100 + 0.5) / 100
    跌停价 = ceil(pre_close × (1 - limit_pct) × 100 - 0.5) / 100
    简化实现：round(pre_close × (1 ± limit_pct), 2)
    """
    return round(price, 2)


def check_price_collar(
    order_price: float,
    base_price: float,
    collar_pct: float,
    is_buy: bool,
) -> bool:
    """
    价格笼子校验

    A 股价格笼子规则:
    - 买入申报价 ≤ 基准价 × (1 + 价格笼子%)
    - 卖出申报价 ≥ 基准价 × (1 - 价格笼子%)
    - 超出笼子的订单不会被交易所接受

    Args:
        order_price: 申报价格
        base_price: 基准价格（最新成交价或前收盘价）
        collar_pct: 价格笼子比例（如 0.02 表示 ±2%）
        is_buy: 是否为买入订单

    Returns:
        bool: 订单价格是否在价格笼子内
    """
    if is_buy:
        limit_price = round_price(base_price * (1.0 + collar_pct))
        return order_price <= limit_price
    else:
        limit_price = round_price(base_price * (1.0 - collar_pct))
        return order_price >= limit_price


def compute_limit_prices(
    pre_close: float,
    limit_pct: float,
) -> Tuple[float, float]:
    """
    计算涨跌停价（使用交易所 round 规则）

    Args:
        pre_close: 前收盘价
        limit_pct: 涨跌停比例（如 0.10 表示 ±10%）

    Returns:
        (涨停价, 跌停价)

    示例:
        >>> compute_limit_prices(10.0, 0.10)
        (11.0, 9.0)
        >>> compute_limit_prices(18.52, 0.20)
        (22.22, 14.82)  # round(18.52 * 1.20, 2) = 22.224 → 22.22
    """
    up_limit = round_price(pre_close * (1.0 + limit_pct))
    down_limit = round_price(pre_close * (1.0 - limit_pct))
    return up_limit, down_limit
```
---

## 6. 使用示例

### 6.1 板块识别

```python
from uniquant.shared.a_share_rules import detect_board, BoardType

# 标准识别
board = detect_board("000001.SZ")          # BoardType.MAIN_SZ
board = detect_board("688001.SH")          # BoardType.STAR
board = detect_board("300750.SZ")          # BoardType.GEM
board = detect_board("830799.BJ")          # BoardType.BEIJING

# ST 识别（需要名称）
board = detect_board("000001.SZ", "*ST 新海")  # BoardType.ST

# 无后缀降级识别
board = detect_board("688001")             # BoardType.STAR
```

### 6.2 涨跌停检测

```python
from uniquant.shared.a_share_rules import check_limit_status, classify_limit_move

# 基础检测
status = check_limit_status(
    current_price=11.0,
    pre_close=10.0,
    symbol="000001.SZ",
)
print(status.is_limit_up)    # True
print(status.can_buy)        # False
print(status.limit_pct)      # 0.10

# 封板/炸板分类
move_type = classify_limit_move(
    open_price=10.5,
    close_price=11.0,
    high_price=11.0,     # 最高价 = 涨停价 → 封板
    low_price=10.2,
    pre_close=10.0,
    volume=50000,
    avg_volume=20000,
    symbol="000001.SZ",
)
print(move_type)  # LimitMoveType.LIMIT_UP

# 炸板示例
move_type = classify_limit_move(
    open_price=10.5,
    close_price=10.8,    # 收盘未封住
    high_price=11.0,     # 但最高价触及涨停
    low_price=10.2,
    pre_close=10.0,
    volume=80000,
    avg_volume=20000,
    symbol="000001.SZ",
)
print(move_type)  # LimitMoveType.BREAK_LIMIT_UP
```

### 6.3 批量涨跌停检测

```python
import pandas as pd
from uniquant.shared.a_share_rules import detect_limit_moves

df = pd.read_parquet("data/daily/000001.SZ.parquet")
moves = detect_limit_moves(df, symbol="000001.SZ", lookback=20)

for m in moves:
    print(f"{m.date}: {m.move_type.value} @ {m.price} ({m.volume_level.value})")
```

### 6.4 量能分类

```python
import pandas as pd
from uniquant.shared.a_share_rules import classify_volume, VolumeLevel

volume_series = pd.Series([10000, 12000, 11000, 9000, 15000] * 6)  # 30 个数据点

level = classify_volume(volume=30000, volume_series=volume_series)
print(level)  # VolumeLevel.EXTREME_HIGH (30000 / ~11400 ≈ 2.6)

level = classify_volume(volume=5000, volume_series=volume_series)
print(level)  # VolumeLevel.EXTREME_LOW
```

### 6.5 T+1 风险评估

```python
from uniquant.shared.a_share_rules import assess_t1_risk, T1RiskLevel

# 安全场景
result = assess_t1_risk(entry_price=10.0, support_low=9.8)
print(result.risk_level)          # T1RiskLevel.SAFE
print(result.max_drawdown_pct)    # 2.0
print(result.description)         # "极限回撤2.0%，安全"

# 超限场景
result = assess_t1_risk(entry_price=10.0, support_low=9.3)
print(result.risk_level)          # T1RiskLevel.EXCEEDED

# 带流动性警告
result = assess_t1_risk(
    entry_price=10.0,
    support_low=9.7,
    recent_limit_moves=[{"price": 9.65, "type": "跌停"}],
)
print(result.liquidity_warning)   # "流动性风险警告：止损位附近有跌停记录..."
```

### 6.6 智能止损

```python
from uniquant.shared.a_share_rules import compute_stop_loss

result = compute_stop_loss(key_low=9.50)
print(result.stop_loss_price)     # 9.452
print(result.precision_warning)   # True (止损幅度 0.5% < 1.5%)
print(result.stop_logic)          # "关键低点9.50×0.995=9.45"

# 带流动性警告
result = compute_stop_loss(
    key_low=9.50,
    recent_limit_moves=[{"price": 9.40, "type": "跌停"}],
)
print(result.liquidity_risk_warning)  # "流动性风险警告：..."
```

---

## 7. 迁移计划

### 7.1 Phase 0: 创建模块

1. 创建 `src/uniquant/shared/a_share_rules.py`
2. 实现所有接口（从现有代码提取，不引入新依赖）
3. 编写单元测试 `tests/test_a_share_rules.py`

### 7.2 Phase 1: 兼容层

1. 改写 `src/uniquant/shared/limits.py` 指向 `a_share_rules`
2. 改写 `src/uniquant/shared/limit_checker.py` 内部调用 `a_share_rules`
3. 保留所有旧接口签名，确保零破坏性

```python
# limits.py 改写后
from .a_share_rules import (
    check_limit_status,
    LimitStatus,
    LimitMoveType,
    LimitMove,
)

# 兼容旧接口
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

### 7.3 Phase 2: 迁移调用方

1. `brain/wyckoff/classifiers.py` 中的 `detect_limit_moves` 迁移到 `a_share_rules`
2. `brain/wyckoff/rules.py` 中的 `rule3_t1_risk_test` 和 `rule10_stop_loss` 委托给 `a_share_rules`
3. 更新 `brain/wyckoff/models.py` 中的 `LimitMoveType` 和 `VolumeLevel` 为 `a_share_rules` 的别名

### 7.4 Phase 3: 清理

1. 移除 `limit_checker.py` 中的重复逻辑（保留兼容层）
2. 统一 `market_rules.py` 的 `BoardType` 枚举为 `a_share_rules` 的别名
3. 更新 `shared/__init__.py` 导出

### 7.5 迁移检查清单

```bash
# 1. 导入链验证
python -c "from uniquant.shared.a_share_rules import detect_board, check_limit_status; print('OK')"

# 2. 兼容层验证
python -c "from uniquant.shared.limits import is_limit_up, is_limit_down; print('OK')"

# 3. Wyckoff 引擎验证
python -c "from uniquant.brain.wyckoff.classifiers import detect_limit_moves; print('OK')"

# 4. 全量测试
pytest tests/test_a_share_rules.py -xvs
pytest tests/test_engine_factory.py -xvs

# 5. Lint
ruff check src/uniquant/shared/a_share_rules.py
```

---

## 8. 测试策略

### 8.1 单元测试覆盖

| 测试类 | 覆盖函数 | 用例数 |
|--------|----------|--------|
| `TestDetectBoard` | `detect_board()` | 15+ (所有板块 + ST + 无后缀 + 边界) |
| `TestGetLimitRatio` | `get_limit_ratio()` | 6 (每板块 1 个) |
| `TestCheckLimitStatus` | `check_limit_status()` | 10+ (涨停/跌停/正常/无效输入) |
| `TestClassifyLimitMove` | `classify_limit_move()` | 8 (封板/炸板/跌停/撬板/无) |
| `TestClassifyVolume` | `classify_volume()` | 5 (每级 1 个 + 边界) |
| `TestAssessT1Risk` | `assess_t1_risk()` | 6 (安全/偏薄/超限/无效/流动性警告) |
| `TestComputeStopLoss` | `compute_stop_loss()` | 5 (正常/精度警告/流动性警告) |
| `TestDetectLimitMoves` | `detect_limit_moves()` | 3 (空 DataFrame/正常/ST) |

### 8.2 关键测试用例

```python
class TestClassifyLimitMove:
    """封板/炸板分类测试"""

    def test_limit_up_sealed(self):
        """收盘封住涨停"""
        result = classify_limit_move(
            open_price=10.5, close_price=11.0,
            high_price=11.0, low_price=10.2,
            pre_close=10.0, volume=50000, avg_volume=20000,
            symbol="000001.SZ",
        )
        assert result == LimitMoveType.LIMIT_UP

    def test_break_limit_up(self):
        """炸板：盘中触及涨停但收盘未封住"""
        result = classify_limit_move(
            open_price=10.5, close_price=10.8,
            high_price=11.0, low_price=10.2,
            pre_close=10.0, volume=80000, avg_volume=20000,
            symbol="000001.SZ",
        )
        assert result == LimitMoveType.BREAK_LIMIT_UP

    def test_limit_down_sealed(self):
        """收盘封住跌停"""
        result = classify_limit_move(
            open_price=9.5, close_price=9.0,
            high_price=9.6, low_price=9.0,
            pre_close=10.0, volume=50000, avg_volume=20000,
            symbol="000001.SZ",
        )
        assert result == LimitMoveType.LIMIT_DOWN

    def test_st_limit_5pct(self):
        """ST 股票 ±5% 涨跌停"""
        result = classify_limit_move(
            open_price=10.3, close_price=10.5,
            high_price=10.5, low_price=10.0,
            pre_close=10.0, volume=50000, avg_volume=20000,
            symbol="000001.SZ", name="*ST 新海",
        )
        assert result == LimitMoveType.LIMIT_UP

    def test_star_limit_20pct(self):
        """科创板 ±20% 涨跌停"""
        result = classify_limit_move(
            open_price=110.0, close_price=120.0,
            high_price=120.0, low_price=108.0,
            pre_close=100.0, volume=50000, avg_volume=20000,
            symbol="688001.SH",
        )
        assert result == LimitMoveType.LIMIT_UP
```

---

## 9. A 股约束速查表

| 板块 | 代码前缀 | 涨跌停比例 | 最小交易单位 | 价格笼子 |
|------|----------|-----------|-------------|---------|
| 上交所主板 | 600/601/603/605 | ±10% | 100 股 | ±2% |
| 深交所主板 | 000/001/002 | ±10% | 100 股 | ±2% |
| 创业板 | 300/301/302 | ±20% | 100 股 | ±1% |
| 科创板 | 688/689 | ±20% | 200 股 | ±1% |
| 北交所 | 8xx/4xx | ±30% | 100 股 | ±1% |
| ST 股 | 名称含 ST/*ST | ±5% | 100 股 | ±1% |

---

## 10. 待决事项

| # | 问题 | 建议 | 状态 |
|---|------|------|------|
| 1 | `market_rules.py` 的 `BoardType` 枚举与新模块重复 | 新模块的 `BoardType` 作为主定义，`market_rules` 改为别名 | 待确认 |
| 2 | `limit_checker.py` 的 `validate_trade_action` 是否迁移 | 保留在 `limit_checker.py`，调用 `a_share_rules` | 待确认 |
| 3 | 北交所代码前缀 `8`/`4` 可能误匹配 | 增加长度校验（6 位数字） | 待确认 |
| 4 | `classifiers.py:246` 的硬编码前缀列表是否扩展 | 统一使用 `detect_board` + `BOARD_RULES` | 待确认 |
| 5 | 是否需要支持港股/美股扩展 | 当前仅 A 股，预留 `BoardType.UNKNOWN` | 待确认 |
| 6 | `LimitStatus` 使用 `frozen=True` 为破坏性变更 | 现有 `limit_checker.LimitStatus` 为普通 `@dataclass`，如有代码修改字段会引发 `FrozenInstanceError` | 待确认 |

---

*文档版本: v1.0 | 基于 limit_checker.py, market_rules.py, classifiers.py, rules.py 源码分析*
