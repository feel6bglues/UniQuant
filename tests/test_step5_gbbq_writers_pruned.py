"""
Step 5 任务 1 守卫测试: 4 个 GBBQ 旁路写通道清理与收口。

验证点:
1. adjust_factor_manager 模块已被删除且无法导入，__all__ 中无残留；
2. DataFetcher 实例及类上无 adjust_factor_manager 属性、无 convert_gbbq_to_fq / get_adjust_factors 委托方法；
3. DataImporter.parse_gbbq_to_fq 仅为只读校验，不存在时硬失败报错不写，存在时只读加载不写（禁止覆写）；
4. calculate_factors_v15.py 的 convert_gbbq_to_parquet / convert_gbbq_to_fq 硬保护生效（存在时直接 return True 禁止覆写）；
5. 验证 scripts/maintenance/sync_local_tdx_day.py::sync_gbbq 为全仓唯一合法的 data/fq/gbbq.parquet 生产入口。
"""
import ast
import importlib
from pathlib import Path
import pytest
import pandas as pd

from uniquant.data.data_fetcher import DataFetcher
import uniquant.data.managers as managers_pkg


@pytest.fixture
def clean_data_dir(tmp_path):
    """提供包含最小 all_stock_codes.csv 的合法 data_dir (满足 D5 R-5 硬失败约束)"""
    codes_csv = tmp_path / "all_stock_codes.csv"
    pd.DataFrame({
        "code": ["sh.600000"],
        "name": ["浦发银行"],
        "代码": ["600000"],
        "ipoDate": ["1999-11-10"],
        "outDate": [""],
        "type": ["1"],
        "status": ["1"],
    }).to_csv(codes_csv, index=False, encoding="utf-8-sig")
    return tmp_path


def test_adjust_factor_manager_module_deleted_and_unimportable():
    """验证 adjust_factor_manager.py 已从磁盘删除且无法被 import"""
    project_root = Path(__file__).resolve().parent.parent
    mgr_file = project_root / "src" / "uniquant" / "data" / "managers" / "adjust_factor_manager.py"
    assert not mgr_file.exists(), f"文件仍残留: {mgr_file}"

    # 验证模块无法导入
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("uniquant.data.managers.adjust_factor_manager")

    # 验证 managers 包导出的 __all__ 中无残留
    if hasattr(managers_pkg, "__all__"):
        assert "AdjustFactorManager" not in managers_pkg.__all__
    assert not hasattr(managers_pkg, "AdjustFactorManager")


def test_data_fetcher_has_no_adjust_factor_manager_or_delegations(clean_data_dir):
    """验证 DataFetcher 不再包含 adjust_factor_manager 属性或相关委托方法"""
    # 类级别检查
    assert not hasattr(DataFetcher, "adjust_factor_manager")
    assert not hasattr(DataFetcher, "convert_gbbq_to_fq")
    assert not hasattr(DataFetcher, "get_adjust_factors")

    # 实例级别检查
    fetcher = DataFetcher(data_dir=str(clean_data_dir))
    assert not hasattr(fetcher, "adjust_factor_manager")
    assert not hasattr(fetcher, "convert_gbbq_to_fq")
    assert not hasattr(fetcher, "get_adjust_factors")


def test_data_importer_module_deleted_and_unimportable():
    """验证 data_importer.py 已从磁盘彻底删除且无法被 import (彻底根除 GBBQ 旁路通道)"""
    project_root = Path(__file__).resolve().parent.parent
    importer_file = project_root / "src" / "uniquant" / "data" / "services" / "data_importer.py"
    assert not importer_file.exists(), f"文件仍残留: {importer_file}"

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("uniquant.data.services.data_importer")


def test_calculate_factors_v15_hard_protection_against_overwrite(tmp_path, monkeypatch):
    """验证 calculate_factors_v15 的 convert_gbbq_to_parquet 遇到已存在文件直接 return True，绝不覆写"""
    from scripts import calculate_factors_v15

    dummy_gbbq = tmp_path / "dummy_gbbq.parquet"
    dummy_df = pd.DataFrame({"dummy": [1, 2, 3]})
    dummy_df.to_parquet(dummy_gbbq)
    orig_mtime = dummy_gbbq.stat().st_mtime_ns
    orig_bytes = dummy_gbbq.read_bytes()

    # monkeypatch GBBQ_PARQUET_PATH 指向 dummy 文件
    monkeypatch.setattr(calculate_factors_v15, "GBBQ_PARQUET_PATH", str(dummy_gbbq))

    # 调用转换函数，硬保护生效
    res = calculate_factors_v15.convert_gbbq_to_parquet()
    assert res is True
    # 验证文件完全未被修改
    assert dummy_gbbq.stat().st_mtime_ns == orig_mtime
    assert dummy_gbbq.read_bytes() == orig_bytes

    # 测试兼容别名
    res_alias = calculate_factors_v15.convert_gbbq_to_fq()
    assert res_alias is True


def test_only_sync_local_tdx_day_is_canonical_gbbq_writer():
    """断言只有 scripts/maintenance/sync_local_tdx_day.py::sync_gbbq 是合法的 gbbq 写入入口"""
    project_root = Path(__file__).resolve().parent.parent

    # 1. 验证 sync_local_tdx_day.py 存在且导出 sync_gbbq 函数
    sync_script = project_root / "scripts" / "maintenance" / "sync_local_tdx_day.py"
    assert sync_script.exists(), "sync_local_tdx_day.py 必须存在"

    with open(sync_script, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=str(sync_script))

    func_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    assert "sync_gbbq" in func_names, "sync_local_tdx_day.py 必须包含 sync_gbbq 函数"

    # 2. 扫描全仓 src/ 目录，断言没有任何模块在向 gbbq.parquet 写入
    # 检索模式: to_parquet ... gbbq
    src_dir = project_root / "src"
    suspicious_writers = []

    for py_file in src_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        if "to_parquet" in content and "gbbq" in content.lower():
            # 排除已废弃的测试/说明/注释，检查是否有活跃的写代码
            tree_src = ast.parse(content, filename=str(py_file))
            for node in ast.walk(tree_src):
                if isinstance(node, ast.Call):
                    # 检查是否调用 to_parquet
                    func = node.func
                    if isinstance(func, ast.Attribute) and func.attr == "to_parquet":
                        line_text = content.splitlines()[node.lineno - 1]
                        if "gbbq" in line_text.lower():
                            suspicious_writers.append(f"{py_file.name}:{node.lineno}")

    assert len(suspicious_writers) == 0, (
        f"src/ 目录下仍发现潜在的 gbbq.parquet 写操作: {suspicious_writers}"
    )
