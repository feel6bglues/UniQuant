import pandas as pd

from ...shared.logger_factory import get_logger
from ..managers.factor_manager import FactorManager

logger = get_logger(__name__)


class DataAdjuster:
    """数据复权器 - 核心算法实现"""

    def __init__(self, storage_manager):
        self.storage_manager = storage_manager
        # 初始化 FactorManager
        if storage_manager:
            self.factor_manager = FactorManager(storage_manager.data_dir)
        else:
            self.factor_manager = None

    def is_valid_stock_code(self, code: str, market: str) -> bool:
        """验证股票代码是否在指定范围内
        
        Args:
            code: 股票代码
            market: 市场代码 (SH/SZ)
            
        Returns:
            bool: 是否为有效股票代码
        """
        # 沪市主板: 60xxxx
        if market == 'SH' and code.startswith('60') and len(code) == 6:
            return True
        # 科创板: 68xxxx
        elif market == 'SH' and code.startswith('68') and len(code) == 6:
            return True
        # 深市主板/中小板: 00xxxx
        elif market == 'SZ' and code.startswith('00') and len(code) == 6:
            return True
        # 创业板: 30xxxx
        elif market == 'SZ' and code.startswith('30') and len(code) == 6:
            return True
        return False

    def update_factors(self, symbol: str):
        """从本地通达信数据计算复权因子并存储"""
        try:
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
            
            # 过滤非指定范围内的股票代码
            if not self.is_valid_stock_code(code, market):
                logger.info(f"股票代码 {symbol} 不在指定范围内，跳过复权因子计算")
                return False

            # 获取不复权数据（从本地存储）
            logger.info(f"开始从本地通达信数据计算 {symbol} 的复权因子")

            # 读取本地日线数据
            df_day = pd.DataFrame()
            if self.storage_manager:
                df_day = self.storage_manager.read_local_raw(symbol)

            if df_day.empty:
                logger.warning(f"未找到 {symbol} 的日线数据")
                return False

            # 确保日线数据按日期排序
            df_day = df_day.sort_values("date")
            df_day['date'] = pd.to_datetime(df_day['date'])

            # 读取本地gbbq数据
            # 使用 storage_manager.data_dir 获取正确的路径
            gbbq_path = self.storage_manager.data_dir / "fq" / "gbbq.parquet"
            if not gbbq_path.exists():
                logger.error(f"gbbq数据文件不存在: {gbbq_path}")
                return False

            try:
                df_gbbq = pd.read_parquet(str(gbbq_path))
            except (OSError, ValueError, pd.errors.ParserError) as e:
                logger.error(f"读取gbbq数据失败: {e}")
                return False

            if df_gbbq.empty:
                logger.warning("gbbq数据为空")
                return False

            # 筛选该股的gbbq数据
            stock_gbbq = None
            if 'code' in df_gbbq.columns:
                # 先按代码筛选
                stock_gbbq = df_gbbq[df_gbbq['code'] == code]
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
                        stock_gbbq = stock_gbbq[stock_gbbq['market'] == tdx_market_code]
            elif '代码' in df_gbbq.columns:
                stock_gbbq = df_gbbq[df_gbbq['代码'] == code]
            elif '证券代码' in df_gbbq.columns:
                stock_gbbq = df_gbbq[df_gbbq['证券代码'] == code]
            
            # 清理数据，确保日期格式正确
            if stock_gbbq is not None and not stock_gbbq.empty:
                # 确保日期列存在且格式正确
                if 'date' in stock_gbbq.columns:
                    # 移除无效日期
                    stock_gbbq = stock_gbbq.dropna(subset=['date'])
                    # 确保日期类型正确
                    if not pd.api.types.is_datetime64_any_dtype(stock_gbbq['date']):
                        try:
                            stock_gbbq['date'] = pd.to_datetime(stock_gbbq['date'], format='%Y%m%d', errors='coerce')
                            stock_gbbq = stock_gbbq.dropna(subset=['date'])
                        except (ValueError, TypeError):
                            stock_gbbq = pd.DataFrame()

            if stock_gbbq is None or stock_gbbq.empty:
                logger.info(f"未找到 {symbol} 的除权除息数据，跳过复权因子计算")
                return False

            # 使用 FactorManager 计算并保存复权因子
            if self.factor_manager:
                success = self.factor_manager.calculate_and_save_factor(symbol, df_day, stock_gbbq)
                if success:
                    logger.info(f"成功从本地通达信数据更新 {symbol} 的复权因子")
                    return True
                else:
                    logger.warning(f"未计算到 {symbol} 的复权因子，跳过")
                    return False
            else:
                logger.error("FactorManager 未初始化")
                return False
        except (OSError, ValueError, KeyError, TypeError) as e:
            logger.error(f"更新复权因子失败 {symbol}: {e}")
            import traceback
            logger.error(f"错误堆栈: {traceback.format_exc()}")
            return False

    def apply_adjustment(
        self, symbol: str, df_raw: pd.DataFrame, method: str
    ) -> pd.DataFrame:
        """应用复权算法 (Vectorized Implementation)"""
        if df_raw.empty or method not in ["qfq", "hfq"]:
            logger.warning(f"无效的复权参数: method={method}, 数据行数={len(df_raw)}")
            return df_raw

        logger.info(f"应用 {method} 复权，数据共 {len(df_raw)} 条记录")

        # 1. 读取本地因子表
        df_factor = pd.DataFrame()
        if self.factor_manager:
            df_factor = self.factor_manager.read_factor(symbol)
        elif self.storage_manager:
            df_factor = self.storage_manager.read_local_factor(symbol)

        if df_factor.empty:
            logger.warning(f"未找到 {symbol} 的复权因子数据，返回原始数据")
            return df_raw  # 无因子，降级返回原始数据

        # 2. 预处理
        df_raw = df_raw.copy()
        df_raw["date"] = pd.to_datetime(df_raw["date"])
        df_factor["date"] = pd.to_datetime(df_factor["date"])
        
        # 确保因子按日期排序
        df_factor = df_factor.sort_values("date")

        # 3. 核心算法：Merge AsOf
        # 过滤掉包含null值的数据
        df_raw_filtered = df_raw.dropna(subset=["date"]).copy()
        df_factor_filtered = df_factor.dropna(subset=["date"]).copy()
        
        if df_raw_filtered.empty:
            logger.warning(f"过滤后原始数据为空: {symbol}")
            return df_raw
        
        if df_factor_filtered.empty:
            logger.warning(f"过滤后因子数据为空: {symbol}")
            return df_raw
        
        df_merged = pd.merge_asof(
            df_raw_filtered.sort_values("date"),
            df_factor_filtered.sort_values("date"),
            on="date",
            direction="backward"
        )

        # 4. 缺失因子填充
        # 如果原始数据早于因子表的第一条记录，fillna(1.0) 是对的
        df_merged["factor"] = df_merged["factor"].ffill().fillna(1.0)

        # 5. 执行计算
        # 注意：factor 是 HFQ 累积因子 (Start=1.0, Split -> Factor increases)
        adjust_cols = ["open", "high", "low", "close"]
        
        # 在计算前增加检查，防止因子数值异常
        if (df_merged["factor"] <= 0).any():
            logger.error("发现异常因子值(<=0)，请检查gbbq数据清洗逻辑")
            return df_raw
        
        if (df_merged["factor"] > 1000000).any() or (df_merged["factor"] < 0.000001).any():
            logger.error("发现异常因子值，范围过大或过小")
            return df_raw
        
        if method == "hfq":
            # HFQ = Price * Factor
            for col in adjust_cols:
                if col in df_merged.columns:
                    # 使用 float64 避免溢出，最后再 round
                    df_merged[col] = (df_merged[col].astype('float64') * df_merged["factor"]).round(3)
                    # 限制价格范围，防止异常值
                    df_merged[col] = df_merged[col].clip(lower=0.001, upper=100000)
            # 处理成交量
            if "volume" in df_merged.columns:
                df_merged["volume"] = (df_merged["volume"].astype('float64') / df_merged["factor"]).round(0)
                # 限制成交量范围，防止异常值
                df_merged["volume"] = df_merged["volume"].clip(lower=0, upper=10000000000)
        elif method == "qfq":
            # QFQ = Price * Factor / LatestFactor
            # 获取最新的因子值 (当前累积因子)
            latest_factor = df_factor_filtered["factor"].iloc[-1]
            if latest_factor == 0:
                logger.error(f"最新因子为0，无法计算前复权: {symbol}")
                return df_raw
                
            qfq_multiplier = df_merged["factor"] / latest_factor
            
            # 检查前复权乘数是否异常
            if (qfq_multiplier > 1000000).any() or (qfq_multiplier < 0.000001).any():
                logger.error("发现异常前复权乘数，范围过大或过小")
                return df_raw
                
            for col in adjust_cols:
                if col in df_merged.columns:
                    # 使用 float64 避免溢出，最后再 round
                    df_merged[col] = (df_merged[col].astype('float64') * qfq_multiplier).round(3)
                    # 限制价格范围，防止异常值
                    df_merged[col] = df_merged[col].clip(lower=0.001, upper=100000)
            # 处理成交量
            if "volume" in df_merged.columns:
                df_merged["volume"] = (df_merged["volume"].astype('float64') / qfq_multiplier).round(0)
                # 限制成交量范围，防止异常值
                df_merged["volume"] = df_merged["volume"].clip(lower=0, upper=10000000000)

        # 6. 清理和排序
        df_result = df_merged.drop(columns=["factor"])
        df_result = df_result.sort_values("date").reset_index(drop=True)

        logger.info(f"复权完成，共 {len(df_result)} 条记录")
        return df_result

    def get_adjusted_data(
        self, symbol: str, start_date: str, end_date: str, adjust: str = ""
    ) -> pd.DataFrame:
        """获取复权后的数据"""
        if not self.storage_manager:
            logger.error("StorageManager 未初始化")
            return pd.DataFrame()

        # 读取原始数据
        df_raw = self.storage_manager.read_local_raw(symbol)

        # 应用复权
        if adjust == "qfq":
            return self.apply_adjustment(symbol, df_raw, method="qfq")
        elif adjust == "hfq":
            return self.apply_adjustment(symbol, df_raw, method="hfq")

        return df_raw
