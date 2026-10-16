"""
QTR-OS Research Control Plane: Degrees of Freedom Ledger persistence.

File: uniquant/research/ledger/ledger_store.py

JSON-backed store so the :class:`DegreesOfFreedomLedger` accumulates trials
across process runs. Cumulative multiple-testing accounting is the entire point
of the ledger — an in-memory-only ledger silently resets ``total_trials`` to 0
on every run, which is exactly the "island" failure mode this module removes.

Writes are atomic (temp file + ``os.replace``) and best-effort: a read/write
failure degrades to a fresh in-memory ledger rather than breaking a scan.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Union

from uniquant.research.ledger.degrees_of_freedom import DegreesOfFreedomLedger
from uniquant.shared.logger_factory import get_logger

logger = get_logger(__name__)


class LedgerStore:
    """Load/save a :class:`DegreesOfFreedomLedger` as a single JSON document."""

    def __init__(self, path: Union[str, Path]) -> None:
        self.path = Path(path)

    def load(self) -> DegreesOfFreedomLedger:
        """Return the persisted ledger, or a fresh one when absent/corrupt."""
        if not self.path.exists():
            return DegreesOfFreedomLedger()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Ledger 读取失败，改用空账本: %s (%s)", self.path, exc)
            return DegreesOfFreedomLedger()
        if not isinstance(raw, dict):
            logger.warning("Ledger 状态格式非法，改用空账本: %s", self.path)
            return DegreesOfFreedomLedger()
        try:
            return DegreesOfFreedomLedger.from_state(raw)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Ledger 状态反序列化失败，改用空账本: %s (%s)", self.path, exc)
            return DegreesOfFreedomLedger()

    def save(self, ledger: DegreesOfFreedomLedger) -> bool:
        """Atomically persist ``ledger``; return True on success."""
        tmp_path: str | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self.path.parent), prefix=self.path.name, suffix=".tmp"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(
                    ledger.to_state(),
                    fh,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
            os.replace(tmp_path, self.path)
            return True
        except OSError as exc:
            logger.warning("Ledger 落盘失败（不影响扫描）: %s (%s)", self.path, exc)
            return False
        finally:
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
