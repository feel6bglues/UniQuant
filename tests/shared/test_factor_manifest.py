from __future__ import annotations

from uniquant.shared.archive.factor_governance import FactorManifest
from uniquant.brain.factors.registry import FactorAccessLevel


def test_create_minimal():
    m = FactorManifest(name="test_factor")
    assert m.name == "test_factor"
    assert m.description == ""
    assert m.category == "generic"
    assert m.data_source == ""
    assert m.access_level == FactorAccessLevel.FREE
    assert m.tags == []
    assert m.metadata == {}


def test_create_full():
    m = FactorManifest(
        name="my_factor",
        description="A test factor for unit tests",
        category="technical",
        data_source="stock_kline",
        access_level=FactorAccessLevel.WARN,
        tags=["momentum", "trend"],
        metadata={"author": "test"},
    )
    assert m.name == "my_factor"
    assert "test factor" in m.description.lower()
    assert m.category == "technical"
    assert m.data_source == "stock_kline"
    assert m.access_level == FactorAccessLevel.WARN
    assert len(m.tags) == 2


def test_different_categories():
    for cat in ("technical", "fundamental", "alternative", "custom", "generic"):
        m = FactorManifest(name=f"factor_{cat}", category=cat)
        assert m.category == cat


def test_name_uniqueness():
    m1 = FactorManifest(name="unique_factor")
    m2 = FactorManifest(name="unique_factor")
    assert m1.name == m2.name
    assert m1 is not m2
