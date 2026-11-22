"""TdxDataOnlineSource 单元测试 (tdxdata 2026-09 新协议在线源)。

背景: 旧协议客户端 (pytdx/mootdx/tdxpy) 的 bars 命令自 2026-09 起被通达信
服务端拒绝 (响应被截断/短错误包); tdxdata 为新协议适配库, 2026-11-20 实测
与数据湖日线逐位一致 (600519 6044 交易日 0 差异)。

全部用例注入假客户端, 不触网、不读湖 (CI 安全)。
"""

import sys
import types

import pandas as pd
import pytest

from uniquant.data.sources.tdxdata_online import (
    LOT_TO_SHARE,
    PAGE_SIZE,
    TdxDataOnlineSource,
)


def _row(day: str, close: float = 10.0, vol: float = 1234.0) -> dict:
    """构造一根与 tdxdata.bars 返回结构一致的日线记录 (vol 单位=手)。"""
    return {
        "datetime": f"{day} 00:00",
        "open": close,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "vol": vol,
        "amount": close * vol,
    }


class _FakeClient:
    """镜像 tdxdata.TdxClient 的最小接口; pages 为按翻页序排列的行块。"""

    def __init__(self, pages=None, snap=None, finance=None, xdxr=None, fail=False):
        self.pages = pages or []
        self.snap_payload = snap
        self.finance_payload = finance
        self.xdxr_payload = xdxr
        self.fail = fail
        self.connected = False
        self.closed = False

    def connect(self):
        self.connected = True

    def close(self):
        self.closed = True

    def bars(self, category, code, start=0, count=PAGE_SIZE, market=None):
        if self.fail:
            raise ConnectionError("server down")
        idx = start // count
        return list(self.pages[idx]) if idx < len(self.pages) else []

    def snap(self, code, market=None):
        return dict(self.snap_payload or {})

    def finance(self, code, market=None):
        return dict(self.finance_payload or {})

    def xdxr(self, code, market=None, category=1):
        return list(self.xdxr_payload or [])


def _make_source(client: _FakeClient) -> TdxDataOnlineSource:
    src = TdxDataOnlineSource()
    src._client = client
    return src


def _full_page(days) -> list:
    return [_row(d) for d in days]


class TestFetchDaily:
    def test_shape_and_lot_to_share_conversion(self):
        src = _make_source(_FakeClient(pages=[_full_page(["2026-11-18", "2026-11-19"])]))
        df = src.fetch_daily("600519.SH", "2026-11-01", "2026-11-30")
        assert list(df.columns) == ["date", "open", "high", "low", "close", "volume", "amount", "code"]
        assert df["volume"].iloc[0] == pytest.approx(1234.0 * LOT_TO_SHARE)
        assert (df["code"] == "600519.SH").all()
        assert df["date"].is_monotonic_increasing
        assert df["date"].dt.tz is None

    def test_pagination_stops_once_start_date_covered(self):
        days_p0 = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end="2026-11-20", periods=PAGE_SIZE)]
        days_p1 = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end=days_p0[0], periods=PAGE_SIZE)[:-1]]
        src = _make_source(_FakeClient(pages=[_full_page(days_p0), _full_page(days_p1)]))
        start_day = days_p1[200]  # 落在第 2 页内部 → 必须翻页才能覆盖
        df = src.fetch_daily("600519.SH", start_day, "2026-11-20")
        expected_days = {d for d in set(days_p0) | set(days_p1) if start_day <= d <= "2026-11-20"}
        assert set(df["date"].dt.date) == {pd.Timestamp(d).date() for d in expected_days}
        assert pd.Timestamp(days_p1[300]).date() in set(df["date"].dt.date)  # 第 2 页内容确实被拉到
        assert df["date"].is_monotonic_increasing

    def test_filters_out_of_range_rows(self):
        src = _make_source(_FakeClient(pages=[_full_page(["2026-11-17", "2026-11-18", "2026-11-19"])]))
        df = src.fetch_daily("600519.SH", "2026-11-18", "2026-11-18")
        assert len(df) == 1
        assert df["date"].iloc[0] == pd.Timestamp("2026-11-18")

    def test_dedup_keeps_last_and_drops_vol_alias(self):
        rows = [_row("2026-11-18", close=10.0), _row("2026-11-18", close=11.0), _row("2026-11-19")]
        src = _make_source(_FakeClient(pages=[rows]))
        df = src.fetch_daily("600519.SH", "2026-11-01", "2026-11-30")
        assert len(df) == 2
        assert df[df["date"] == pd.Timestamp("2026-11-18")]["close"].iloc[0] == pytest.approx(11.0)
        assert "vol" not in df.columns

    def test_empty_dataframe_on_client_error(self):
        src = _make_source(_FakeClient(fail=True))
        df = src.fetch_daily("600519.SH", "2026-11-01", "2026-11-30")
        assert df.empty

    def test_empty_dataframe_on_no_data(self):
        src = _make_source(_FakeClient(pages=[]))
        assert src.fetch_daily("600519.SH", "2026-11-01", "2026-11-30").empty


