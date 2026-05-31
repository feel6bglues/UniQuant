import warnings

from .evt_risk import EVTRisk


class HistoricalSimulationRisk(EVTRisk):
    """
    Historical Simulation based risk calculator.
    Wraps EVTRisk with deprecation notice — use HistoricalSimulationRisk directly.
    """

    def __init__(self):
        super().__init__()
        warnings.warn(
            "EVTRisk is deprecated, use HistoricalSimulationRisk",
            DeprecationWarning,
            stacklevel=2,
        )
