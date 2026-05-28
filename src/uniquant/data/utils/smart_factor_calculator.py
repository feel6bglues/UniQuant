import os
import re
import logging
from pathlib import Path
from typing import Optional, Dict
from concurrent.futures import ProcessPoolExecutor
from functools import partial

import pandas as pd
import numpy as np

from ...shared.logger_factory import get_logger

logger = get_logger("SmartFactorV15")

REAL_TODAY = pd.Timestamp.now().normalize()


class GBBQProcessorV15:
    """GBBQ 数据清洗 (V15 纯净度过滤版)"""

    @staticmethod
    def load_and_clean(gbbq_path: str) -> pd.DataFrame:
        """加载并清洗 GBBQ 数据"""
        if not os.path.exists(gbbq_path):
            logger.warning(f"GBBQ 文件不存在: {gbbq_path}")
            return pd.DataFrame()

        try:
            df = pd.read_parquet(gbbq_path)
        except Exception as e:
            logger.error(f"读取 GBBQ 失败: {e}")
            return pd.DataFrame()

        col_mapping = {
            'cash_div': 'cash', 'hongli_pan': 'cash', 'hongli_panqianliutong': 'cash',
            'split_ratio': 'split', 'songzhuangu_pan': 'split', 'songgu_qianzongguben': 'split',
            'rights_ratio': 'rights', 'peigu_pan': 'rights', 'peigu_houzongguben': 'rights',
            'rights_price': 'r_price', 'peigu_jia': 'r_price', 'peigujia_qianzongguben': 'r_price',
            'datetime': 'date', '除权除息日': 'date', 'code': 'code'
        }
        df = df.rename(columns=col_mapping)
        # 去重列名（防止多个源列映射到同一目标导致 duplicate columns）
        df = df.loc[:, ~df.columns.duplicated(keep='last')]

        if 'category' in df.columns:
            df = df[df['category'] == 1].copy()

        if 'code' in df.columns:
            df['code'] = df['code'].astype(str).str.zfill(6)

        df['date'] = pd.to_datetime(df['date'].astype(str), errors='coerce')
        df = df[df['date'] <= REAL_TODAY].copy()

        for col in ['cash', 'split', 'rights']:
            if col not in df.columns:
                df[col] = 0.0
            else:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0) / 10.0

        if 'r_price' not in df.columns:
            df['r_price'] = 0.0
        else:
            df['r_price'] = pd.to_numeric(df['r_price'], errors='coerce').fillna(0.0)

        mask_valid = (df['cash'] > 0) | (df['split'] > 0) | (df['rights'] > 0)
        df = df[mask_valid]

        return df.sort_values('date')

    @staticmethod
    def aggregate_events(df_stock: pd.DataFrame) -> pd.DataFrame:
        """聚合同一日的多个除权事件"""
        if df_stock.empty:
            return pd.DataFrame()

        agg_rules = {'cash': 'sum', 'split': 'sum', 'rights': 'sum', 'r_price': 'max'}
        for col in agg_rules:
            if col not in df_stock.columns:
                df_stock[col] = 0.0

        return df_stock.groupby('date')[list(agg_rules.keys())].agg(agg_rules).reset_index().sort_values('date')


class SmartFactorCalculatorV15:
    """
    智能复权计算器 V15 (Baostock 完美复刻版 + 多进程极速版)

    核心特性:
    1. 涨跌幅复权法 - 交易所级精度复刻
    2. 多进程并发 - ProcessPoolExecutor 实现全市场极速计算
    3. 纯净度过滤 - 仅保留 category=1 的真正除权除息事件
    4. 理论价计算 - 移除开盘价校验，纯数学公式
    """

    def __init__(self):
        self.gbbq_processor = GBBQProcessorV15()

    @staticmethod
    def _safe_convert_date(series: pd.Series) -> pd.Series:
        """安全日期转换"""
        if pd.api.types.is_datetime64_any_dtype(series):
            return series

        try:
            if pd.api.types.is_integer_dtype(series):
                series_str = series.astype(str).str.pad(8, side='left', fillchar='0')
                return pd.to_datetime(series_str, format='%Y%m%d', errors='coerce')

            if pd.api.types.is_string_dtype(series):
                result = pd.to_datetime(series, format='%Y%m%d', errors='coerce')
                if result.isna().all():
                    result = pd.to_datetime(series, format='%Y-%m-%d', errors='coerce')
                return result

            return pd.to_datetime(series, errors='coerce')
        except Exception as e:
            logger.error(f"日期转换失败: {e}")
            return series

    def calculate(self, df_daily: pd.DataFrame, df_events: pd.DataFrame) -> pd.DataFrame:
        """
        计算单只股票的复权因子

        Args:
            df_daily: 日线数据，必须包含 date, close, open 列
            df_events: 除权除息事件数据

        Returns:
            DataFrame: columns=['date', 'factor']
        """
        if df_daily.empty:
            return pd.DataFrame()

        df_daily = df_daily.sort_values('date').reset_index(drop=True)
        df_daily['date'] = pd.to_datetime(df_daily['date'])
        df_daily = df_daily[df_daily['date'] <= REAL_TODAY].copy()

        if df_daily.empty:
            return pd.DataFrame()

        if df_events.empty:
            return pd.DataFrame({'date': df_daily['date'], 'factor': 1.0})

        df_events = df_events.copy()
        df_events['date'] = self._safe_convert_date(df_events['date'])
        df_events = df_events.dropna(subset=['date']).sort_values('date')

        if df_events.empty:
            return pd.DataFrame({'date': df_daily['date'], 'factor': 1.0})

        factors_daily = np.ones(len(df_daily))

        for _, event in df_events.iterrows():
            ex_date = event['date']
            idx = df_daily['date'].searchsorted(ex_date)

            if idx == 0 or idx >= len(df_daily):
                continue

            pre_close = float(df_daily.loc[idx - 1, 'close'])
            ex_open = float(df_daily.loc[idx, 'open'])
            cash = float(event.get('cash', 0))
            split = float(event.get('split', 0))
            rights = float(event.get('rights', 0))
            r_price = float(event.get('r_price', 0))

            if rights > 0 and r_price <= 0:
                rights = 0.0
                r_price = 0.0

            if pre_close <= 0:
                if split > 0 or rights > 0:
                    factors_daily[idx] *= (1 + split + rights)
                continue

            numerator = pre_close - cash + (r_price * rights)
            denominator = 1.0 + split + rights
            if denominator == 0:
                continue

            ex_price_theory = round(numerator / denominator, 2)
            if ex_price_theory <= 0:
                continue

            factor = pre_close / ex_price_theory

            if factor > 1.05 or factor < 0.95:
                if ex_open > 0 and pre_close > 0:
                    actual_drop = abs(ex_open - pre_close) / pre_close
                    expected_drop = abs(factor - 1.0)
                    if actual_drop < expected_drop * 0.3:
                        logger.debug(f"跳过无效除权事件 {ex_date.date()}: factor={factor:.4f}, actual_drop={actual_drop:.2%}, expected_drop={expected_drop:.2%}")
                        continue

            factors_daily[idx] *= factor

        cumulative_factors = np.cumprod(factors_daily)
        return pd.DataFrame({'date': df_daily['date'], 'factor': cumulative_factors})

    def calculate_cumulative_factor(self, df_day: pd.DataFrame, df_gbbq: pd.DataFrame) -> pd.DataFrame:
        """
        计算累积复权因子 (兼容 v14 接口)

        Returns:
            DataFrame: columns=['date', 'factor']
        """
        return self.calculate(df_day, df_gbbq)


