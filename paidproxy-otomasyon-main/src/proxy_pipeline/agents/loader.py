from __future__ import annotations

import importlib
import os
from typing import Any

from proxy_pipeline.agents.tak import ajan as hooked


class LoadedRoute:
    version = "loaded-1"

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.version = getattr(inner, "version", "loaded-1")

    def decide(self, context):
        return self.inner.decide(context)


def _from_spec(spec: str) -> Any:
    module_name, _, attr = spec.partition(":")
    if not module_name or not attr:
        raise ValueError("PIPELINE_AJAN formati: modul:Sinif")
    module = importlib.import_module(module_name)
    target = getattr(module, attr)
    return target() if isinstance(target, type) else target


def load_routes() -> list:
    routes: list = []
    spec = os.environ.get("PIPELINE_AJAN", "").strip()
    if spec:
        routes.append(LoadedRoute(_from_spec(spec)))
    elif hooked is not None:
        routes.append(LoadedRoute(hooked))
    return routes
