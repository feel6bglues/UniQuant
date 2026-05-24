import importlib
from typing import Any, Dict

from uniquant.shared.logger_factory import get_logger

logger = get_logger(__name__)

MODULE_LOAD_ERRORS = (
    AttributeError,
    ImportError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)


class ModuleHealthChecker:
    """
    Checker for 100% Sovereign V1.0 Module Integrity.
    Verifies that core engines (Brain, Risk, Data) are functional.
    """

    @staticmethod
    def check_all() -> Dict[str, bool]:
        """Check status of all critical V1.0 sub-systems."""
        modules = {
            "FSM Engine": "uniquant.brain.fsm",
            "CZSC Engine": "uniquant.brain.czsc.czsc_engine",
            "LPPL Engine": "uniquant.brain.lppl.engine",
            "LRD Engine": "uniquant.brain.regime.regime_detector",
            "NTF Engine": "uniquant.brain.ntf.ntf_engine",
            "EVT Risk": "uniquant.risk.evt_risk",
            "Data Fetcher": "uniquant.data.data_fetcher",
            "Storage Manager": "uniquant.data.lake.storage_manager",
        }

        status = {}
        for name, path in modules.items():
            try:
                module = importlib.import_module(path)
                logger.info(f"Module {name} ({path}) loaded successfully")
                status[name] = True
            except ImportError as e:
                logger.error(f"Module {name} ({path}) failure: {e}")
                status[name] = False
            except MODULE_LOAD_ERRORS as e:
                logger.error(f"Module {name} ({path}) unexpected failure: {e}")
                status[name] = False
        return status
