#!/usr/bin/env python3
"""
AKShare东方财富数据更新脚本 - 稳健版
更新数据湖中的日线数据，包含原始/前复权/后复权价格
"""

import time
import random
from pathlib import Path

from ...shared.time_provider import get_time_provider
from typing import Optional, List, Tuple

import pandas as pd
import numpy as np
from uniquant.shared.logger_factory import get_logger

# NON_RESEARCH_RANDOMNESS: script sleeps are provider throttling/backoff controls.

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DAILY_DIR = DATA_DIR / "lake" / "quotes" / "daily"
STOCK_CODES_FILE = DATA_DIR / "all_stock_codes.csv"
PROGRESS_FILE = DATA_DIR / ".update_progress.json"
LOG_FILE = DATA_DIR / "update_daily.log"

DAILY_DIR.mkdir(parents=True, exist_ok=True)

logger = get_logger(__name__)


def load_stock_list() -> List[Tuple[str, str]]:
    """加载股票列表"""
    if not STOCK_CODES_FILE.exists():
        logger.error(f"股票列表文件不存在: {STOCK_CODES_FILE}")
        return []
    
    df = pd.read_csv(STOCK_CODES_FILE, encoding='utf-8-sig')
    
    valid_stocks = []
    for row in df.itertuples(index=False):
        code_raw = str(row.code)
        status = row.status
        
        if status != 1:
            continue
        
        if code_raw.startswith('sh.'):
            code = code_raw[3:]
            if code.startswith('60') or code.startswith('68'):
                valid_stocks.append((code, f"{code}.SH"))
        elif code_raw.startswith('sz.'):
            code = code_raw[3:]
            if code.startswith('00') or code.startswith('30'):
                valid_stocks.append((code, f"{code}.SZ"))
        elif code_raw.startswith('bj.'):
            code = code_raw[3:]
            if code.startswith('4') or code.startswith('8'):
                valid_stocks.append((code, f"{code}.BJ"))
    
    logger.info(f"加载有效股票数: {len(valid_stocks)}")
    return valid_stocks


def load_progress() -> set:
    """加载已完成的进度"""
    import json
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, 'r') as f:
                data = json.load(f)
                return set(data.get('completed', []))
        except (json.JSONDecodeError, IOError, OSError):
            logger.exception("加载进度文件失败，返回空集合")
            pass
    return set()


def save_progress(completed: set):
    """保存进度"""
    import json
    try:
        with open(PROGRESS_FILE, 'w') as f:
            json.dump({'completed': list(completed), 'last_update': get_time_provider().now().isoformat()}, f)
    except Exception as e:
        logger.warning(f"保存进度失败: {e}")


def fetch_data(code: str) -> Optional[dict]:
    """获取三种复权类型的数据"""
    import akshare as ak
    
    end_date = get_time_provider().now().strftime('%Y%m%d')
    start_date = '19900101'
    
    result = {}
    
    for adjust_type in ['qfq', 'hfq', '']:
        for retry in range(3):
            try:
                df = ak.stock_zh_a_hist(
                    symbol=code,
                    period='daily',
                    start_date=start_date,
                    end_date=end_date,
                    adjust=adjust_type
                )
                
                if df is not None and not df.empty:
                    key = adjust_type if adjust_type else 'raw'
                    result[key] = df
                break
                
            except Exception as e:
                if retry < 2:
                    logger.warning(f"获取 {code} ({adjust_type}) 失败，重试 {retry+1}/3: {e}")
                    time.sleep(random.uniform(2, 5))
                else:
                    logger.error(f"获取 {code} ({adjust_type}) 最终失败: {e}")
    
    if len(result) >= 2:
        return result
    return None


