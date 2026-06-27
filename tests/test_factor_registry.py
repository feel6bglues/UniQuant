import logging
import pytest

from uniquant.brain.factors.registry import FactorAccessLevel, FactorRegistry


def dummy_factor1(df):
    return df['close'] * 2

def dummy_factor2(df):
    return df['close'] * 3

@pytest.fixture(autouse=True)
def clean_registry():
    """测试前清空单例的内容，并启用日志传播便于 caplog 捕获"""
    FactorRegistry._factors.clear()
    logger = logging.getLogger("FactorRegistry")
    logger.propagate = True
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


def test_check_access_registered_factor_no_warn(caplog):
    """已注册因子通过 check_access 时不应产生 warning"""
    caplog.set_level(logging.WARNING, logger="FactorRegistry")
    FactorRegistry.register(name="f1", compute_func=dummy_factor1)
    assert FactorRegistry.check_access("f1") is True
    assert "未注册因子访问" not in caplog.text


def test_check_access_unregistered_warns(caplog):
    """未注册因子在 WARN 模式下应产生 warning 日志"""
    caplog.set_level(logging.WARNING, logger="FactorRegistry")
    FactorRegistry.set_mode(FactorAccessLevel.WARN)
    assert FactorRegistry.check_access("nonexistent") is True
    assert "未注册因子访问: nonexistent (mode=warn)" in caplog.text


def test_check_access_unregistered_block():
    """未注册因子在 BLOCK 模式下应抛出 ValueError"""
    FactorRegistry.set_mode(FactorAccessLevel.BLOCK)
    with pytest.raises(ValueError, match="未注册因子被拦截: nonexistent"):
        FactorRegistry.check_access("nonexistent")


def test_get_factor_triggers_check_access_unregistered(caplog):
    """get_factor 对未注册因子应触发 check_access warning"""
    caplog.set_level(logging.WARNING, logger="FactorRegistry")
    FactorRegistry.set_mode(FactorAccessLevel.WARN)
    result = FactorRegistry.get_factor("never_registered")
    assert result is None
    assert "未注册因子访问: never_registered (mode=warn)" in caplog.text


def test_get_factor_registered_no_warn(caplog):
    """get_factor 对已注册因子不应产生 warning"""
    caplog.set_level(logging.WARNING, logger="FactorRegistry")
    FactorRegistry.register(name="f1", compute_func=dummy_factor1)
    FactorRegistry.set_mode(FactorAccessLevel.WARN)
    result = FactorRegistry.get_factor("f1")
    assert result is not None
    assert "未注册因子访问" not in caplog.text


def test_get_enabled_triggers_check_access(caplog):
    """get_enabled 对每个启用因子应触发 check_access"""
    caplog.set_level(logging.WARNING, logger="FactorRegistry")
    FactorRegistry.register(name="f1", compute_func=dummy_factor1)
    FactorRegistry.register(name="f2", compute_func=dummy_factor2)
    FactorRegistry.set_mode(FactorAccessLevel.WARN)
    enabled = FactorRegistry.get_enabled()
    assert len(enabled) == 2
    assert "未注册因子访问" not in caplog.text  # 因为是已注册因子


def test_get_enabled_unknown_in_block_mode():
    """BLOCK 模式下 get_enabled 对已知因子不抛异常"""
    FactorRegistry.set_mode(FactorAccessLevel.BLOCK)
    FactorRegistry.register(name="f1", compute_func=dummy_factor1)
    enabled = FactorRegistry.get_enabled()
    assert len(enabled) == 1
