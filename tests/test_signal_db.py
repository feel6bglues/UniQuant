"""Tests for signal/db.py — SignalDatabase persistence layer."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from uniquant.signal.db import SignalDatabase, SignalRecord
from uniquant.signal.models import (
    Signal,
    SignalBatch,
    SignalSource,
    SignalStrength,
    SignalType,
)
from uniquant.shared.time_provider import FrozenTimeProvider, set_time_provider


# ───────────────────────── fixtures ─────────────────────────

@pytest.fixture
def frozen_time():
    provider = FrozenTimeProvider(datetime(2024, 6, 1, 10, 0, 0))
    set_time_provider(provider)
    yield provider
    set_time_provider(None)


@pytest.fixture
def db(frozen_time):
    database = SignalDatabase(connection_string="sqlite:///:memory:")
    yield database


@pytest.fixture
def sample_signal() -> Signal:
    return Signal(
        symbol="000001",
        signal_type=SignalType.TREND_BULLISH,
        source=SignalSource.INDICATOR,
        direction=1,
        strength=SignalStrength.STRONG,
        confidence=0.85,
        price=10.5,
        value=1.0,
        metadata={"ma": "5", "period": 20},
    )


@pytest.fixture
def sample_signal_2() -> Signal:
    return Signal(
        symbol="000002",
        signal_type=SignalType.TREND_BEARISH,
        source=SignalSource.WYCKOFF,
        direction=-1,
        strength=SignalStrength.WEAK,
        confidence=0.3,
        price=20.0,
        value=-0.5,
        metadata={"pattern": "distribution"},
    )


@pytest.fixture
def sample_signal_3() -> Signal:
    return Signal(
        symbol="000001",
        signal_type=SignalType.VOLUME_SURGE,
        source=SignalSource.INDICATOR,
        direction=0,
        strength=SignalStrength.MODERATE,
        confidence=0.6,
        price=11.0,
        value=0.0,
        metadata={},
    )


# ───────────────────────── save_signal ─────────────────────────

class TestSaveSignal:
    def test_save_and_retrieve(self, db, sample_signal):
        saved_id = db.save_signal(sample_signal)
        assert saved_id == sample_signal.id

        retrieved = db.get_by_id(sample_signal.id)
        assert retrieved is not None
        assert retrieved.id == sample_signal.id
        assert retrieved.symbol == "000001"
        assert retrieved.signal_type == SignalType.TREND_BULLISH
        assert retrieved.source == SignalSource.INDICATOR
        assert retrieved.direction == 1
        assert retrieved.strength == SignalStrength.STRONG
        assert retrieved.confidence == 0.85
        assert retrieved.price == 10.5
        assert retrieved.metadata == {"ma": "5", "period": 20}

    def test_overwrite_existing(self, db, sample_signal):
        db.save_signal(sample_signal)
        updated = Signal(
            id=sample_signal.id,
            symbol="000001",
            signal_type=SignalType.TREND_NEUTRAL,
            source=SignalSource.INDICATOR,
            direction=0,
            confidence=0.5,
            price=11.0,
            value=0.0,
        )
        db.save_signal(updated)
        retrieved = db.get_by_id(sample_signal.id)
        assert retrieved is not None
        assert retrieved.signal_type == SignalType.TREND_NEUTRAL
        assert retrieved.price == 11.0

    def test_save_with_expiration(self, db, frozen_time):
        exp = frozen_time.now() + timedelta(hours=1)
        sig = Signal(symbol="000001", expiration=exp)
        db.save_signal(sig)
        retrieved = db.get_by_id(sig.id)
        assert retrieved is not None
        assert retrieved.expiration == exp

    def test_save_with_parent_id(self, db):
        parent = Signal(symbol="000001")
        child = Signal(symbol="000001", parent_id=parent.id)
        db.save_signal(parent)
        db.save_signal(child)
        retrieved = db.get_by_id(child.id)
        assert retrieved is not None
        assert retrieved.parent_id == parent.id


# ───────────────────────── save_batch ─────────────────────────

class TestSaveBatch:
    def test_save_batch(self, db, sample_signal, sample_signal_2):
        batch = SignalBatch(signals=[sample_signal, sample_signal_2])
        ids = db.save_batch(batch)
        assert len(ids) == 2
        assert sample_signal.id in ids
        assert sample_signal_2.id in ids

        retrieved = db.get_by_id(sample_signal.id)
        assert retrieved is not None
        assert retrieved.symbol == "000001"

    def test_batch_empty(self, db):
        batch = SignalBatch(signals=[])
        ids = db.save_batch(batch)
        assert ids == []


# ───────────────────────── get_by_id ─────────────────────────

class TestGetById:
    def test_not_found(self, db):
        result = db.get_by_id("nonexistent")
        assert result is None

    def test_by_id(self, db, sample_signal):
        db.save_signal(sample_signal)
        retrieved = db.get_by_id(sample_signal.id)
        assert retrieved is not None
        assert retrieved.id == sample_signal.id


# ───────────────────────── query_by_symbol ─────────────────────────

class TestQueryBySymbol:
    def test_by_symbol(self, db, sample_signal, sample_signal_2, sample_signal_3):
        db.save_signal(sample_signal)
        db.save_signal(sample_signal_2)
        db.save_signal(sample_signal_3)

        results = db.query_by_symbol("000001")
        assert len(results) == 2
        assert all(r.symbol == "000001" for r in results)

    def test_by_symbol_with_time_range(self, db, sample_signal, sample_signal_3, frozen_time):
        db.save_signal(sample_signal)
        frozen_time.advance(hours=2)
        sig2 = Signal(
            id="time2",
            symbol="000001",
            timestamp=frozen_time.now(),
        )
        db.save_signal(sig2)
        frozen_time.advance(hours=2)
        sig3 = Signal(
            id="time3",
            symbol="000001",
            timestamp=frozen_time.now(),
        )
        db.save_signal(sig3)

        results = db.query_by_symbol(
            "000001",
            start=datetime(2024, 6, 1, 11, 0, 0),
            end=datetime(2024, 6, 1, 13, 30, 0),
        )
        assert len(results) == 1
        assert results[0].id == "time2"

    def test_by_symbol_no_results(self, db):
        results = db.query_by_symbol("nonexistent")
        assert results == []

    def test_by_symbol_limit(self, db):
        for i in range(5):
            sig = Signal(
                id=f"lim_{i}",
                symbol="000001",
                timestamp=datetime(2024, 6, 1, 10, i, 0),
            )
            db.save_signal(sig)
        results = db.query_by_symbol("000001", limit=3)
        assert len(results) == 3


# ───────────────────────── query_by_source ─────────────────────────

class TestQueryBySource:
    def test_by_source(self, db, sample_signal, sample_signal_2, sample_signal_3):
        db.save_signal(sample_signal)
        db.save_signal(sample_signal_2)
        db.save_signal(sample_signal_3)

        results = db.query_by_source(SignalSource.INDICATOR)
        assert len(results) == 2
        assert all(r.source == SignalSource.INDICATOR for r in results)

    def test_by_source_no_results(self, db):
        results = db.query_by_source(SignalSource.ENSEMBLE)
        assert results == []

    def test_by_source_with_time_range(self, db, sample_signal, frozen_time):
        db.save_signal(sample_signal)
        frozen_time.advance(hours=3)
        sig2 = Signal(
            id="src_time2",
            symbol="000001",
            source=SignalSource.INDICATOR,
            timestamp=frozen_time.now(),
        )
        db.save_signal(sig2)

        results = db.query_by_source(
            SignalSource.INDICATOR,
            start=datetime(2024, 6, 1, 10, 30, 0),
        )
        assert len(results) == 1
        assert results[0].id == "src_time2"

    def test_by_source_limit(self, db):
        for i in range(5):
            sig = Signal(
                id=f"src_lim_{i}",
                symbol="000001",
                source=SignalSource.REGIME,
                timestamp=datetime(2024, 6, 1, 10, i, 0),
            )
            db.save_signal(sig)
        results = db.query_by_source(SignalSource.REGIME, limit=2)
        assert len(results) == 2


# ───────────────────────── query_by_type ─────────────────────────

class TestQueryByType:
    def test_by_type(self, db, sample_signal, sample_signal_2, sample_signal_3):
        db.save_signal(sample_signal)
        db.save_signal(sample_signal_2)
        db.save_signal(sample_signal_3)

        results = db.query_by_type(SignalType.TREND_BULLISH)
        assert len(results) == 1
        assert results[0].signal_type == SignalType.TREND_BULLISH

    def test_by_type_no_results(self, db):
        results = db.query_by_type(SignalType.LPPL_BUBBLE)
        assert results == []

    def test_by_type_limit(self, db):
        for i in range(5):
            sig = Signal(
                id=f"type_lim_{i}",
                symbol="000001",
                signal_type=SignalType.MOMENTUM_OVERSOLD,
                timestamp=datetime(2024, 6, 1, 10, i, 0),
            )
            db.save_signal(sig)
        results = db.query_by_type(SignalType.MOMENTUM_OVERSOLD, limit=3)
        assert len(results) == 3


# ───────────────────────── get_recent_signals ─────────────────────────

class TestGetRecentSignals:
    def test_recent_signals(self, db, sample_signal, frozen_time):
        db.save_signal(sample_signal)
        frozen_time.advance(minutes=30)
        sig2 = Signal(
            id="recent2",
            symbol="000002",
            timestamp=frozen_time.now(),
        )
        db.save_signal(sig2)
        frozen_time.advance(minutes=20)

        results = db.get_recent_signals(minutes=45)
        assert len(results) == 1
        assert results[0].id == "recent2"

    def test_recent_signals_default(self, db, sample_signal, frozen_time):
        db.save_signal(sample_signal)
        frozen_time.advance(minutes=30)
        sig2 = Signal(
            id="recent_default",
            symbol="000002",
            timestamp=frozen_time.now(),
        )
        db.save_signal(sig2)

        results = db.get_recent_signals()
        assert len(results) == 2

    def test_recent_signals_none(self, db, frozen_time):
        frozen_time.advance(hours=5)
        sig = Signal(id="old", symbol="000001", timestamp=frozen_time.now())
        db.save_signal(sig)
        frozen_time.advance(hours=2)

        results = db.get_recent_signals(minutes=60)
        assert len(results) == 0


# ───────────────────────── get_statistics ─────────────────────────

class TestGetStatistics:
    def test_empty_stats(self, db):
        stats = db.get_statistics()
        assert stats["total"] == 0
        assert stats["by_source"] == {}
        assert stats["by_type"] == {}
        assert stats["average_confidence"] == 0.0
        assert stats["unique_symbols"] == 0

    def test_stats(self, db, sample_signal, sample_signal_2, sample_signal_3):
        db.save_signal(sample_signal)
        db.save_signal(sample_signal_2)
        db.save_signal(sample_signal_3)

        stats = db.get_statistics()
        assert stats["total"] == 3
        assert stats["by_source"]["indicator"] == 2
        assert stats["by_source"]["wyckoff"] == 1
        assert stats["by_type"]["trend_bullish"] == 1
        assert stats["by_type"]["trend_bearish"] == 1
        assert stats["by_type"]["volume_surge"] == 1
        assert stats["average_confidence"] == pytest.approx(round((0.85 + 0.3 + 0.6) / 3, 4), abs=1e-4)
        assert stats["unique_symbols"] == 2

    def test_stats_after_delete(self, db, sample_signal, sample_signal_2):
        db.save_signal(sample_signal)
        db.save_signal(sample_signal_2)
        deleted = db.delete_old(datetime(2024, 1, 1))
        assert deleted == 0
        stats = db.get_statistics()
        assert stats["total"] == 2


# ───────────────────────── delete_old ─────────────────────────

class TestDeleteOld:
    def test_delete_old(self, db, frozen_time):
        sig_old = Signal(
            id="old_sig",
            symbol="000001",
            timestamp=frozen_time.now() - timedelta(days=10),
        )
        sig_new = Signal(
            id="new_sig",
            symbol="000002",
            timestamp=frozen_time.now(),
        )
        db.save_signal(sig_old)
        db.save_signal(sig_new)

        deleted = db.delete_old(frozen_time.now() - timedelta(days=5))
        assert deleted == 1

        assert db.get_by_id("old_sig") is None
        assert db.get_by_id("new_sig") is not None

    def test_delete_old_none(self, db, frozen_time):
        sig = Signal(
            id="recent",
            symbol="000001",
            timestamp=frozen_time.now(),
        )
        db.save_signal(sig)
        deleted = db.delete_old(frozen_time.now() - timedelta(hours=1))
        assert deleted == 0

    def test_delete_old_all(self, db, frozen_time):
        for i in range(3):
            sig = Signal(
                id=f"old_{i}",
                symbol="000001",
                timestamp=frozen_time.now() - timedelta(days=30),
            )
            db.save_signal(sig)
        deleted = db.delete_old(frozen_time.now())
        assert deleted == 3
        stats = db.get_statistics()
        assert stats["total"] == 0


# ───────────────────────── Error handling ─────────────────────────

class TestErrorHandling:
    def test_to_signal_bad_json(self, db, sample_signal):
        db.save_signal(sample_signal)
        with db._get_session() as session:
            record = session.get(SignalRecord, sample_signal.id)
            record.metadata_json = "{invalid json}"
            session.commit()
        retrieved = db.get_by_id(sample_signal.id)
        assert retrieved is not None
        assert retrieved.metadata == {}

    def test_to_signal_type_nonexistent(self, db, sample_signal):
        db.save_signal(sample_signal)
        with db._get_session() as session:
            record = session.get(SignalRecord, sample_signal.id)
            record.signal_type = "nonexistent_type"
            session.commit()
        retrieved = db.get_by_id(sample_signal.id)
        assert retrieved is not None
        assert retrieved.signal_type == SignalType.TREND_NEUTRAL

    def test_to_signal_source_nonexistent(self, db, sample_signal):
        db.save_signal(sample_signal)
        with db._get_session() as session:
            record = session.get(SignalRecord, sample_signal.id)
            record.source = "nonexistent_source"
            session.commit()
        retrieved = db.get_by_id(sample_signal.id)
        assert retrieved is not None
        assert retrieved.source == SignalSource.INDICATOR

    def test_to_signal_strength_nonexistent(self, db, sample_signal):
        db.save_signal(sample_signal)
        with db._get_session() as session:
            record = session.get(SignalRecord, sample_signal.id)
            record.strength = 999
            session.commit()
        retrieved = db.get_by_id(sample_signal.id)
        assert retrieved is not None
        assert retrieved.strength == SignalStrength.MODERATE

    def test_metadata_none(self, db, sample_signal):
        db.save_signal(sample_signal)
        with db._get_session() as session:
            record = session.get(SignalRecord, sample_signal.id)
            record.metadata_json = None
            session.commit()
        retrieved = db.get_by_id(sample_signal.id)
        assert retrieved is not None
        assert retrieved.metadata == {}

    def test_metadata_empty_string(self, db, sample_signal):
        db.save_signal(sample_signal)
        with db._get_session() as session:
            record = session.get(SignalRecord, sample_signal.id)
            record.metadata_json = ""
            session.commit()
        retrieved = db.get_by_id(sample_signal.id)
        assert retrieved is not None
        assert retrieved.metadata == {}

    def test_metadata_invalid_json(self, db, sample_signal):
        db.save_signal(sample_signal)
        with db._get_session() as session:
            record = session.get(SignalRecord, sample_signal.id)
            record.metadata_json = "{broken}"
            session.commit()
        retrieved = db.get_by_id(sample_signal.id)
        assert retrieved is not None
        assert retrieved.metadata == {}