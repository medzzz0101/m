"""registry.py — auto-discover every BaseModule subclass in app/modules/.

Drop a new file in `app/modules/` that defines a `BaseModule` subclass and it
shows up in the API and UI automatically — no central list to maintain. That's
the payoff of the tiny base vocabulary.
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Iterable

from . import base
from .base import BaseModule, InputType


class Registry:
    def __init__(self) -> None:
        self._modules: dict[str, BaseModule] = {}

    def discover(self, package: str = "app.modules") -> None:
        pkg = importlib.import_module(package)
        for info in pkgutil.iter_modules(pkg.__path__):
            if info.name.startswith("_"):
                continue
            mod = importlib.import_module(f"{package}.{info.name}")
            for attr in vars(mod).values():
                if (isinstance(attr, type) and issubclass(attr, BaseModule)
                        and attr is not BaseModule):
                    inst = attr()
                    if not inst.id:
                        continue
                    self._modules[inst.id] = inst

    def restrict(self, categories: set[str]) -> None:
        """Keep only modules in the given categories (used for the social-only
        build). Everything else is dropped from the registry entirely."""
        self._modules = {mid: m for mid, m in self._modules.items()
                         if m.category.value in categories}

    def all(self) -> list[BaseModule]:
        return sorted(self._modules.values(), key=lambda m: (m.category.value, m.name))

    def get(self, module_id: str) -> BaseModule | None:
        return self._modules.get(module_id)

    def for_input(self, input_type: InputType) -> list[BaseModule]:
        return [m for m in self.all() if input_type in m.inputs]

    def manifests(self) -> list[dict]:
        return [m.manifest() for m in self.all()]

    def __len__(self) -> int:
        return len(self._modules)
