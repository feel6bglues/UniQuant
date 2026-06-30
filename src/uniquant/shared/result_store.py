"""Analysis result persistence for research pipeline."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _json_default(obj: Any) -> str:
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


@dataclass
class AnalysisRecord:
    symbol: str
    analysis_date: date
    regime: Optional[str] = None
    lppl_score: Optional[float] = None
    ntf_detected: Optional[bool] = None
    czsc_signal: Optional[str] = None
    wyckoff_signal: Optional[str] = None
    action: Optional[str] = None
    confidence: Optional[float] = None
    backtest_sharpe: Optional[float] = None
    backtest_return: Optional[float] = None
    backtest_mdd: Optional[float] = None
    metadata: Optional[dict] = None


class ResultStore:
    """Persist analysis results as JSON files under results/{date}/{symbol}.json."""

    def __init__(self, path: str = "./results") -> None:
        self._root = Path(path)

    # ── helpers ──────────────────────────────────────────────

    def _date_dir(self, d: date) -> Path:
        return self._root / d.isoformat()

    def _file_path(self, symbol: str, d: date) -> Path:
        return self._date_dir(d) / f"{symbol}.json"

    # ── public API ───────────────────────────────────────────

    def save(self, symbol: str, record: AnalysisRecord) -> None:
        d = record.analysis_date
        target = self._file_path(symbol, d)
        target.parent.mkdir(parents=True, exist_ok=True)

        data = asdict(record)
        data["analysis_date"] = d.isoformat()

        tmp = tempfile.NamedTemporaryFile(
            mode="w", dir=str(target.parent), suffix=".tmp",
            delete=False, encoding="utf-8",
        )
        try:
            tmp.write(json.dumps(data, default=_json_default, ensure_ascii=False))
            tmp.close()
            os.replace(tmp.name, str(target))
        except BaseException:
            os.unlink(tmp.name)
            raise

    def load(self, symbol: str, analysis_date: date) -> Optional[AnalysisRecord]:
        path = self._file_path(symbol, analysis_date)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return self._dict_to_record(data)

    def load_latest(self, symbol: str) -> Optional[AnalysisRecord]:
        if not self._root.exists():
            return None
        date_dirs = sorted(
            [d for d in self._root.iterdir() if d.is_dir()],
            reverse=True,
        )
        for dd in date_dirs:
            candidate = dd / f"{symbol}.json"
            if candidate.exists():
                try:
                    data = json.loads(candidate.read_text(encoding="utf-8"))
                    return self._dict_to_record(data)
                except Exception:
                    continue
        return None

    def query(self, analysis_date: date) -> List[AnalysisRecord]:
        results: List[AnalysisRecord] = []
        dd = self._date_dir(analysis_date)
        if not dd.exists():
            return results
        for p in sorted(dd.iterdir()):
            if p.suffix != ".json":
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                results.append(self._dict_to_record(data))
            except Exception:
                continue
        return results

    def query_range(self, symbol: str, start: date, end: date) -> List[AnalysisRecord]:
        results: List[AnalysisRecord] = []
        if not self._root.exists():
            return results
        for dd in sorted(self._root.iterdir()):
            if not dd.is_dir():
                continue
            try:
                d = date.fromisoformat(dd.name)
            except ValueError:
                continue
            if d < start or d > end:
                continue
            candidate = dd / f"{symbol}.json"
            if candidate.exists():
                try:
                    data = json.loads(candidate.read_text(encoding="utf-8"))
                    results.append(self._dict_to_record(data))
                except Exception:
                    continue
        return results

    def compare(self, symbol: str, date1: date, date2: date) -> Dict[str, tuple]:
        r1 = self.load(symbol, date1)
        r2 = self.load(symbol, date2)
        if r1 is None or r2 is None:
            return {}
        fields = [
            "regime", "lppl_score", "ntf_detected", "czsc_signal",
            "wyckoff_signal", "action", "confidence",
            "backtest_sharpe", "backtest_return", "backtest_mdd",
        ]
        diff: Dict[str, tuple] = {}
        for f in fields:
            v1 = getattr(r1, f)
            v2 = getattr(r2, f)
            if v1 != v2:
                diff[f] = (v1, v2)
        return diff

    # ── internal ─────────────────────────────────────────────

    @staticmethod
    def _dict_to_record(data: Dict[str, Any]) -> AnalysisRecord:
        ad_str = data.pop("analysis_date", None)
        if ad_str:
            data["analysis_date"] = date.fromisoformat(ad_str)
        return AnalysisRecord(**data)
