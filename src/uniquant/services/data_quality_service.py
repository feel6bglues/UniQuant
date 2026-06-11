"""
数据质量服务
负责数据质量检查、报告生成和监控
"""
from typing import Any, Dict, List

import pandas as pd

from ..shared.time_provider import get_time_provider
from ..shared.constants import DataServiceConstants
from ..shared.logger_factory import get_logger

logger = get_logger("DataQualityService")

QUALITY_RECOVERABLE_ERRORS = (
    AttributeError,
    KeyError,
    OSError,
    TypeError,
    ValueError,
)


class DataQualityService:
    """
    数据质量服务
    
    职责：
    - 数据质量指标计算（完整性、一致性、时效性、有效性、唯一性）
    - 数据质量报告生成
    - 数据质量监控和告警
    """
    
    def calculate_data_quality(
        self, 
        data: pd.DataFrame, 
        symbol: str, 
        data_type: str = "stock"
    ) -> Dict[str, Any]:
        """
        计算数据质量指标
        
        Args:
            data: 数据DataFrame
            symbol: 证券代码
            data_type: 数据类型
            
        Returns:
            Dict: 数据质量指标
        """
        if data.empty:
            return {
                "symbol": symbol,
                "data_type": data_type,
                "quality_score": 0.0,
                "status": "no_data",
                "metrics": {},
                "timestamp": pd.Timestamp(get_time_provider().now()).strftime("%Y-%m-%d %H:%M:%S"),
            }
        
        metrics = {
            "completeness": self._calculate_completeness(data),
            "consistency": self._calculate_consistency(data),
            "timeliness": self._calculate_timeliness(data),
            "validity": self._calculate_validity(data, data_type),
            "uniqueness": self._calculate_uniqueness(data),
        }
        
        quality_score = sum(metrics.values()) / len(metrics) * 100
        
        if quality_score >= DataServiceConstants.QUALITY_SCORE_EXCELLENT:
            status = "excellent"
        elif quality_score >= DataServiceConstants.QUALITY_SCORE_GOOD:
            status = "good"
        elif quality_score >= DataServiceConstants.QUALITY_SCORE_FAIR:
            status = "fair"
        else:
            status = "poor"
        
        result = {
            "symbol": symbol,
            "data_type": data_type,
            "quality_score": round(quality_score, 2),
            "status": status,
            "metrics": metrics,
            "timestamp": pd.Timestamp(get_time_provider().now()).strftime("%Y-%m-%d %H:%M:%S"),
        }
        
        logger.info("Data quality for %s: %s", symbol, result)
        return result
    
    def _calculate_completeness(self, df: pd.DataFrame) -> float:
        """计算数据完整性 (0-1)"""
        if df.empty:
            return 0.0
        
        total_cells = df.size
        non_null_cells = df.notna().sum().sum()
        
        return non_null_cells / total_cells if total_cells > 0 else 0.0
    
    def _calculate_consistency(self, df: pd.DataFrame) -> float:
        """计算数据一致性 (0-1)"""
        if df.empty:
            return 0.0
        
        consistency_score = 1.0
        
        if all(col in df.columns for col in ["high", "low", "open", "close"]):
            high_low_consistent = (df["high"] >= df["low"]).all()
            if not high_low_consistent:
                consistency_score -= 0.25
            
            price_consistent = (
                (df["high"] >= df["open"])
                & (df["high"] >= df["close"])
                & (df["low"] <= df["open"])
                & (df["low"] <= df["close"])
            ).all()
            if not price_consistent:
                consistency_score -= 0.25
        
        if isinstance(df.index, pd.DatetimeIndex):
            if not df.index.is_monotonic_increasing:
                consistency_score -= 0.25
            
            if df.index.duplicated().any():
                consistency_score -= 0.25
        
        return max(0.0, consistency_score)
    
    def _calculate_timeliness(self, df: pd.DataFrame) -> float:
        """计算数据时效性 (0-1)"""
        if df.empty:
            return 0.0
        
        if isinstance(df.index, pd.DatetimeIndex):
            latest_date = df.index.max()
            today = pd.Timestamp(get_time_provider().now()).normalize()
            days_diff = (today - latest_date).days
            
            if days_diff == 0:
                return DataServiceConstants.TIMELINESS_SCORE_TODAY
            elif days_diff <= DataServiceConstants.TIMELINESS_THRESHOLD_1_DAY:
                return DataServiceConstants.TIMELINESS_SCORE_1_DAY
            elif days_diff <= DataServiceConstants.TIMELINESS_THRESHOLD_3_DAYS:
                return DataServiceConstants.TIMELINESS_SCORE_3_DAYS
            elif days_diff <= DataServiceConstants.TIMELINESS_THRESHOLD_7_DAYS:
                return DataServiceConstants.TIMELINESS_SCORE_7_DAYS
            elif days_diff <= DataServiceConstants.TIMELINESS_THRESHOLD_30_DAYS:
                return DataServiceConstants.TIMELINESS_SCORE_30_DAYS
            else:
                return DataServiceConstants.TIMELINESS_SCORE_OLD
        
        return 0.5
    
    def _calculate_validity(self, df: pd.DataFrame, data_type: str) -> float:
        """计算数据有效性 (0-1)"""
        if df.empty:
            return 0.0
        
        validity_score = 1.0
        
        price_columns = ["open", "high", "low", "close"]
        for col in price_columns:
            if col in df.columns:
                if (df[col] <= 0).any():
                    validity_score -= 0.1
        
        if "volume" in df.columns:
            if (df["volume"] < 0).any():
                validity_score -= 0.1
        
        if "amount" in df.columns:
            if (df["amount"] < 0).any():
                validity_score -= 0.1
        
        return max(0.0, validity_score)
    
    def _calculate_uniqueness(self, df: pd.DataFrame) -> float:
        """计算数据唯一性 (0-1)"""
        if df.empty:
            return 0.0
        
        if df.index.duplicated().any():
            duplicate_ratio = df.index.duplicated().sum() / len(df)
            return max(0.0, 1.0 - duplicate_ratio)
        
        return 1.0
    
    def check_data_health(
        self, 
        data_items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        检查多个数据项的健康状态
        
        Args:
            data_items: 数据项列表，每项包含 data, symbol, data_type
            
        Returns:
            List[Dict]: 数据健康状态列表
        """
        results = []
        for item in data_items:
            quality = self.calculate_data_quality(
                item.get("data", pd.DataFrame()),
                item.get("symbol", ""),
                item.get("data_type", "stock")
            )
            results.append(quality)
        
        return results
    
    def generate_data_quality_report(
        self, 
        data_items: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        生成数据质量报告
        
        Args:
            data_items: 数据项列表
            
        Returns:
            Dict: 数据质量报告
        """
        try:
            health_results = self.check_data_health(data_items)
            
            if health_results:
                avg_score = sum(
                    r.get("quality_score", 0) for r in health_results
                ) / len(health_results)
                status_counts: Dict[str, int] = {}
                for r in health_results:
                    status = r.get("status", "unknown")
                    status_counts[status] = status_counts.get(status, 0) + 1
                
                problem_data = [
                    r for r in health_results if r.get("status") in ["poor", "no_data"]
                ]
            else:
                avg_score = 0.0
                status_counts = {}
                problem_data = []
            
            report = {
                "report_id": pd.Timestamp(get_time_provider().now()).strftime("%Y%m%d_%H%M%S"),
                "timestamp": pd.Timestamp(get_time_provider().now()).strftime("%Y-%m-%d %H:%M:%S"),
                "total_items": len(data_items),
                "analyzed_items": len(health_results),
                "average_quality_score": round(avg_score, 2),
                "status_distribution": status_counts,
                "problem_count": len(problem_data),
                "problem_details": problem_data,
                "recommendations": self._generate_recommendations(problem_data),
            }
            
            logger.info("Generated data quality report: %s", report['report_id'])
            return report
        except QUALITY_RECOVERABLE_ERRORS as e:
            logger.error("Failed to generate data quality report: %s", e)
            return {
                "error": str(e),
                "timestamp": pd.Timestamp(get_time_provider().now()).strftime("%Y-%m-%d %H:%M:%S"),
            }
    
    def _generate_recommendations(
        self, 
        problem_data: List[Dict[str, Any]]
    ) -> List[str]:
        """生成数据质量改进建议"""
        recommendations = []
        
        if not problem_data:
            recommendations.append("All data is in good condition.")
            return recommendations
        
        no_data_count = sum(1 for r in problem_data if r.get("status") == "no_data")
        poor_quality_count = sum(1 for r in problem_data if r.get("status") == "poor")
        
        if no_data_count > 0:
            recommendations.append(
                f"{no_data_count} items have no data. Consider fetching data from sources."
            )
        
        if poor_quality_count > 0:
            recommendations.append(
                f"{poor_quality_count} items have poor data quality. Consider rebuilding their data."
            )
        
        for item in problem_data[:5]:
            symbol = item.get("symbol")
            status = item.get("status")
            metrics = item.get("metrics", {})
            
            if status == "no_data":
                recommendations.append(
                    f"Symbol {symbol}: No data available. Need to fetch from source."
                )
            elif status == "poor":
                low_metrics = [k for k, v in metrics.items() if v < 0.5]
                if low_metrics:
                    recommendations.append(
                        f"Symbol {symbol}: Low metrics: {', '.join(low_metrics)}."
                    )
        
        return recommendations
    
    def monitor_data_quality(
        self,
        data_items: List[Dict[str, Any]],
        threshold: float = 70.0,
    ) -> List[Dict[str, Any]]:
        """
        监控数据质量并生成告警
        
        Args:
            data_items: 数据项列表
            threshold: 质量评分阈值
            
        Returns:
            List[Dict]: 告警列表
        """
        alerts = []
        
        health_results = self.check_data_health(data_items)
        
        for result in health_results:
            quality_score = result.get("quality_score", 0)
            if quality_score < threshold:
                alert = {
                    "alert_id": f"{result.get('symbol')}_{pd.Timestamp(get_time_provider().now()).strftime('%Y%m%d_%H%M%S')}",
                    "symbol": result.get("symbol"),
                    "data_type": result.get("data_type"),
                    "quality_score": quality_score,
                    "status": result.get("status"),
                    "threshold": threshold,
                    "severity": "high" if quality_score < 50 else "medium",
                    "timestamp": pd.Timestamp(get_time_provider().now()).strftime("%Y-%m-%d %H:%M:%S"),
                    "message": f"Data quality alert for {result.get('symbol')}: {quality_score:.2f} < {threshold}",
                }
                alerts.append(alert)
                logger.warning(alert["message"])
        
        return alerts
