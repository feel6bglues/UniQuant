"""信号持久化

使用 SQLAlchemy 实现信号的关系数据库存储，默认 SQLite。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .models import Signal, SignalBatch, SignalSource, SignalStrength, SignalType


# 延迟导入 SQLAlchemy，允许在未安装时优雅降级
try:
    from sqlalchemy import (
        Column,
        DateTime,
        Float,
        Integer,
        String,
        Text,
        create_engine,
        func,
    )
    from sqlalchemy.orm import Session, declarative_base, sessionmaker

    Base = declarative_base()
    _SQLA_AVAILABLE = True
except ImportError:
    Base = None  # type: ignore[assignment]
    _SQLA_AVAILABLE = False


# ───────────────────────── ORM 模型 ─────────────────────────

if _SQLA_AVAILABLE:

    class SignalRecord(Base):  # type: ignore[no-redef]
        """信号 ORM 模型，映射到 signals 表"""
        __tablename__ = "signals"

        id = Column(String(64), primary_key=True)
        symbol = Column(String(32), index=True, nullable=False, default="")
        signal_type = Column(String(64), nullable=False)
        source = Column(String(32), nullable=False)
        direction = Column(Integer, nullable=False, default=0)
        strength = Column(Integer, nullable=False, default=2)
        confidence = Column(Float, nullable=False, default=0.5)
        timestamp = Column(DateTime, index=True, nullable=False)
        expiration = Column(DateTime, nullable=True)
        price = Column(Float, nullable=False, default=0.0)
        value = Column(Float, nullable=False, default=0.0)
        metadata_json = Column(Text, nullable=True)
        parent_id = Column(String(64), nullable=True)

        def to_signal(self) -> Signal:
            """转换为 Signal 数据类"""
            meta = json.loads(self.metadata_json) if self.metadata_json else {}
            return Signal(
                id=self.id,
                symbol=self.symbol,
                signal_type=SignalType(self.signal_type),
                source=SignalSource(self.source),
                direction=self.direction,
                strength=SignalStrength(self.strength),
                confidence=self.confidence,
                timestamp=self.timestamp,
                expiration=self.expiration,
                price=self.price,
                value=self.value,
                metadata=meta,
                parent_id=self.parent_id,
            )

        @classmethod
        def from_signal(cls, signal: Signal) -> SignalRecord:
            """从 Signal 数据类创建"""
            return cls(
                id=signal.id,
                symbol=signal.symbol,
                signal_type=signal.signal_type.value,
                source=signal.source.value,
                direction=signal.direction,
                strength=signal.strength.value,
                confidence=signal.confidence,
                timestamp=signal.timestamp,
                expiration=signal.expiration,
                price=signal.price,
                value=signal.value,
                metadata_json=json.dumps(signal.metadata, ensure_ascii=False, default=str),
                parent_id=signal.parent_id,
            )


# ───────────────────────── 信号数据库 ─────────────────────────

class SignalDatabase:
    """信号持久化数据库

    默认使用 SQLite，可通过 connection_string 切换到其他数据库。

    Args:
        connection_string: 数据库连接字符串
    """

    def __init__(self, connection_string: str = "sqlite:///signals.db") -> None:
        if not _SQLA_AVAILABLE:
            raise ImportError(
                "SQLAlchemy 未安装，请执行: pip install sqlalchemy"
            )
        self._engine = create_engine(connection_string, echo=False)
        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(bind=self._engine)

    def _get_session(self) -> Session:
        return self._session_factory()

    def save_signal(self, signal: Signal) -> str:
        """保存单个信号

        Args:
            signal: 待保存的信号

        Returns:
            信号 ID
        """
        with self._get_session() as session:
            record = SignalRecord.from_signal(signal)
            session.merge(record)
            session.commit()
            return signal.id

    def save_batch(self, batch: SignalBatch) -> List[str]:
        """批量保存 SignalBatch

        Args:
            batch: 待保存的信号批次

        Returns:
            信号 ID 列表
        """
        ids: List[str] = []
        with self._get_session() as session:
            for signal in batch:
                record = SignalRecord.from_signal(signal)
                session.merge(record)
                ids.append(signal.id)
            session.commit()
        return ids

    def get_by_id(self, signal_id: str) -> Optional[Signal]:
        """按 ID 查询

        Args:
            signal_id: 信号 ID

        Returns:
            信号对象，不存在返回 None
        """
        with self._get_session() as session:
            record = session.get(SignalRecord, signal_id)
            return record.to_signal() if record else None

    def query_by_symbol(
        self,
        symbol: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[Signal]:
        """按证券代码查询，按时间倒序

        Args:
            symbol: 证券代码
            start: 起始时间
            end: 结束时间
            limit: 返回条数上限

        Returns:
            信号列表
        """
        with self._get_session() as session:
            q = session.query(SignalRecord).filter(SignalRecord.symbol == symbol)
            if start is not None:
                q = q.filter(SignalRecord.timestamp >= start)
            if end is not None:
                q = q.filter(SignalRecord.timestamp <= end)
            records = q.order_by(SignalRecord.timestamp.desc()).limit(limit).all()
            return [r.to_signal() for r in records]

    def query_by_source(
        self,
        source: SignalSource,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Signal]:
        """按信号来源查询

        Args:
            source: 信号来源
            start: 起始时间
            end: 结束时间
            limit: 返回条数上限

        Returns:
            信号列表
        """
        with self._get_session() as session:
            q = session.query(SignalRecord).filter(SignalRecord.source == source.value)
            if start is not None:
                q = q.filter(SignalRecord.timestamp >= start)
            if end is not None:
                q = q.filter(SignalRecord.timestamp <= end)
            records = q.order_by(SignalRecord.timestamp.desc()).limit(limit).all()
            return [r.to_signal() for r in records]

    def query_by_type(
        self,
        signal_type: SignalType,
        limit: int = 100,
    ) -> List[Signal]:
        """按信号类型查询

        Args:
            signal_type: 信号类型
            limit: 返回条数上限

        Returns:
            信号列表
        """
        with self._get_session() as session:
            records = (
                session.query(SignalRecord)
                .filter(SignalRecord.signal_type == signal_type.value)
                .order_by(SignalRecord.timestamp.desc())
                .limit(limit)
                .all()
            )
            return [r.to_signal() for r in records]

    def get_recent_signals(self, minutes: int = 60) -> List[Signal]:
        """获取最近 N 分钟内的信号

        Args:
            minutes: 时间范围（分钟）

        Returns:
            信号列表
        """
        cutoff = datetime.now() - timedelta(minutes=minutes)
        with self._get_session() as session:
            records = (
                session.query(SignalRecord)
                .filter(SignalRecord.timestamp >= cutoff)
                .order_by(SignalRecord.timestamp.desc())
                .all()
            )
            return [r.to_signal() for r in records]

    def get_statistics(self) -> Dict[str, Any]:
        """统计信息

        Returns:
            包含总数、按来源/类型分布、平均置信度、唯一证券数的统计字典
        """
        with self._get_session() as session:
            total = session.query(func.count(SignalRecord.id)).scalar() or 0
            avg_conf = session.query(func.avg(SignalRecord.confidence)).scalar() or 0.0
            unique_symbols = session.query(func.count(func.distinct(SignalRecord.symbol))).scalar() or 0

            # 按来源分布
            source_rows = (
                session.query(SignalRecord.source, func.count(SignalRecord.id))
                .group_by(SignalRecord.source)
                .all()
            )
            by_source = {row[0]: row[1] for row in source_rows}

            # 按类型分布
            type_rows = (
                session.query(SignalRecord.signal_type, func.count(SignalRecord.id))
                .group_by(SignalRecord.signal_type)
                .all()
            )
            by_type = {row[0]: row[1] for row in type_rows}

            return {
                "total": total,
                "by_source": by_source,
                "by_type": by_type,
                "average_confidence": round(float(avg_conf), 4),
                "unique_symbols": unique_symbols,
            }

    def delete_old(self, before: datetime) -> int:
        """删除指定时间之前的旧信号

        Args:
            before: 时间阈值

        Returns:
            删除的记录数
        """
        with self._get_session() as session:
            count = (
                session.query(SignalRecord)
                .filter(SignalRecord.timestamp < before)
                .delete()
            )
            session.commit()
            return count
