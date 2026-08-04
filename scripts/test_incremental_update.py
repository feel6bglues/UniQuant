#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试修复后的增量更新功能
抽样100个代码进行校验
"""

import sys
import random
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from uniquant.shared.logger_factory import get_logger
from uniquant.data.managers.tdx_updater import TdxUpdater
from scripts.validate_tdx_import import (
    get_all_parquet_symbols,
    validate_batch,
    print_validation_report
)

logger = get_logger("TestIncremental")


def test_incremental_update(sample_size: int = 100):
    """测试增量更新并抽样校验"""
    print("\n" + "=" * 70)
    print("增量更新修复测试")
    print("=" * 70)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Step 1: 获取当前数据状态
    print("\n[Step 1] 获取当前数据湖状态...")
    all_symbols = get_all_parquet_symbols()
    print(f"  - 当前数据湖中共有 {len(all_symbols)} 只股票")
    
    if len(all_symbols) == 0:
        print("  - 错误: 未找到任何数据文件")
        return
    
    # Step 2: 随机抽样
    print(f"\n[Step 2] 随机抽样 {sample_size} 个代码...")
    if len(all_symbols) > sample_size:
        sample_symbols = random.sample(all_symbols, sample_size)
    else:
        sample_symbols = all_symbols
    print(f"  - 抽样股票: {', '.join(sample_symbols[:5])}...")
    
    # Step 3: 检查抽样股票的日期状态
    print("\n[Step 3] 检查抽样股票的日期状态...")
    from uniquant.data.lake.storage_manager import StorageManager
    storage = StorageManager()
    
    outdated_stocks = []
    for symbol in sample_symbols:
        try:
            df = storage.read_data(symbol, data_type="daily")
            if not df.empty and 'date' in df.columns:
                max_date = df['date'].max()
                print(f"  - {symbol}: 最新日期 {max_date}")
                # 检查是否缺少2026-03-02的数据
                if pd.to_datetime(max_date).date() < pd.to_datetime('2026-03-02').date():
                    outdated_stocks.append(symbol)
        except Exception as e:
            print(f"  - {symbol}: 读取失败 - {e}")
    
    print(f"\n  - 需要更新的股票: {len(outdated_stocks)} 只")
    if outdated_stocks:
        print(f"    示例: {', '.join(outdated_stocks[:10])}")
    
    # Step 4: 执行增量更新
    print("\n[Step 4] 执行增量更新...")
    updater = TdxUpdater(data_dir=str(PROJECT_ROOT / "data"))
    results = updater.update_all_data(full_update=False)
    
    print("\n增量更新结果:")
    print(f"  - 日线数据更新: {results.get('daily', 0)} 只股票")
    print(f"  - GBBQ数据更新: {'成功' if results.get('gbbq') else '跳过'}")
    
    # Step 5: 再次检查抽样股票的日期状态
    print("\n[Step 5] 更新后检查抽样股票的日期状态...")
    updated_count = 0
    for symbol in sample_symbols:
        try:
            df = storage.read_data(symbol, data_type="daily")
            if not df.empty and 'date' in df.columns:
                max_date = df['date'].max()
                has_latest = pd.to_datetime(max_date).date() >= pd.to_datetime('2026-03-02').date()
                if has_latest:
                    updated_count += 1
                    status = "✅ 已更新"
                else:
                    status = "❌ 未更新"
                print(f"  - {symbol}: 最新日期 {max_date} {status}")
        except Exception as e:
            print(f"  - {symbol}: 读取失败 - {e}")
    
    # Step 6: 抽样校验
    print(f"\n[Step 6] 抽样校验 ({sample_size} 个代码)...")
    validation_results = validate_batch(sample_symbols, sample_size=len(sample_symbols))
    print_validation_report(validation_results)
    
    # Step 7: 输出汇总
    print("\n" + "=" * 70)
    print("测试汇总")
    print("=" * 70)
    print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\n更新前需要更新的股票: {len(outdated_stocks)} 只")
    print(f"更新后已更新的股票: {updated_count} 只")
    print(f"\n校验样本数: {validation_results['total']}")
    print(f"校验通过: {validation_results['ok']}")
    print(f"存在差异: {validation_results['diff']}")
    print(f"校验错误: {validation_results['error']}")
    
    pass_rate = validation_results['ok'] / validation_results['total'] * 100 if validation_results['total'] > 0 else 0
    print(f"\n通过率: {pass_rate:.1f}%")
    
    if pass_rate >= 95:
        print("\n✅ 测试通过！增量更新修复成功。")
    elif pass_rate >= 80:
        print("\n⚠️ 测试部分通过，建议检查差异详情。")
    else:
        print("\n❌ 测试失败，建议检查修复逻辑。")
    
    return validation_results


if __name__ == "__main__":
    test_incremental_update(sample_size=100)
