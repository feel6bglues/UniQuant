from pathlib import Path
from typing import Optional

import yaml


def load_strategy_weights(config_path: Optional[str] = None) -> Optional[dict]:
    if config_path is None:
        p = Path(__file__).resolve().parents[2] / "config" / "trading.yaml"
    else:
        p = Path(config_path)
    if not p.exists():
        return None
    with open(p) as f:
        cfg = yaml.safe_load(f)
    return cfg.get("strategy_weights")