class TestRealtimeAndFundamentals:
    def test_real_time_parses_last_only(self):
        """snap 解析 (第二十四轮修正): 只输出全样本可验证的 last。

        反例驱动: 600959 prices[0]=89088.477 (垃圾值, 昨收实为 3.02) →
        第二十三轮 "prices[0]=昨收/[1]=今开" 语义外推系伪回归, 已回退。
        """
        snap = {
            "ok": True,
            "code": "600519",
            "market": 0,
            "prices": [1460.21, 1450.89, 1445.3, 1448.47, 1485.75],
            "last": 1485.75,
            "compressed": True,
        }
        src = _make_source(_FakeClient(snap=snap))
        df = src.fetch_real_time("600519.SH")
        assert list(df.columns) == ["code", "market", "last", "series_points", "compressed"]
        assert len(df) == 1
        assert df["code"].iloc[0] == "600519.SH"
        assert df["last"].iloc[0] == pytest.approx(1485.75)
        assert df["series_points"].iloc[0] == 5
        assert bool(df["compressed"].iloc[0]) is True
        assert "prev_close" not in df.columns and "open" not in df.columns
        assert "high" not in df.columns and "low" not in df.columns

    def test_real_time_tolerates_empty_prices(self):
        snap = {"prices": [], "last": 10.5}
        src = _make_source(_FakeClient(snap=snap))
        df = src.fetch_real_time("000001.SZ")
        assert df["last"].iloc[0] == pytest.approx(10.5)
        assert df["series_points"].iloc[0] == 0

    def test_real_time_empty_without_symbol(self):
        src = _make_source(_FakeClient(snap={"last": 1.0}))
        assert src.fetch_real_time(None).empty

    def test_real_time_empty_on_error(self):
        src = _make_source(_FakeClient(fail=True))
        assert src.fetch_real_time("600519.SH").empty


class TestFetchMinute:
    """分钟线 (1/5/15/30/60min): vol 已是股 (实测比值 1.00), 不做 ×100。"""

    def _minute_row(self, dt: str, close: float = 10.0, vol: float = 954_600.0) -> dict:
        return {
            "datetime": dt,
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "vol": vol,
            "amount": close * vol,
        }

    def test_unknown_frequency_raises_value_error(self):
        src = _make_source(_FakeClient())
        with pytest.raises(ValueError, match="分钟频率"):
            src.fetch_minute("600519.SH", frequency="2h")

    def test_shape_and_volume_not_rescaled(self):
        rows = [self._minute_row("2026-11-20 14:55"), self._minute_row("2026-11-20 15:00")]
        src = _make_source(_FakeClient(pages=[rows]))
        df = src.fetch_minute("600519.SH", frequency="5min")
        assert list(df.columns) == [
            "datetime", "open", "high", "low", "close", "volume", "amount", "code",
        ]
        assert df["volume"].iloc[0] == pytest.approx(954_600.0)  # 原样 (股), 未 ×100
        assert df["datetime"].iloc[0] == pd.Timestamp("2026-11-20 14:55")
        assert (df["code"] == "600519.SH").all()

    def test_range_filtering(self):
        rows = [
            self._minute_row("2026-11-20 09:35"),
            self._minute_row("2026-11-20 10:00"),
            self._minute_row("2026-11-20 14:55"),
        ]
        src = _make_source(_FakeClient(pages=[rows]))
        df = src.fetch_minute("600519.SH", start_dt="2026-11-20 10:00", end_dt="2026-11-20 14:55")
        assert len(df) == 2

    def test_empty_on_no_data(self):
        src = _make_source(_FakeClient(pages=[]))
        assert src.fetch_minute("600519.SH").empty

    def test_market_cap_from_finance_shares_times_latest_close(self):
        fin = {"zongguben": 1_250_081_562.5, "liutongguben": 1_250_081_562.5}
        rows = [_row("2026-11-19", close=1460.21), _row("2026-11-20", close=1485.75)]
        src = _make_source(_FakeClient(pages=[rows], finance=fin))
        cap = src.fetch_market_cap("600519.SH")
        assert cap == pytest.approx(1_250_081_562.5 * 1485.75, rel=1e-9)

    def test_market_cap_zero_on_failure(self):
        src = _make_source(_FakeClient(fail=True))
        assert src.fetch_market_cap("600519.SH") == 0.0

    def test_finance_passthrough(self):
        fin = {"zongguben": 1.0, "net_profit": 64_467_424_000.0}
        src = _make_source(_FakeClient(finance=fin))
        assert src.fetch_finance("600519.SH") == fin

    def test_xdxr_passthrough(self):
        xdxr = [{"year": 2024, "category": 1, "fenhong": 54.76}]
        src = _make_source(_FakeClient(xdxr=xdxr))
        assert src.fetch_xdxr("600519.SH") == xdxr


