from pathlib import Path
from typing import Optional

import yaml

from uniquant.shared.constants.path import PROJECT_ROOT


def load_strategy_weights(config_path: Optional[str] = None) -> Optional[dict]:
    if config_path is None:
        # 第八轮修复: 原为 `Path(__file__).resolve().parents[2]`，本文件位于
        # src/uniquant/shared/，parents[2] 指向 src/ 而非仓库根，解析出的
        # src/config/trading.yaml 不存在 → 静默返回 None（策略权重从未被加载）。
        p = PROJECT_ROOT / "config" / "trading.yaml"
    else:
        p = Path(config_path)
    if not p.exists():
        return None
    with open(p) as f:
        cfg = yaml.safe_load(f)
    return cfg.get("strategy_weights")
