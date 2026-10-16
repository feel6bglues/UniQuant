"""``data/utils/akshare_wrapper.py`` — AkShare 包装器测试.

该模块是**在生产链路上**的: ``MarketDataCoordinator.fetch_index_daily`` →
``akshare_wrapper.fetch_index_daily``, 而 ``fetch_index_daily`` 被
``data_access_service`` (data_type=="index")、``macro_service``、
``macro_analysis_engine`` 调用; ``fetch_sector_daily`` 被 ``data_service`` 调用。

覆盖点: 初始化/重初始化、请求头轮换、速率控制、方法级统计、``call`` 的错误与
重试分支、以及对 ``market_service`` 的 10 个薄委托方法。

纪律: akshare 本体与网络**全部 mock**, 时间源注入 fake (真实 sleep 被消除)。
"""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from uniquant.data.utils import akshare_wrapper as aw_mod
from uniquant.data.utils.akshare_wrapper import AkShareWrapper


class _FakeRandom:
    """确定性 random 替身: choice 取首项, uniform 取上界。"""

    @staticmethod
    def choice(seq):
        return seq[0]

    @staticmethod
    def uniform(low, high):
        return high


class _FakeTime:
    def __init__(self, now: float = 0.0):
        self.now = now
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)


@pytest.fixture
def fake_time(monkeypatch):
    """替换 akshare_wrapper 与 retry_decorator 两处的时间源。"""
    ft = _FakeTime()
    monkeypatch.setattr(aw_mod, "time", ft)
    monkeypatch.setattr("uniquant.shared.retry_decorator.time", ft)
    monkeypatch.setattr(aw_mod, "random", _FakeRandom)
    return ft


def _wrapper(initialized=True, ak=None) -> AkShareWrapper:
    """不经真实 ``_init_akshare`` 装配实例。"""
    w = AkShareWrapper.__new__(AkShareWrapper)
    w._ak = ak
    w._initialized = initialized
    w._last_call_time = -1.0          # elapsed = 1.0 ≥ min_interval → 不触发等待
    w._min_interval = 0.5
    w._method_stats = {}
    w._request_headers = {"User-Agent": "test"}
    w.market_service = MagicMock()
    return w


# ── construction & headers ────────────────────────────────────────────────


class TestConstruction:
    def test_init_skips_real_akshare(self, monkeypatch):
        monkeypatch.setattr(AkShareWrapper, "_init_akshare", lambda self: setattr(self, "_initialized", True))
        w = AkShareWrapper()
        assert w._ak is None
        assert w._initialized is True
        assert w._last_call_time == 0
        assert w._min_interval == 0.5
        assert w._method_stats == {}
        assert "User-Agent" in w._request_headers
        assert w.market_service is not None

    def test_generate_request_headers_shape(self):
        w = _wrapper()
        headers = w._generate_request_headers()
        assert headers["User-Agent"].startswith("Mozilla/5.0")
        assert headers["Referer"] == "https://quote.eastmoney.com/"
        assert headers["Accept-Encoding"] == "gzip, deflate, br"

    def test_is_initialized_reflects_flag(self):
        assert _wrapper(initialized=True).is_initialized() is True
        assert _wrapper(initialized=False).is_initialized() is False


class TestInitAkshare:
    def _fake_ak(self, **attrs):
        mod = SimpleNamespace(**attrs)
        mod.set_option = MagicMock()
        return mod

    def test_success_sets_module_and_flag(self, monkeypatch):
        fake = self._fake_ak()
        monkeypatch.setitem(sys.modules, "akshare", fake)
        w = _wrapper(initialized=False)
        w._init_akshare()
        assert w._initialized is True
        assert w._ak is fake
        assert fake.set_option.call_count == 2

    def test_set_option_failure_is_warned_not_fatal(self, monkeypatch):
        fake = SimpleNamespace(set_option=MagicMock(side_effect=ValueError("bad option")))
        monkeypatch.setitem(sys.modules, "akshare", fake)
        w = _wrapper(initialized=False)
        w._init_akshare()
        assert w._initialized is True

    def test_set_headers_invoked_when_present(self, monkeypatch):
        fake = self._fake_ak(set_headers=MagicMock())
        monkeypatch.setitem(sys.modules, "akshare", fake)
        w = _wrapper(initialized=False)
        w._init_akshare()
        fake.set_headers.assert_called_once()

    def test_set_headers_failure_is_warned_not_fatal(self, monkeypatch):
        fake = self._fake_ak(set_headers=MagicMock(side_effect=TypeError("nope")))
        monkeypatch.setitem(sys.modules, "akshare", fake)
        w = _wrapper(initialized=False)
        w._init_akshare()
        assert w._initialized is True

    def test_no_set_option_attribute(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace())
        w = _wrapper(initialized=False)
        w._init_akshare()
        assert w._initialized is True

    def test_import_error_leaves_uninitialized(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "akshare", None)   # import → ImportError
        w = _wrapper(initialized=True)
        w._init_akshare()
        assert w._initialized is False
        assert w._ak is None


# ── rate control & stats ──────────────────────────────────────────────────


class TestRateControl:
    def test_no_sleep_when_interval_elapsed(self, fake_time):
        fake_time.now = 100.0
        w = _wrapper()
        w._last_call_time = 90.0          # elapsed = 10.0 ≥ 0.5
        w._control_request_rate()
        assert fake_time.sleeps == []
        assert w._last_call_time == 100.0

    def test_sleeps_when_too_fast(self, fake_time):
        fake_time.now = 0.0
        w = _wrapper()
        w._last_call_time = 0.0
        w._min_interval = 0.5
        w._control_request_rate()
        assert len(fake_time.sleeps) == 1
        assert fake_time.sleeps[0] == pytest.approx(0.5 + 0.7)


