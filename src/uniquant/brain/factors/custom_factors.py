# src/brain/factors/custom_factors.py
from .registry import FactorRegistry
import pandas as pd
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view


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


def _rolling_rank_pct_last(s: pd.Series, window: int = 20) -> pd.Series:
    """滚动窗口内最后一个值在窗口内的百分位秩 (pandas rank pct=True 等价)。

    原实现 rolling().apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1])
    每窗口构造一个 Series, 50 只股票 ~77s (占全因子计算 99%)。
    用 sliding_window_view 向量化, 语义逐位等价 (含平均秩处理 ties + NaN 掩码)。
    """
    vals = s.to_numpy(dtype=float)
    n = len(vals)
    out = np.full(n, np.nan)
    if n < window:
        return pd.Series(out, index=s.index)
    win = sliding_window_view(vals, window)
    last = win[:, -1]
    has_nan = np.isnan(win).any(axis=1)
    less = np.sum(win < last[:, None], axis=1)
    equal = np.sum(win == last[:, None], axis=1)
    rank_pct = (less + (equal + 1) / 2.0) / window
    out[window - 1:] = np.where(has_nan, np.nan, rank_pct)
    return pd.Series(out, index=s.index)


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
    close_rank = _rolling_rank_pct_last(df["close"], window=20)
    vol_rank = _rolling_rank_pct_last(df["volume"], window=20)
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


# ─── 逻辑驱动因子方向族 (2026-08-19) ──────────────────────────────────
# 文献调研见 docs/analysis/LOGIC_FACTOR_RESEARCH_PLAN.md
# P1 基线确认仅 2 因子正 OOS IC (illiq_20d +0.070, idio_vol +0.075),
# P2 GP 挖掘 0/25 幸存 → 转向有金融学理论支撑的逻辑因子。


