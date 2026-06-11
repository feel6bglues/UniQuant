from __future__ import annotations

import datetime
from typing import Optional, Protocol


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


class RealTimeProvider:
    """生产环境时间提供者 — 返回真实时间"""

    def now(self) -> datetime.datetime:
        return datetime.datetime.now()

    def today(self) -> datetime.date:
        return datetime.date.today()

    def timestamp(self) -> str:
        return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


class FrozenTimeProvider:
    """回测/测试环境时间提供者 — 返回固定时间

    用法:
        provider = FrozenTimeProvider(datetime.datetime(2024, 6, 1))
        provider.now()  # 总是返回 2024-06-01
    """

    def __init__(self, fixed: Optional[datetime.datetime] = None):
        self._fixed = fixed or datetime.datetime(2024, 6, 1, 9, 30, 0)

    def now(self) -> datetime.datetime:
        return self._fixed

    def today(self) -> datetime.date:
        return self._fixed.date()

    def timestamp(self) -> str:
        return self._fixed.strftime("%Y%m%d_%H%M%S")

    def advance(self, **kwargs) -> None:
        self._fixed = self._fixed + datetime.timedelta(**kwargs)