class TestLifecycle:
    def test_capabilities_flags(self):
        caps = TdxDataOnlineSource().get_capabilities()
        assert caps["offline"] is False
        assert caps["daily"] is True
        assert caps["realtime"] is True
        assert caps["financial"] is True

    def test_close_resets_client(self):
        src = _make_source(_FakeClient())
        src.close()
        assert src._client is None

    def test_lazy_client_created_with_host_and_connected(self, monkeypatch):
        created = {}

        class _CreatedClient(_FakeClient):
            def __init__(self, **kwargs):
                super().__init__()
                created.update(kwargs)
                self.connect_called = False

            def connect(self):
                self.connected = True
                self.connect_called = True

        fake_mod = types.ModuleType("tdxdata")
        fake_mod.TdxClient = _CreatedClient
        monkeypatch.setitem(sys.modules, "tdxdata", fake_mod)

        src = TdxDataOnlineSource(host="101.35.121.35", port=7709)
        client = src._get_client()
        assert created == {"host": "101.35.121.35", "port": 7709}
        assert client.connect_called is True

    def test_name(self):
        assert TdxDataOnlineSource().name == "TdxDataOnline"


class TestFetchXdXrAsGbbq:
    """xdxr → gbbq 八列契约转换 (2026-11-20 实测: 5 标的 170 事件四字段逐位一致)。"""

    def _xdxr_row(self, date, cat=1, fenhong=280.24, song=1.0, peigu=0.0, price=0.0):
        return {
            "market": 1,
            "code": "600519",
            "date": date,
            "category": cat,
            "fenhong": fenhong,
            "peigujia": price,
            "songzhuangu": song,
            "peigu": peigu,
            "shares": None,
        }

    def test_contract_columns_and_mapping(self):
        rows = [self._xdxr_row(20260626), self._xdxr_row(20250626, fenhong=276.73, song=0.0)]
        src = _make_source(_FakeClient(xdxr=rows))
        df = src.fetch_xdxr_as_gbbq("600519.SH")
        assert list(df.columns) == [
            "code", "market", "date", "category", "cash_div", "split_ratio", "rights_ratio", "rights_price",
        ]
        assert len(df) == 2
        top = df[df["date"] == 20260626].iloc[0]
        assert top["code"] == "600519"
        assert top["market"] == 1
        assert top["cash_div"] == pytest.approx(280.24)
        assert top["split_ratio"] == pytest.approx(1.0)
        assert top["rights_ratio"] == pytest.approx(0.0)
        assert top["rights_price"] == pytest.approx(0.0)

    def test_sorted_by_date_and_all_categories_passthrough(self):
        rows = [
            self._xdxr_row(20260626),
            self._xdxr_row(20020725, cat=5, fenhong=0.0, song=1.0),
            self._xdxr_row(20250626),
        ]
        src = _make_source(_FakeClient(xdxr=rows))
        df = src.fetch_xdxr_as_gbbq("600519.SH")
        assert list(df["date"]) == [20020725, 20250626, 20260626]
        assert set(df["category"]) == {1, 5}

    def test_error_returns_empty_with_contract_columns(self):
        src = _make_source(_FakeClient(fail=True))
        df = src.fetch_xdxr_as_gbbq("600519.SH")
        assert df.empty
        assert "cash_div" in df.columns and "split_ratio" in df.columns

    def test_empty_xdxr_returns_empty_with_columns(self):
        src = _make_source(_FakeClient(xdxr=[]))
        df = src.fetch_xdxr_as_gbbq("600519.SH")
        assert df.empty and "rights_price" in df.columns


