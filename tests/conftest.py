import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import pandas as pd
import numpy as np

np.random.seed(42)


# ─── Third-party config-dir race guard ────────────────────────────────────────
# ``mootdx.utils.get_config_path()`` is invoked at *import* time through the
# ``@file_cache`` decorators in ``mootdx.utils.adjust`` / ``mootdx.utils.holiday``
# and does, with no ``exist_ok``:
#
#     Path(pathname).exists() or Path(pathname).mkdir(parents=True)
#
# On a fresh runner (e.g. GitHub CI) where ``~/.mootdx`` does not yet exist, two
# pytest-xdist workers can both pass the ``exists()`` check and one then dies
# with ``FileExistsError: ... '/home/runner/.mootdx'`` *during collection*, which
# takes the worker down and surfaces as
# ``Different tests were collected between gw0 and gw1`` (observed on the CI
# ``coverage`` job, 2026-10-17).  Pre-create the library's own config dirs here,
# at conftest import time (i.e. before any test module is imported by a worker),
# so its ``exists()`` check short-circuits.  Race-safe because ``exist_ok=True``
# swallows the concurrent-creation ``FileExistsError``; a no-op once the dirs
# exist (developer machines that have used mootdx).
_MOOTDX_HOME = os.path.join(os.path.expanduser("~"), ".mootdx")
for _sub in ("", "caches", "xdxr"):
    try:
        os.makedirs(os.path.join(_MOOTDX_HOME, _sub), exist_ok=True)
    except OSError:
        pass


# ─── Local (gitignored) data availability guards ──────────────────────────────
# The market data lake under data/lake/, the GBBQ baseline under data/fq/, and
# bulk research output are gitignored: they exist only on a machine that has run
# the data-sync scripts.  Tests that read them must *declaredly* skip when the
# local lake is absent (e.g. in CI), otherwise ``pytest tests/`` can never be
# green there.  Apply the ``requires_lake`` / ``requires_futures_lake`` /
# ``requires_gbbq`` markers and the skip reason is attached centrally below.
#
# NOTE: a declared skip is deliberately *not* a silent pass.  The skip reason
# names the missing artifact and the script that regenerates it, and it is
# visible in the pytest summary.  Tests that need real data must never be
# written so that they vacuously pass on an empty frame.
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


def _has_any_parquet(path: str) -> bool:
    for _root, _dirs, _files in os.walk(path):
        if any(name.endswith(".parquet") for name in _files):
            return True
    return False


DATA_LAKE_AVAILABLE = _has_any_parquet(os.path.join(_PROJECT_ROOT, "data", "lake"))
FUTURES_LAKE_AVAILABLE = _has_any_parquet(
    os.path.join(_PROJECT_ROOT, "data", "lake", "futures")
)
GBBQ_AVAILABLE = os.path.isfile(
    os.path.join(_PROJECT_ROOT, "data", "fq", "gbbq.parquet")
)

_LAKE_MARKER_REASONS = {
    "requires_lake": (
        DATA_LAKE_AVAILABLE,
        "本地数据湖不可用 (data/lake/ 未生成; 该目录 gitignored, 需先运行数据同步脚本)",
    ),
    "requires_futures_lake": (
        FUTURES_LAKE_AVAILABLE,
        "本地期货数据湖不可用 (data/lake/futures/ 未生成; gitignored)",
    ),
    "requires_gbbq": (
        GBBQ_AVAILABLE,
        "GBBQ 股本变迁基线缺失 (data/fq/gbbq.parquet; gitignored) — "
        "python scripts/maintenance/sync_local_tdx_day.py",
    ),
}


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requires_lake: 需要本地数据湖 (data/lake/, gitignored) — 缺失时自动跳过",
    )
    config.addinivalue_line(
        "markers",
        "requires_futures_lake: 需要本地期货数据湖 (data/lake/futures/) — 缺失时自动跳过",
    )
    config.addinivalue_line(
        "markers",
        "requires_gbbq: 需要 GBBQ 复权基线 (data/fq/gbbq.parquet, gitignored) — 缺失时自动跳过",
    )


def pytest_collection_modifyitems(config, items):
    for item in items:
        for marker, (available, reason) in _LAKE_MARKER_REASONS.items():
            if not available and item.get_closest_marker(marker) is not None:
                item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture
def sample_ohlcv_data():
    dates = pd.date_range("2024-01-01", periods=252, freq="B")
    return pd.DataFrame({
        "date": dates,
        "open": np.random.randn(252).cumsum() + 100,
        "high": np.random.randn(252).cumsum() + 102,
        "low": np.random.randn(252).cumsum() + 98,
        "close": np.random.randn(252).cumsum() + 100,
        "volume": np.random.randint(100000, 10000000, 252),
    })

@pytest.fixture
def sample_wyckoff_data():
    dates = pd.date_range("2024-01-01", periods=400, freq="B")
    return pd.DataFrame({
        "date": dates,
        "open": np.random.randn(400).cumsum() + 100,
        "high": np.random.randn(400).cumsum() + 102,
        "low": np.random.randn(400).cumsum() + 98,
        "close": np.random.randn(400).cumsum() + 100,
        "volume": np.random.randint(100000, 10000000, 400),
    })
