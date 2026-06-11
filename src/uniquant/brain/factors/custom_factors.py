# src/brain/factors/custom_factors.py
from .registry import FactorRegistry
import pandas as pd
import numpy as np


def compute_momentum_20d(df: pd.DataFrame) -> pd.Series:
    """20日动量因子 (收益率)"""
    if 'close' not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    return df['close'].pct_change(20, fill_method=None)


def compute_momentum_60d(df: pd.DataFrame) -> pd.Series:
    """60日动量因子 (收益率)"""
    if 'close' not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    return df['close'].pct_change(60, fill_method=None)


def compute_volatility_20d(df: pd.DataFrame) -> pd.Series:
    """20日波动率因子"""
    if 'close' not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    returns = df['close'].pct_change(fill_method=None)
    return returns.rolling(window=20).std() * np.sqrt(252)


def compute_volatility_60d(df: pd.DataFrame) -> pd.Series:
    """60日波动率因子"""
    if 'close' not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    returns = df['close'].pct_change(fill_method=None)
    return returns.rolling(window=60).std() * np.sqrt(252)


def compute_ma_ratio_5_20(df: pd.DataFrame) -> pd.Series:
    """5日/20日均线比率"""
    if 'close' not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    ma5 = df['close'].rolling(window=5).mean()
    ma20 = df['close'].rolling(window=20).mean()
    return ma5 / ma20.replace(0, np.nan) - 1


def compute_ma_ratio_10_60(df: pd.DataFrame) -> pd.Series:
    """10日/60日均线比率"""
    if 'close' not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    ma10 = df['close'].rolling(window=10).mean()
    ma60 = df['close'].rolling(window=60).mean()
    return ma10 / ma60.replace(0, np.nan) - 1


def compute_volume_ratio_5_20(df: pd.DataFrame) -> pd.Series:
    """5日/20日成交量比率"""
    if 'volume' not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    vol5 = df['volume'].rolling(window=5).mean()
    vol20 = df['volume'].rolling(window=20).mean()
    return vol5 / vol20.replace(0, np.nan) - 1


def compute_rsi_14(df: pd.DataFrame) -> pd.Series:
    """14日RSI因子"""
    if 'close' not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_price_position_20d(df: pd.DataFrame) -> pd.Series:
    """20日价格位置 (当前价格在20日高低点中的位置)"""
    if 'close' not in df.columns or 'high' not in df.columns or 'low' not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    high_20 = df['high'].rolling(window=20).max()
    low_20 = df['low'].rolling(window=20).min()
    denominator = (high_20 - low_20).replace(0, np.nan)
    return (df['close'] - low_20) / denominator


# ─── 逻辑因子: 四大金刚 (2026-06-09) ─────────────────────────────────────────


def compute_illiq_20d(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    ILLIQ因子 (Amihud非流动性指标)

    金融微观结构假设:
    - Amihud (2002): ILLIQ 度量单位交易额(元)产生的价格冲击幅度
    - 流动性越差的股票, 做市商和投资者承担的交易成本风险越高,
      因此需要更高的预期收益作为补偿 (流动性风险溢价)
    - 计算: mean(|r_t| / amount_t) over past 20 days, scaled by 1e9
    - 横截面预测方向: 做多高ILLIQ(低流动性)股票, 做空低ILLIQ(高流动性)股票
    - IC预期: 正值 (高ILLIQ → 高未来收益)
    """
    if "close" not in df.columns or "amount" not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    returns = df["close"].pct_change(fill_method=None).abs()
    illiq = returns / df["amount"].replace(0, np.nan)
    return illiq.rolling(window=20, min_periods=10).mean() * 1e9


def compute_pv_divergence_20d(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    量价背离因子 (Price-Volume Divergence)

    金融微观结构假设:
    - 有效市场中, 价格上涨应有成交量放大配合 (参与方共识增强)
    - 当价格创新高但成交量萎缩时, 表明买方力量衰竭, 趋势难以持续
    - 这是技术分析中"价量背离"的量化表达, 捕捉短期反转信号
    - 计算: 过去20日收盘价百分位秩 - 过去20日成交量百分位秩
    - 正值 = 价格在高位但量能在萎缩 = 卖出信号
    - 横截面预测方向: 做空高背离(价升量缩)股票
    - IC预期: 负值 (高背离 → 低未来收益)
    """
    if "close" not in df.columns or "volume" not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    close_rank = df["close"].rolling(window=20).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1] if len(x) >= 5 else np.nan
    )
    vol_rank = df["volume"].rolling(window=20).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1] if len(x) >= 5 else np.nan
    )
    return vol_rank - close_rank


