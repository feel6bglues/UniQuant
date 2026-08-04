import os
import sys
import logging
import platform
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from uniquant.data.utils.smart_factor_calculator import (
    run_parallel_calculation
)
from uniquant.shared.config_loader import get_config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("FactorCalculator")

DAILY_DIR = str(PROJECT_ROOT / "data" / "lake" / "quotes" / "daily")
GBBQ_PARQUET_PATH = str(PROJECT_ROOT / "data" / "fq" / "gbbq.parquet")
OUTPUT_DIR = str(PROJECT_ROOT / "data" / "factors")
BAOSTOCK_FACTORS_DIR = str(PROJECT_ROOT / "data" / "baostock_factors")


def _resolve_gbbq_raw_path() -> str:
    """从环境变量或配置文件解析 GBBQ 原始文件路径"""
    env_path = os.environ.get("GBBQ_TDX_PATH")
    if env_path:
        return env_path
    try:
        config = get_config()
        tdx_base = config.get("base", {}).get("tdx", {}).get("path", "")
        if tdx_base:
            candidate = Path(tdx_base) / "T0002" / "hq_cache" / "gbbq"
            if candidate.exists():
                return str(candidate)
    except Exception:
        pass
    # 跨平台默认路径
    if platform.system() == "Windows":
        candidates = [
            r"D:\dfzq\T0002\hq_cache\gbbq",
            r"D:\通达信\T0002\hq_cache\gbbq",
            r"C:\tdx\T0002\hq_cache\gbbq",
        ]
    else:
        candidates = [
            str(Path.home() / ".local/share/tdxcfv/drive_c/tc/T0002/hq_cache/gbbq"),
            str(Path.home() / ".tdx/T0002/hq_cache/gbbq"),
            "/opt/tdx/T0002/hq_cache/gbbq",
        ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return ""


def convert_gbbq_to_parquet():
    """将通达信 GBBQ 转换为 parquet 格式"""
    from uniquant.data.parsers.tdx_parser import TDXParser

    if os.path.exists(GBBQ_PARQUET_PATH):
        logger.info(f"GBBQ parquet 已存在: {GBBQ_PARQUET_PATH}")
        return True

    gbbq_raw_path = _resolve_gbbq_raw_path()
    if not gbbq_raw_path or not os.path.exists(gbbq_raw_path):
        logger.error("未找到 GBBQ 原始文件。请设置 GBBQ_TDX_PATH 环境变量或在配置中指定 tdx.path。")
        logger.error(f"尝试的路径: {gbbq_raw_path}")
        return False

    logger.info(f"开始转换 GBBQ: {gbbq_raw_path} -> {GBBQ_PARQUET_PATH}")

    parser = TDXParser()
    success = parser.save_gbbq_to_fq(gbbq_raw_path, GBBQ_PARQUET_PATH)

    if success:
        logger.info("GBBQ 转换成功!")
    else:
        logger.error("GBBQ 转换失败")

    return success


def verify_single_stock(local_factor: float, baostock_factor: float, tolerance: float = 0.01) -> dict:
    """校验单只股票的因子误差"""
    if baostock_factor == 0:
        return {"match": False, "error": "baostock factor is zero", "local": local_factor, "baostock": baostock_factor}

    error = abs(local_factor - baostock_factor) / baostock_factor
    match = error <= tolerance

    return {
        "match": match,
        "error": error,
        "local": local_factor,
        "baostock": baostock_factor,
        "tolerance": tolerance
    }


def compare_with_baostock(factors_dir: str, baostock_dir: str, sample_size: int = 100) -> pd.DataFrame:
    """
    与 Baostock 因子进行全量对比

    Args:
        factors_dir: 本地计算的因子目录
        baostock_dir: Baostock 因子目录
        sample_size: 抽样对比数量

    Returns:
        DataFrame: 对比结果
    """
    logger.info("开始与 Baostock 因子对比...")

    local_files = list(Path(factors_dir).glob("*.parquet"))
    logger.info(f"本地因子文件数量: {len(local_files)}")

    results = []
    comparison_count = 0

    for local_file in local_files[:sample_size]:
        try:
            full_code = local_file.stem
            
            if '.' in full_code:
                code, market = full_code.split('.')
            else:
                code = full_code
                market = 'SH' if code.startswith('6') else 'SZ'
            
            local_df = pd.read_parquet(local_file)

            bs_prefix = 'sh' if market == 'SH' else 'sz'
            bs_file = Path(baostock_dir) / f"{bs_prefix}.{code}.csv"

            if not bs_file.exists():
                continue

            bs_df = pd.read_csv(bs_file)
            if 'backAdjustFactor' not in bs_df.columns:
                continue

            latest_local = local_df.iloc[-1] if not local_df.empty else None
            latest_bs = bs_df.iloc[-1] if not bs_df.empty else None

            if latest_local is None or latest_bs is None:
                continue

            local_factor = latest_local.get('factor', 1.0)
            bs_factor = latest_bs.get('backAdjustFactor', 1.0)

            if pd.isna(local_factor) or pd.isna(bs_factor) or bs_factor == 0:
                continue

            result = verify_single_stock(local_factor, bs_factor)
            result['code'] = code
            result['market'] = market
            results.append(result)
            comparison_count += 1

            if comparison_count % 50 == 0:
                logger.info(f"已对比 {comparison_count} 只股票...")

        except (OSError, ValueError, TypeError, pd.errors.ParserError) as e:
            logger.debug(f"对比 {local_file.name} 失败: {e}")
            continue

    if not results:
        logger.warning("没有找到可对比的数据")
        return pd.DataFrame()

    result_df = pd.DataFrame(results)
    match_count = result_df['match'].sum() if 'match' in result_df.columns else 0

    logger.info("=== 对比完成 ===")
    logger.info(f"总对比数量: {len(result_df)}")
    logger.info(f"误差 <= 1% 匹配数量: {match_count}")
    logger.info(f"匹配率: {match_count / len(result_df) * 100:.2f}%")

    if 'error' in result_df.columns:
        mean_error = result_df['error'].mean() * 100
        max_error = result_df['error'].max() * 100
        logger.info(f"平均误差: {mean_error:.2f}%")
        logger.info(f"最大误差: {max_error:.2f}%")

    return result_df


def run_full_calculation():
    """执行完整的复权因子计算流程"""
    logger.info("=" * 60)
    logger.info("开始复权因子计算 (V15 算法)")
    logger.info("=" * 60)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    logger.info(f"1. 日线数据目录: {DAILY_DIR}")
    logger.info(f"2. GBBQ parquet 路径: {GBBQ_PARQUET_PATH}")
    logger.info(f"3. 输出目录: {OUTPUT_DIR}")

    logger.info("=" * 60)
    logger.info("步骤0: 转换 GBBQ 数据格式")
    logger.info("=" * 60)

    if not convert_gbbq_to_parquet():
        logger.error("GBBQ 转换失败，无法继续")
        return

    gbbq_path = GBBQ_PARQUET_PATH
    logger.info(f"使用 GBBQ: {gbbq_path}")

    logger.info("=" * 60)
    logger.info("步骤1: 多进程并行计算复权因子")
    logger.info("=" * 60)

    success_count = run_parallel_calculation(
        daily_dir=DAILY_DIR,
        gbbq_path=gbbq_path,
        output_dir=OUTPUT_DIR,
        is_hfq=True,
        max_workers=None
    )

    logger.info(f"成功计算 {success_count} 只股票的复权因子")

    logger.info("=" * 60)
    logger.info("步骤2: 与 Baostock 因子对比")
    logger.info("=" * 60)

    comparison_result = compare_with_baostock(
        factors_dir=OUTPUT_DIR,
        baostock_dir=BAOSTOCK_FACTORS_DIR,
        sample_size=500
    )

    if not comparison_result.empty:
        output_comparison = OUTPUT_DIR + "/comparison_result.csv"
        comparison_result.to_csv(output_comparison, index=False)
        logger.info(f"对比结果已保存到: {output_comparison}")

        print("\n" + "=" * 60)
        print("对比结果摘要:")
        print("=" * 60)
        print(comparison_result.head(20).to_string())
        print("=" * 60)

    logger.info("=" * 60)
    logger.info("复权因子计算完成!")
    logger.info("=" * 60)


if __name__ == "__main__":
    run_full_calculation()
