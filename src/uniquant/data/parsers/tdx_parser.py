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


# ---------------------------------------------------------------------------
# GBBQ 列契约（Step 2b / WS-B，2026-10-12 冻结）
#
# 考古结论（已实测，勿重复调查）：本文件原 `column_mapping` 为全中文 key
# （代码/证券代码/日期/除权除息日/分红/派息/送股/送转股/配股/配股价），
# 而 pytdx `GbbqReader.get_df` 输出恒为 8 拼音列
# （market, code, datetime, category, hongli_panqianliutong,
#  peigujia_qianzongguben, songgu_qianzongguben, peigu_houzongguben）
# → 0/10 命中、rename 恒 no-op、`if 'date' in df.columns` 恒 False 跳过日期转换。
# **中文表从未匹配过 pytdx 输出。**
#
# 冻结对照组 = scripts/maintenance/sync_local_tdx_day.py:106-112（5/5 命中），
# 下面 _GBBQ_PYDX_COLUMN_MAPPING 与该表逐字同口径，不得单方面改动。
# ---------------------------------------------------------------------------

# 拼音表（主映射，冻结来源: sync_local_tdx_day.py:106-112）
_GBBQ_PYDX_COLUMN_MAPPING = {
    "datetime": "date",
    "hongli_panqianliutong": "cash_div",
    "peigujia_qianzongguben": "rights_price",
    "songgu_qianzongguben": "split_ratio",
    "peigu_houzongguben": "rights_ratio",
}

# 中文表保留为兼容别名（历史/第三方中文表头来源），宽进容错，
# 两种来源经合并表收敛到同一 8 列英文契约。
_GBBQ_CN_COLUMN_ALIASES = {
    "代码": "code",
    "证券代码": "code",
    "日期": "date",
    "除权除息日": "date",
    "分红": "cash_div",
    "派息": "cash_div",
    "送股": "split_ratio",
    "送转股": "split_ratio",
    "配股": "rights_ratio",
    "配股价": "rights_price",
}

_GBBQ_COLUMN_MAPPING = {**_GBBQ_PYDX_COLUMN_MAPPING, **_GBBQ_CN_COLUMN_ALIASES}

# 输出契约（= data/fq/gbbq.parquet 现列），列序一并冻结
_GBBQ_TARGET_COLS = [
    "code",
    "market",
    "date",
    "category",
    "cash_div",
    "split_ratio",
    "rights_ratio",
    "rights_price",
]

# 缺失 market/category 时的 unknown 占位（真实 category 取值为正整数，-1 不可混淆）
_GBBQ_UNKNOWN_INT = -1


