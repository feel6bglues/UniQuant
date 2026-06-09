"""
DEPRECATED: This module is superseded by uniquant.services.service_container.

Use ``from uniquant.services.service_container import ServiceContainer`` instead.
This module is retained only for backward compatibility and will be removed in a
future release.
"""

import warnings
from typing import Any

try:
    from ..services.service_container import ServiceContainer
except ImportError:
    ServiceContainer = None

warnings.warn(
    "uniquant.shared.di_container is deprecated and will be removed in a future "
    "release. Use uniquant.services.service_container.ServiceContainer instead.",
    DeprecationWarning,
    stacklevel=2,
)


class _LazyContainerProxy:
    """Backward-compatible container proxy without import-time singleton creation."""

    def _target(self) -> Any:
        if ServiceContainer is None:
            raise RuntimeError("ServiceContainer is unavailable")
        return ServiceContainer.instance()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target(), name)

    def __repr__(self) -> str:
        return "<LazyServiceContainerProxy>"


# Backward compatibility alias
DIContainer = ServiceContainer
container = _LazyContainerProxy()
