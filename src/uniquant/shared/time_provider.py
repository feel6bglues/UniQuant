from __future__ import annotations

import datetime
import time
from typing import Optional, Protocol


# 模块级默认时间提供者，可被 set_time_provider() 替换以支持测试
_default_provider: Optional[TimeProvider] = None


def get_time_provider() -> TimeProvider:
    global _default_provider
    if _default_provider is None:
        _default_provider = RealTimeProvider()
    return _default_provider


def set_time_provider(provider: TimeProvider) -> None:
    global _default_provider
    _default_provider = provider


class TimeProvider(Protocol):
    """可注入的时间提供者协议

    用依赖注入替代所有 pd.Timestamp.now() / datetime.now() 的硬编码调用。
    """

    def now(self) -> datetime.datetime:
        ...

    def today(self) -> datetime.date:
        ...

    def timestamp(self) -> str:
        ...

    def epoch(self) -> float:
        """返回当前时间的 Unix 时间戳 (秒)"""
        ...

    def epoch_ms(self) -> int:
        """返回当前时间的 Unix 时间戳 (毫秒)"""
        ...


class RealTimeProvider:
    """生产环境时间提供者 — 返回真实时间"""

    def now(self) -> datetime.datetime:
        return datetime.datetime.now()

    def today(self) -> datetime.date:
        return datetime.date.today()

    def timestamp(self) -> str:
        return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    def epoch(self) -> float:
        return time.time()

    def epoch_ms(self) -> int:
        return int(time.time() * 1000)


class FrozenTimeProvider:
    """回测/测试环境时间提供者 — 返回固定时间

    用法:
        provider = FrozenTimeProvider(datetime.datetime(2024, 6, 1))
        provider.now()  # 总是返回 2024-06-01
    """

    def __init__(self, fixed: Optional[datetime.datetime] = None):
        fixed = fixed or datetime.datetime(2024, 6, 1, 9, 30, 0)
        self._fixed = fixed
        self._epoch_base = fixed.timestamp()

    def now(self) -> datetime.datetime:
        return self._fixed

    def today(self) -> datetime.date:
        return self._fixed.date()

    def timestamp(self) -> str:
        return self._fixed.strftime("%Y%m%d_%H%M%S")

    def epoch(self) -> float:
        return self._epoch_base

    def epoch_ms(self) -> int:
        return int(self._epoch_base * 1000)

    def advance(self, **kwargs) -> None:
        self._fixed = self._fixed + datetime.timedelta(**kwargs)
        self._epoch_base = self._fixed.timestamp()
