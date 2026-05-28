from typing import Dict, Any, Sequence
import pandas as pd
import concurrent.futures
import time
import pybreaker

from ...shared.constants import NetworkConstants
from ...shared.logger_factory import get_logger
from .standard_adapter import DataSourceAdapter

logger = get_logger(__name__)


class SourceRouter:
    """数据源路由中心"""

    def __init__(self, adapters: Sequence[DataSourceAdapter]):
        self.adapters = adapters
        self.max_workers = min(3, len(adapters))  # 并发数限制
        self.source_health: Dict[int, Dict[str, Any]] = {}  # 数据源健康状态缓存

    def fetch_data(self, symbol: str, start_date: str, max_retries: int = 2) -> pd.DataFrame:
        """尝试从多个数据源获取数据，实现故障转移"""
        logger.info(f"开始获取 {symbol} 数据，使用 {len(self.adapters)} 个数据源")

        for i, adapter in enumerate(self.adapters):
            # 检查数据源健康状态
            health_status = self.check_source_health(i)
            if health_status != "available":
                logger.warning(f"数据源 {i+1} 状态为 {health_status}，跳过")
                continue

            for retry in range(max_retries + 1):
                try:
                    logger.info(f"尝试使用第 {i+1} 个数据源获取 {symbol} 数据 (重试 {retry}/{max_retries})")
                    # 添加超时控制
                    df = self._fetch_with_timeout(adapter, symbol, start_date, timeout=NetworkConstants.SOCKET_TIMEOUT)
                    if not df.empty:
                        # 验证数据完整性
                        if self._validate_data_integrity(df):
                            logger.info(
                                f"成功使用第 {i+1} 个数据源获取 {symbol} 数据，共 {len(df)} 条记录"
                            )
                            # 更新数据源健康状态为可用
                            self.update_source_health(i, "available")
                            return df
                        else:
                            logger.warning(f"第 {i+1} 个数据源返回的数据不完整")
                            if retry >= max_retries:
                                self.update_source_health(i, "unavailable")
                            continue
                    else:
                        logger.warning(f"第 {i+1} 个数据源返回空数据")
                        if retry >= max_retries:
                            self.update_source_health(i, "unavailable")
                        break
                except TimeoutError as e:
                    logger.warning(f"第 {i+1} 个数据源超时: {e}")
                    if retry >= max_retries:
                        self.update_source_health(i, "unavailable")
                    # 超时错误使用更长的延迟
                    time.sleep(min(2 * (retry + 1), 10))
                    continue
                except Exception as e:  # noqa: E722 — 故障转移，需捕获一切以尝试下一个数据源
                    logger.warning(f"第 {i+1} 个数据源失败: {e}")
                    if retry >= max_retries:
                        self.update_source_health(i, "unavailable")
                    # 其他错误使用标准延迟
                    time.sleep(min(1 * (retry + 1), 5))
                    continue

        # 所有数据源都失败
        logger.error(f"所有数据源都无法获取 {symbol} 数据")
        return pd.DataFrame()

    def _validate_data_integrity(self, df: pd.DataFrame) -> bool:
        """验证数据完整性"""
        if df.empty:
            return False
        
        # 检查必要的列
        required_columns = ['date', 'open', 'high', 'low', 'close', 'volume']
        for col in required_columns:
            if col not in df.columns:
                logger.warning(f"数据缺少必要列: {col}")
                return False
        
        # 检查数据类型
        if not pd.api.types.is_datetime64_any_dtype(df['date']):
            logger.warning("日期列不是datetime类型")
            return False
        
        # 检查数据范围
        if len(df) < 1:
            logger.warning("数据量不足")
            return False
        
        return True

    def _fetch_with_timeout(self, adapter: DataSourceAdapter, symbol: str, start_date: str, timeout: int) -> pd.DataFrame:
        """带超时控制的数据源获取"""
        def fetch_func():
            return adapter.fetch(symbol, start_date)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(fetch_func)
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                raise TimeoutError(f"数据源获取超时 ({timeout}秒)")

    def fetch_data_with_race(self, symbol: str, start_date: str) -> pd.DataFrame:
        """竞速模式：同时请求多个数据源，谁快用谁"""
        logger.info(f"开始竞速模式获取 {symbol} 数据")

        # 只使用健康状态为可用的数据源进行竞速
        healthy_adapters = []
        for i, adapter in enumerate(self.adapters):
            if self.check_source_health(i) == "available":
                healthy_adapters.append((i, adapter))
                if len(healthy_adapters) >= self.max_workers:
                    break

        if not healthy_adapters:
            logger.warning("没有可用的数据源进行竞速")
            return self.fetch_data(symbol, start_date)

        race_adapters = [adapter for _, adapter in healthy_adapters]
        results = []

        def fetch_with_adapter(adapter):
            try:
                start_time = time.time()
                df = self._fetch_with_timeout(adapter, symbol, start_date, timeout=NetworkConstants.SOCKET_TIMEOUT)
                end_time = time.time()
                if not df.empty:
                    return df, end_time - start_time
            except Exception as e:  # noqa: E722 — 竞速模式，需捕获一切
                logger.warning(f"竞速模式中数据源失败: {e}")
            return pd.DataFrame(), float("inf")

        # 使用线程池并发获取数据
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(race_adapters)
        ) as executor:
            future_to_adapter = {
                executor.submit(fetch_with_adapter, adapter): adapter
                for adapter in race_adapters
            }

            for future in concurrent.futures.as_completed(future_to_adapter):
                df, elapsed = future.result()
                if not df.empty:
                    results.append((df, elapsed))

        # 选择最快返回的有效数据
        if results:
            # 按耗时排序
            results.sort(key=lambda x: x[1])
            fastest_df, fastest_time = results[0]
            logger.info(
                f"竞速模式完成，最快数据源耗时 {fastest_time:.2f} 秒，获取 {len(fastest_df)} 条记录"
            )
            return fastest_df

        logger.error("竞速模式下所有数据源都失败")
        return pd.DataFrame()

    def check_source_health(self, source_index: int) -> str:
        """检查数据源健康状态"""
        if source_index not in self.source_health:
            # 默认状态为可用
            return "available"
        
        health_info = self.source_health[source_index]
        # 检查状态是否过期（5分钟过期）
        if time.time() - health_info.get("timestamp", 0) > 300:
            return "available"
        
        return health_info.get("status", "available")

    def update_source_health(self, source_index: int, status: str):
        """更新数据源健康状态"""
        self.source_health[source_index] = {
            "status": status,
            "timestamp": time.time()
        }

    def get_source_health_report(self) -> Dict[str, Any]:
        """获取数据源健康报告"""
        report: Dict[str, Any] = {
            "total_sources": len(self.adapters),
            "available_sources": 0,
            "details": [],
        }

        for i, adapter in enumerate(self.adapters):
            status = self.check_source_health(i)
            if status == "available":
                report["available_sources"] += 1
            
            source_info: Dict[str, Any] = {
                "source_index": i + 1,
                "status": status,
                "name": getattr(adapter, "name", f"Source_{i+1}"),
                "last_checked": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.source_health.get(i, {}).get("timestamp", time.time())))
            }
            report["details"].append(source_info)

        return report

    def print_source_health_report(self):
        """打印数据源健康报告"""
        report = self.get_source_health_report()
        logger.info("数据源健康报告:")
        logger.info(f"总数据源数: {report['total_sources']}")
        logger.info(f"可用数据源数: {report['available_sources']}")

        for detail in report["details"]:
            logger.info(
                f"数据源 {detail['source_index']}: {detail['name']} - {detail['status']} (最后检查: {detail['last_checked']})"
            )

    def get_healthy_sources_count(self) -> int:
        """获取健康数据源数量"""
        count = 0
        for i in range(len(self.adapters)):
            if self.check_source_health(i) == "available":
                count += 1
        return count

    def fetch_with_fallback(self, symbol: str, method: str = "fetch", **kwargs):
        last_error = None
        for adapter in self.adapters:
            try:
                if hasattr(adapter, 'fetch'):
                    return adapter.fetch(symbol, **kwargs)
                return adapter
            except pybreaker.CircuitBreakerError:
                logger.warning("Source %s open, trying next", getattr(adapter, 'name', str(adapter)))
            except Exception as e:
                last_error = e
                logger.warning("Source %s failed: %s", getattr(adapter, 'name', str(adapter)), e)
        if last_error:
            raise last_error
        return None
