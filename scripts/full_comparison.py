"""
全量对比本地计算的复权因子与 Baostock 因子
"""
import os
import sys
import pandas as pd
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

FACTORS_DIR = str(PROJECT_ROOT / "data" / "factors")
BAOSTOCK_DIR = str(PROJECT_ROOT / "data" / "baostock_factors")
OUTPUT_FILE = str(PROJECT_ROOT / "data" / "factors" / "full_comparison_result.csv")


def get_code_mapping():
    """获取股票代码映射"""
    mapping = {}
    
    # 本地因子文件 (新格式: 000001.SZ.parquet)
    for f in os.listdir(FACTORS_DIR):
        if f.endswith('.parquet') and '.' in f.replace('.parquet', ''):
            full_code = f.replace('.parquet', '')
            parts = full_code.split('.')
            if len(parts) == 2:
                code = parts[0]
                market = parts[1]
                # Baostock 格式: sh.600000 或 sz.000001
                bs_prefix = 'sh' if market == 'SH' else 'sz'
                bs_code = f"{bs_prefix}.{code}"
                mapping[code] = {'local': full_code, 'baostock': bs_code, 'market': market}
    
    return mapping


def compare_single_stock(args):
    """对比单只股票的因子"""
    code_base, file_info = args
    
    result = {
        'code': code_base,
        'market': file_info.get('market', ''),
        'local_factor': None,
        'baostock_factor': None,
        'ratio': None,
        'error_pct': None,
        'match': False,
        'local_records': 0,
        'baostock_records': 0,
        'status': 'ok'
    }
    
    try:
        # 读取本地因子
        if file_info['local']:
            local_path = os.path.join(FACTORS_DIR, f"{file_info['local']}.parquet")
            if not os.path.exists(local_path):
                local_path = os.path.join(FACTORS_DIR, file_info['local'])
            
            if os.path.exists(local_path):
                df_local = pd.read_parquet(local_path)
                result['local_records'] = len(df_local)
                if not df_local.empty and 'factor' in df_local.columns:
                    result['local_factor'] = float(df_local['factor'].iloc[-1])
            else:
                result['status'] = 'local_file_not_found'
        
        # 读取 Baostock 因子
        if file_info['baostock']:
            bs_path = os.path.join(BAOSTOCK_DIR, f"{file_info['baostock']}.csv")
            if not os.path.exists(bs_path):
                bs_path = os.path.join(BAOSTOCK_DIR, f"{file_info['baostock']}")
            
            if os.path.exists(bs_path):
                df_bs = pd.read_csv(bs_path)
                result['baostock_records'] = len(df_bs)
                if not df_bs.empty and 'backAdjustFactor' in df_bs.columns:
                    result['baostock_factor'] = float(df_bs['backAdjustFactor'].iloc[-1])
            else:
                result['status'] = 'baostock_file_not_found'
        
        # 计算对比结果
        if result['local_factor'] is not None and result['baostock_factor'] is not None:
            if result['baostock_factor'] > 0:
                result['ratio'] = result['local_factor'] / result['baostock_factor']
                result['error_pct'] = abs(result['ratio'] - 1.0) * 100
                result['match'] = result['error_pct'] <= 1.0
            else:
                result['status'] = 'zero_baostock_factor'
        elif result['local_factor'] is None:
            result['status'] = 'no_local_factor'
        elif result['baostock_factor'] is None:
            result['status'] = 'no_baostock_factor'
            
    except Exception as e:
        result['status'] = f'error: {str(e)[:50]}'
    
    return result


def run_full_comparison():
    """运行全量对比"""
    print("=" * 60)
    print("全量复权因子对比")
    print("=" * 60)
    
    # 获取代码映射
    print("1. 获取股票代码映射...")
    mapping = get_code_mapping()
    print(f"   共 {len(mapping)} 只股票")
    
    # 并行对比
    print("\n2. 并行对比因子...")
    results = []
    
    with ProcessPoolExecutor(max_workers=None) as executor:
        args_list = list(mapping.items())
        futures = list(tqdm(
            executor.map(compare_single_stock, args_list),
            total=len(args_list),
            desc="对比进度"
        ))
        results = futures
    
    # 生成结果 DataFrame
    print("\n3. 生成统计报告...")
    df_results = pd.DataFrame(results)
    
    # 统计信息
    total = len(df_results)
    matched = df_results['match'].sum()
    
    print(f"\n{'='*60}")
    print("对比结果统计")
    print(f"{'='*60}")
    print(f"总对比数: {total}")
    print(f"匹配数 (误差≤1%): {matched}")
    print(f"匹配率: {matched/total*100:.2f}%")
    
    # 误差分布
    valid_errors = df_results[df_results['error_pct'].notna()]['error_pct']
    print("\n误差分布:")
    print(f"  ≤0.1%: {(valid_errors <= 0.1).sum()}")
    print(f"  0.1%-0.5%: {((valid_errors > 0.1) & (valid_errors <= 0.5)).sum()}")
    print(f"  0.5%-1%: {((valid_errors > 0.5) & (valid_errors <= 1)).sum()}")
    print(f"  1%-5%: {((valid_errors > 1) & (valid_errors <= 5)).sum()}")
    print(f"  5%-10%: {((valid_errors > 5) & (valid_errors <= 10)).sum()}")
    print(f"  >10%: {(valid_errors > 10).sum()}")
    
    # 状态分布
    print("\n状态分布:")
    print(df_results['status'].value_counts().to_string())
    
    # 保存结果
    df_results.to_csv(OUTPUT_FILE, index=False)
    print(f"\n结果已保存: {OUTPUT_FILE}")
    
    # 保存不匹配的股票详情
    mismatch_file = OUTPUT_FILE.replace('.csv', '_mismatch.csv')
    df_mismatch = df_results[~df_results['match']].sort_values('error_pct', ascending=False)
    df_mismatch.to_csv(mismatch_file, index=False)
    print(f"不匹配股票已保存: {mismatch_file}")
    
    return df_results


if __name__ == "__main__":
    df = run_full_comparison()
