"""
mootdx 复权因子管理器

使用 mootdx.utils.factor.fq_factor 下载和管理复权因子。
"""

from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from ...shared.logger_factory import get_logger

logger = get_logger("MootdxFactorManager")


class MootdxFactorManager:
    """mootdx 复权因子管理器

    使用 mootdx.utils.factor.fq_factor 下载和管理复权因子。
    支持前复权 (qfq)、后复权 (hfq) 两种模式。
    """

    SUPPORTED_ADJUST = ("qfq", "hfq")

    def __init__(self, data_dir: Optional[str] = None):
        """
        初始化 mootdx 复权因子管理器

        Args:
            data_dir: 数据存储目录，为 None 时从 GlobalConfig 获取
        """
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            from ...shared.config_loader import get_config
            config = get_config()
            self.data_dir = Path(str(config.DATA_DIR))

        self.factors_dir = self.data_dir / "fq"
        self.factors_dir.mkdir(parents=True, exist_ok=True)

        self._cache: Dict[str, pd.DataFrame] = {}

    def get_factor(self, symbol: str, adjust: str = "qfq") -> pd.DataFrame:
        """
        获取复权因子

        优先从本地 Parquet 缓存读取，缓存不存在时通过 mootdx 下载。

        Args:
            symbol: 股票代码，如 '600519' 或 '600519.SH'
            adjust: 复权类型，'qfq' (前复权) 或 'hfq' (后复权)

        Returns:
            pd.DataFrame: 复权因子数据，包含 date, factor 列
        """
        if adjust not in self.SUPPORTED_ADJUST:
            logger.error(f"不支持的复权类型: {adjust}，仅支持 {self.SUPPORTED_ADJUST}")
            return pd.DataFrame()

        code = symbol.split(".")[0]
        cache_key = f"{code}_{adjust}"

        if cache_key in self._cache:
            return self._cache[cache_key].copy()

        parquet_path = self.factors_dir / f"{cache_key}.parquet"
        if parquet_path.exists():
            try:
                df = pd.read_parquet(str(parquet_path))
                if not df.empty:
                    self._cache[cache_key] = df
                    logger.info(f"从缓存加载 {code} {adjust} 复权因子: {len(df)} 条")
                    return df.copy()
            except Exception as e:
                logger.warning(f"读取本地复权因子失败 {code}: {e}")

        return self._download_factor(code, adjust)

    def _download_factor(self, code: str, adjust: str) -> pd.DataFrame:
        """
        通过 mootdx 下载复权因子

        Args:
            code: 纯股票代码，如 '600519'
            adjust: 复权类型

        Returns:
            pd.DataFrame: 复权因子数据
        """
        try:
            from mootdx.utils.factor import fq_factor
        except ImportError:
            logger.error("mootdx 未安装，请执行: pip install mootdx>=0.11.7")
            return pd.DataFrame()

        try:
            logger.info(f"通过 mootdx 下载 {code} {adjust} 复权因子")
            df = fq_factor(code, adjust)

            if df is None or df.empty:
                logger.warning(f"mootdx 未返回 {code} 的复权因子")
                return pd.DataFrame()

            df = self._normalize_factor(df, code)

            cache_key = f"{code}_{adjust}"
            self._cache[cache_key] = df
            self.save_factors({cache_key: df})

            logger.info(f"成功下载 {code} {adjust} 复权因子: {len(df)} 条")
            return df.copy()

        except Exception as e:
            logger.error(f"下载 {code} 复权因子失败: {e}")
            return pd.DataFrame()

    def update_factors(self, symbols: list, adjust: str = "qfq") -> Dict[str, bool]:
        """
        批量更新复权因子

        Args:
            symbols: 股票代码列表
            adjust: 复权类型

        Returns:
            Dict[str, bool]: 各股票更新结果
        """
        results = {}
        for symbol in symbols:
            code = symbol.split(".")[0]
            df = self.get_factor(code, adjust)
            results[symbol] = not df.empty

        success = sum(1 for v in results.values() if v)
        logger.info(f"批量更新完成: {success}/{len(symbols)} 成功")
        return results

    def save_factors(self, factors: Dict[str, pd.DataFrame], path: Optional[str] = None):
        """
        保存复权因子到 Parquet 文件

        Args:
            factors: {cache_key: DataFrame} 字典
            path: 保存目录，为 None 时使用默认 factors_dir
        """
        target_dir = Path(path) if path else self.factors_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        for key, df in factors.items():
            if df.empty:
                continue
            try:
                parquet_path = target_dir / f"{key}.parquet"
                df.to_parquet(str(parquet_path), compression="snappy", index=False)
                logger.debug(f"保存复权因子: {parquet_path}")
            except Exception as e:
                logger.error(f"保存复权因子失败 {key}: {e}")

    def load_factors(self, path: Optional[str] = None) -> Dict[str, pd.DataFrame]:
        """
        从 Parquet 目录加载所有复权因子

        Args:
            path: 加载目录，为 None 时使用默认 factors_dir

        Returns:
            Dict[str, pd.DataFrame]: {cache_key: DataFrame} 字典
        """
        target_dir = Path(path) if path else self.factors_dir
        if not target_dir.exists():
            logger.warning(f"复权因子目录不存在: {target_dir}")
            return {}

        factors = {}
        for parquet_file in target_dir.glob("*.parquet"):
            key = parquet_file.stem
            try:
                df = pd.read_parquet(str(parquet_file))
                if not df.empty:
                    factors[key] = df
                    self._cache[key] = df
            except Exception as e:
                logger.error(f"加载复权因子失败 {key}: {e}")

        logger.info(f"加载复权因子: {len(factors)} 个文件")
        return factors

    @staticmethod
    def _normalize_factor(df: pd.DataFrame, code: str) -> pd.DataFrame:
        """
        标准化 mootdx 返回的复权因子格式

        Args:
            df: mootdx 原始返回
            code: 股票代码

        Returns:
            pd.DataFrame: 标准化后的 DataFrame，包含 date, code, factor 列
        """
        df = df.copy()

        date_col = None
        for candidate in ("date", "datetime", "trade_date"):
            if candidate in df.columns:
                date_col = candidate
                break

        if date_col is None and isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index()
            date_col = df.columns[0]

        if date_col and date_col != "date":
            df = df.rename(columns={date_col: "date"})

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])
            df = df.sort_values("date").reset_index(drop=True)

        factor_col = None
        for candidate in ("factor", "fq_factor", "adj_factor", "close"):
            if candidate in df.columns:
                factor_col = candidate
                break

        if factor_col and factor_col != "factor":
            df = df.rename(columns={factor_col: "factor"})

        if "factor" not in df.columns and len(df.columns) >= 2:
            numeric_cols = df.select_dtypes(include=["number"]).columns
            if len(numeric_cols) > 0:
                df = df.rename(columns={numeric_cols[-1]: "factor"})

        if "factor" in df.columns:
            df["factor"] = pd.to_numeric(df["factor"], errors="coerce")
            df = df.dropna(subset=["factor"])

        df["code"] = code

        keep_cols = [c for c in ("date", "code", "factor") if c in df.columns]
        if keep_cols:
            df = df[keep_cols]

        return df
