#!/usr/bin/env python3
"""
ETF数据导入脚本
从通达信本地数据导入国家队ETF数据用于NTF检测

使用方法:
    python scripts/download_etf_data.py
"""

import os
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import sys
from pathlib import Path
from typing import Optional

import pandas as pd

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from uniquant.data.parsers.tdx_parser import TDXParser
from uniquant.shared.logger_factory import get_logger
from uniquant.shared.config_loader import get_config

logger = get_logger("ImportETF")

ETF_LIST = [
    ("510300", "510300.SH", "沪深300ETF"),
    ("510500", "510500.SH", "中证500ETF"),
    ("510050", "510050.SH", "上证50ETF"),
    ("159915", "159915.SZ", "创业板ETF"),
    ("512880", "512880.SH", "证券ETF"),
    ("512660", "512660.SH", "军工ETF"),
    ("512690", "512690.SH", "酒ETF"),
    ("159919", "159919.SZ", "沪深300ETF深"),
    ("588000", "588000.SH", "科创50ETF"),
    ("159949", "159949.SZ", "创业板50ETF"),
]

DATA_DIR = project_root / "data" / "lake" / "quotes" / "daily"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def get_tdx_path() -> Optional[Path]:
    """获取通达信安装路径"""
    config = get_config()
    tdx_path = config.get("base.tdx.path", None)
    if tdx_path:
        return Path(tdx_path)
    
    default_paths = [
        Path(p) for p in os.environ.get("TDX_BASE_PATH", "").split(os.pathsep) if p
    ]
    if not default_paths:
        default_paths = [
            Path(r"d:\dfq"),
            Path(r"d:\通达信"),
            Path(r"c:\tdx"),
            Path(r"c:\通达信"),
        ]
    
    for path in default_paths:
        if Path(path).exists():
            return Path(path)
    
    return None


def get_day_file_path(tdx_path: Path, symbol: str) -> Optional[Path]:
    """构建通达信 .day 文件路径"""
    code = symbol.split('.')[0]
    market = symbol.split('.')[1].lower()
    
    if market == 'sh':
        day_dir = tdx_path / "vipdoc" / "sh" / "lday"
        filename = f"sh{code}.day"
    elif market == 'sz':
        day_dir = tdx_path / "vipdoc" / "sz" / "lday"
        filename = f"sz{code}.day"
    else:
        return None
    
    day_path = day_dir / filename
    return day_path if day_path.exists() else None


def import_etf_from_tdx(code: str, symbol: str, tdx_path: Path, parser: TDXParser) -> Optional[pd.DataFrame]:
    """从通达信本地数据导入ETF数据"""
    day_path = get_day_file_path(tdx_path, symbol)
    
    if not day_path:
        logger.warning(f"通达信文件不存在: {symbol}")
        return None
    
    try:
        df = parser.parse_day_file(str(day_path))
        
        if df is None or df.empty:
            return None
        
        if 'date' not in df.columns:
            df = df.reset_index()
        
        df['code'] = code
        df['market'] = symbol.split('.')[-1]
        
        numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'amount']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        df = df.sort_values('date').reset_index(drop=True)
        
        return df
        
    except (OSError, ValueError, KeyError, TypeError) as e:
        logger.error(f"解析通达信文件失败 {symbol}: {e}")
        return None


def save_etf_data(df: pd.DataFrame, symbol: str) -> bool:
    """保存ETF数据到Parquet"""
    try:
        file_path = DATA_DIR / f"{symbol}.parquet"
        df.to_parquet(str(file_path), compression='snappy', index=False)
        return True
    except (OSError, ValueError) as e:
        logger.error(f"保存ETF数据失败 {symbol}: {e}")
        return False


def main():
    logger.info("=" * 60)
    logger.info("ETF数据导入任务启动（通达信本地数据源）")
    logger.info("=" * 60)
    
    tdx_path = get_tdx_path()
    if not tdx_path:
        logger.error("未找到通达信安装路径，请在配置文件中设置 base.tdx.path")
        return
    
    logger.info(f"通达信路径: {tdx_path}")
    
    parser = TDXParser()
    
    success_count = 0
    fail_count = 0
    
    for i, (code, symbol, name) in enumerate(ETF_LIST, 1):
        logger.info(f"[{i}/{len(ETF_LIST)}] 导入 {name} ({symbol})...")
        
        df = import_etf_from_tdx(code, symbol, tdx_path, parser)
        
        if df is not None and not df.empty:
            if save_etf_data(df, symbol):
                logger.info(f"  成功: {len(df)} 条记录")
                success_count += 1
            else:
                fail_count += 1
        else:
            logger.warning("  失败: 无法获取数据")
            fail_count += 1
    
    logger.info("=" * 60)
    logger.info(f"导入完成: 成功 {success_count}, 失败 {fail_count}")
    logger.info(f"数据保存目录: {DATA_DIR}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
