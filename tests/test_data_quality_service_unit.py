"""Unit tests for uniquant.services.data_quality_service.

Covers quality-metric math (completeness/consistency/timeliness/validity/
uniqueness), status thresholds, health checks, report generation,
recommendations and monitoring/alerts.

CI-safe: no network, no ``data/`` access, time frozen via ``FrozenTimeProvider``.
"""

import datetime
import math

import pandas as pd
import pytest

from uniquant.services.data_quality_service import DataQualityService
from uniquant.shared.constants import DataServiceConstants
from uniquant.shared.time_provider import (
    FrozenTimeProvider,
    get_time_provider,
    set_time_provider,
)

FROZEN_NOW = datetime.datetime(2024, 6, 1, 9, 30, 0)


@pytest.fixture
def frozen_time():
    """Pin the module-level time provider to a deterministic instant."""
    original = get_time_provider()
    set_time_provider(FrozenTimeProvider(FROZEN_NOW))
    try:
        yield FROZEN_NOW
    finally:
        set_time_provider(original)


def _clean_ohlcv(index=None, **overrides):
    """Build a fully consistent OHLCV frame (score components all 1.0)."""
    data = {
        "open": [10.0, 11.0],
        "high": [12.0, 13.0],
        "low": [9.0, 10.0],
        "close": [11.0, 12.0],
        "volume": [100.0, 200.0],
        "amount": [1000.0, 2000.0],
    }
    data.update(overrides)
    if index is None:
        index = pd.DatetimeIndex([pd.Timestamp("2024-05-31"), pd.Timestamp("2024-06-01")])
    return pd.DataFrame(data, index=index)


# --------------------------------------------------------------------------
# calculate_data_quality
# --------------------------------------------------------------------------

def test_calculate_data_quality_empty_returns_no_data(frozen_time):
    service = DataQualityService()
    result = service.calculate_data_quality(pd.DataFrame(), "000001.SZ")

    assert result["symbol"] == "000001.SZ"
    assert result["data_type"] == "stock"
    assert result["quality_score"] == 0.0
    assert result["status"] == "no_data"
    assert result["metrics"] == {}
    assert result["timestamp"] == "2024-06-01 09:30:00"


def test_calculate_data_quality_clean_data_is_excellent(frozen_time):
    service = DataQualityService()
    result = service.calculate_data_quality(_clean_ohlcv(), "600519.SH", data_type="index")

    assert result["status"] == "excellent"
    assert result["quality_score"] == 100.0
    assert result["data_type"] == "index"
    assert set(result["metrics"]) == {
        "completeness",
        "consistency",
        "timeliness",
        "validity",
        "uniqueness",
    }
    assert all(math.isclose(v, 1.0) for v in result["metrics"].values())


def test_calculate_data_quality_poor_data(frozen_time):
    service = DataQualityService()
    # Degenerate frame: NaN holes, negative prices, stale + duplicated index.
    index = pd.DatetimeIndex(["2024-05-01", "2024-05-01", "2019-01-01"])
    data = pd.DataFrame(
        {
            "open": [-1.0, None, None],
            "high": [1.0, None, None],
            "low": [1.0, None, None],
            "close": [1.0, None, None],
            "volume": [-5.0, None, None],
            "amount": [None, None, None],
        },
        index=index,
    )
    result = service.calculate_data_quality(data, "000002.SZ")

    assert result["status"] == "poor"
    assert result["quality_score"] < DataServiceConstants.QUALITY_SCORE_FAIR


@pytest.mark.parametrize(
    "value, expected",
    [
        (0.95, "excellent"),
        (0.80, "good"),
        (0.65, "fair"),
        (0.10, "poor"),
    ],
)
def test_calculate_data_quality_status_thresholds(frozen_time, monkeypatch, value, expected):
    service = DataQualityService()
    # Force every metric component to the same value -> score = value * 100.
    monkeypatch.setattr(service, "_calculate_completeness", lambda df: value)
    monkeypatch.setattr(service, "_calculate_consistency", lambda df: value)
    monkeypatch.setattr(service, "_calculate_timeliness", lambda df: value)
    monkeypatch.setattr(service, "_calculate_validity", lambda df, dt: value)
    monkeypatch.setattr(service, "_calculate_uniqueness", lambda df: value)

    result = service.calculate_data_quality(pd.DataFrame({"close": [1.0]}), "X")
    assert result["status"] == expected
    assert result["quality_score"] == pytest.approx(value * 100, abs=0.01)


# --------------------------------------------------------------------------
# _calculate_completeness
# --------------------------------------------------------------------------

def test_completeness_counts_non_null_ratio():
    service = DataQualityService()
    df = pd.DataFrame({"a": [1.0, None], "b": [2.0, 3.0]})  # 3 / 4 non-null
    assert service._calculate_completeness(df) == 0.75


def test_completeness_empty_is_zero():
    service = DataQualityService()
    assert service._calculate_completeness(pd.DataFrame()) == 0.0


# --------------------------------------------------------------------------
# _calculate_consistency
# --------------------------------------------------------------------------

