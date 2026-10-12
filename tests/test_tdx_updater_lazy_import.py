"""
回归测试：tdx_updater 的 pytdx 延迟导入（Bug4, DATA_SOURCE_MIGRATION_PLAN §6 Step 1）。

pytdx 是可选依赖（pyproject.toml extras=["tdx"]），tdx_updater 顶层不得裸导
`from pytdx.reader import GbbqReader`：
- 用例①：pytdx 不可用时，`import uniquant.data.managers.tdx_updater` 仍成功；
- 用例②：pytdx 缺失时调用真正使用 GbbqReader 的 GBBQ 更新函数，抛 ImportError
  且消息含安装指引（pip install pytdx / pip install -e ".[tdx]"）。
"""

import importlib
import sys

import pytest


def _block_pytdx(monkeypatch) -> None:
    """模拟 pytdx 未安装：sys.modules 中置 None 会令 import 抛 ImportError。"""
    monkeypatch.setitem(sys.modules, "pytdx", None)
    monkeypatch.delitem(sys.modules, "pytdx.reader", raising=False)


class TestTdxUpdaterLazyImport:
    def test_module_imports_without_pytdx(self, monkeypatch):
        """用例①：pytdx 不可用时，模块顶层导入仍成功（无裸导）。"""
        _block_pytdx(monkeypatch)
        # 弹出缓存后重放模块顶层导入语句
        sys.modules.pop("uniquant.data.managers.tdx_updater", None)
        mod = importlib.import_module("uniquant.data.managers.tdx_updater")
        assert hasattr(mod, "TdxUpdater")

    @pytest.mark.parametrize(
        "method_name", ["update_gbbq_data_full", "update_gbbq_data_incremental"]
    )
    def test_gbbq_update_raises_importerror_without_pytdx(
        self, monkeypatch, tmp_path, method_name
    ):
        """用例②：pytdx 缺失时调用 GBBQ 更新函数，抛 ImportError 且含安装指引。"""
        from uniquant.data.managers import tdx_updater

        _block_pytdx(monkeypatch)

        # 绕过 __init__ 重依赖（StorageManager/TdxSource/文件系统），直接构造实例
        updater = tdx_updater.TdxUpdater.__new__(tdx_updater.TdxUpdater)
        # 令函数走到解析 GBBQ 的分支（有 gbbq 路径且文件视为已变化）
        monkeypatch.setattr(updater, "get_gbbq_path", lambda: str(tmp_path / "gbbq"))
        monkeypatch.setattr(updater, "_needs_update", lambda _path: True)

        with pytest.raises(ImportError) as excinfo:
            getattr(updater, method_name)()

        msg = str(excinfo.value)
        assert "pip install" in msg
        assert "pytdx" in msg