def process_data(data: dict, code: str, symbol: str) -> Optional[pd.DataFrame]:
    """处理数据，合并原始/前复权/后复权"""
    try:
        raw_df = data.get('raw')
        qfq_df = data.get('qfq')
        hfq_df = data.get('hfq')
        
        if raw_df is None or raw_df.empty:
            return None
        
        column_map = {
            '日期': 'date',
            '开盘': 'open',
            '收盘': 'close',
            '最高': 'high',
            '最低': 'low',
            '成交量': 'vol',
            '成交额': 'amount',
            '振幅': 'amplitude',
            '涨跌幅': 'pct_change',
            '换手率': 'turnover'
        }
        
        df = raw_df.copy()
        df = df.rename(columns=column_map)
        
        if '日期' in raw_df.columns:
            df['date'] = pd.to_datetime(raw_df['日期'])
        elif 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
        
        df['code'] = code
        df['market'] = symbol.split('.')[-1] if '.' in symbol else ''
        
        if qfq_df is not None and not qfq_df.empty:
            qfq_renamed = qfq_df.rename(columns=column_map)
            if '日期' in qfq_df.columns:
                qfq_renamed['date'] = pd.to_datetime(qfq_df['日期'])
            elif 'date' in qfq_renamed.columns:
                qfq_renamed['date'] = pd.to_datetime(qfq_renamed['date'])
            
            qfq_cols = ['date', 'open', 'close', 'high', 'low']
            qfq_subset = qfq_renamed[qfq_cols].copy()
            qfq_subset.columns = ['date', 'qfq_open', 'qfq_close', 'qfq_high', 'qfq_low']
            df = df.merge(qfq_subset, on='date', how='left')
        
        if hfq_df is not None and not hfq_df.empty:
            hfq_renamed = hfq_df.rename(columns=column_map)
            if '日期' in hfq_df.columns:
                hfq_renamed['date'] = pd.to_datetime(hfq_df['日期'])
            elif 'date' in hfq_renamed.columns:
                hfq_renamed['date'] = pd.to_datetime(hfq_renamed['date'])
            
            hfq_cols = ['date', 'open', 'close', 'high', 'low']
            hfq_subset = hfq_renamed[hfq_cols].copy()
            hfq_subset.columns = ['date', 'hfq_open', 'hfq_close', 'hfq_high', 'hfq_low']
            df = df.merge(hfq_subset, on='date', how='left')
        
        if 'qfq_close' in df.columns and 'close' in df.columns:
            df['qfq_factor'] = np.where(
                df['close'] > 0,
                df['qfq_close'] / df['close'],
                1.0
            )
        
        if 'hfq_close' in df.columns and 'close' in df.columns:
            df['adj_factor'] = np.where(
                df['close'] > 0,
                df['hfq_close'] / df['close'],
                1.0
            )
        
        numeric_cols = ['open', 'high', 'low', 'close', 'vol', 'amount']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        df = df.sort_values('date').reset_index(drop=True)
        
        return df
        
    except Exception as e:
        logger.error(f"处理数据失败 {symbol}: {e}")
        return None


def save_data(df: pd.DataFrame, symbol: str) -> bool:
    """保存数据到Parquet"""
    try:
        file_path = DAILY_DIR / f"{symbol}.parquet"
        df.to_parquet(str(file_path), compression='snappy', index=False)
        return True
    except Exception as e:
        logger.error(f"保存数据失败 {symbol}: {e}")
        return False


def main():
    logger.info("=" * 60)
    logger.info("AKShare 东方财富数据更新任务启动")
    logger.info("=" * 60)
    
    stock_list = load_stock_list()
    if not stock_list:
        logger.error("没有有效的股票列表")
        return
    
    completed = load_progress()
    
    if completed:
        logger.info(f"断点续传: 已完成 {len(completed)} 只股票")
    
    total = len(stock_list)
    success_count = 0
    fail_count = 0
    skip_count = 0
    failed_symbols = []
    request_count = 0
    
    for i, (code, symbol) in enumerate(stock_list, 1):
        if symbol in completed:
            skip_count += 1
            if i % 500 == 0:
                logger.info(f"进度: {i}/{total} (跳过: {skip_count})")
            continue
        
        logger.info(f"[{i}/{total}] 更新 {symbol}...")
        
        try:
            data = fetch_data(code)
            
            if data is None:
                logger.warning(f"{symbol} 数据获取失败")
                fail_count += 1
                failed_symbols.append(symbol)
            else:
                df = process_data(data, code, symbol)
                
                if df is None or df.empty:
                    logger.warning(f"{symbol} 数据处理失败")
                    fail_count += 1
                    failed_symbols.append(symbol)
                else:
                    if save_data(df, symbol):
                        logger.info(f"{symbol} 更新成功，共 {len(df)} 条记录")
                        success_count += 1
                        completed.add(symbol)
                    else:
                        fail_count += 1
                        failed_symbols.append(symbol)
        
        except Exception as e:
            logger.error(f"更新 {symbol} 异常: {e}")
            fail_count += 1
            failed_symbols.append(symbol)
        
        if i % 10 == 0:
            save_progress(completed)
        
        request_count += 1
        delay = random.uniform(0.8, 2.0)
        time.sleep(delay)
        
        if request_count % 50 == 0:
            batch_delay = random.uniform(30, 60)
            logger.info(f"已完成 {request_count} 只股票，休息 {batch_delay:.1f} 秒...")
            time.sleep(batch_delay)
    
    save_progress(completed)
    
    logger.info("=" * 60)
    logger.info("更新任务完成")
    logger.info(f"总数: {total}")
    logger.info(f"成功: {success_count}")
    logger.info(f"跳过: {skip_count}")
    logger.info(f"失败: {fail_count}")
    
    if failed_symbols:
        logger.info(f"失败股票数: {len(failed_symbols)}")
        
        failed_file = DATA_DIR / "failed_updates.txt"
        with open(failed_file, 'w') as f:
            for s in failed_symbols:
                f.write(s + '\n')
        logger.info(f"失败列表已保存到: {failed_file}")


if __name__ == "__main__":
    main()