def test_consistency_clean_frame_is_one():
    service = DataQualityService()
    assert service._calculate_consistency(_clean_ohlcv()) == 1.0


def test_consistency_empty_is_zero():
    service = DataQualityService()
    assert service._calculate_consistency(pd.DataFrame()) == 0.0


def test_consistency_price_structure_penalty():
    service = DataQualityService()
    # high >= low is satisfied but open/close sit above high -> one penalty.
    df = pd.DataFrame(
        {"open": [20.0], "high": [10.0], "low": [5.0], "close": [20.0]}
    )
    assert service._calculate_consistency(df) == pytest.approx(0.75)


def test_consistency_high_below_low_and_structure_penalty():
    service = DataQualityService()
    df = pd.DataFrame(
        {"open": [11.0], "high": [10.0], "low": [12.0], "close": [11.0]}
    )
    # high < low and the price-bounds check both fail -> two penalties.
    assert service._calculate_consistency(df) == pytest.approx(0.5)


def test_consistency_non_monotonic_datetime_index():
    service = DataQualityService()
    index = pd.DatetimeIndex(["2024-06-02", "2024-06-01"])
    df = _clean_ohlcv(index=index)
    assert service._calculate_consistency(df) == pytest.approx(0.75)


def test_consistency_duplicate_datetime_index():
    service = DataQualityService()
    d = pd.Timestamp("2024-06-01")
    index = pd.DatetimeIndex([d, d])
    df = _clean_ohlcv(index=index)
    assert service._calculate_consistency(df) == pytest.approx(0.75)


def test_consistency_unsorted_and_duplicated_index():
    service = DataQualityService()
    index = pd.DatetimeIndex(["2024-06-02", "2024-06-01", "2024-06-01"])
    df = pd.DataFrame(
        {
            "open": [10.0, 11.0, 12.0],
            "high": [12.0, 13.0, 14.0],
            "low": [9.0, 10.0, 11.0],
            "close": [11.0, 12.0, 13.0],
        },
        index=index,
    )
    # Not monotonic (-0.25) *and* duplicated (-0.25).
    assert service._calculate_consistency(df) == pytest.approx(0.5)


# --------------------------------------------------------------------------
# _calculate_timeliness
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "days_diff, expected",
    [
        (0, DataServiceConstants.TIMELINESS_SCORE_TODAY),
        (1, DataServiceConstants.TIMELINESS_SCORE_1_DAY),
        (3, DataServiceConstants.TIMELINESS_SCORE_3_DAYS),
        (7, DataServiceConstants.TIMELINESS_SCORE_7_DAYS),
        (30, DataServiceConstants.TIMELINESS_SCORE_30_DAYS),
        (400, DataServiceConstants.TIMELINESS_SCORE_OLD),
    ],
)
def test_timeliness_bands(frozen_time, days_diff, expected):
    service = DataQualityService()
    latest = FROZEN_NOW.date() - datetime.timedelta(days=days_diff)
    df = pd.DataFrame({"close": [1.0]}, index=pd.DatetimeIndex([pd.Timestamp(latest)]))
    assert service._calculate_timeliness(df) == expected


def test_timeliness_non_datetime_index_is_neutral():
    service = DataQualityService()
    df = pd.DataFrame({"close": [1.0, 2.0]})  # RangeIndex
    assert service._calculate_timeliness(df) == 0.5


def test_timeliness_empty_is_zero():
    service = DataQualityService()
    assert service._calculate_timeliness(pd.DataFrame()) == 0.0


# --------------------------------------------------------------------------
# _calculate_validity
# --------------------------------------------------------------------------

def test_validity_negative_price_penalty():
    service = DataQualityService()
    df = _clean_ohlcv(open=[-1.0, 11.0])
    assert service._calculate_validity(df, "stock") == pytest.approx(0.9)


def test_validity_negative_volume_and_amount_penalty():
    service = DataQualityService()
    df = _clean_ohlcv(volume=[-100.0, 200.0], amount=[-1.0, 2000.0])
    assert service._calculate_validity(df, "stock") == pytest.approx(0.8)


def test_validity_multiple_price_penalties():
    service = DataQualityService()
    df = _clean_ohlcv(open=[0.0, 11.0], close=[-3.0, 12.0])
    assert service._calculate_validity(df, "stock") == pytest.approx(0.8)


def test_validity_empty_is_zero():
    service = DataQualityService()
    assert service._calculate_validity(pd.DataFrame(), "stock") == 0.0


# --------------------------------------------------------------------------
# _calculate_uniqueness
# --------------------------------------------------------------------------

def test_uniqueness_clean_is_one():
    service = DataQualityService()
    assert service._calculate_uniqueness(_clean_ohlcv()) == 1.0


def test_uniqueness_with_duplicates():
    service = DataQualityService()
    index = pd.DatetimeIndex(["2024-06-01", "2024-06-01", "2024-06-02", "2024-06-03"])
    df = pd.DataFrame({"close": [1.0, 2.0, 3.0, 4.0]}, index=index)
    assert service._calculate_uniqueness(df) == pytest.approx(0.75)


