from __future__ import annotations

from proxy_pipeline.routing.routes import RouteRegistry


class Router:
    def __init__(self, registry: RouteRegistry, handlers: dict[tuple[str, str], object]) -> None:
        self.registry = registry
        self.handlers = handlers

    def resolve(self, role: str, capability: str = "decision"):
        for route in self.registry.for_role(role, capability):
            handler = self.handlers.get((route.provider, route.model))
            if handler is not None:
                return handler
        raise RuntimeError(f"no healthy route for role={role} capability={capability}")