class TestParseSymbol:
    """验证证券与指数代码及市场码解析。"""

    def test_parse_symbol_varieties(self):
        assert TdxDataOnlineSource._parse_symbol("600519.SH") == ("600519", 1)
        assert TdxDataOnlineSource._parse_symbol("000001.SZ") == ("000001", 0)
        assert TdxDataOnlineSource._parse_symbol("830001.BJ") == ("830001", 2)
        assert TdxDataOnlineSource._parse_symbol("000300.SH") == ("000300", 1)
        assert TdxDataOnlineSource._parse_symbol("399001.SZ") == ("399001", 0)
        assert TdxDataOnlineSource._parse_symbol("600519") == ("600519", None)


class TestParseIndexBarsResponse:
    """验证指数 K 线专有响应解码 (包含 up_count/down_count 4 字节指针步进)。"""

    @staticmethod
    def _encode_varint(val: int) -> bytes:
        sign = 0x40 if val < 0 else 0
        uval = abs(val)
        first = (uval & 0x3F) | sign
        uval >>= 6
        if uval > 0:
            first |= 0x80
            out = [first]
            while uval > 0:
                b = uval & 0x7F
                uval >>= 7
                if uval > 0:
                    b |= 0x80
                out.append(b)
            return bytes(out)
        return bytes([first])

    def test_empty_or_short_buffer_returns_empty_list(self):
        from uniquant.data.sources.tdxdata_online import _parse_index_bars_response

        assert _parse_index_bars_response(b"", category=4) == []
        assert _parse_index_bars_response(b"\x00", category=4) == []

    def test_daily_category_decode(self):
        import struct
        from uniquant.data.sources.tdxdata_online import _parse_index_bars_response

        body = struct.pack("<H", 1)
        body += struct.pack("<I", 20261120)
        body += self._encode_varint(3000)
        body += self._encode_varint(100)
        body += self._encode_varint(200)
        body += self._encode_varint(-100)
        body += struct.pack("<ff", 50000.0, 155000.0)
        body += struct.pack("<HH", 1200, 800)

        rows = _parse_index_bars_response(body, category=4)
        assert len(rows) == 1
        r = rows[0]
        assert r["datetime"] == "2026-11-20 00:00"
        assert r["open"] == pytest.approx(3.0)
        assert r["close"] == pytest.approx(3.1)
        assert r["high"] == pytest.approx(3.2)
        assert r["low"] == pytest.approx(2.9)
        assert r["vol"] == pytest.approx(50000.0)
        assert r["amount"] == pytest.approx(155000.0)

    def test_minute_category_decode(self):
        import struct
        from uniquant.data.sources.tdxdata_online import _parse_index_bars_response

        zipday = ((2026 - 2004) << 11) + (11 * 100 + 20)
        tminutes = 14 * 60 + 30
        body = struct.pack("<H", 1)
        body += struct.pack("<HH", zipday, tminutes)
        body += self._encode_varint(3000)
        body += self._encode_varint(100)
        body += self._encode_varint(200)
        body += self._encode_varint(-100)
        body += struct.pack("<ff", 50000.0, 155000.0)
        body += struct.pack("<HH", 1200, 800)

        rows = _parse_index_bars_response(body, category=0)
        assert len(rows) == 1
        r = rows[0]
        assert r["datetime"] == "2026-11-20 14:30"
        assert r["open"] == pytest.approx(3.0)
        assert r["close"] == pytest.approx(3.1)


class TestFetchIndexOnline:
    """验证指数日线拉取整合 (包括 _FakeClient 兼容)。"""

    def test_fetch_daily_index_with_fake_client(self):
        rows = [_row("2026-11-19", close=3950.0), _row("2026-11-20", close=3960.0)]
        src = _make_source(_FakeClient(pages=[rows]))
        df = src.fetch_daily("000300.SH", "2026-11-19", "2026-11-20")
        assert len(df) == 2
        assert (df["code"] == "000300.SH").all()
        assert df["close"].iloc[1] == pytest.approx(3960.0)

