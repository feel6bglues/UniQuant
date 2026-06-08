import datetime
import json
from typing import Dict, List, Any

import pandas as pd

from ..shared.config_loader import get_config
from ..shared.logger_factory import get_logger
from .data_service import DataService
from .analysis_service_legacy import AnalysisService
from ..brain.fsm import DecisionBrain
from ..risk.evt_risk import HistoricalSimulationRisk as EVTRisk
from ..risk.sizer import PositionSizer


RECOVERABLE_ERRORS = (
    AttributeError,
    ImportError,
    KeyError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)

logger = get_logger("HealthService")


class HealthService:
    """
    Health monitoring service for Alpha-Tactician
    Provides comprehensive health checks and monitoring endpoints
    """

    def __init__(self):
        """
        Initialize health service
        """
        self.config = get_config()
        self.data_service = DataService()
        self.analysis_service = AnalysisService(self.data_service)
        self.evt_risk = EVTRisk()
        self.sizer = PositionSizer()
        self.brain = DecisionBrain(evt_risk=self.evt_risk, sizer=self.sizer)

        self.health_check_history = []
        self.max_history_size = 100

    def get_system_health(self) -> Dict[str, Any]:
        """
        Get comprehensive system health status

        Returns:
            Dict[str, Any]: System health status
        """
        try:
            health_status: Dict[str, Any] = {
                "timestamp": datetime.datetime.now().isoformat(),
                "overall_status": "healthy",
                "components": {
                    "config": self._check_config_health(),
                    "data_service": self._check_data_service_health(),
                    "analysis_service": self._check_analysis_service_health(),
                    "brain": self._check_brain_health(),
                    "risk": self._check_risk_health(),
                    "cache": self._check_cache_health(),
                    "data_lake": self._check_data_lake_health(),
                    "system": self._check_system_health(),
                },
                "metrics": self._get_system_metrics(),
                "recommendations": self._get_health_recommendations(),
            }

            # Determine overall status
            components: Dict[str, Any] = health_status["components"]
            for component, status in components.items():
                if status["status"] != "healthy":
                    health_status["overall_status"] = "unhealthy"
                    break

            # Add to history
            self._add_to_history(health_status)

            logger.info(
                f"System health check completed with status: {health_status['overall_status']}"
            )
            return health_status
        except RECOVERABLE_ERRORS as e:
            logger.error(f"Error getting system health: {e}")
            return {
                "timestamp": datetime.datetime.now().isoformat(),
                "overall_status": "error",
                "error": str(e),
            }

    def _check_config_health(self) -> Dict[str, Any]:
        """
        Check configuration health
        """
        try:
            # Check config validation
            validation_result = self.config.validate_config()

            # Check brain config
            brain_config = self.config.get("brain")

            return {
                "status": "healthy" if validation_result else "unhealthy",
                "details": {
                    "validation_passed": validation_result,
                    "brain_config_loaded": brain_config is not None,
                    "config_sections": list(self.config._config.keys()),
                },
            }
        except RECOVERABLE_ERRORS as e:
            logger.error(f"Error checking config health: {e}")
            return {"status": "unhealthy", "error": str(e)}

    def _check_data_service_health(self) -> Dict[str, Any]:
        """
        Check data service health
        """
        try:
            # Test data service functionality
            test_stock = "601339"
            test_data = self.data_service.fetch_data(test_stock, "20230101", "20230131")

            # Check cache health
            cache_stats = self.data_service.cache_manager.get_stats()

            return {
                "status": "healthy" if test_data is not None else "unhealthy",
                "details": {
                    "data_fetched": test_data is not None,
                    "data_shape": test_data.shape if test_data is not None else None,
                    "cache_stats": cache_stats,
                },
            }
        except RECOVERABLE_ERRORS as e:
            logger.error(f"Error checking data service health: {e}")
            return {"status": "unhealthy", "error": str(e)}

    def _check_analysis_service_health(self) -> Dict[str, Any]:
        """
        Check analysis service health
        """
        try:
            # Test macro health analysis
            macro_health = self.analysis_service.analyze_macro_health()

            return {
                "status": "healthy" if isinstance(macro_health, dict) else "unhealthy",
                "details": {
                    "macro_health_analyzed": isinstance(macro_health, dict),
                    "risk_metrics_calculated": (
                        "var_95" in macro_health
                        if isinstance(macro_health, dict)
                        else False
                    ),
                },
            }
        except RECOVERABLE_ERRORS as e:
            logger.error(f"Error checking analysis service health: {e}")
            return {"status": "unhealthy", "error": str(e)}

    def _check_brain_health(self) -> Dict[str, Any]:
        """
        Check brain health
        """
        try:
            # Test brain functionality
            test_stock = "601339"
            data_pack = self.data_service.fetch_for_brain(test_stock)

            if data_pack and "stock" in data_pack and not data_pack["stock"].empty:
                decision = self.brain.make_decision(data_pack)
                return {
                    "status": "healthy" if isinstance(decision, dict) else "unhealthy",
                    "details": {
                        "decision_made": isinstance(decision, dict),
                        "action_in_decision": (
                            "action" in decision
                            if isinstance(decision, dict)
                            else False
                        ),
                    },
                }
            else:
                return {
                    "status": "degraded",
                    "details": {
                        "data_available": False,
                        "reason": "No data available for brain test",
                    },
                }
        except RECOVERABLE_ERRORS as e:
            logger.error(f"Error checking brain health: {e}")
            return {"status": "unhealthy", "error": str(e)}

    def _check_risk_health(self) -> Dict[str, Any]:
        """
        Check risk service health
        """
        try:
            # Test EVT risk calculation
            test_returns = pd.Series([0.01, -0.02, 0.03, -0.01, 0.02])
            risk_metrics = self.evt_risk.calculate_metrics(test_returns)

            return {
                "status": "healthy" if isinstance(risk_metrics, dict) else "unhealthy",
                "details": {
                    "risk_metrics_calculated": isinstance(risk_metrics, dict),
                    "var_calculated": (
                        "var_q" in risk_metrics
                        if isinstance(risk_metrics, dict)
                        else False
                    ),
                },
            }
        except RECOVERABLE_ERRORS as e:
            logger.error(f"Error checking risk health: {e}")
            return {"status": "unhealthy", "error": str(e)}

    def _check_cache_health(self) -> Dict[str, Any]:
        """
        Check cache health
        """
        try:
            # Check cache manager health
            cache_stats = self.data_service.cache_manager.get_stats()

            return {
                "status": "healthy",
                "details": {"cache_enabled": True, "cache_stats": cache_stats},
            }
        except RECOVERABLE_ERRORS as e:
            logger.error(f"Error checking cache health: {e}")
            return {"status": "unhealthy", "error": str(e)}

    def _check_data_lake_health(self) -> Dict[str, Any]:
        """
        Check data lake health
        """
        try:
            # Check data lake directory
            lake_dir = self.config.LAKE_DIR
            lake_dir.exists()

            # Check data files
            data_files = self.data_service.list_data_files()

            return {
                "status": "healthy",
                "details": {
                    "lake_dir_exists": lake_dir.exists(),
                    "data_files_count": len(data_files),
                },
            }
        except RECOVERABLE_ERRORS as e:
            logger.error(f"Error checking data lake health: {e}")
            return {"status": "unhealthy", "error": str(e)}

    def _check_system_health(self) -> Dict[str, Any]:
        """
        Check system health
        """
        try:
            # Check system resources
            import psutil

            cpu_percent = psutil.cpu_percent()
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage(".")

            return {
                "status": "healthy",
                "details": {
                    "cpu_usage": cpu_percent,
                    "memory_usage": memory.percent,
                    "disk_usage": disk.percent,
                },
            }
        except ImportError:
            # psutil not installed, return basic info
            return {"status": "healthy", "details": {"psutil_not_installed": True}}
        except RECOVERABLE_ERRORS as e:
            logger.error(f"Error checking system health: {e}")
            return {"status": "unhealthy", "error": str(e)}

    def _get_system_metrics(self) -> Dict[str, Any]:
        """
        Get system metrics
        """
        try:
            return {
                "timestamp": datetime.datetime.now().isoformat(),
                "uptime": self._get_uptime(),
                "health_check_history": len(self.health_check_history),
                "config_count": len(self.config._config),
                "cache_size": self.data_service.cache_manager.get_stats().get(
                    "total_items", 0
                ),
            }
        except RECOVERABLE_ERRORS as e:
            logger.error(f"Error getting system metrics: {e}")
            return {"error": str(e)}

    def _get_uptime(self) -> str:
        """
        Get system uptime
        """
        try:
            import psutil

            boot_time = psutil.boot_time()
            uptime_seconds = datetime.datetime.now().timestamp() - boot_time
            uptime_hours = uptime_seconds / 3600
            return f"{uptime_hours:.2f} hours"
        except (ImportError, OSError):
            return "Unknown"

    def _get_health_recommendations(self) -> List[str]:
        """
        Get health recommendations based on system status
        """
        recommendations = []

        try:
            # Check config
            if not self.config.get("brain"):
                recommendations.append(
                    "Create brain.yaml config file for optimized strategy parameters"
                )

            # Check data
            data_files_count = len(self.data_service.list_data_files())
            if data_files_count < 10:
                recommendations.append(
                    "Download more historical data for better analysis"
                )

            # Check cache
            cache_size = self.data_service.cache_manager.get_stats().get(
                "total_items", 0
            )
            if cache_size == 0:
                recommendations.append(
                    "Cache is empty, consider preloading frequently used data"
                )

            # Check system resources
            try:
                import psutil

                memory = psutil.virtual_memory()
                if memory.percent > 80:
                    recommendations.append(
                        "High memory usage detected, consider optimizing memory usage"
                    )
                disk = psutil.disk_usage(".")
                if disk.percent > 80:
                    recommendations.append(
                        "Low disk space detected, consider cleaning up old data"
                    )
            except (ImportError, OSError):
                logger.exception("检查磁盘空间失败，跳过")
                pass

            if not recommendations:
                recommendations.append("System health is optimal")

        except RECOVERABLE_ERRORS as e:
            logger.error(f"Error getting health recommendations: {e}")
            recommendations.append("Error generating recommendations")

        return recommendations

    def _add_to_history(self, health_status: Dict[str, Any]):
        """
        Add health check to history
        """
        try:
            self.health_check_history.append(health_status)
            # Limit history size
            if len(self.health_check_history) > self.max_history_size:
                self.health_check_history.pop(0)
        except RECOVERABLE_ERRORS as e:
            logger.error(f"Error adding to health history: {e}")

    def get_health_history(self) -> List[Dict[str, Any]]:
        """
        Get health check history

        Returns:
            List[Dict[str, Any]]: Health check history
        """
        return self.health_check_history

    def get_health_summary(self) -> Dict[str, Any]:
        """
        Get health summary

        Returns:
            Dict[str, Any]: Health summary
        """
        try:
            if not self.health_check_history:
                return {"error": "No health check history available"}

            latest_health = self.health_check_history[-1]

            # Calculate health trends
            status_counts: Dict[str, int] = {}
            for check in self.health_check_history:
                status = check.get("overall_status", "unknown")
                status_counts[status] = status_counts.get(status, 0) + 1

            return {
                "latest_status": latest_health.get("overall_status"),
                "status_trend": status_counts,
                "check_count": len(self.health_check_history),
                "latest_check": latest_health.get("timestamp"),
                "components_status": {
                    k: v["status"]
                    for k, v in latest_health.get("components", {}).items()
                },
            }
        except RECOVERABLE_ERRORS as e:
            logger.error(f"Error getting health summary: {e}")
            return {"error": str(e)}

    def export_health_report(self, format: str = "json") -> str:
        """
        Export health report

        Args:
            format: Export format (json or txt)

        Returns:
            str: Exported report content
        """
        try:
            health_status = self.get_system_health()

            if format == "json":
                return json.dumps(health_status, ensure_ascii=False, indent=2)
            elif format == "txt":
                report = "Alpha-Tactician Health Report\n"
                report += f"Timestamp: {health_status.get('timestamp')}\n"
                report += f"Overall Status: {health_status.get('overall_status')}\n\n"

                report += "Components:\n"
                for component, status in health_status.get("components", {}).items():
                    report += f"  {component}: {status.get('status')}\n"

                report += "\nMetrics:\n"
                for metric, value in health_status.get("metrics", {}).items():
                    report += f"  {metric}: {value}\n"

                report += "\nRecommendations:\n"
                for recommendation in health_status.get("recommendations", []):
                    report += f"  - {recommendation}\n"

                return report
            else:
                return f"Unsupported format: {format}"
        except RECOVERABLE_ERRORS as e:
            logger.error(f"Error exporting health report: {e}")
            return f"Error exporting report: {str(e)}"

    def save_health_report(self, file_path: str, format: str = "json") -> bool:
        """
        Save health report to file

        Args:
            file_path: File path to save report
            format: Export format (json or txt)

        Returns:
            bool: True if saved successfully
        """
        try:
            report_content = self.export_health_report(format)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(report_content)
            logger.info(f"Health report saved to {file_path}")
            return True
        except RECOVERABLE_ERRORS as e:
            logger.error(f"Error saving health report: {e}")
            return False


# Global health service instance
health_service = None


def get_health_service() -> HealthService:
    """
    Get global health service instance

    Returns:
        HealthService: Health service instance
    """
    global health_service
    if health_service is None:
        health_service = HealthService()
    return health_service