def compute_cs_momentum_20d(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    横截面动量因子 (Cross-Sectional Momentum)

    金融微观结构假设:
    - 中期动量(3-12月)与短期反转(1-4周)由不同微观机制驱动:
      * 短期反转: 做市商补偿、买卖报价反弹、对新闻过度反应后的修正
      * 中期动量: 信息渐近扩散、机构投资者的订单拆分、趋势追随行为
    - 通过 (1+r20d)/(1+r5d)-1, 从20日动量中精确复利剥离短期反转成分
    - 相比一阶近似 r20-r5, 复利剥离公式在回报率不对称时(大涨/大跌)
      消除 r5 的百分比基数效应, 使因子测度真正正交于短期收益
    - 计算: (1 + past_20d_return) / (1 + past_5d_return) - 1
    - 横截面预测方向: 做多高CSMOM(中期动量强)股票
    - IC预期: 正值 (高CSMOM → 高未来收益)
    """
    if "close" not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    r20 = df["close"].pct_change(20, fill_method=None)
    r5 = df["close"].pct_change(5, fill_method=None)
    denom = r5.replace(-1.0, np.nan)
    return (1 + r20) / (1 + denom) - 1


def compute_idiosyncratic_vol_20d(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    特质波动率因子 (Idiosyncratic Volatility)

    金融微观结构假设:
    - Ang, Hodrick, Xing & Zhang (2006):
      高特质波动率股票具有异常低的预期收益
    - 原因: "彩票需求"效应 — 投资者为高IVOL股票支付溢价
      (类似购买彩票的快感), 导致这些股票初始定价过高, 后续收益低迷
    - IVOL 捕获与市场正交的公司特质风险
    - 计算: 用20日窗口回归日收益率对市场收益率的残差波动率
      简化实现: 日收益减5日滚动均值后的20日波动率
    - 横截面预测方向: 做空高IVOL(特质波动大)股票
    - IC预期: 正值 (我们取-IVOL, 高因子值=低IVOL=高未来收益)
    """
    if "close" not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    returns = df["close"].pct_change(fill_method=None)
    local_trend = returns.rolling(window=5).mean()
    residual = returns - local_trend
    ivol = residual.rolling(window=20, min_periods=10).std() * np.sqrt(252)
    return -ivol  # 取负: 高因子值=低IVOL=做多信号


def compute_turnover_momentum_20d(df: pd.DataFrame) -> pd.Series:
    """20日换手率动量因子"""
    if "volume" not in df.columns:
        return pd.Series(index=df.index, dtype=float)

    if "turnover" in df.columns:
        turnover = df["turnover"]
    elif "turnover_rate" in df.columns:
        turnover = df["turnover_rate"]
    elif "turnover_rate_f" in df.columns:
        turnover = df["turnover_rate_f"]
    elif "circulating_market_cap" in df.columns and "close" in df.columns:
        turnover = df["volume"] * df["close"] / df["circulating_market_cap"].replace(0, np.nan)
    elif "circulating_market_cap" in df.columns and "amount" in df.columns:
        turnover = df["amount"] / df["circulating_market_cap"].replace(0, np.nan)
    else:
        return pd.Series(index=df.index, dtype=float)
    return turnover.pct_change(20, fill_method=None)


def register_all() -> None:
    """Register all custom factors with the FactorRegistry."""
    FactorRegistry.register(
        name="momentum_20d",
        compute_func=compute_momentum_20d,
        category="technical",
        default_weight=1.0,
        description="20日动量因子 (收益率)"
    )

    FactorRegistry.register(
        name="momentum_60d",
        compute_func=compute_momentum_60d,
        category="technical",
        default_weight=0.9,
        description="60日动量因子 (收益率)"
    )

    FactorRegistry.register(
        name="volatility_20d",
        compute_func=compute_volatility_20d,
        category="technical",
        default_weight=0.8,
        description="20日波动率因子"
    )

    FactorRegistry.register(
        name="volatility_60d",
        compute_func=compute_volatility_60d,
        category="technical",
        default_weight=0.7,
        description="60日波动率因子"
    )

    FactorRegistry.register(
        name="ma_ratio_5_20",
        compute_func=compute_ma_ratio_5_20,
        category="technical",
        default_weight=0.85,
        description="5日/20日均线比率"
    )

    FactorRegistry.register(
        name="ma_ratio_10_60",
        compute_func=compute_ma_ratio_10_60,
        category="technical",
        default_weight=0.75,
        description="10日/60日均线比率"
    )

    FactorRegistry.register(
        name="volume_ratio_5_20",
        compute_func=compute_volume_ratio_5_20,
        category="technical",
        default_weight=0.6,
        description="5日/20日成交量比率"
    )

    FactorRegistry.register(
        name="rsi_14",
        compute_func=compute_rsi_14,
        category="technical",
        default_weight=0.8,
        description="14日RSI因子"
    )

    FactorRegistry.register(
        name="price_position_20d",
        compute_func=compute_price_position_20d,
        category="technical",
        default_weight=0.7,
        description="20日价格位置因子"
    )

    FactorRegistry.register(
        name="turnover_momentum_20d",
        compute_func=compute_turnover_momentum_20d,
        category="technical",
        default_weight=0.85,
        description="20日换手率动量因子"
    )

    # ─── 四大逻辑因子注册 (2026-06-09) ─────────────────────────────────────
    FactorRegistry.register(
        name="illiq_20d",
        compute_func=compute_illiq_20d,
        category="custom",
        default_weight=1.0,
        description="ILLIQ因子 | Amihud非流动性: mean(|r|/amt) 20d, 做多低流动性溢价"
    )
    FactorRegistry.register(
        name="pv_divergence_20d",
        compute_func=compute_pv_divergence_20d,
        category="custom",
        default_weight=1.0,
        description="量价背离因子 | 价创新高量萎缩: rank(vol)-rank(close), 做空背离"
    )
    FactorRegistry.register(
        name="cs_momentum_20d",
        compute_func=compute_cs_momentum_20d,
        category="custom",
        default_weight=1.0,
        description="横截面动量因子 | (1+r20d)/(1+r5d)-1, 复利剥离短期反转后的纯动量"
    )
    FactorRegistry.register(
        name="idiosyncratic_vol_20d",
        compute_func=compute_idiosyncratic_vol_20d,
        category="custom",
        default_weight=1.0,
        description="特质波动率因子 | -IVOL: 残差波动率, 做空高IVOL彩票股"
    )


register_all()
