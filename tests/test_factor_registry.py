import pytest

from uniquant.brain.factors.registry import FactorRegistry


def dummy_factor1(df):
    return df['close'] * 2

def dummy_factor2(df):
    return df['close'] * 3

@pytest.fixture(autouse=True)
def clean_registry():
    """测试前清空单例的内容"""
    FactorRegistry._factors.clear()
    yield

def test_factor_registration():
    FactorRegistry.register(name="f1", compute_func=dummy_factor1, category="test", default_weight=1.5)
    
    assert len(FactorRegistry.get_all()) == 1
    
    factor = FactorRegistry.get_factor("f1")
    assert factor is not None
    assert factor.name == "f1"
    assert factor.category == "test"
    assert factor.default_weight == 1.5
    assert factor.enabled is True

def test_factor_enable_disable():
    FactorRegistry.register(name="f1", compute_func=dummy_factor1)
    FactorRegistry.register(name="f2", compute_func=dummy_factor2)
    
    FactorRegistry.disable("f1")
    
    enabled_factors = FactorRegistry.get_enabled()
    assert len(enabled_factors) == 1
    assert enabled_factors[0].name == "f2"
    
    FactorRegistry.enable("f1")
    enabled_factors = FactorRegistry.get_enabled()
    assert len(enabled_factors) == 2
    
    names = [f.name for f in enabled_factors]
    assert "f1" in names
    assert "f2" in names

def test_list_factors():
    FactorRegistry.register(name="test_fac", compute_func=dummy_factor1, description="A test factor")
    factor_dict = FactorRegistry.list_factors()
    
    assert "test_fac" in factor_dict
    assert factor_dict["test_fac"] == "A test factor"
