"""
单进程计算复权因子（用于调试）
"""
import os
import sys
import pandas as pd
import numpy as np
import re
from pathlib import Path
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from uniquant.data.utils.smart_factor_calculator import GBBQProcessorV15, SmartFactorCalculatorV15

DAILY_DIR = Path(PROJECT_ROOT) / "data" / "lake" / "quotes" / "daily"
GBBQ_PATH = str(PROJECT_ROOT / "data" / "fq" / "gbbq.parquet")
OUTPUT_DIR = Path(PROJECT_ROOT) / "data" / "factors"

def run_single_process():
    """单进程计算"""
    print("=" * 60)
    print("单进程计算复权因子")
    print("=" * 60)
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # 清理旧文件
    for f in OUTPUT_DIR.glob("*.parquet"):
        os.remove(f)
    for f in OUTPUT_DIR.glob("*.csv"):
        os.remove(f)
    print("已清理旧文件")
    
    # 加载 GBBQ
    print("加载 GBBQ 数据...")
    df_cleaned = GBBQProcessorV15.load_and_clean(GBBQ_PATH)
    gbbq_dict = {code: df for code, df in df_cleaned.groupby('code')}
    print(f"加载了 {len(gbbq_dict)} 只股票的 GBBQ 数据")
    
    # 获取日线文件列表
    daily_files = list(DAILY_DIR.glob("*.parquet"))
    print(f"日线文件数: {len(daily_files)}")
    
    success_count = 0
    
    for file_path in tqdm(daily_files, desc="计算进度"):
        try:
            # 新格式: 提取代码和市场
            match = re.search(r'(\d{6})\.([A-Z]{2})', file_path.name)
            if not match:
                continue
            
            code = match.group(1)
            market = match.group(2)
            full_code = f"{code}.{market}"
            
            df_daily = pd.read_parquet(file_path)
            
            df_stock_gbbq = gbbq_dict.get(code, pd.DataFrame())
            df_events = GBBQProcessorV15.aggregate_events(df_stock_gbbq)
            
            calculator = SmartFactorCalculatorV15()
            result = calculator.calculate(df_daily, df_events)
            
            if not result.empty:
                result['code'] = code
                result['market'] = market
                result['type'] = 'hfq'
                output_file = OUTPUT_DIR / f"{full_code}.parquet"
                result.to_parquet(output_file, index=False, compression='snappy')
                success_count += 1
                
        except Exception as e:
            pass
    
    print(f"\n成功计算 {success_count} 只股票")
    
    # 验证 000001.SZ
    sz_file = OUTPUT_DIR / "000001.SZ.parquet"
    if sz_file.exists():
        df_000001 = pd.read_parquet(sz_file)
        print(f"\n验证 000001.SZ:")
        print(f"  记录数: {len(df_000001)}")
        print(f"  日期范围: {df_000001['date'].min()} ~ {df_000001['date'].max()}")
        print(f"  因子范围: {df_000001['factor'].min():.4f} ~ {df_000001['factor'].max():.4f}")
        
        # 对比 Baostock
        df_bs = pd.read_csv(PROJECT_ROOT / "data" / "baostock_factors" / "sz.000001.csv")
        print(f"\nBaostock backAdjustFactor: {df_bs['backAdjustFactor'].iloc[-1]}")
        print(f"比率: {df_000001['factor'].iloc[-1] / df_bs['backAdjustFactor'].iloc[-1]:.4f}")

if __name__ == "__main__":
    run_single_process()