def compute_max_ret_20d(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    MAX 效应因子 (Bali, Cakici & Whitelaw 2011)

    彩票偏好理论: 投资者对"彩票型"股票(过去曾出现极端正收益)
    有过度需求, 推高当前价格, 导致未来收益偏低。
    MAX = 过去 20 日最大日收益率。
    因子值 = MAX (高 MAX = 彩票偏好 = 预期低收益)。
    IC 预期: 负值 (高 MAX → 低未来收益)。
    """
    if "close" not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    ret = df["close"].pct_change(fill_method=None)
    return ret.rolling(window=20, min_periods=10).max()


def compute_reversal_1d(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    1 日反转因子 (Jegadeesh 1990)

    短期反转: 微观结构噪声(买卖报价反弹、做市商补偿)导致
    日度收益负自相关。A 股个人投资者占比高, 追涨杀跌行为
    更突出, 反转效应较美股更显著。
    因子值 = −1 × 昨日收益率 (高因子值 = 昨日跌 = 预期今日涨)。
    IC 预期: 正值 (昨日跌 → 今日涨)。
    """
    if "close" not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    return -df["close"].pct_change(1, fill_method=None)


def compute_amivest_20d(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    Amivest 流动性比率因子

    Amivest (1970s) 是最早的流动性度量之一, 与 Amihud ILLIQ 反号:
    Amivest = 单位价格变动所承载的成交额, 值越高 = 流动性越好。
    ILLIQ 度量"非流动性"(价格冲击), Amivest 度量"流动性"(深度)。
    两者包含互补信息, 但方向相反。
    因子值 = mean(amount / |r|, 20d)。
    IC 预期: 负值 (高流动性 → 低收益, 流动性溢价的反面)。
    """
    if "close" not in df.columns or "amount" not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    ret_abs = df["close"].pct_change(fill_method=None).abs()
    ret_abs = ret_abs.clip(lower=1e-10)
    ratio = df["amount"] / ret_abs
    ratio = ratio.replace([np.inf, -np.inf], np.nan)
    return ratio.rolling(window=20, min_periods=10).mean()


def compute_range_20d(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    20 日价格区间比因子

    高波动股票的溢价补偿: 用 H/L 区间替代标准差度量波动率,
    对极端值更稳健 (Parkinson 1980 极差波动率近似)。
    因子值 = (max_high_20d - min_low_20d) / close。
    IC 预期: 正值 (高波动 → 高风险溢价 → 高收益)。
    """
    if "close" not in df.columns or "high" not in df.columns or "low" not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    high_max = df["high"].rolling(window=20, min_periods=10).max()
    low_min = df["low"].rolling(window=20, min_periods=10).min()
    return (high_max - low_min) / df["close"].replace(0, np.nan)


def compute_skew_20d(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    日收益率偏度因子

    彩票偏好的另一代理变量 (Kumar 2009): 高正偏度 = 右尾厚 =
    彩票需求强 = 当前定价过高 = 未来收益低。
    因子值 = 过去 20 日日收益率偏度。
    IC 预期: 负值 (高正偏度 → 低未来收益)。
    """
    if "close" not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    ret = df["close"].pct_change(fill_method=None)
    return ret.rolling(window=20, min_periods=10).skew()


def compute_reversal_5d(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    5 日反转因子

    周度反转: A 股个人投资者周度追涨杀跌行为更显著。
    因子值 = −1 × 过去 5 日收益率。
    P1 基线 momentum_20d 的 OOS IC = -0.062, 暗示 20d 反转成立,
    5d 反转预期更强。
    IC 预期: 正值 (过去 5 日跌 → 未来 5 日涨)。
    """
    if "close" not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    return -df["close"].pct_change(5, fill_method=None)


def compute_reversal_20d(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    20 日反转因子

    P1 基线 momentum_20d 的 OOS IC = -0.062, 说明 20d 动量实际
    为负即反转成立。本因子显式取负, 使方向与预期一致。
    因子值 = −1 × 过去 20 日收益率。
    IC 预期: 正值 (过去 20 日跌 → 未来 5 日涨)。
    """
    if "close" not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    return -df["close"].pct_change(20, fill_method=None)


def compute_neg_range_20d(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    取反的 20 日价格区间比因子 (反彩票效应)

    range_20d 的 IC 为 -0.0625, 方向与理论预期相反:
    高波动→低收益 (反彩票解释, Ang et al. 2006)。
    取反后 IC 为正, 对应反彩票效应: 低波动股票未来收益高。
    因子值 = −(max_high_20d - min_low_20d) / close。
    IC 预期: 正值 (低波动 → 高收益, 反彩票)。
    """
    if "close" not in df.columns or "high" not in df.columns or "low" not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    high_max = df["high"].rolling(window=20, min_periods=10).max()
    low_min = df["low"].rolling(window=20, min_periods=10).min()
    return -(high_max - low_min) / df["close"].replace(0, np.nan)


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
    elif "free_float_shares" in df.columns:
        # P11 (2026-08-26): 经 bridge extra_fields 合并 自由流通股(股) 后可算
        turnover = df["volume"] / df["free_float_shares"].replace(0, np.nan)
    else:
        return pd.Series(index=df.index, dtype=float)
    return turnover.pct_change(20, fill_method=None)


# ─── 基本面价值/质量因子族 (2026-08-26, P11) ──────────────────────────────
# 前置条件: 日线主表先经 FinancialFactorBridge.process(extra_fields=...) 合并财务列;
# 缺列时返回全 NaN Series (与 turnover_momentum_20d 缺 turnover 列同先例)。
# 预注册文档: docs/analysis/FUNDAMENTAL_FACTOR_PREREGISTRATION.md
# 注: 日线湖为不复权原始价, 财务字段为披露时点名义值 → 比值口径时点正确。


def _fundamental_ratio(
    df: pd.DataFrame, numer_cols: list[str], denom_col: str,
    require_positive_denom: bool = True,
) -> pd.Series:
    """基本面比值通用助手: 分子线性组合 ÷ 分母, 缺列/除零返回 NaN。"""
    missing = [c for c in (*numer_cols, denom_col) if c not in df.columns]
    if missing:
        return pd.Series(index=df.index, dtype=float)
    numer = df[numer_cols[0]].astype(float)
    for col in numer_cols[1:]:
        numer = numer - df[col].astype(float)  # 仅支持两列相减 (rev-cost 形态)
    denom = df[denom_col].astype(float).replace(0, np.nan)
    if require_positive_denom:
        denom = denom.where(denom > 0)
    return numer / denom


def compute_ep_ttm(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    EP 因子: 盈利收益率 = EPS_TTM / 收盘价

    金融学假设:
    - Fama-French (1992/1993): 高 E/P 股票未来收益更高 (价值溢价)
    - 行为解释: 投资者对成长股过度外推, 对低估值股票系统性低估
    - 相比 PE 倒数形式的优势: 亏损股 (EPS<0) 自然得到负 EP 排序靠后,
      无需剔除或截断
    - IC 预期: 正值 (高 EP → 高未来收益)
    """
    return _fundamental_ratio(df, ["eps_ttm"], "close", require_positive_denom=False)


def compute_bp(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    BP 因子: 账面市值比 = BPS / 收盘价

    金融学假设:
    - Fama-French HML 的直接代理; 高 B/P = 市场对其净资产定价低
    - 风险解释: 高 B/P 公司多处于财务困境, 要求风险补偿
    - IC 预期: 正值 (高 BP → 高未来收益)
    """
    return _fundamental_ratio(df, ["bps"], "close", require_positive_denom=False)


def compute_cfp_ttm(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    CFP 因子: 现金流收益率 = OCF_PS_TTM / 收盘价

    金融学假设:
    - Lakonishok, Shleifer & Vishny (1994): 现金流 yield 优于盈利 yield —
      现金流更难被盈余管理操纵
    - 与 EP 组合可分离"应计虚增"与"真实现金创造"
    - IC 预期: 正值 (高 CFP → 高未来收益)
    """
    return _fundamental_ratio(df, ["ocf_ps_ttm"], "close", require_positive_denom=False)


def compute_sp_ttm(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    SP 因子: 销售收益率 = Revenue_TTM / (收盘价 × 总股本)

    金融学假设:
    - Barbee, Mukherji & Raines (1996): S/P 在美国市场预测力优于 B/P
    - 营收比利润更难操纵, 且对周期底部亏损股仍有定义
    - IC 预期: 正值 (高 SP → 高未来收益)
    """
    if not {"revenue_ttm", "total_shares", "close"} <= set(df.columns):
        return pd.Series(index=df.index, dtype=float)
    market_cap = (
        df["close"].astype(float) * df["total_shares"].astype(float).where(
            lambda x: x > 0
        )
    ).replace(0, np.nan)
    return df["revenue_ttm"].astype(float) / market_cap


def compute_gross_profitability(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    毛利盈利能力因子 = (Revenue_TTM − Operating_Cost_TTM) / 总资产

    金融学假设:
    - Novy-Marx (2013): 毛利/资产是盈利质量最纯净的度量 — 毛利在利润表
      上游, 远离应计操纵; G/P 高的公司每单位资产创造更多经济租金
    - ⚠️ 对立假设 (预注册登记): 本项目 P5 实测 roe@fwd63 IC=-0.0780、
      P6 实测 roe 在 trend_on|vol_low +0.029 vs vol_high −0.129 翻转 →
      A 股该窗口"质量溢价"整体存疑, GP 可能整体无效甚至负向
    - IC 预期: 正值; 若整体 ≤0 则按对立假设记录, 不改判
    """
    return _fundamental_ratio(df, ["revenue_ttm", "operating_cost_ttm"], "total_assets")


def compute_accruals(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    应计因子 = (归母净利_TTM − OCF_TTM) / 总资产

    金融学假设:
    - Sloan (1996): 应计异象 — 利润中现金含量低 (高应计) 的公司,
      未来收益系统性更低 (应计不可持续 + 盈余管理信号)
    - A 股盈余管理普遍, 该效应可能更强
    - IC 预期: 负值 (高应计 → 低未来收益)
    """
    if not {"net_profit_parent_ttm", "ocf_ttm", "total_assets"} <= set(df.columns):
        return pd.Series(index=df.index, dtype=float)
    assets = df["total_assets"].astype(float).replace(0, np.nan).where(lambda x: x > 0)
    return (df["net_profit_parent_ttm"].astype(float)
            - df["ocf_ttm"].astype(float)) / assets


def compute_turnover_20d(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    20 日平均换手率因子 = mean(volume / 自由流通股, 20d)

    金融学假设:
    - Datar, Naik & Radcliffe (1998): 高换手率股票流动性大、
      投资者过度交易/追捧, 未来收益低 (换手率异象)
    - 自由流通股来自最近季报快照 (merge_asof backward), 季内近似恒定
    - IC 预期: 负值 (高换手 → 低未来收益); 与 illiq_20d 反号但信息源不同
      (交易活跃度 vs 价格冲击)
    """
    if not {"volume", "free_float_shares"} <= set(df.columns):
        return pd.Series(index=df.index, dtype=float)
    turnover = df["volume"].astype(float) / df["free_float_shares"].astype(float).replace(0, np.nan)
    return turnover.rolling(window=20, min_periods=10).mean()


# ─── P12 尾部风险因子族 (2026-08-26) ──────────────────────────────────────
# 预注册: docs/analysis/P12_PREREGISTRATION_TAIL_CHIP_FACTORS.md


def compute_cvar_95_60d(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    CVaR 因子: 60 日窗内最差 5% 日收益均值 (≈最差 3 日均值, 左尾预期损失)

    金融学假设:
    - Kelly & Jiang (2014): 尾部风险横截面有正溢价; Atilgan et al. (2020) 国际证据
    - 对立假设 (预注册登记): 若 IVOL/反彩票主导则高左尾=低未来收益
      (vol_60d IC=-0.104 先例同向)
    - IC 预期: 正值 (深左尾 → 高补偿)
    """
    if "close" not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    rets = df["close"].pct_change(fill_method=None)

    def _cvar(x: np.ndarray) -> float:
        vals = x[~np.isnan(x)]
        if len(vals) < 30:
            return np.nan
        k = max(1, int(np.ceil(0.05 * len(vals))))
        return float(np.sort(vals)[:k].mean())

    return rets.rolling(window=60, min_periods=40).apply(_cvar, raw=True)


def compute_max_drawdown_20d(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    最大回撤因子: 20 日窗内峰谷最大跌幅 (≤0, 越深越负)

    金融学假设:
    - De Bondt & Thaler (1985) 过度反应: 深跌股被系统性超卖 → 未来反弹
    - 与 reversal 族同向但度量路径依赖下行深度 (信息源不同)
    - IC 预期: 正值 (更深回撤 → 更高未来收益); 对立假设: 崩盘延续为负
    """
    if "close" not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    close = df["close"].astype(float).to_numpy()
    n = len(close)
    out = np.full(n, np.nan)
    w = 20
    if n < w:
        return pd.Series(out, index=df.index)
    win = sliding_window_view(close, w)
    valid = (~np.isnan(win)).all(axis=1) & (win > 0).all(axis=1)
    peak = np.where(np.isnan(win), -np.inf, win)
    peak = np.maximum.accumulate(peak, axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        mdd = np.where(win > 0, win / peak - 1.0, np.nan).min(axis=1)
    out[w - 1:] = np.where(valid, mdd, np.nan)
    return pd.Series(out, index=df.index)


def compute_downside_semivol_20d(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    下行半波动因子: √(mean(r² | r<0)) × √252

    金融学假设:
    - Ang et al. (2006): 下行风险与 IVOL 同族 — 高下行波动股票被彩票需求
      推高定价, 未来收益低 (本项目 vol_60d IC=-0.104 同向先例)
    - 半偏差形式对少数极端亏损日稳健 (区别于仅统计负收益日的 std)
    - IC 预期: 负值 (高下行半波动 → 低未来收益)
    """
    if "close" not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    rets = df["close"].pct_change(fill_method=None)
    neg_sq = rets.where(rets < 0, 0.0) ** 2
    return np.sqrt(neg_sq.rolling(window=20, min_periods=15).mean()) * np.sqrt(252)


def compute_kurtosis_20d(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    峰度因子: 20 日日收益超额峰度 (pandas 样本 kurtosis)

    金融学假设:
    - 彩票偏好族: 投资者对肥尾分布 (小概率大涨大跌) 过度需求,
      推高当期价格 → 未来低收益 (Bali et al. 2011 MAX/skew 同族扩展)
    - IC 预期: 负值 (高峰度 → 低未来收益)
    """
    if "close" not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    rets = df["close"].pct_change(fill_method=None)
    return rets.rolling(window=20, min_periods=15).kurt()


# ─── P12 筹码结构因子族 (2026-08-26) ──────────────────────────────────────
# 输入列由测试脚本在季频财务帧上派生 q-o-q 变化率后经 bridge extra_fields 合并;
# 缺列全 NaN (先例安全)。分母口径陷阱见预注册 §2 Batch B 设计说明。


def _chip_passthrough(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce")


def compute_holder_num_chg_1q(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    股东户数变化因子: ln(股东人数) 季度环比变化率 (季报快照 PIT)

    金融学假设:
    - 户数增加 = 筹码分散 = 散户接盘 → 未来收益低 (Dhar & Zhu 2006 散户偏好;
      A 股筹码集中度实证主流方向)
    - IC 预期: 负值 (户数增 → 看跌)
    """
    return _chip_passthrough(df, "holder_num_chg_1q")


def compute_inst_shares_chg_1q(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    机构持股变化因子: 机构持股总量季度环比变化率

    金融学假设:
    - 机构净增持 = 知情交易者流入 → 未来收益高 (Nofsinger & Sias 1999;
      A 股机构增减持信号效应)
    - ⚠️ 口径: 总量含被动指数成分, 且生效走保守披露偏移路径
    - IC 预期: 正值 (机构增持 → 看涨)
    """
    return _chip_passthrough(df, "inst_shares_chg_1q")


def compute_top10_float_chg_1q(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    大股东持股变化因子: 十大流通股东合计持股季度环比变化率

    金融学假设:
    - 大股东/重要股东增持 = 内部人信号 → 未来收益高
    - IC 预期: 正值 (十大流通增持 → 看涨)
    """
    return _chip_passthrough(df, "top10_float_chg_1q")


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

    # ─── 逻辑驱动因子方向族注册 (2026-08-19) ──────────────────────────────
    FactorRegistry.register(
        name="max_ret_20d",
        compute_func=compute_max_ret_20d,
        category="custom",
        default_weight=1.0,
        description="MAX效应 | 20d最大日收益, 做空高MAX彩票股 (Bali et al. 2011)"
    )
    FactorRegistry.register(
        name="reversal_1d",
        compute_func=compute_reversal_1d,
        category="custom",
        default_weight=1.0,
        description="1日反转 | 做多昨日跌股 (Jegadeesh 1990)"
    )
    FactorRegistry.register(
        name="amivest_20d",
        compute_func=compute_amivest_20d,
        category="custom",
        default_weight=1.0,
        description="Amivest流动性比率 | mean(amt/|r|), 做空高流动性股"
    )
    FactorRegistry.register(
        name="range_20d",
        compute_func=compute_range_20d,
        category="custom",
        default_weight=1.0,
        description="20d价格区间比 | (maxH-minL)/close, 做多高波动股"
    )
    FactorRegistry.register(
        name="skew_20d",
        compute_func=compute_skew_20d,
        category="custom",
        default_weight=1.0,
        description="20d日收益率偏度 | 做空高正偏度彩票股 (Kumar 2009)"
    )
    FactorRegistry.register(
        name="reversal_5d",
        compute_func=compute_reversal_5d,
        category="custom",
        default_weight=1.0,
        description="5日反转 | 做多过去5日跌股"
    )
    FactorRegistry.register(
        name="reversal_20d",
        compute_func=compute_reversal_20d,
        category="custom",
        default_weight=1.0,
        description="20日反转 | 做多过去20日跌股 (P1基线momentum_20d IC=-0.062暗示)"
    )
    FactorRegistry.register(
        name="neg_range_20d",
        compute_func=compute_neg_range_20d,
        category="custom",
        default_weight=1.0,
        description="取反20d价格区间比 | -(maxH-minL)/close, 反彩票效应 (Ang et al. 2006)"
    )

    # ─── 基本面价值/质量因子族注册 (2026-08-26, P11) ──────────────────────
    # 依赖日线主表预合并财务列 (bridge extra_fields), 缺列时全 NaN
    FactorRegistry.register(
        name="ep_ttm",
        compute_func=compute_ep_ttm,
        category="fundamental",
        default_weight=1.0,
        description="EP盈利收益率 | eps_ttm/close, 做多深度价值 (Fama-French)"
    )
    FactorRegistry.register(
        name="bp",
        compute_func=compute_bp,
        category="fundamental",
        default_weight=1.0,
        description="BP账面市值比 | bps/close, HML代理 (Fama-French 1993)"
    )
    FactorRegistry.register(
        name="cfp_ttm",
        compute_func=compute_cfp_ttm,
        category="fundamental",
        default_weight=1.0,
        description="CFP现金流收益率 | ocf_ps_ttm/close, 抗盈余管理 (LSV 1994)"
    )
    FactorRegistry.register(
        name="sp_ttm",
        compute_func=compute_sp_ttm,
        category="fundamental",
        default_weight=1.0,
        description="SP销售收益率 | revenue_ttm/市值, 营收yield (Barbee 1996)"
    )
    FactorRegistry.register(
        name="gross_profitability",
        compute_func=compute_gross_profitability,
        category="fundamental",
        default_weight=1.0,
        description="毛利盈利能力 | (rev_ttm-cost_ttm)/总资产 (Novy-Marx 2013; 对立假设已登记)"
    )
    FactorRegistry.register(
        name="accruals",
        compute_func=compute_accruals,
        category="fundamental",
        default_weight=1.0,
        description="应计异象 | (归母净利_ttm-ocf_ttm)/总资产, 做多低应计 (Sloan 1996)"
    )
    FactorRegistry.register(
        name="turnover_20d",
        compute_func=compute_turnover_20d,
        category="fundamental",
        default_weight=1.0,
        description="20d平均换手率 | volume/自由流通股, 换手率异象做空高换手 (Datar 1998)"
    )

    # ─── P12 尾部风险因子族注册 (2026-08-26) ──────────────────────────────
    FactorRegistry.register(
        name="cvar_95_60d",
        compute_func=compute_cvar_95_60d,
        category="custom",
        default_weight=1.0,
        description="CVaR左尾 | 60d最差5%日收益均值, 尾部风险溢价 (Kelly-Jiang 2014; 对立假设已登记)"
    )
    FactorRegistry.register(
        name="max_drawdown_20d",
        compute_func=compute_max_drawdown_20d,
        category="custom",
        default_weight=1.0,
        description="20d最大回撤 | 峰谷深度≤0, 过度反应反弹 (De Bondt-Thaler 1985)"
    )
    FactorRegistry.register(
        name="downside_semivol_20d",
        compute_func=compute_downside_semivol_20d,
        category="custom",
        default_weight=1.0,
        description="下行半波动 | √mean(r²|r<0)×√252, IVOL族 (Ang 2006)"
    )
    FactorRegistry.register(
        name="kurtosis_20d",
        compute_func=compute_kurtosis_20d,
        category="custom",
        default_weight=1.0,
        description="超额峰度 | 20d日收益肥尾, 彩票偏好做空 (Bali 2011 同族)"
    )

    # ─── P12 筹码结构因子族注册 (2026-08-26, 需脚本派生列预合并) ────────────
    FactorRegistry.register(
        name="holder_num_chg_1q",
        compute_func=compute_holder_num_chg_1q,
        category="fundamental",
        default_weight=1.0,
        description="股东户数变化 | q-o-q变化率, 户数增=散户化看跌"
    )
    FactorRegistry.register(
        name="inst_shares_chg_1q",
        compute_func=compute_inst_shares_chg_1q,
        category="fundamental",
        default_weight=1.0,
        description="机构持股变化 | 机构持股总量q-o-q变化率, 净增持看涨"
    )
    FactorRegistry.register(
        name="top10_float_chg_1q",
        compute_func=compute_top10_float_chg_1q,
        category="fundamental",
        default_weight=1.0,
        description="十大流通股东变化 | 合计持股q-o-q变化率, 大股东信号"
    )


register_all()
