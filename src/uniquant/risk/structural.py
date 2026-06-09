from typing import Any, Dict

from ..shared.config_loader import config
from ..shared.logger_factory import get_logger

logger = get_logger(__name__)


class StructuralRiskManager:
    """
    Structural Risk Manager for Alpha-Tactician Pro V8.0.
    Implements risk matrix for multiple indices and provides overall risk assessment.
    """

    def __init__(self):
        # Load index names from config, with fallback to defaults
        raw = config.get(
            "markets.indices",
            {
                "000300.SH": "沪深300",
                "000905.SH": "中证500",
                "000852.SH": "中证1000",
                "000016.SH": "上证50",
            },
        )
        if isinstance(raw, list):
            self.index_names = {item["id"]: item["name"] for item in raw}
        else:
            self.index_names = raw

    def get_macro_conclusion(self, overall_risk: str) -> str:
        """
        Get macro conclusion based on overall risk level.

        Args:
            overall_risk: Overall risk level (Safe, Warning, Danger)

        Returns:
            Macro conclusion string
        """
        if overall_risk == "Danger":
            return "宏观环境风险较高，不建议开仓"
        elif overall_risk == "Warning":
            return "宏观环境存在一定风险，建议谨慎开仓"
        else:
            return "宏观环境安全，允许开仓"

    def format_risk_matrix_for_report(
        self, risk_matrix: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Format risk matrix for report generation.

        Args:
            risk_matrix: Raw risk matrix data

        Returns:
            Formatted risk matrix for report
        """
        formatted_matrix = {}

        for index_symbol, risk_info in risk_matrix.items():
            formatted_matrix[index_symbol] = {
                "tc": risk_info.get("tc"),
                "status": risk_info.get("status", "Safe"),
                "note": risk_info.get("note", ""),
            }

        return formatted_matrix

    def get_risk_emoji(self, status: str) -> str:
        """
        Get emoji for risk status.

        Args:
            status: Risk status (Safe, Warning, Danger)

        Returns:
            Emoji string
        """
        if status == "Safe":
            return "🟢"
        elif status == "Warning":
            return "🟡"
        else:
            return "🔴"

    def generate_structural_context(
        self, risk_matrix: Dict[str, Any], overall_risk: str
    ) -> Dict[str, Any]:
        """
        Generate structural context for report.

        Args:
            risk_matrix: Risk matrix data
            overall_risk: Overall risk level

        Returns:
            Structural context dictionary
        """
        return {
            "risk_matrix": risk_matrix,
            "overall_risk": overall_risk,
            "macro_conclusion": self.get_macro_conclusion(overall_risk),
            "index_names": self.index_names,
        }
