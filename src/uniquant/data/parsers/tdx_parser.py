#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通达信文件解析器
负责解析通达信 .day 文件和 gbbq 文件
"""

import os
import struct
import pandas as pd
from pathlib import Path
from typing import Optional

from ...shared.logger_factory import get_logger

logger = get_logger("TDXParser")


class TDXParser:
    """
    通达信文件解析器
    负责解析通达信 .day 文件和 gbbq 文件
    """
    
    def __init__(self, vipdoc_path=None):
        """
        初始化通达信文件解析器
        
        Args:
            vipdoc_path: 通达信vipdoc目录路径，用于mootdx库解析gbbq文件
        """
        self.vipdoc_path = vipdoc_path

    def parse_day_file(self, file_path: str) -> pd.DataFrame:
        """
        解析通达信日线(.day)文件

        Args:
            file_path: .day文件的绝对路径

        Returns:
            Pandas DataFrame
        """
        data_list = []
        
        # 获取文件大小，校验完整性
        file_size = os.path.getsize(file_path)
        if file_size % 32 != 0:
            logger.warning(f"警告: 文件 {file_path} 大小不是32的倍数，可能损坏或包含非标准数据。")
        
        # 使用二进制模式打开文件
        with open(file_path, 'rb') as f:
            buffer = f.read()
        
        # 定义 struct 格式
        fmt = "<IIIIIfii"
        
        # 使用 struct.iter_unpack 高效迭代
        for record in struct.iter_unpack(fmt, buffer):
            data_list.append(record)
        
        # 转换为 DataFrame
        df = pd.DataFrame(data_list, columns=[
            'date', 'open', 'high', 'low', 'close', 'amount', 'volume', 'reserved'
        ])
        
        # 数据清洗与类型转换
        df['date'] = pd.to_datetime(df['date'].astype(str), format='%Y%m%d', errors='coerce')
        
        # 从文件路径提取股票代码
        filename = os.path.basename(file_path)
        symbol_part = filename.split('.')[0]
        code = ''
        if symbol_part.startswith('sh') or symbol_part.startswith('sz'):
            code = symbol_part[2:]
        else:
            code = symbol_part
        
        # 价格处理：根据证券类型选择不同的除数
        price_cols = ['open', 'high', 'low', 'close']
        
        if code.startswith('11') or code.startswith('12'):
            for col in price_cols:
                df[col] = df[col] / 10000.0
        elif code.startswith('5') or code.startswith('15'):
            for col in price_cols:
                df[col] = df[col] / 1000.0
        elif code.startswith('9'):
            for col in price_cols:
                df[col] = df[col] / 1000.0
        else:
            for col in price_cols:
                df[col] = df[col] / 100.0
        
        df.set_index('date', inplace=True)
        df.dropna(inplace=True)
        
        return df

    def parse_gbbq_file(self, gbbq_path: str) -> pd.DataFrame:
        """
        解析通达信 gbbq 股本变迁文件
        使用 pytdx 的 GbbqReader 进行解析
        """
        logger.info(f"开始解析 gbbq 文件: {gbbq_path}")
        
        if not os.path.exists(gbbq_path):
            logger.error(f"文件不存在: {gbbq_path}")
            return pd.DataFrame()

        try:
            from pytdx.reader import GbbqReader
            logger.info("使用 pytdx 的 GbbqReader 解析 gbbq 文件")
            
            reader = GbbqReader()
            logger.info("GbbqReader 初始化成功")
            
            logger.info("开始解析 gbbq 文件...")
            df = reader.get_df(gbbq_path)
            
            if df is None:
                logger.error("pytdx 解析 gbbq 文件返回 None")
                return pd.DataFrame()
            
            if df.empty:
                logger.error("pytdx 解析 gbbq 文件失败，返回空数据")
                return pd.DataFrame()
            
            logger.info(f"pytdx 解析成功，共 {len(df)} 条记录")
            logger.info(f"解析结果列名: {list(df.columns)}")
            
            column_mapping = {
                '代码': 'code',
                '证券代码': 'code',
                '日期': 'date',
                '除权除息日': 'date',
                '分红': 'cash_div',
                '派息': 'cash_div',
                '送股': 'split_ratio',
                '送转股': 'split_ratio',
                '配股': 'rights_ratio',
                '配股价': 'rights_price'
            }
            
            df = df.rename(columns=column_mapping)
            logger.info(f"重命名后列名: {list(df.columns)}")
            
            if 'code' in df.columns:
                df = df[df['code'].astype(str).str.match(r'^\d{6}$')]
            
            logger.info(f"过滤后剩余 {len(df)} 条有效记录")
            if not df.empty:
                logger.info(f"前5条记录:\n{df.head()}")
            
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'], format='%Y%m%d', errors='coerce')
                df.dropna(subset=['date'], inplace=True)
                logger.info(f"日期格式化后剩余 {len(df)} 条有效记录")
            
            return df
            
        except ImportError:
            logger.error("pytdx 库未安装，请先安装 pytdx 库")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"pytdx 解析 gbbq 文件失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return pd.DataFrame()


    def _parse_gbbq_manually(self, gbbq_path: str) -> pd.DataFrame:
        """
        手动解析 gbbq 文件（含 TEA 解密）

        TDX GBBQ 文件使用 TEA-like 分组加密算法。
        每条记录 29 字节：24 字节加密数据 + 5 字节明文。
        """
        from ctypes import c_uint32 as cu32
        from pytdx.reader.gbbq_reader import GbbqReader

        _reader = GbbqReader()
        bin_keys = bytes.fromhex(_reader.hexdump_keys.replace(' ', ''))

        gbbq_data = []
        try:
            with open(gbbq_path, 'rb') as f:
                file_content = f.read()
            logger.info(f"读取 gbbq 文件成功，文件大小: {len(file_content)} 字节")

            if len(file_content) < 4:
                logger.error("gbbq 文件太小")
                return pd.DataFrame()

            count = struct.unpack("<I", file_content[:4])[0]
            logger.info(f"gbbq 文件记录数: {count}")

            data_offset = 4

            for rec_idx in range(count):
                if data_offset + 29 > len(file_content):
                    break

                clear_data = bytearray()
                for _ in range(3):
                    eax = struct.unpack("<I", bin_keys[0x44:0x48])[0]
                    ebx = struct.unpack("<I", file_content[data_offset:data_offset + 4])[0]
                    num = cu32(eax ^ ebx).value
                    numold = struct.unpack("<I", file_content[data_offset + 4:data_offset + 8])[0]

                    for j in range(0x40, 3, -4):
                        ebx_tmp = (num & 0xFF0000) >> 16
                        eax = struct.unpack("<I", bin_keys[ebx_tmp * 4 + 0x448:ebx_tmp * 4 + 0x44C])[0]
                        ebx_tmp = num >> 24
                        eax += struct.unpack("<I", bin_keys[ebx_tmp * 4 + 0x48:ebx_tmp * 4 + 0x4C])[0]
                        eax = cu32(eax).value
                        ebx_tmp = (num & 0xFF00) >> 8
                        eax ^= struct.unpack("<I", bin_keys[ebx_tmp * 4 + 0x848:ebx_tmp * 4 + 0x84C])[0]
                        eax = cu32(eax).value
                        ebx_tmp = num & 0xFF
                        eax += struct.unpack("<I", bin_keys[ebx_tmp * 4 + 0xC48:ebx_tmp * 4 + 0xC4C])[0]
                        eax = cu32(eax).value
                        eax ^= struct.unpack("<I", bin_keys[j:j + 4])[0]
                        eax = cu32(eax).value
                        ebx_tmp = num
                        num = cu32(numold ^ eax).value
                        numold = ebx_tmp

                    numold ^= struct.unpack("<I", bin_keys[0:4])[0]
                    numold = cu32(numold).value
                    clear_data.extend(struct.pack("<II", numold, num))
                    data_offset += 8

                clear_data.extend(file_content[data_offset:data_offset + 5])
                data_offset += 5

                v1, v2, v3, v4, v5, v6, v7, v8 = struct.unpack("<B7sIBffff", clear_data)
                code = v2.rstrip(b"\x00").decode("utf-8", errors="ignore")

                if code:
                    gbbq_data.append({
                        'code': code,
                        'market': v1,
                        'date': str(v3),
                        'category': v4,
                        'cash_div': v5,
                        'rights_price': v6,
                        'split_ratio': v7,
                        'rights_ratio': v8,
                    })

                if (rec_idx + 1) % 10000 == 0:
                    logger.info(f"已解析 {rec_idx + 1}/{count} 条 gbbq 记录")

        except Exception as e:
            logger.error(f"手动解析 gbbq 文件失败: {e}")
            import traceback
            logger.error(traceback.format_exc())

        df = pd.DataFrame(gbbq_data)
        logger.info(f"手动解析完成，共 {len(df)} 条记录")
        if not df.empty:
            logger.info(f"解析结果列名: {list(df.columns)}")
            logger.info(f"前5条记录:\n{df.head()}")
        return df



    def save_gbbq_data(self, df: pd.DataFrame, output_path: str) -> None:
        try:
            if not df.empty:
                df.to_parquet(output_path, compression="snappy")
                logger.info(f"成功保存 gbbq 数据到: {output_path}")
                logger.info(f"gbbq 数据形状: {df.shape}")
            else:
                logger.warning(f"gbbq 数据为空，跳过保存: {output_path}")
        except Exception as e:
            logger.error(f"保存 gbbq 数据失败: {e}")
            import traceback
            logger.error(f"错误堆栈: {traceback.format_exc()}")

    def save_stock_gbbq_data(self, df: pd.DataFrame, code: str, output_dir: str) -> None:
        try:
            if not df.empty:
                output_path = Path(output_dir) / f"{code}.parquet"
                df.to_parquet(str(output_path), compression="snappy")
                logger.info(f"成功保存股票 {code} 的 gbbq 数据到: {output_path}")
                logger.info(f"数据形状: {df.shape}")
            else:
                logger.warning(f"股票 {code} 的 gbbq 数据为空，跳过保存")
        except Exception as e:
            logger.error(f"保存股票 {code} 的 gbbq 数据失败: {e}")
            import traceback
            logger.error(f"错误堆栈: {traceback.format_exc()}")

    def save_gbbq_to_fq(self, gbbq_path: str, output_path: str = "data/fq/gbbq.parquet") -> bool:
        """解析并保存GBBQ数据到data/fq/gbbq.parquet"""
        try:
            logger.info(f"开始解析并保存GBBQ数据到: {output_path}")
            
            df = parse_gbbq_native(gbbq_path)
            
            if df.empty:
                logger.error("GBBQ数据解析失败，返回空数据")
                return False
            
            output_dir = Path(output_path).parent
            output_dir.mkdir(parents=True, exist_ok=True)
            
            df.to_parquet(output_path, compression="snappy")
            logger.info(f"成功保存GBBQ数据到: {output_path}")
            logger.info(f"GBBQ数据形状: {df.shape}")
            logger.info(f"包含股票数量: {df['code'].nunique()}")
            
            return True
        except Exception as e:
            logger.error(f"保存GBBQ数据到fq目录失败: {e}")
            import traceback
            logger.error(f"错误堆栈: {traceback.format_exc()}")
            return False



    def calculate_adj_factors(self, df_day: pd.DataFrame, df_gbbq: pd.DataFrame) -> pd.DataFrame:
        """
        基于gbbq数据计算复权因子 (累积后复权因子)
        """
        try:
            from ...data.utils.smart_factor_calculator import SmartFactorCalculator
        except ImportError:
            import sys
            from pathlib import Path
            project_root = Path(__file__).resolve().parent.parent.parent
            if str(project_root) not in sys.path:
                sys.path.append(str(project_root))
            from ...data.utils.smart_factor_calculator import SmartFactorCalculator
        
        calculator = SmartFactorCalculator()
        
        if df_day.index.name == 'date':
            df_day = df_day.reset_index()
        
        df_factor = calculator.calculate_cumulative_factor(df_day, df_gbbq)
        
        if df_factor.empty:
            logger.warning("未计算到复权因子，返回默认因子(1.0)")
            return pd.DataFrame(columns=['date', 'factor'])
        
        logger.info(f"复权因子计算完成，共生成 {len(df_factor)} 条因子记录")
        
        return df_factor

    def get_symbol_from_filename(self, filename: str) -> Optional[str]:
        """从文件名中提取股票代码"""
        try:
            symbol_part = filename.split('.')[0]
            
            if symbol_part.startswith('sh'):
                code = symbol_part[2:]
                return f"{code}.SH"
            elif symbol_part.startswith('sz'):
                code = symbol_part[2:]
                return f"{code}.SZ"
            else:
                logger.warning(f"无法识别的股票代码格式: {filename}")
                return None
        except Exception as e:
            logger.error(f"转换股票代码格式失败: {e}")
            return None


def parse_gbbq_native(file_path: str) -> pd.DataFrame:
    """
    解析通达信 GBBQ 文件
    使用mootdx的网络API获取除权除息信息
    """
    logger.info(f"开始解析 GBBQ 文件: {file_path}")
    
    parser = TDXParser()
    
    df = parser.parse_gbbq_file(file_path)
    
    if not df.empty:
        return df
    
    df = parser._parse_gbbq_manually(file_path)
    
    return df


def get_adjust_factors(symbol: str, gbbq_path: str) -> Optional[pd.DataFrame]:
    """获取指定股票的除权因子"""
    df = parse_gbbq_native(gbbq_path)
    
    if df.empty:
        logger.warning(f"未找到 {symbol} 的除权数据")
        return None
    
    code = symbol.split('.')[0]
    
    symbol_df = df[df['code'] == code].copy()
    
    if symbol_df.empty:
        logger.warning(f"未找到 {symbol} 的除权数据")
        return None
    
    if 'date' in symbol_df.columns:
        symbol_df.sort_values('date', inplace=True)
    elif all(col in symbol_df.columns for col in ['year', 'month', 'day']):
        symbol_df['date'] = pd.to_datetime(symbol_df[['year', 'month', 'day']])
        symbol_df.sort_values('date', inplace=True)
    
    logger.info(f"{symbol} 的除权数据 shape: {symbol_df.shape}")
    logger.info(f"除权日期数量: {len(symbol_df)}")
    
    return symbol_df


def main():
    """测试解析"""
    import platform
    
    if platform.system() == "Windows":
        default_gbbq_path = r"d:\dfzq\T0002\hq_cache\gbbq"
    else:
        default_gbbq_path = "/home/james/.local/share/tdxcfv/drive_c/tc/T0002/hq_cache/gbbq"
    
    gbbq_path = os.environ.get("TDX_GBBQ_PATH", default_gbbq_path)
    
    df = parse_gbbq_native(gbbq_path)
    
    if not df.empty:
        logger.info("解析成功！")
        logger.info(f"总记录数: {len(df)}")
        logger.info(f"股票数量: {df['code'].nunique()}")
        logger.info(f"列名: {list(df.columns)}")
        
        test_symbol = "600000.SH"
        factor_df = get_adjust_factors(test_symbol, gbbq_path)
        if factor_df is not None and not factor_df.empty:
            logger.info(f"成功获取 {test_symbol} 的除权因子，共 {len(factor_df)} 条记录")


if __name__ == "__main__":
    main()
