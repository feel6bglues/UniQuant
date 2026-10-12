"""Step4 S4a: 死源/死组件删除守卫测试 (预注册 G1/G5)

删除清单 (共 11 文件, −3,142 行):
- 9 个网络爬虫死源: sina / tencent / ths / eastmoney / eastmoney_base /
  eastmoney_financial / eastmoney_quote / protocols / realtime_bridge
- pipeline/data_aligner.py (日历对齐)
- pipeline/data_adjuster.py (旧轨复权薄壳, Step2c 已委托新轨)

守卫断言:
1. 全部 11 模块 spec 消失
2. 包导入仍成功 (sources/pipeline)
3. src/ 下无残留 import 引用
4. 删除行数核对
"""
import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEAD_MODULES = [
    "uniquant.data.sources.sina",
    "uniquant.data.sources.tencent",
    "uniquant.data.sources.ths",
    "uniquant.data.sources.eastmoney",
    "uniquant.data.sources.eastmoney_base",
    "uniquant.data.sources.eastmoney_financial",
    "uniquant.data.sources.eastmoney_quote",
    "uniquant.data.sources.protocols",
    "uniquant.data.sources.realtime_bridge",
    "uniquant.data.pipeline.data_aligner",
    "uniquant.data.pipeline.data_adjuster",
]


def test_all_dead_modules_spec_gone():
    for mod in DEAD_MODULES:
        assert importlib.util.find_spec(mod) is None, f"{mod} 应已删除"


def test_packages_still_importable():
    import uniquant.data.sources  # noqa: F401
    import uniquant.data.pipeline  # noqa: F401

    from uniquant.data.pipeline import __all__

    assert "DataAdjuster" not in __all__
    assert set(__all__) == {"DataCleaner", "DataValidator"}


def test_no_residual_imports_in_src():
    import re

    dead_names = [
        "sina", "tencent", "ths", "eastmoney", "realtime_bridge",
        "data_aligner", "DataAligner", "data_adjuster", "DataAdjuster",
    ]
    src_root = PROJECT_ROOT / "src" / "uniquant"
    residuals = []
    for path in src_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in dead_names:
            # import 语句中的引用才算残留
            if re.search(rf"^\s*(from|import)\s+.*\b{name}\b", text, re.MULTILINE):
                residuals.append(f"{path.relative_to(PROJECT_ROOT)}: {name}")
    assert residuals == [], f"src/ 存在残留 import: {residuals}"


def test_dead_source_files_physically_gone():
    dead_files = [
        "src/uniquant/data/sources/sina.py",
        "src/uniquant/data/sources/tencent.py",
        "src/uniquant/data/sources/ths.py",
        "src/uniquant/data/sources/eastmoney.py",
        "src/uniquant/data/sources/eastmoney_base.py",
        "src/uniquant/data/sources/eastmoney_financial.py",
        "src/uniquant/data/sources/eastmoney_quote.py",
        "src/uniquant/data/sources/protocols.py",
        "src/uniquant/data/sources/realtime_bridge.py",
        "src/uniquant/data/pipeline/data_aligner.py",
        "src/uniquant/data/pipeline/data_adjuster.py",
    ]
    for rel in dead_files:
        assert not (PROJECT_ROOT / rel).exists(), f"{rel} 应已物理删除"


def test_baostock_survives_for_s4b():
    """S4a 不影响 baostock (S4b 门): 现由 managers/_baostock_client 承接, sources/baostock.py 待门。"""
    assert (PROJECT_ROOT / "src/uniquant/data/managers/_baostock_client.py").exists()
    # data_fetcher 湖优先单源不引用爬虫源
    fetcher = (PROJECT_ROOT / "src/uniquant/data/data_fetcher.py").read_text(encoding="utf-8")
    for name in ("SinaSource", "TencentSource", "ThsSource", "BaostockSource"):
        assert name not in fetcher