def test_uniqueness_empty_is_zero():
    service = DataQualityService()
    assert service._calculate_uniqueness(pd.DataFrame()) == 0.0


# --------------------------------------------------------------------------
# check_data_health / generate_data_quality_report
# --------------------------------------------------------------------------

def test_check_data_health_processes_each_item(frozen_time):
    service = DataQualityService()
    items = [
        {"data": _clean_ohlcv(), "symbol": "600519.SH"},
        {"data": pd.DataFrame(), "symbol": "000001.SZ", "data_type": "index"},
    ]
    results = service.check_data_health(items)

    assert len(results) == 2
    assert results[0]["symbol"] == "600519.SH"
    assert results[0]["status"] == "excellent"
    assert results[1]["status"] == "no_data"
    assert results[1]["data_type"] == "index"


def test_check_data_health_defaults_missing_keys(frozen_time):
    service = DataQualityService()
    results = service.check_data_health([{}])
    assert results[0]["symbol"] == ""
    assert results[0]["data_type"] == "stock"
    assert results[0]["status"] == "no_data"


def test_generate_report_with_mixed_items(frozen_time):
    service = DataQualityService()
    items = [
        {"data": _clean_ohlcv(), "symbol": "600519.SH"},
        {"data": pd.DataFrame(), "symbol": "000001.SZ"},
    ]
    report = service.generate_data_quality_report(items)

    assert report["total_items"] == 2
    assert report["analyzed_items"] == 2
    assert report["problem_count"] == 1
    assert report["status_distribution"] == {"excellent": 1, "no_data": 1}
    assert report["average_quality_score"] == 50.0
    assert report["problem_details"][0]["symbol"] == "000001.SZ"
    assert any("no data" in r for r in report["recommendations"])
    assert report["report_id"] == "20240601_093000"


def test_generate_report_empty_items(frozen_time):
    service = DataQualityService()
    report = service.generate_data_quality_report([])

    assert report["total_items"] == 0
    assert report["analyzed_items"] == 0
    assert report["average_quality_score"] == 0.0
    assert report["status_distribution"] == {}
    assert report["problem_count"] == 0
    assert report["recommendations"] == ["All data is in good condition."]


def test_generate_report_recovers_from_error(frozen_time, monkeypatch):
    service = DataQualityService()

    def boom(_items):
        raise ValueError("kaboom")

    monkeypatch.setattr(service, "check_data_health", boom)
    report = service.generate_data_quality_report([{"symbol": "X"}])

    assert report["error"] == "kaboom"
    assert "timestamp" in report


# --------------------------------------------------------------------------
# _generate_recommendations
# --------------------------------------------------------------------------

def test_recommendations_all_good():
    service = DataQualityService()
    assert service._generate_recommendations([]) == ["All data is in good condition."]


def test_recommendations_no_data_and_poor():
    service = DataQualityService()
    problems = [
        {"symbol": "A", "status": "no_data", "metrics": {}},
        {
            "symbol": "B",
            "status": "poor",
            "metrics": {"completeness": 0.2, "validity": 0.9},
        },
    ]
    recs = service._generate_recommendations(problems)

    assert any("1 items have no data" in r for r in recs)
    assert any("1 items have poor data quality" in r for r in recs)
    assert any("Symbol A: No data available" in r for r in recs)
    assert any("Symbol B: Low metrics: completeness" in r for r in recs)


def test_recommendations_poor_without_low_metrics():
    service = DataQualityService()
    recs = service._generate_recommendations(
        [{"symbol": "C", "status": "poor", "metrics": {"completeness": 0.9}}]
    )
    # Summary line is emitted but no per-symbol low-metric line.
    assert not any(r.startswith("Symbol C") for r in recs)


# --------------------------------------------------------------------------
# monitor_data_quality
# --------------------------------------------------------------------------

def test_monitor_emits_alerts_for_low_scores(frozen_time):
    service = DataQualityService()
    items = [
        {"data": pd.DataFrame(), "symbol": "EMPTY"},
        {"data": _clean_ohlcv(), "symbol": "GOOD"},
    ]
    alerts = service.monitor_data_quality(items, threshold=70.0)

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["symbol"] == "EMPTY"
    assert alert["severity"] == "high"
    assert alert["threshold"] == 70.0
    assert alert["alert_id"] == "EMPTY_20240601_093000"
    assert "EMPTY" in alert["message"]


def test_monitor_severity_medium_between_50_and_threshold(frozen_time, monkeypatch):
    service = DataQualityService()
    monkeypatch.setattr(
        service,
        "check_data_health",
        lambda items: [
            {"symbol": "MID", "data_type": "stock", "quality_score": 60.0, "status": "fair"}
        ],
    )
    alerts = service.monitor_data_quality([{"symbol": "MID"}], threshold=70.0)

    assert len(alerts) == 1
    assert alerts[0]["severity"] == "medium"


def test_monitor_no_alerts_when_all_healthy(frozen_time):
    service = DataQualityService()
    alerts = service.monitor_data_quality(
        [{"data": _clean_ohlcv(), "symbol": "GOOD"}], threshold=70.0
    )
    assert alerts == []
