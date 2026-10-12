#!/usr/bin/env python3
"""
migrate_index_parquets.py - 冲突 C5 物理清障脚本

功能:
1. 在 /home/james/Documents/Project/UniQuant/data/lake/quotes/ 创建 index/ 目录；
2. 将 daily/ 下所有 000*.SH.parquet (200个) 与 399*.SZ.parquet (354个) 物理移动至 index/；
3. 移动对应的 .lock 文件（若存在）；
4. 维护 /home/james/Documents/Project/UniQuant/data/lake/index 软链接指向 quotes/index，保障旧路径兼容；
5. 验证迁移后 daily/ 剩余文件数正好为 5,201 (5755 - 554)；
6. 验证 StorageManager 读取正常 (分别验证 daily/ 股票读取与 index/ 指数读取)。
"""

import os
import shutil
import sys
from pathlib import Path

UNIQUANT_DIR = Path("/home/james/Documents/Project/UniQuant")
DATA_DIR = UNIQUANT_DIR / "data"
QUOTES_DIR = DATA_DIR / "lake" / "quotes"
DAILY_DIR = QUOTES_DIR / "daily"
INDEX_DIR = QUOTES_DIR / "index"
LAKE_INDEX_DIR = DATA_DIR / "lake" / "index"


def migrate_parquets(dry_run: bool = False):
    print(f"=== 开始执行 C5 指数 Parquet 文件物理迁移 ===")
    print(f"源目录: {DAILY_DIR}")
    print(f"目标目录: {INDEX_DIR}")
    print(f"Dry Run: {dry_run}")

    if not DAILY_DIR.exists():
        raise FileNotFoundError(f"日线数据目录不存在: {DAILY_DIR}")

    # 1. 扫描匹配文件
    sh_files = sorted(list(DAILY_DIR.glob("000*.SH.parquet")))
    sz_files = sorted(list(DAILY_DIR.glob("399*.SZ.parquet")))
    all_daily = sorted(list(DAILY_DIR.glob("*.parquet")))

    print(f"当前 daily/ 总 parquet 文件数: {len(all_daily)}")
    print(f"匹配到 000*.SH.parquet: {len(sh_files)} 个")
    print(f"匹配到 399*.SZ.parquet: {len(sz_files)} 个")

    total_to_move = len(sh_files) + len(sz_files)
    print(f"待迁移指数文件总计: {total_to_move} 个")

    if total_to_move != 554 and len(all_daily) == 5755:
        raise ValueError(f"预期待迁移 554 个文件，实际发现 {total_to_move} 个文件！")

    if not dry_run:
        INDEX_DIR.mkdir(parents=True, exist_ok=True)

    # 2. 执行移动
    moved_count = 0
    lock_moved_count = 0
    files_to_move = sh_files + sz_files

    for src_path in files_to_move:
        dest_path = INDEX_DIR / src_path.name
        lock_src = src_path.with_suffix(src_path.suffix + ".lock")
        lock_dest = INDEX_DIR / lock_src.name

        if not dry_run:
            shutil.move(str(src_path), str(dest_path))
            moved_count += 1
            if lock_src.exists():
                shutil.move(str(lock_src), str(lock_dest))
                lock_moved_count += 1
        else:
            moved_count += 1

    print(f"已迁移 parquet 文件数: {moved_count}, 附带 lock 文件数: {lock_moved_count}")

    # 3. 维护 data/lake/index 兼容软链接
    if not dry_run:
        if LAKE_INDEX_DIR.is_symlink():
            print(f"data/lake/index 已是软链接: {LAKE_INDEX_DIR.resolve()}")
        elif LAKE_INDEX_DIR.exists() and not any(LAKE_INDEX_DIR.iterdir()):
            print(f"data/lake/index 为空目录，替换为软链接指向 {INDEX_DIR}")
            LAKE_INDEX_DIR.rmdir()
            LAKE_INDEX_DIR.symlink_to(Path("quotes") / "index")
        elif not LAKE_INDEX_DIR.exists():
            LAKE_INDEX_DIR.symlink_to(Path("quotes") / "index")

    # 4. 验证剩余文件数量
    remaining_daily = list(DAILY_DIR.glob("*.parquet"))
    index_files = list(INDEX_DIR.glob("*.parquet"))

    print(f"\n--- 迁移后文件校验 ---")
    print(f"daily/ 剩余 parquet 文件数: {len(remaining_daily)} (预期: 5201)")
    print(f"index/ 现有 parquet 文件数: {len(index_files)} (预期: 554)")

    if not dry_run:
        assert len(remaining_daily) == 5201, f"daily/ 剩余文件数不是 5201，而是 {len(remaining_daily)}"
        assert len(index_files) == 554, f"index/ 文件数不是 554，而是 {len(index_files)}"
        print(">>> 物理文件数量校验 100% 通过！")
    else:
        print(f"Dry Run 预演: 迁移后 daily 将有 {len(remaining_daily) - total_to_move} 个，index 将有 {total_to_move} 个")


def verify_storage_manager():
    print(f"\n=== 验证 StorageManager 读取逻辑 ===")
    sys.path.insert(0, str(UNIQUANT_DIR / "src"))
    from uniquant.data.lake.storage_manager import StorageManager

    sm = StorageManager(data_dir=str(DATA_DIR))

    # 验证股票读取
    stock_df = sm.read_data("000001.SZ", data_type="daily")
    print(f"读取股票 000001.SZ (daily): shape={stock_df.shape}, empty={stock_df.empty}")
    assert not stock_df.empty, "股票 000001.SZ 读取失败"

    # 验证指数读取 (通过 data_type='index')
    index_df = sm.read_data("000300.SH", data_type="index")
    print(f"读取指数 000300.SH (index): shape={index_df.shape}, empty={index_df.empty}")
    assert not index_df.empty, "指数 000300.SH 读取失败"

    # 验证指数读取 (399001.SZ)
    sz_idx_df = sm.read_data("399001.SZ", data_type="index")
    print(f"读取指数 399001.SZ (index): shape={sz_idx_df.shape}, empty={sz_idx_df.empty}")
    assert not sz_idx_df.empty, "指数 399001.SZ 读取失败"

    # 验证 get_symbols
    stock_symbols = sm.get_symbols(exclude_indices=True)
    all_symbols = sm.get_symbols(exclude_indices=False)
    print(f"sm.get_symbols(exclude_indices=True): {len(stock_symbols)} (预期: 5201)")
    print(f"sm.get_symbols(exclude_indices=False): {len(all_symbols)} (预期: 5755)")
    assert len(stock_symbols) == 5201, f"stock_symbols 期望 5201，实为 {len(stock_symbols)}"

    print(">>> StorageManager 验收 100% 通过！")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    migrate_parquets(dry_run=dry_run)
    if not dry_run:
        verify_storage_manager()
