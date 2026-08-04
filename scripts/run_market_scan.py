#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""启动市场扫描 - 全量扫描"""
import sys
sys.path.insert(0, '.')

from uniquant.services.scan_service import ScanPipeline, ScanConfig
from uniquant.data.lake.storage_manager import StorageManager
from uniquant.shared.constants import ResultsConstants

# 获取股票列表
storage = StorageManager('./data')
all_symbols = storage.get_symbols()

# 过滤：只保留沪深主板股票 (600/000/300开头)
# 排除指数和板块指数 (000001-000999 是指数, 880xxx 是板块)
main_board = [
    s for s in all_symbols 
    if s.startswith(('600', '601', '603', '605', '000', '001', '002', '003', '300', '301'))
    and not s.startswith(('000001', '000002', '000003', '000004', '000005', '000006', '000007', '000008', '000009'))
    and not s.startswith('0000')  # 排除指数
    and not s.startswith('0001')  # 排除指数
    and not s.startswith('0002')  # 排除指数
    and not s.startswith('0003')  # 排除指数
    and not s.startswith('0009')  # 排除指数
    and not s.startswith('399')   # 排除深证指数
]

print(f"全市场股票数: {len(all_symbols)}")
print(f"主板股票数: {len(main_board)}")
print(f"本次扫描数: {len(main_board)}")
print()

config = ScanConfig(
    top_n=50,
    bottom_n=50,
    lightweight=True  # 轻量模式，跳过IC/IR分析
)

pipeline = ScanPipeline(data_dir='./data', config=config)
output_dir = f"./{ResultsConstants.HANDS_DIR_NAME}/{ResultsConstants.REPORTS_DIR_NAME}"
result = pipeline.run(output_dir=output_dir, symbols=main_board)

if result["status"] == "success":
    print("\n扫描完成!")
    print(f"耗时: {result['duration_seconds']:.2f} 秒")
    print(f"扫描股票数: {result['stocks_scanned']}")
    print(f"处理记录数: {result['records_processed']}")
    print("\n生成的报告文件:")
    for name, path in result["report_files"].items():
        print(f"  - {name}: {path}")
else:
    print("\n扫描失败!")
    print(f"错误: {result.get('error', '未知错误')}")