class TestMethodStats:
    def test_new_method_entry(self):
        w = _wrapper()
        w._update_method_stats("foo", True, 1.5)
        stats = w._method_stats["foo"]
        assert stats["total"] == 1 and stats["success"] == 1 and stats["failed"] == 0
        assert stats["avg_duration"] == pytest.approx(1.5)

    def test_running_average(self):
        w = _wrapper()
        w._update_method_stats("foo", True, 1.0)
        w._update_method_stats("foo", True, 3.0)
        assert w._method_stats["foo"]["avg_duration"] == pytest.approx(2.0)

    def test_failure_increments_failed_only(self):
        w = _wrapper()
        w._update_method_stats("foo", False)
        stats = w._method_stats["foo"]
        assert stats["total"] == 1 and stats["failed"] == 1 and stats["success"] == 0

    def test_get_method_stats_single_and_all(self):
        w = _wrapper()
        w._update_method_stats("foo", True, 1.0)
        assert w.get_method_stats("foo")["total"] == 1
        assert w.get_method_stats("missing") == {}
        assert "foo" in w.get_method_stats()

    def test_clear_method_stats(self):
        w = _wrapper()
        w._update_method_stats("foo", True, 1.0)
        w.clear_method_stats()
        assert w._method_stats == {}


# ── call(): init / success / error / retry ────────────────────────────────


class TestCall:
    def test_reinitialises_when_needed(self, fake_time, monkeypatch):
        ak = SimpleNamespace(ping=MagicMock(return_value="pong"))
        w = _wrapper(initialized=False, ak=None)

        def _reinit():
            w._ak = ak
            w._initialized = True

        monkeypatch.setattr(w, "_init_akshare", _reinit)
        assert w.call("ping") == "pong"

    def test_reinit_failure_returns_none(self, fake_time, monkeypatch):
        w = _wrapper(initialized=False, ak=None)
        monkeypatch.setattr(w, "_init_akshare", lambda: None)
        assert w.call("ping") is None
        assert w._method_stats["ping"]["failed"] == 1

    def test_successful_call_records_stats(self, fake_time):
        ak = SimpleNamespace(fetch=MagicMock(return_value=pd.DataFrame({"a": [1]})))
        w = _wrapper(ak=ak)
        out = w.call("fetch", symbol="600519")
        assert not out.empty
        ak.fetch.assert_called_once_with(symbol="600519")
        assert w._method_stats["fetch"]["success"] == 1

    def test_sets_headers_when_supported(self, fake_time):
        ak = SimpleNamespace(fetch=MagicMock(return_value=1), set_headers=MagicMock())
        w = _wrapper(ak=ak)
        w.call("fetch")
        ak.set_headers.assert_called_once()

    def test_missing_method_returns_none(self, fake_time):
        w = _wrapper(ak=SimpleNamespace())
        assert w.call("does_not_exist") is None
        assert w._method_stats["does_not_exist"]["failed"] == 1

    def test_domain_error_toggles_uninitialized(self, fake_time, monkeypatch):
        """``handle_errors`` 默认 ``reraise=True`` → DataFetchError 不被吞, 进入 retry 循环。

        另注: 首次失败即把 ``_initialized`` 置 False, 故第 2 次尝试走
        "重初始化失败" 短路分支 (此处重初始化被 mock 成 no-op) 而非重放上游调用。
        """
        from uniquant.shared.exceptions import DataFetchError

        ak = SimpleNamespace(fetch=MagicMock(side_effect=DataFetchError("upstream down")))
        w = _wrapper(ak=ak)
        monkeypatch.setattr(w, "_init_akshare", lambda: None)
        assert w.call("fetch") is None
        assert ak.fetch.call_count == 1          # 上游只被触达一次
        assert w._initialized is False
        assert w._method_stats["fetch"]["failed"] == 2

    def test_generic_error_toggles_uninitialized(self, fake_time, monkeypatch):
        ak = SimpleNamespace(fetch=MagicMock(side_effect=RuntimeError("boom")))
        w = _wrapper(ak=ak)
        # 每次重试都假装重初始化成功, 以便让 retry 耗尽并最终抛错
        monkeypatch.setattr(w, "_init_akshare", lambda: setattr(w, "_initialized", True))
        with pytest.raises(RuntimeError):
            w.call("fetch")
        assert w._initialized is False
        assert w._method_stats["fetch"]["failed"] >= 1


# ── thin delegation surface ───────────────────────────────────────────────


class TestMarketServiceDelegation:
    @pytest.mark.parametrize(
        "method,args",
        [
            ("fetch_stock_daily", ("600519", "2024-01-01", "2024-02-01", "qfq")),
            ("fetch_stock_spot", ("sina",)),
            ("fetch_stock_daily_sina", ("600519", "2024-01-01", "2024-02-01")),
            ("fetch_etf_hist", ("510300", "2024-01-01", "2024-02-01")),
            ("fetch_index_daily", ("000300.SH",)),
            ("fetch_minute_data", ("600519", "5", "2024-01-01", "2024-02-01", "qfq")),
            ("fetch_fund_flow", ("600519", "sh")),
            ("fetch_dragon_tiger_list", ("600519", "2024-01-01", "2024-02-01")),
            ("fetch_tick_data", ("600519",)),
        ],
    )
    def test_forwards_arguments(self, method, args):
        w = _wrapper()
        getattr(w.market_service, method).return_value = pd.DataFrame({"x": [1]})
        out = getattr(w, method)(*args)
        assert not out.empty
        getattr(w.market_service, method).assert_called_once_with(*args)


def test_module_singleton_is_exported():
    assert isinstance(aw_mod.akshare_wrapper, AkShareWrapper)
    assert aw_mod.akshare_wrapper.market_service is not None
