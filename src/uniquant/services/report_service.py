from typing import Any, Dict
from ..shared.logger_factory import get_logger

logger = get_logger(__name__)


class ReportService:
    def generate_report(self, result: Dict[str, Any], symbol: str) -> str:
        logger.info("Generating report for %s", symbol)
        return f"Report for {symbol}: OK"
