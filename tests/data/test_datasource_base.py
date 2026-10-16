"""``data/sources/base.py`` — DataSource 抽象契约测试.

覆盖 :class:`DataSource` 的名称派生、资源释放 (含异常吞掉)、上下文管理器语义、
抽象方法强制, 以及 2026-10 去除孤儿共享工具后的接口收窄 (防回归)。
"""

from unittest.mock import MagicMock

import pandas as pd
import pytest

from uniquant.data.sources.base import DataSource


class _Concrete(DataSource):
    """最小可用子类 — 实现全部抽象方法。"""

    def fetch_daily(self, symbol, start_date, end_date):
        return pd.DataFrame({"symbol": [symbol]})

    def fetch_real_time(self, symbol=None):
        return pd.DataFrame()

    def fetch_market_cap(self, symbol):
        return 0.0


class _Renamed(DataSource):
    """类名不以 'Source' 结尾 — 名称应原样返回。"""

    def fetch_daily(self, symbol, start_date, end_date):
        return pd.DataFrame()

    def fetch_real_time(self, symbol=None):
        return pd.DataFrame()

    def fetch_market_cap(self, symbol):
        return 0.0


class TestName:
    def test_strips_source_suffix(self):
        assert _Concrete().name == "_Concrete"

    def test_keeps_name_without_source_suffix(self):
        assert _Renamed().name == "_Renamed"

    def test_real_subclass_name(self):
        from uniquant.data.sources.mootdx_local import MootdxLocalSource

        src = MootdxLocalSource(tdx_dir="/nonexistent")
        assert src.name == "MootdxLocal"


class TestAbstractContract:
    def test_cannot_instantiate_abstract_base(self):
        with pytest.raises(TypeError):
            DataSource()

    def test_missing_abstract_method_blocks_instantiation(self):
        class _Incomplete(DataSource):
            def fetch_daily(self, symbol, start_date, end_date):
                return pd.DataFrame()

        with pytest.raises(TypeError):
            _Incomplete()


class TestClose:
    def test_close_without_session_is_noop(self):
        src = _Concrete()
        src.close()  # 不应抛异常

    def test_close_releases_and_nulls_session(self):
        src = _Concrete()
        session = MagicMock()
        src.session = session
        src.close()
        session.close.assert_called_once()
        assert src.session is None

    def test_close_swallows_session_errors(self):
        src = _Concrete()
        session = MagicMock()
        session.close.side_effect = RuntimeError("socket already closed")
        src.session = session
        src.close()  # 异常被吞掉
        assert src.session is None


class TestContextManager:
    def test_exit_calls_close(self):
        src = _Concrete()
        session = MagicMock()
        src.session = session
        with src as entered:
            assert entered is src
        session.close.assert_called_once()

    def test_destructor_calls_close(self):
        src = _Concrete()
        session = MagicMock()
        src.session = session
        src.__del__()
        session.close.assert_called_once()


class TestOrphanedHelpersRemoved:
    """2026-10 收口: 基类不再保留被 normalizer 取代/无引用的孤儿工具。"""

    @pytest.mark.parametrize(
        "attr",
        [
            "_shared_column_mapping",
            "_CANONICAL_COLUMNS",
            "_DATE_COLUMN_NAMES",
            "_parse_date_column",
            "_normalize_date_column",
            "_filter_by_date_range",
            "_ensure_required_columns",
            "_calculate_metrics",
            "_finalize_dataframe",
            "_standardize_columns",
            "_create_session",
        ],
    )
    def test_helper_is_gone(self, attr):
        assert not hasattr(DataSource, attr), f"{attr} 应已从基类移除"

    def test_circuit_breaker_helper_is_gone(self):
        import uniquant.data.sources.base as base_mod

        assert not hasattr(base_mod, "with_circuit_breaker")
        assert not hasattr(base_mod, "_breaker_locks")
