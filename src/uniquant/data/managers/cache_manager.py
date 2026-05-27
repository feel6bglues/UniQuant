#!/usr/bin/env python3
"""
创建全量股票代码和交易日历的本地缓存
"""

from datetime import datetime

from .baostock_cache_manager import create_baostock_cache
from .trade_calendar_manager import create_trade_calendar
from .stock_codes_cache_manager import create_stock_codes_cache
from ...shared.logger_factory import get_logger

logger = get_logger("CacheManager")


def create_all_caches():
    """
    创建全量股票代码和交易日历的本地缓存
    """
    logger.info("开始创建全量股票代码和交易日历的本地缓存")
    
    # 1. 创建全量股票代码本地缓存
    logger.info("\n1. 创建全量股票代码本地缓存...")
    try:
        # 使用 baostock_cache_manager 创建股票代码缓存
        create_baostock_cache()
    except (RuntimeError, ConnectionError, OSError, ImportError) as e:
        logger.error(f"创建全量股票代码缓存失败: {e}")
    
    # 2. 创建交易日历本地缓存
    logger.info("\n2. 创建交易日历本地缓存...")
    try:
        # 使用 trade_calendar_manager 创建交易日历缓存
        create_trade_calendar()
    except (RuntimeError, ConnectionError, OSError, ImportError) as e:
        logger.error(f"创建交易日历缓存失败: {e}")
    
    # 3. 验证缓存文件是否创建成功
    logger.info("\n3. 验证缓存文件...")
    current_year = datetime.now().year
    cache_files = [
        "data/all_stock_codes.csv",
        "data/trade_calendar.csv"
    ]
    
    try:
        import os
        for file_path in cache_files:
            if os.path.exists(file_path):
                file_size = os.path.getsize(file_path) / 1024  # KB
                logger.info(f"✓ {file_path} - {file_size:.2f} KB")
            else:
                logger.error(f"✗ {file_path} - 不存在")
    except OSError as e:
        logger.error(f"验证缓存文件失败: {e}")
    
    logger.info("缓存创建完成")


def main():
    """
    主函数
    """
    create_all_caches()


if __name__ == "__main__":
    main()
