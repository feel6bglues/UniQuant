"""D5 解耦 + 主数据硬失败契约测试 (Step4 WS-E, 2026-10-12)

覆盖:
1. _baostock_client 可独立导入且不触发 sources.baostock
2. 两 manager 源码不再引用 sources.baostock
3. storage_manager 缺 all_stock_codes.csv → 硬失败 (R-5)
4. stock_metadata_manager 缺文件 → 明确失败 (R-5)
5. all_stock_codes.csv 副本唯一性 (R-7)
6. StockMetadataManager 默认 data_dir 为绝对路径
7. 合成 CSV 正常解析 (行为不回归)
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

import uniquant.data.managers.baostock_cache_manager as bcm
import uniquant.data.managers.trade_calendar_manager as tcm
from uniquant.data.lake.storage_manager import StorageManager
from uniquant.data.managers.stock_metadata_manager import StockMetadataManager


# ═══════════════════════════════════════════════════════════════
# 1-2. 解耦断言
# ═══════════════════════════════════════════════════════════════

def test_baostock_client_importable_without_sources_baostock():
    """_baostock_client 可导入且不触发 sources.baostock"""
    import uniquant.data.managers._baostock_client as client

    assert callable(client.login)
    assert callable(client.logout)
    assert callable(client.fetch_stock_list)
    assert callable(client.fetch_calendar)
    assert "uniquant.data.sources.baostock" not in sys.modules


def test_managers_no_longer_import_sources_baostock():
    """两 manager 源码不含 sources.baostock 引用"""
    bcm_src = Path(bcm.__file__).read_text(encoding="utf-8")
    tcm_src = Path(tcm.__file__).read_text(encoding="utf-8")
    assert "sources.baostock" not in bcm_src
    assert "sources.baostock" not in tcm_src


def test_managers_import_private_client():
    """两 manager 改用 _baostock_client"""
    bcm_src = Path(bcm.__file__).read_text(encoding="utf-8")
    tcm_src = Path(tcm.__file__).read_text(encoding="utf-8")
    assert "_baostock_client" in bcm_src
    assert "_baostock_client" in tcm_src


# ═══════════════════════════════════════════════════════════════
# 3. storage_manager 硬失败
# ═══════════════════════════════════════════════════════════════

def test_storage_manager_missing_csv_hard_fails(tmp_path):
    """缺 all_stock_codes.csv → 抛异常而非空集"""
    with pytest.raises(Exception, match="all_stock_codes.csv"):
        StorageManager(str(tmp_path))


# ═══════════════════════════════════════════════════════════════
# 4. stock_metadata_manager 硬失败
# ═══════════════════════════════════════════════════════════════

def test_stock_metadata_manager_missing_csv_raises(tmp_path):
    """缺 all_stock_codes.csv → _load_all_codes 抛异常 (load 返回 False)"""
    mgr = StockMetadataManager(str(tmp_path))
    with pytest.raises(Exception, match="all_stock_codes.csv"):
        mgr._load_all_codes()
    # load() 捕获异常返回 False, 不静默成功
    assert mgr.load() is False


# ═══════════════════════════════════════════════════════════════
# 5. 副本唯一性
# ═══════════════════════════════════════════════════════════════

def test_only_one_all_stock_codes_copy():
    """全仓 all_stock_codes.csv 只能有 1 个 (R-7)"""
    repo_root = Path(__file__).resolve().parent.parent
    copies = list(repo_root.glob("**/all_stock_codes.csv"))
    # data/ 下的真表必须存在
    data_copy = [p for p in copies if p.parent == repo_root / "data"]
    src_copy = [p for p in copies if str(p).startswith(str(repo_root / "src"))]
    assert len(data_copy) == 1, "data/all_stock_codes.csv 应存在"
    assert len(src_copy) == 0, "src 下不应再有第二副本"


# ═══════════════════════════════════════════════════════════════
# 6. 默认 data_dir 绝对路径
# ═══════════════════════════════════════════════════════════════

def test_stock_metadata_manager_default_data_dir_absolute():
    """StockMetadataManager() 默认 data_dir 是绝对路径且指向项目 data/"""
    mgr = StockMetadataManager()
    p = Path(mgr.data_dir)
    assert p.is_absolute()
    assert p.name == "data"


# ═══════════════════════════════════════════════════════════════
# 7. 合成 CSV 解析不回归
# ═══════════════════════════════════════════════════════════════

def _write_minimal_csv(tmp_path: Path) -> Path:
    csv_path = tmp_path / "all_stock_codes.csv"
    pd.DataFrame({
        "code": ["sh.600519", "sz.000001", "sz.300750"],
        "name": ["贵州茅台", "平安银行", "宁德时代"],
        "代码": ["600519", "000001", "300750"],
        "ipoDate": ["2001-08-27", "1991-04-03", "2018-06-11"],
        "outDate": ["", "", ""],
        "type": ["1", "1", "1"],
        "status": ["1", "1", "1"],
    }).to_csv(csv_path, index=False, encoding="utf-8-sig")
    return csv_path


def test_storage_manager_parses_synthetic_csv(tmp_path):
    """合成 CSV 下 _load_all_stock_codes 正常解析"""
    _write_minimal_csv(tmp_path)
    sm = StorageManager(str(tmp_path))
    codes = sm._load_all_stock_codes()
    assert "600519.SH" in codes
    assert "000001.SZ" in codes
    assert "300750.SZ" in codes


def test_metadata_manager_parses_synthetic_csv(tmp_path):
    """合成 CSV 下 StockMetadataManager 正常加载"""
    _write_minimal_csv(tmp_path)
    mgr = StockMetadataManager(str(tmp_path))
    assert mgr.load() is True
    info = mgr.get_stock_info("600519")
    assert info is not None
    assert info.name == "贵州茅台"
    assert str(info.ipo_date) == "2001-08-27"
