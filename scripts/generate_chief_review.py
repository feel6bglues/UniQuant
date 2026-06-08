import json
from pathlib import Path
from typing import Any, Dict


RESULTS_DIR: str = "data/results"


def analyze_single_date_folder(date_str: str) -> Dict[str, Any]:
    results_dir = Path(RESULTS_DIR)
    date_path = results_dir / date_str

    stats: Dict[str, Any] = {
        "parsed_count": 0,
        "decisions": {},
        "regimes": {},
        "lppl_risks": {},
        "ntf_sides": {},
        "czsc_3buy_count": 0,
        "trend_bullish": 0,
        "macd_golden_cross": 0,
        "rsi_oversold": 0,
        "volume_surge": 0,
    }

    if not date_path.is_dir():
        return stats

    for json_file in sorted(date_path.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        stats["parsed_count"] += 1

        decision = data.get("decision_result", {}).get("final_decision")
        if decision:
            stats["decisions"][decision] = stats["decisions"].get(decision, 0) + 1

        data_pack = data.get("data_pack", {})

        regime = data_pack.get("regime")
        if regime:
            stats["regimes"][regime] = stats["regimes"].get(regime, 0) + 1

        risk = data_pack.get("risk")
        if risk:
            stats["lppl_risks"][risk] = stats["lppl_risks"].get(risk, 0) + 1

        ntf_side = data_pack.get("ntf_side")
        if ntf_side:
            stats["ntf_sides"][ntf_side] = stats["ntf_sides"].get(ntf_side, 0) + 1

        if data_pack.get("is_3rd_buy"):
            stats["czsc_3buy_count"] += 1

        ma_status = data_pack.get("ma_status", "")
        if "MA20 > MA60" in ma_status or "bullish" in ma_status.lower():
            stats["trend_bullish"] += 1

        indicators = data_pack.get("indicators", {})
        macd = indicators.get("macd")
        macd_signal = indicators.get("macd_signal")
        if macd is not None and macd_signal is not None and macd > macd_signal:
            stats["macd_golden_cross"] += 1

        rsi = indicators.get("rsi")
        if rsi is not None and rsi < 30:
            stats["rsi_oversold"] += 1

        vol_ratio = indicators.get("vol_ratio")
        if vol_ratio is not None and vol_ratio > 1.5:
            stats["volume_surge"] += 1

    return stats
