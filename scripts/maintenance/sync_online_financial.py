"""通达信官方财务数据在线同步 (第二十二轮 — 上云解耦财务轨道)。

数据通道: ``mootdx.affair`` → 通达信官方 HTTP 文件分发接口 (``tdxfin/gpcw.txt``
索引 + ``gpcw{YYYYMMDD}.zip`` 季度全量财务, 实测 1988→2026 共 148 期)。
该通道与 2026-09 已被服务端拒绝的 TCP 行情协议无关 (第二十轮根因), 实测存活。

管道: 官方索引 → 增量选择 (--latest N / --all) → 下载 + MD5 校验 → 解压
``gpcw*.dat`` 至暂存 ``vipdoc/cw`` → ``TDXFinancialImporter`` (追加式:
concat 既有 parquet + 按 (code, report_date) 去重 keep-last) → 财务湖。

语义保证: 增量导入绝不破坏湖历史行 (import_financial 写侧为 append+去重);
重复运行幂等 (MD5 缓存命中跳过下载, 指纹跳过已解析文件, 去重兜底)。
指纹文件独立于本地 Wine 导入链 (默认 ``DATA_DIR/financial_fingerprint.json``),
落在缓存目录内, 两轨互不干扰。

用法:
    python scripts/maintenance/sync_online_financial.py            # 最新 1 期
    python scripts/maintenance/sync_online_financial.py --all      # 全量 bootstrap
    python scripts/maintenance/sync_online_financial.py --dry-run  # 只看选择结果
退出码: 0 = 成功 (含无新增); 1 = 失败 (索引/MD5/导入任一环节)。
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path
from typing import Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from uniquant.data.services.import_financial import (  # noqa: E402
    FinancialFingerprint,
    TDXFinancialImporter,
)
from uniquant.shared.constants.path import LAKE_FINANCIAL_DIR, STOCK_LIST_FILE  # noqa: E402
from uniquant.shared.logger_factory import get_logger  # noqa: E402

logger = get_logger("sync_online_financial")

# 季度全量财务 zip: gpcw20260930.zip; 占位预告文件 (如未来报告期) 仅 164 字节,
# 真实文件 ≥ 数 MB → 以小字节阈值排除, 防止下载空壳
GPCW_ZIP_RE = re.compile(r"^gpcw(\d{8})\.zip$")
GPCW_DAT_RE = re.compile(r"^gpcw(\d{8})\.dat$")
MIN_REAL_ZIP_BYTES = 10_000

DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "gpcw"
FINGERPRINT_NAME = "financial_fingerprint_online.json"


def fetch_index(index_fetcher: Callable[[], list] = None) -> list:
    """拉取官方财务文件索引 (可注入假实现供测试)。"""
    if index_fetcher is None:
        from mootdx.affair import Affair

        index_fetcher = Affair.files
    entries = index_fetcher() or []
    return [e for e in entries if isinstance(e, dict) and GPCW_ZIP_RE.match(str(e.get("filename", "")))]


def select_entries(entries: list, latest: int = 1, want_all: bool = False) -> list:
    """过滤占位文件并按报告期倒序选期 (want_all=True 时全选)。

    双重过滤: 文件名必须匹配 gpcw\\d{8}.zip (防索引噪声), 且体积 ≥
    MIN_REAL_ZIP_BYTES (防未来报告期占位空壳)。
    """
    real = []
    for e in entries:
        if not GPCW_ZIP_RE.match(str(e.get("filename", ""))):
            continue
        if int(e.get("filesize") or 0) >= MIN_REAL_ZIP_BYTES:
            real.append(e)
    real.sort(key=lambda e: GPCW_ZIP_RE.match(str(e["filename"])).group(1), reverse=True)
    return real if want_all else real[: max(latest, 0)]


def verify_md5(path: Path, expected: str) -> None:
    """下载完整性校验 (MD5 与官方索引不一致即抛错, 防损坏文件入库)。"""
    digest = hashlib.md5(path.read_bytes()).hexdigest()
    if digest != str(expected).lower():
        raise ValueError(f"MD5 校验失败: {path.name} 期望 {expected} 实得 {digest}")


def download_and_extract(
    entry: dict,
    cache_dir: Path,
    staging_cw_dir: Path,
    downloader: Optional[Callable[[Path, str], bool]] = None,
) -> Path:
    """下载 (带 MD5 缓存命中) 并解压 gpcw*.dat 至暂存 cw 目录, 返回 dat 路径。"""
    if downloader is None:
        from mootdx.financial.financial import Financial

        downloader = lambda downdir, filename: Financial().fetch_only(  # noqa: E731
            report_hook=None, filename=filename, downdir=str(downdir)
        )
    cache_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir / entry["filename"]
    if not zip_path.exists():
        downloader(cache_dir, entry["filename"])
    verify_md5(zip_path, entry.get("hash", ""))

    staging_cw_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        dat_names = [n for n in zf.namelist() if GPCW_DAT_RE.match(Path(n).name)]
        if not dat_names:
            raise ValueError(f"zip 内无 gpcw*.dat: {entry['filename']}")
        dat_path = staging_cw_dir / Path(dat_names[0]).name
        if not dat_path.exists():
            zf.extract(dat_names[0], staging_cw_dir)
    return dat_path


def run_import(
    staging_root: Path,
    output_dir: Path,
    stock_codes_file: Path,
    fingerprint_path: Path,
    force: bool = False,
) -> tuple:
    """经既有 TDXFinancialImporter 入湖 (追加式 + 去重), 返回 (成功, 跳过, 失败)。"""
    importer = TDXFinancialImporter(
        tdx_dir=staging_root, output_dir=Path(output_dir), stock_codes_file=Path(stock_codes_file)
    )
    # 指纹隔离: 在线轨落在缓存目录, 不与本地 Wine 导入链共用 DATA_DIR 指纹
    importer.fingerprint = FinancialFingerprint(filepath=fingerprint_path)
    return importer.import_batch(force=force)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="通达信官方财务数据在线同步 (增量/全量)")
    ap.add_argument("--latest", type=int, default=1, help="只同步最新 N 期 (默认 1)")
    ap.add_argument("--all", action="store_true", help="全量 bootstrap (148 期, 首次上云用)")
    ap.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help="zip 缓存目录")
    ap.add_argument("--output-dir", type=Path, default=LAKE_FINANCIAL_DIR, help="财务湖输出目录")
    ap.add_argument("--stock-codes", type=Path, default=STOCK_LIST_FILE, help="主数据 SSOT")
    ap.add_argument("--force-import", action="store_true", help="忽略指纹强制重解析 (入湖仍去重)")
    ap.add_argument("--dry-run", action="store_true", help="只打印选择结果, 不下载不入库")
    args = ap.parse_args(argv)

    try:
        entries = fetch_index()
    except Exception as e:
        logger.error(f"官方财务索引拉取失败: {e}")
        return 1
    selected = select_entries(entries, latest=args.latest, want_all=args.all)
    if not selected:
        logger.warning("官方索引为空或全部为占位文件 — 无可同步项")
        return 1
    print(f"官方索引 {len(entries)} 项, 选中 {len(selected)} 期: "
          f"{[e['filename'] for e in selected]}")
    if args.dry_run:
        return 0

    staging_root = args.cache_dir / "staging"
    staging_cw_dir = staging_root / "vipdoc" / "cw"
    fingerprint_path = args.cache_dir / FINGERPRINT_NAME
    ok = True
    for entry in selected:
        try:
            dat = download_and_extract(entry, args.cache_dir, staging_cw_dir)
            print(f"  {entry['filename']}: 就绪 -> {dat.name}")
        except (OSError, ValueError) as e:
            logger.error(f"{entry['filename']} 下载/校验失败: {e}")
            ok = False
    if not ok:
        return 1

    success, skipped, failed = run_import(
        staging_root, args.output_dir, args.stock_codes, fingerprint_path, force=args.force_import
    )
    print(f"入湖: 成功解析 {success} / 跳过 {skipped} / 失败 {failed} "
          f"(输出: {args.output_dir})")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())