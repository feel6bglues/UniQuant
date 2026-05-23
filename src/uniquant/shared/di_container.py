import threading
from typing import Any, Dict


class DIContainer:
    """
    Dependency injection container for managing service dependencies.
    """

    def __init__(self):
        self._services: Dict[str, Any] = {}
        self._factories: Dict[str, Any] = {}
        self._instances: Dict[str, Any] = {}
        self._lock = threading.RLock()

    def register(self, name: str, service: Any):
        """
        Register a service instance directly.
        """
        with self._lock:
            self._services[name] = service

    def register_factory(self, name: str, factory: Any):
        """
        Register a factory function to create the service.
        """
        with self._lock:
            self._factories[name] = factory

    def get(self, name: str) -> Any:
        """
        Get a service by name, creating it if necessary.
        """
        with self._lock:
            # Check if service is already instantiated
            if name in self._instances:
                return self._instances[name]

            # Check if service is registered directly
            if name in self._services:
                return self._services[name]

            # Check if factory exists
            if name in self._factories:
                # Create the instance
                instance = self._factories[name](self)
                self._instances[name] = instance
                return instance

        raise ValueError(f"Service {name} not registered")

    def has(self, name: str) -> bool:
        """
        Check if a service is registered.
        """
        with self._lock:
            return (
                name in self._services or name in self._factories or name in self._instances
            )

    def reset(self):
        """
        Reset the container, clearing all instances (singletons).
        Registrations (services and factories) are preserved.
        """
        with self._lock:
            self._instances.clear()

    def clear(self):
        """
        Completely clear the container, including all registrations and instances.
        """
        with self._lock:
            self._services.clear()
            self._factories.clear()
            self._instances.clear()


# Global container instance
container = DIContainer()
