from __future__ import annotations

import pytest
import pandas as pd

from uniquant.shared.interfaces import ResearchDataPack


def test_create_empty():
    pack = ResearchDataPack(symbol="000001.SZ")
    assert pack.symbol == "000001.SZ"
    assert pack.stock_df is None
    assert pack.regime is None


def test_create_with_data():
    df = pd.DataFrame({"date": ["2025-01-01"], "close": [10.0]})
    pack = ResearchDataPack(
        symbol="000001.SZ",
        stock_df=df,
        lppl={"risk_level": "Safe", "confidence": 0.8},
    )
    assert pack.symbol == "000001.SZ"
    assert pack.stock_df is not None
    assert len(pack.stock_df) == 1
    assert pack.lppl["risk_level"] == "Safe"


def test_from_dict():
    data = {
        "symbol": "000001.SZ",
        "stock": pd.DataFrame({"date": ["2025-01-01"], "close": [10.0]}),
        "regime": "NORMAL",
        "lppl": {"risk_level": "Danger"},
    }
    pack = ResearchDataPack.from_dict(data, symbol="000001.SZ")
    assert pack.symbol == "000001.SZ"
    assert pack.regime == "NORMAL"
    assert pack.lppl["risk_level"] == "Danger"


def test_backward_compat_dict_access():
    pack = ResearchDataPack(symbol="000001.SZ", metadata={"source": "test"})
    assert pack.metadata["source"] == "test"


def test_default_fields():
    pack = ResearchDataPack(symbol="600000.SH")
    assert pack.index_df is None
    assert pack.ntf is None
    assert pack.czsc is None
    assert pack.wyckoff is None
    assert pack.alpha is None
    assert pack.factors is None
    assert pack.metadata == {}