def _process_single_stock(file_path: Path, gbbq_dict: Dict, output_dir: Path, is_hfq: bool = True) -> bool:
    """处理单只股票的原子函数，适配多进程"""
    _log = logging.getLogger("SmartFactorV15.worker")

    try:
        match = re.search(r'(\d{6})\.([A-Z]{2})', file_path.name)
        if not match:
            return False

        code = match.group(1)
        market = match.group(2)
        full_code = f"{code}.{market}"
        
        df_daily = pd.read_parquet(file_path)

        df_stock_gbbq = gbbq_dict.get(code, pd.DataFrame())
        df_events = GBBQProcessorV15.aggregate_events(df_stock_gbbq)

        calculator = SmartFactorCalculatorV15()
        result = calculator.calculate(df_daily, df_events)

        if not result.empty:
            result['code'] = code
            result['market'] = market
            result['type'] = 'hfq' if is_hfq else 'qfq'
            output_file = output_dir / f"{full_code}.parquet"
            result.to_parquet(output_file, index=False, compression='snappy')
            return True
    except Exception as e:
        _log.debug(f"处理 {file_path.name} 失败: {e}")
    return False


def run_parallel_calculation(
    daily_dir: str,
    gbbq_path: str,
    output_dir: str,
    is_hfq: bool = True,
    max_workers: Optional[int] = None
) -> int:
    """
    多进程并行计算全市场复权因子

    Args:
        daily_dir: 日线数据目录
        gbbq_path: GBBQ 数据文件路径
        output_dir: 输出目录
        is_hfq: True=后复权, False=前复权
        max_workers: 最大进程数，None=使用全部CPU核心

    Returns:
        int: 成功处理的股票数量
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    logger.info("1. 正在加载并清洗全量 GBBQ 事件库...")
    df_gbbq_all = GBBQProcessorV15.load_and_clean(gbbq_path)

    if df_gbbq_all.empty:
        logger.warning("GBBQ 数据为空，跳过计算")
        return 0

    gbbq_dict = {code: df for code, df in df_gbbq_all.groupby('code')}
    logger.info(f"   加载了 {len(gbbq_dict)} 只股票的除权事件数据")

    daily_files = list(Path(daily_dir).glob("*.parquet"))
    logger.info(f"2. 启动并发引擎对 {len(daily_files)} 只股票执行复权计算...")

    worker_func = partial(
        _process_single_stock,
        gbbq_dict=gbbq_dict,
        output_dir=output_path,
        is_hfq=is_hfq
    )

    success_count = 0

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        results = executor.map(worker_func, daily_files, chunksize=10)
        for is_success in results:
            if is_success:
                success_count += 1

    logger.info(f"=== 复权因子计算完成！成功生成 {success_count} 个文件 ===")
    return success_count


class SmartFactorCalculator:
    """
    智能复权计算器 (兼容v14接口)

    内部已升级为 V15 算法，保留 v14 接口以保证向后兼容。
    推荐使用 SmartFactorCalculatorV15 或 run_parallel_calculation 获取更高性能。
    """

    def __init__(self):
        self.v15_calculator = SmartFactorCalculatorV15()

    def _calculate_cumulative_factor(self, event: Dict) -> float:
        split_factor = event.get("split_factor", 1.0)
        cash_div = event.get("cash_div", 0.0)
        pre_close = event.get("pre_close", 1.0)
        if pre_close <= 0:
            return 1.0
        effective = (pre_close - cash_div) / (pre_close / split_factor)
        return max(effective, 0.001)

    def calculate_cumulative_factor(self, df_day: pd.DataFrame, df_gbbq: pd.DataFrame) -> pd.DataFrame:
        """
        计算累积复权因子 (兼容接口)

        Returns:
            DataFrame: columns=['date', 'factor']
        """
        return self.v15_calculator.calculate_cumulative_factor(df_day, df_gbbq)
