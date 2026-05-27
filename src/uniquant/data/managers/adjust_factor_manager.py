import os
from typing import Optional
import pandas as pd

from ...shared.logger_factory import get_logger
from ...data.lake.storage_manager import StorageManager
from ...data.parsers.tdx_parser import get_adjust_factors as get_tdx_adjust_factors

logger = get_logger(__name__)

class AdjustFactorManager:
    """复权因子管理器"""

    def __init__(self, storage_manager: StorageManager):
        self.storage_manager = storage_manager

    def get_adjust_factors(self, symbol: str, gbbq_path: Optional[str] = None) -> Optional[pd.DataFrame]:
        """
        获取指定股票的除权因子

        Args:
            symbol: 股票代码，格式为 'code.market' 如 '000001.SZ'
            gbbq_path: GBBQ 文件路径，如果为 None 则使用默认路径

        Returns:
            Optional[pd.DataFrame]: 除权因子数据，为空时返回 None
        """
        logger.info(f"获取 {symbol} 的除权因子")
        
        # 1. 优先从data/fq/gbbq.parquet读取
        fq_gbbq_path = os.path.join(self.storage_manager.data_dir, "fq", "gbbq.parquet")
        if os.path.exists(fq_gbbq_path):
            try:
                logger.info(f"从 {fq_gbbq_path} 读取GBBQ数据")
                df_gbbq = pd.read_parquet(fq_gbbq_path)
                
                # 提取股票代码和市场
                if "." in symbol:
                    code, market = symbol.split(".")
                else:
                    code = symbol
                    market = ""
                
                # 标准化市场代码
                market_map = {
                    'SH': 'SH', 'sh': 'SH',
                    'SZ': 'SZ', 'sz': 'SZ',
                    'BJ': 'BJ', 'bj': 'BJ'
                }
                market = market_map.get(market, "")
                
                # 过滤指定股票
                symbol_df = df_gbbq[df_gbbq['code'] == code].copy()
                
                # 如果有market列且市场信息可用，再按市场筛选
                if 'market' in df_gbbq.columns and market:
                    # 市场代码映射（通达信市场代码到标准市场代码）
                    tdx_market_map = {
                        1: 'SH',  # 上海
                        0: 'SZ',  # 深圳
                        2: 'BJ'   # 北京
                    }
                    # 反向映射，从标准市场代码到通达信市场代码
                    reverse_market_map = {v: k for k, v in tdx_market_map.items()}
                    tdx_market_code = reverse_market_map.get(market)
                    if tdx_market_code is not None:
                        symbol_df = symbol_df[symbol_df['market'] == tdx_market_code]
                
                if not symbol_df.empty:
                    # 按日期排序
                    if 'date' in symbol_df.columns:
                        symbol_df.sort_values('date', inplace=True)
                    logger.info(f"成功从 {fq_gbbq_path} 获取 {symbol} 的除权因子，共 {len(symbol_df)} 条记录")
                    return symbol_df
                else:
                    logger.warning(f"从 {fq_gbbq_path} 未找到 {symbol} 的除权数据")
            except Exception as e:
                logger.error(f"读取 {fq_gbbq_path} 失败: {e}")
        
        # 2. 如果data/fq/gbbq.parquet不存在或读取失败，使用原始GBBQ文件
        logger.info("尝试使用原始GBBQ文件获取除权因子")
        
        # 使用默认 GBBQ 路径 (跨平台)
        if gbbq_path is None:
            import platform
            system = platform.system()
            
            if system == "Windows":
                default_paths = [
                    r"d:\dfzq\T0002\hq_cache\gbbq",
                    r"d:\通达信\T0002\hq_cache\gbbq",
                    r"c:\tdx\T0002\hq_cache\gbbq",
                ]
            else:  # Linux 或 Mac
                default_paths = [
                    "/home/james/.local/share/tdxcfv/drive_c/tc/T0002/hq_cache/gbbq",  # Wine通达信
                    os.path.expanduser("~/.tdx/T0002/hq_cache/gbbq"),
                    "/opt/tdx/T0002/hq_cache/gbbq",
                    os.path.expanduser("~/tdx/T0002/hq_cache/gbbq"),
                ]
            
            for path in default_paths:
                if os.path.exists(path):
                    gbbq_path = path
                    break
            
            if gbbq_path is None:
                logger.error("未找到 GBBQ 文件路径，请指定 gbbq_path 参数")
                return None
        
        # 调用 TDX 解析器获取除权因子
        factors = get_tdx_adjust_factors(symbol, gbbq_path)
        
        if factors is not None:
            logger.info(f"成功获取 {symbol} 的除权因子，共 {len(factors)} 条记录")
        else:
            logger.warning(f"未找到 {symbol} 的除权因子数据")
        
        return factors
        
    def convert_gbbq_to_fq(self, gbbq_path: Optional[str] = None) -> bool:
        """
        转换GBBQ数据到data/fq/gbbq.parquet

        Args:
            gbbq_path: GBBQ 文件路径，如果为 None 则使用默认路径

        Returns:
            bool: 是否转换成功
        """
        logger.info("开始转换GBBQ数据到data/fq/gbbq.parquet")
        
        # 使用默认 GBBQ 路径 (跨平台)
        if gbbq_path is None:
            import platform
            system = platform.system()
            
            if system == "Windows":
                default_paths = [
                    r"d:\dfzq\T0002\hq_cache\gbbq",
                    r"d:\通达信\T0002\hq_cache\gbbq",
                    r"c:\tdx\T0002\hq_cache\gbbq",
                ]
            else:  # Linux 或 Mac
                default_paths = [
                    "/home/james/.local/share/tdxcfv/drive_c/tc/T0002/hq_cache/gbbq",  # Wine通达信
                    os.path.expanduser("~/.tdx/T0002/hq_cache/gbbq"),
                    "/opt/tdx/T0002/hq_cache/gbbq",
                    os.path.expanduser("~/tdx/T0002/hq_cache/gbbq"),
                ]
            
            for path in default_paths:
                if os.path.exists(path):
                    gbbq_path = path
                    break
            
            if gbbq_path is None:
                logger.error("未找到 GBBQ 文件路径，请指定 gbbq_path 参数")
                return False
        
        # 调用TDXParser的save_gbbq_to_fq方法
        from ...data.parsers.tdx_parser import TDXParser
        parser = TDXParser()
        
        fq_gbbq_path = os.path.join(self.storage_manager.data_dir, "fq", "gbbq.parquet")
        success = parser.save_gbbq_to_fq(gbbq_path, fq_gbbq_path)
        
        if success:
            logger.info("GBBQ数据转换成功")
        else:
            logger.error("GBBQ数据转换失败")
        
        return success
