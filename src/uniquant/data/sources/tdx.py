"""
通达信数据源
"""

import os
import struct
from pathlib import Path
from typing import Optional, Dict

import pandas as pd

from .base import DataSource
from ...shared.logger_factory import get_logger
from ..parsers.tdx_parser import TDXParser

logger = get_logger("TdxSource")


class TdxSource(DataSource):
    """
    通达信数据源
    从本地通达信安装目录获取数据
    """

    def __init__(self, tdx_path: Optional[str] = None):
        """
        初始化通达信数据源

        Args:
            tdx_path: 通达信安装目录路径
        """
        self.tdx_path: Optional[Path] = None
        # 优先使用传入的路径，否则从配置文件读取
        if tdx_path:
            self.tdx_path = Path(tdx_path)
        else:
            # 从配置文件读取通达信路径
            from ...shared.config_loader import get_config
            config = get_config()
            tdx_path_from_config = config.get("base.tdx.path", None)
            if tdx_path_from_config:
                self.tdx_path = Path(tdx_path_from_config)
                logger.info(f"从配置文件读取通达信路径: {self.tdx_path}")
            else:
                # 尝试默认路径 (跨平台)
                import platform
                system = platform.system()
                
                if system == "Windows":
                    default_paths = [
                        r"d:\dfzq",
                        r"d:\通达信",
                        r"c:\tdx",
                        r"c:\通达信",
                    ]
                else:  # Linux 或 Mac
                    default_paths = [
                        "/home/james/.local/share/tdxcfv/drive_c/tc",  # Wine通达信
                        os.path.expanduser("~/.tdx"),
                        "/opt/tdx",
                        "/usr/local/tdx",
                        os.path.expanduser("~/tdx"),
                    ]
                
                found_path = None
                for path in default_paths:
                    if os.path.exists(path):
                        found_path = Path(path)
                        logger.info(f"使用默认通达信路径: {found_path}")
                        break
                
                self.tdx_path = found_path
        
        self.tdx_parser = TDXParser()
        self.data_cache: Dict[str, pd.DataFrame] = {}

    def fetch_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        从通达信 .day 文件获取日线数据

        Args:
            symbol: 股票代码，如 600000.SH
            start_date: 开始日期，格式 YYYY-MM-DD
            end_date: 结束日期，格式 YYYY-MM-DD

        Returns:
            pd.DataFrame: 日线数据
        """
        try:
            # 检查通达信路径是否设置
            if not self.tdx_path:
                logger.error("通达信路径未设置")
                return pd.DataFrame()

            # 转换股票代码格式
            code = symbol.split('.')[0]
            market = symbol.split('.')[1].lower()

            # 构建通达信 .day 文件路径
            if market == 'sh':
                day_dir = self.tdx_path / "vipdoc" / "sh" / "lday"
                filename = f"sh{code}.day"
            elif market == 'sz':
                day_dir = self.tdx_path / "vipdoc" / "sz" / "lday"
                filename = f"sz{code}.day"
            else:
                logger.error(f"不支持的市场: {market}")
                return pd.DataFrame()

            day_path = day_dir / filename

            # 检查文件是否存在
            if not day_path.exists():
                logger.error(f"通达信文件不存在: {day_path}")
                return pd.DataFrame()

            # 检查缓存
            cache_key = f"{symbol}_{start_date}_{end_date}"
            if cache_key in self.data_cache:
                logger.debug(f"从缓存获取数据: {cache_key}")
                return self.data_cache[cache_key]

            # 解析 .day 文件
            df = self.tdx_parser.parse_day_file(str(day_path))

            # 筛选日期范围
            start = pd.to_datetime(start_date)
            end = pd.to_datetime(end_date)
            df = df[(df.index >= start) & (df.index <= end)]

            # 将索引转换为date列，与系统格式保持一致
            df = df.reset_index()

            # 确保date列是datetime类型
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
            
            # 添加code列（DataValidator要求）
            df['code'] = symbol

            # 缓存数据
            self.data_cache[cache_key] = df

            logger.info(f"成功从通达信获取 {symbol} 的日线数据，共 {len(df)} 条记录")
            return df

        except (OSError, ValueError, KeyError, TypeError, struct.error) as e:
            logger.error(f"获取通达信日线数据失败: {e}")
            return pd.DataFrame()

    def fetch_real_time(self, symbol: Optional[str] = None) -> pd.DataFrame:
        """
        获取实时数据
        注：通达信实时数据需要特殊处理，这里暂时返回空数据

        Args:
            symbol: 股票代码，None 表示获取所有

        Returns:
            pd.DataFrame: 实时数据
        """
        logger.warning("通达信数据源暂不支持实时数据获取")
        return pd.DataFrame()

    def fetch_market_cap(self, symbol: str) -> float:
        """
        获取市值
        注：通达信数据文件中不包含市值信息，这里暂时返回 0

        Args:
            symbol: 股票代码

        Returns:
            float: 市值
        """
        logger.warning("通达信数据源暂不支持市值获取")
        return 0.0
