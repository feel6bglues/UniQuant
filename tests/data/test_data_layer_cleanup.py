"""数据层死代码清理守卫 (2026-10).

防止已物理删除的无引用模块被重新引入:
  * ``uniquant.data.managers.cache_manager`` — 手工缓存构建工具, 仅有被注释掉的
    导入方, 零生产/测试引用 (与 ``data/lake`` + ``managers/_baostock_client``
    的现行缓存路径重复)。

并锁定 ``uniquant.data`` 包门面 (``__init__.py``) 的**延迟导入契约** —— 与
``services/__init__.py`` 同理: 包导入不得触发重型子模块 (避免循环依赖)。
"""

import importlib
import subprocess
import sys

import pytest


def test_cache_manager_module_is_physically_removed():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("uniquant.data.managers.cache_manager")


def test_removed_module_symbol_not_exported():
    import uniquant.data.managers as managers_pkg

    assert not hasattr(managers_pkg, "create_all_caches")


def test_managers_package_still_importable():
    import uniquant.data.managers as managers_pkg

    assert managers_pkg.StockMetadataManager is not None


class TestDataPackageFacade:
    """``uniquant.data`` 的 PEP 562 延迟导入门面。"""

    @pytest.mark.parametrize(
        "name,expected_module",
        [
            ("DataFetcher", "uniquant.data.data_fetcher"),
            ("StorageManager", "uniquant.data.lake.storage_manager"),
            ("DataPipeline", "uniquant.data.data_pipeline_service"),
            ("LPPLDataService", "uniquant.data.services.lppl_data_service"),
        ],
    )
    def test_getattr_resolves_lazily(self, name, expected_module):
        import uniquant.data as data_pkg

        obj = getattr(data_pkg, name)
        assert obj is not None
        assert obj.__module__.startswith(expected_module)

    def test_unknown_attribute_raises_attribute_error(self):
        import uniquant.data as data_pkg

        with pytest.raises(AttributeError, match="has no attribute 'nope'"):
            data_pkg.nope

    def test_all_exports_resolve(self):
        import uniquant.data as data_pkg

        for name in data_pkg.__all__:
            assert getattr(data_pkg, name) is not None

    def test_package_import_does_not_eagerly_load_heavy_submodules(self):
        """包级 import 不得把 data_fetcher / storage_manager 拉进 sys.modules。"""
        code = (
            "import sys, uniquant.data;"
            "heavy=[m for m in sys.modules "
            "if m in ('uniquant.data.data_fetcher','uniquant.data.lake.storage_manager')];"
            "print(heavy)"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        )
        assert out.stdout.strip() == "[]"

