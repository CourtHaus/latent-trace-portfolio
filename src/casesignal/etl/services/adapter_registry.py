from __future__ import annotations

from casesignal.etl.adapters.base import SourceAdapter
from casesignal.etl.services.source_definition import SourceDefinition


class AdapterRegistryError(Exception):
    """Base exception for adapter registry errors."""


class AdapterRegistrationError(AdapterRegistryError):
    """Raised when adapter registration is invalid."""


class AdapterResolutionError(AdapterRegistryError):
    """Raised when an adapter cannot be resolved from the registry."""


class AdapterRegistry:
    """
    Registry for source adapter classes keyed by adapter_name.

    The registry is responsible for:
    - registering concrete adapter classes
    - resolving adapter classes by adapter_name
    - instantiating adapters for SourceDefinition objects
    """

    def __init__(self) -> None:
        self._registry: dict[str, type[SourceAdapter]] = {}

    def register(self, adapter_cls: type[SourceAdapter]) -> None:
        """
        Register a concrete adapter class.

        The adapter class must expose a non-empty `adapter_name` property.
        """
        if not issubclass(adapter_cls, SourceAdapter):
            raise AdapterRegistrationError(
                f"Adapter class '{adapter_cls.__name__}' must inherit from SourceAdapter."
            )

        try:
            adapter_name = getattr(adapter_cls, "adapter_name", None)
        except Exception as exc:
            raise AdapterRegistrationError(
                f"Failed to inspect adapter)name for adapter class '{adapter_cls.__name__}'."
            ) from exc

        if not isinstance(adapter_name, str) or not adapter_name.strip():
            raise AdapterRegistrationError(
                f"Adapter class '{adapter_cls.__name__}' must define a non-empty adapter_name."
            )

        if adapter_name in self._registry:
            existing = self._registry[adapter_name].__name__
            raise AdapterRegistrationError(
                f" Adapter name '{adapter_name}' is already registered to '{existing}'."
            )

        self._registry[adapter_name] = adapter_cls

    def resolve_class(self, adapter_name: str) -> type[SourceAdapter]:
        """Resolve an adapter class by adapter_name."""
        try:
            return self._registry[adapter_name]
        except KeyError as exc:
            available = ", ".join(sorted(self._registry))
            raise AdapterResolutionError(
                f"Unknown adapter_name '{adapter_name}'. Available adapters: {available}"
            ) from exc

    def create_adapter(self, source_definition: SourceDefinition) -> SourceAdapter:
        """
        Instantiate the correct adapter for the given SourceDefinition.
        """
        adapter_cls = self.resolve_class(source_definition.adapter_name)
        return adapter_cls(source_definition)
