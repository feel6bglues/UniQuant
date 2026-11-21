"""通达信官方 gbbq 在线写通道 (第二十三轮 — 拔除本地 Wine gbbq 硬依赖)。

数据通道: ``tdxdata.download_gbbq()`` → 通达信官方 HTTP 分发 (tdx.com.cn
``gbbq.zip``) → ``decrypt_records`` 解密。2026-11-21 实测: 官方解密 208,075
条, **category=1 (复权链唯一消费类, corporate_action.py 严格过滤 cat=1) 为
本地 Wine gbbq 的严格超集** (64,125 条交集零缺失, 四字段最大差 4.74e-07 =
float32 存储精度), 另含 5,396 条本地没有的新事件。

写策略 (**合并式, 不丢元数据**):
- 官方 cat=1 全量**替换**本地 cat=1 (更精确的 float64 值 + 新事件);
- 本地非 cat=1 行 (股本变更类, 113k+ 行) **原样保留** (官方解码对非 cat1
  置零, 无信息量);
- 守卫: 写前断言**无损失** (旧表每一 (code, date, category) 键都在新表中);
- 原子写 (tmp + os.replace) + 写前备份 ``gbbq.parquet.bak``;
- dtypes 与既有文件逐列对齐 (code=object/int64/float64), 消费方零感知。

用法:
    python scripts/maintenance/sync_online_gbbq.py                  # 写真实 data/fq/gbbq.parquet
    python scripts/maintenance/sync_online_gbbq.py --output /tmp/x  # 沙盒
退出码: 0 = 成功; 1 = 失败 (拉取/守卫任一环节, 绝不半写)。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from uniquant.shared.logger_factory import get_logger  # noqa: E402

logger = get_logger("sync_online_gbbq")

GBBQ_COLUMNS = ["code", "market", "date", "category", "cash_div", "split_ratio", "rights_ratio", "rights_price"]
INT_COLS = ["market", "date", "category"]
FLOAT_COLS = ["cash_div", "split_ratio", "rights_ratio", "rights_price"]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "fq" / "gbbq.parquet"
# TDX 纪元空日期 (官方表含 1 条 18991230 垃圾行, 第二十二轮侦察登记)
EPOCH_MIN_DATE = 19900101


def fetch_official_records(fetcher: Optional[Callable[[], list]] = None) -> list:
    """拉取并解密官方 gbbq 记录 (可注入假实现供测试)。"""
    if fetcher is None:
        from tdxdata import decrypt_records, download_gbbq

        fetcher = lambda: decrypt_records(download_gbbq()["gbbq"])  # noqa: E731
    return fetcher() or []


def _cast_contract(df: pd.DataFrame) -> pd.DataFrame:
    """逐列对齐既有 gbbq.parquet dtypes (code=object 6位, int64 日期, float64 值)。"""
    out = df.copy()
    out["code"] = out["code"].astype(str).str.zfill(6)
    for col in INT_COLS:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype("int64")
    for col in FLOAT_COLS:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0).astype("float64")
    return out[GBBQ_COLUMNS]


def official_cat1_frame(records: list) -> pd.DataFrame:
    """官方记录 → cat=1 契约帧 (滤 TDX 纪元行; 字段映射见第二十一轮 170 事件对账)。"""
    rows = []
    for r in records:
        try:
            date = int(r.get("date") or 0)
        except (TypeError, ValueError):
            continue
        if r.get("category") != 1 or date < EPOCH_MIN_DATE:
            continue
        rows.append(
            {
                "code": str(r.get("code") or "").zfill(6),
                "market": r.get("market"),
                "date": date,
                "category": 1,
                "cash_div": float(r.get("fenhong") or 0.0),
                "split_ratio": float(r.get("songzhuangu") or 0.0),
                "rights_ratio": float(r.get("peigu") or 0.0),
                "rights_price": float(r.get("peigujia") or 0.0),
            }
        )
    if not rows:
        return _cast_contract(pd.DataFrame(columns=GBBQ_COLUMNS))
    df = _cast_contract(pd.DataFrame(rows))
    return df.sort_values(["date", "code"]).reset_index(drop=True)


def load_local(path: Path) -> pd.DataFrame:
    """读本地既有 gbbq (不存在/损坏 → 空契约帧, 首次上云全量重建路径)。"""
    if not Path(path).exists():
        return _cast_contract(pd.DataFrame(columns=GBBQ_COLUMNS))
    try:
        df = pd.read_parquet(path)
    except Exception as e:
        logger.error(f"本地 gbbq 读取失败 (将视为空表, 全量重建): {e}")
        return _cast_contract(pd.DataFrame(columns=GBBQ_COLUMNS))
    return _cast_contract(df)


def verify_no_loss(prev: pd.DataFrame, final: pd.DataFrame) -> None:
    """无损失守卫: 旧表每一键必须存在于新表 (fail-closed, 绝不半写)。"""
    prev_keys = set(zip(prev["code"], prev["date"], prev["category"]))
    final_keys = set(zip(final["code"], final["date"], final["category"]))
    missing = prev_keys - final_keys
    if missing:
        sample = sorted(missing)[:3]
        raise ValueError(f"无损失守卫失败: {len(missing)} 个旧键丢失, 样本 {sample}")


def merge_frames(local_df: pd.DataFrame, official_df: pd.DataFrame) -> pd.DataFrame:
    """本地非 cat1 保留 + 官方 cat1 替换 (官方为本地 cat1 严格超集)。"""
    local_keep = local_df[local_df["category"] != 1]
    final = pd.concat([local_keep, official_df], ignore_index=True)
    final = final.drop_duplicates(subset=["code", "date", "category"], keep="last")
    final = final.sort_values(["date", "code"]).reset_index(drop=True)
    return _cast_contract(final)


def write_atomic(df: pd.DataFrame, out_path: Path) -> None:
    """原子写 + 上一版备份 (数据文件不在 git, .bak 是唯一回滚保险)。"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        shutil.copy2(out_path, out_path.with_suffix(".parquet.bak"))
    tmp = out_path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, out_path)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="通达信官方 gbbq 在线同步写通道")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="gbbq.parquet 输出路径")
    args = ap.parse_args(argv)

    try:
        records = fetch_official_records()
    except Exception as e:
        logger.error(f"官方 gbbq 拉取/解密失败: {e}")
        return 1
    official = official_cat1_frame(records)
    if official.empty:
        logger.error("官方解密结果为空 (cat=1) — 拒绝写空表")
        return 1

    local = load_local(args.output)
    prev_keys = len(set(zip(local["code"], local["date"], local["category"])))
    local_cat1 = local[local["category"] == 1]
    local_cat1_keys = set(zip(local_cat1["code"], local_cat1["date"]))
    official_keys = set(zip(official["code"], official["date"]))
    lost_cat1 = local_cat1_keys - official_keys
    if lost_cat1:
        logger.error(f"官方 cat=1 非本地超集: 缺失 {len(lost_cat1)} 键, 样本 {sorted(lost_cat1)[:3]}")
        return 1

    final = merge_frames(local, official)
    verify_no_loss(local, final)
    write_atomic(final, args.output)
    added = len(official_keys - local_cat1_keys)
    print(
        f"完成: 官方 cat1 {len(official)} 条 (新增 {added}) + 本地非 cat1 保留 "
        f"{len(local) - len(local_cat1)} 行 → {args.output} 共 {len(final)} 行 "
        f"(旧 {len(local)} 行 / {prev_keys} 键, .bak 已备份)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())