def _normalize_gbbq_date(series: pd.Series) -> pd.Series:
    """
    任意来源 date 列 → YYYYMMDD 数值（非法值为 NaN）。

    语义与 sync_local_tdx_day.py:125 `df_clean["date"].astype(int)` 一致：
    输出为 **int YYYYMMDD**，不是 datetime64。
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        converted = pd.to_datetime(series, errors="coerce").dt.strftime("%Y%m%d")
        return pd.to_numeric(converted, errors="coerce")

    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.isna().any():
        # '1990-03-01' / Timestamp 混合对象等 → 先转 datetime 再归一
        as_dt = pd.to_datetime(series, errors="coerce")
        numeric = numeric.fillna(pd.to_numeric(as_dt.dt.strftime("%Y%m%d"), errors="coerce"))
    return numeric


def _enforce_gbbq_contract(df: pd.DataFrame) -> pd.DataFrame:
    """断言契约列齐全并按冻结列序重排（函数尾统一出口）。"""
    missing = [col for col in _GBBQ_TARGET_COLS if col not in df.columns]
    if missing:
        raise ValueError(f"gbbq 数据缺少契约列 {missing}，实际列: {list(df.columns)}")
    return df.loc[:, _GBBQ_TARGET_COLS].reset_index(drop=True)


def _normalize_gbbq_frame(df: pd.DataFrame) -> pd.DataFrame:
    """
    把任意来源（pytdx 拼音列 / 中文表头 / 手动解密）的 gbbq DataFrame
    收敛到冻结 8 列契约: code, market, date, category,
    cash_div, split_ratio, rights_ratio, rights_price。

    - rename 用 `_GBBQ_COLUMN_MAPPING`（拼音主表 + 中文兼容别名合并）；
    - date 归一为 int YYYYMMDD（与 sync 脚本同口径）；
    - code 补零到 6 位（与 sync 脚本 `str.zfill(6)` 同口径）；
    - 缺失的 market/category 以 -1 占位（宽进容错，保证 8 列契约）。
    """
    if df is None:
        return pd.DataFrame(columns=_GBBQ_TARGET_COLS)
    if df.empty:
        return df.reindex(columns=_GBBQ_TARGET_COLS)

    out = df.rename(columns=_GBBQ_COLUMN_MAPPING)
    # 同一目标列被多个别名同时命中时去重（保留最后，与 smart_factor_calculator 同策略）
    out = out.loc[:, ~out.columns.duplicated(keep="last")]

    if "code" in out.columns:
        out["code"] = out["code"].astype(str).str.zfill(6)

    if "date" in out.columns:
        date_num = _normalize_gbbq_date(out["date"])
        invalid = date_num.isna()
        if invalid.any():
            logger.warning(f"剔除 {int(invalid.sum())} 条非法 gbbq 日期记录")
            out = out.loc[~invalid].copy()
            date_num = date_num.loc[~invalid]
        out["date"] = date_num.astype("int64")

    for col in ("market", "category"):
        if col not in out.columns:
            logger.warning(f"gbbq 数据缺少 {col} 列，以 {_GBBQ_UNKNOWN_INT} (unknown) 占位")
            out[col] = _GBBQ_UNKNOWN_INT

    return _enforce_gbbq_contract(out)


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

        # 截断到完整记录边界：struct.iter_unpack 对非 32 字节整数倍的缓冲会抛
        # struct.error，与上面"损坏则告警但继续解析完整记录"的意图相矛盾。
        fmt = "<IIIIIfii"
        _record_size = struct.calcsize(fmt)
        buffer = buffer[: len(buffer) - (len(buffer) % _record_size)]

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
        # DataFrame.dropna 不检查索引，NaT 日期的行会被保留 → 显式剔除无效日期
        # (与上方 errors='coerce' 的意图一致)。
        df = df[df.index.notna()]
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
            
            # Step 2b: 拼音冻结表(+中文兼容别名) rename + datetime(int YYYYMMDD)→date 归一
            df = _normalize_gbbq_frame(df)
            logger.info(f"归一后列名: {list(df.columns)}")
            
            if 'code' in df.columns:
                df = df[df['code'].astype(str).str.match(r'^\d{6}$')]
            
            logger.info(f"过滤后剩余 {len(df)} 条有效记录")
            if not df.empty:
                logger.info(f"前5条记录:\n{df.head()}")
            
            # 函数尾: 断言并按冻结契约重排列序（date 已在归一化中转为 int YYYYMMDD）
            df = _enforce_gbbq_contract(df)
            if 'date' in df.columns:
                logger.info(f"date 已归一为 int YYYYMMDD（与 sync_local_tdx_day 同口径）: dtype={df['date'].dtype}")
            
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
        # Step 2b: 手动解密输出（date 原为 str YYYYMMDD、列序不同）归一到同一 8 列契约
        return _normalize_gbbq_frame(df)



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
            
            # Step 2b: 写盘前强制归一到冻结 8 列契约（date = int YYYYMMDD）
            df = _enforce_gbbq_contract(_normalize_gbbq_frame(df))
            
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
        default_gbbq_path = str(
            Path.home() / ".local/share/tdxcfv/drive_c/tc/T0002/hq_cache/gbbq"
        )
    
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
