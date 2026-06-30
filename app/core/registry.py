"""
core/registry.py
================
Auto-discovery of modules. On startup we import every file in app/modules/,
find every subclass of BaseModule, instantiate it, and index it by key and by
the InputTypes it accepts.

Why auto-discover instead of a hand-maintained list? So that adding a new
capability is literally "drop a new file in app/modules/" — no wiring, no
registration boilerplate. That is what makes the architecture "genuinely
modular" as required.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Iterable

from .base import BaseModule, InputType


class Registry:
    def __init__(self) -> None:
        self.modules: dict[str, BaseModule] = {}            # key -> instance
        self._by_type: dict[InputType, list[BaseModule]] = {}

    # ----------------------------------------------------------------------
    def discover(self, package: str = "app.modules") -> "Registry":
        """Import the package and register every BaseModule subclass found."""
        pkg = importlib.import_module(package)
        for mod_info in pkgutil.iter_modules(pkg.__path__):
            if mod_info.name.startswith("_"):
                continue  # skip private/helper files like _http_utils.py
            module = importlib.import_module(f"{package}.{mod_info.name}")
            for _, obj in inspect.getmembers(module, inspect.isclass):
                # Register concrete subclasses defined IN this module only
                # (avoids re-registering imported base classes).
                if (
                    issubclass(obj, BaseModule)
                    and obj is not BaseModule
                    and obj.__module__ == module.__name__
                    and not inspect.isabstract(obj)
                ):
                    self.register(obj())
        return self

    def register(self, instance: BaseModule) -> None:
        if instance.key in self.modules:
            raise ValueError(f"Duplicate module key: {instance.key!r}")
        self.modules[instance.key] = instance
        for itype in instance.accepts:
            self._by_type.setdefault(itype, []).append(instance)

    # ----------------------------------------------------------------------
    def for_type(self, itype: InputType) -> list[BaseModule]:
        """All modules that can handle a given input type."""
        return list(self._by_type.get(itype, []))

    def get(self, key: str) -> BaseModule | None:
        return self.modules.get(key)

    def all(self) -> Iterable[BaseModule]:
        return self.modules.values()

    def manifest(self) -> list[dict]:
        """Sorted metadata for the whole catalog (powers the sidebar)."""
        return sorted(
            (m.manifest() for m in self.modules.values()),
            key=lambda m: (m["category"], m["name"]),
        )
