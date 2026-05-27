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
