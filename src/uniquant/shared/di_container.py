"""
DEPRECATED: This module is superseded by uniquant.services.service_container.

Use ``from uniquant.services.service_container import ServiceContainer`` instead.
This module is retained only for backward compatibility and will be removed in a
future release.
"""

import warnings

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

# Backward compatibility alias
DIContainer = ServiceContainer
container = ServiceContainer.instance()
