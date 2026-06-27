from typing import Any, Dict

from ...shared.interfaces import (
    AlphaOutput,
    CZSCOutput,
    LPPLOutput,
    NtfOutput,
    RegimeOutput,
    ResearchDataPack,
    WyckoffOutput,
)


class DictPackWriter:
    @staticmethod
    def get_stock_df(data_pack: Dict[str, Any]):
        return data_pack.get("stock")

    @staticmethod
    def get_symbol(data_pack: Dict[str, Any]) -> str:
        return data_pack.get("symbol", "unknown")

    @staticmethod
    def write_regime(data_pack: Dict[str, Any], output: RegimeOutput) -> None:
        data_pack["regime_output"] = output
        data_pack["regime"] = output.regime
        data_pack["entropy"] = output.entropy
        data_pack["turnover_z"] = output.turnover_z

    @staticmethod
    def write_lppl(data_pack: Dict[str, Any], output: LPPLOutput) -> None:
        data_pack["lppl_output"] = output
        data_pack["risk"] = output.risk_level
        data_pack["bubble_confidence"] = output.confidence

    @staticmethod
    def write_ntf(data_pack: Dict[str, Any], output: NtfOutput, action: str = "") -> None:
        data_pack["ntf_output"] = output
        data_pack["ntf_side"] = output.side
        data_pack["ntf_intensity"] = output.intensity
        data_pack["ntf_action"] = action

    @staticmethod
    def write_czsc(data_pack: Dict[str, Any], output: CZSCOutput) -> None:
        data_pack["czsc_output"] = output
        data_pack["is_3rd_buy"] = output.is_3rd_buy
        data_pack["bi_count"] = output.bi_count

    @staticmethod
    def write_wyckoff(data_pack: Dict[str, Any], output: WyckoffOutput) -> None:
        data_pack["wyckoff_output"] = output
        data_pack["wyckoff_phase"] = output.phase
        data_pack["wyckoff_confidence"] = output.confidence
        data_pack["wyckoff_spring"] = output.spring
        data_pack["wyckoff_utad"] = output.utad
        data_pack["rr_ratio"] = output.rr_ratio
        data_pack["bypassed"] = output.bypassed

    @staticmethod
    def write_alpha(data_pack: Dict[str, Any], output: AlphaOutput) -> None:
        data_pack["alpha_output"] = output
        data_pack["alpha_score"] = output.score

    @staticmethod
    def mark_engine_status(
        data_pack: Dict[str, Any],
        engine_name: str,
        status: str,
        error: str | None = None,
    ) -> None:
        data_pack.setdefault("engine_status", {})[engine_name] = status
        if error:
            data_pack.setdefault("engine_errors", {})[engine_name] = error


class RDPackWriter:
    @staticmethod
    def get_stock_df(data_pack: ResearchDataPack):
        return data_pack.stock_df

    @staticmethod
    def get_symbol(data_pack: ResearchDataPack) -> str:
        return data_pack.symbol

    @staticmethod
    def write_regime(data_pack: ResearchDataPack, output: RegimeOutput) -> None:
        data_pack.regime = output
        data_pack.metadata["regime"] = output.regime
        data_pack.metadata["entropy"] = output.entropy
        data_pack.metadata["turnover_z"] = output.turnover_z

    @staticmethod
    def write_lppl(data_pack: ResearchDataPack, output: LPPLOutput) -> None:
        data_pack.lppl = output
        data_pack.metadata["risk"] = output.risk_level
        data_pack.metadata["bubble_confidence"] = output.confidence

    @staticmethod
    def write_ntf(data_pack: ResearchDataPack, output: NtfOutput, action: str = "") -> None:
        data_pack.ntf = output
        data_pack.metadata["ntf_side"] = output.side
        data_pack.metadata["ntf_intensity"] = output.intensity
        data_pack.metadata["ntf_action"] = action

    @staticmethod
    def write_czsc(data_pack: ResearchDataPack, output: CZSCOutput) -> None:
        data_pack.czsc = output
        data_pack.metadata["is_3rd_buy"] = output.is_3rd_buy
        data_pack.metadata["bi_count"] = output.bi_count

    @staticmethod
    def write_wyckoff(data_pack: ResearchDataPack, output: WyckoffOutput) -> None:
        data_pack.wyckoff = output
        data_pack.metadata["wyckoff_phase"] = output.phase
        data_pack.metadata["wyckoff_confidence"] = output.confidence
        data_pack.metadata["wyckoff_spring"] = output.spring
        data_pack.metadata["wyckoff_utad"] = output.utad
        data_pack.metadata["rr_ratio"] = output.rr_ratio
        data_pack.metadata["bypassed"] = output.bypassed

    @staticmethod
    def write_alpha(data_pack: ResearchDataPack, output: AlphaOutput) -> None:
        data_pack.alpha = output
        data_pack.metadata["alpha_score"] = output.score

    @staticmethod
    def mark_engine_status(
        data_pack: ResearchDataPack,
        engine_name: str,
        status: str,
        error: str | None = None,
    ) -> None:
        data_pack.metadata.setdefault("engine_status", {})[engine_name] = status
        if error:
            data_pack.metadata.setdefault("engine_errors", {})[engine_name] = error