"""Plant registry.

Every sub-package of ``historiansim.plants`` that defines a module-level ``PLANT``
is registered automatically, so adding a process is adding a folder. The
package name, the plant name and ``ScenarioConfig.unit`` are the same string.
"""

from __future__ import annotations

import importlib
import pkgutil

from historiansim.plants.base import (
    GENERIC_SECTIONS,
    BenignEvent,
    Plant,
    PlantDescription,
    Section,
)
from historiansim.plants.unit import UnitModel

__all__ = [
    "Plant",
    "BenignEvent",
    "PlantDescription",
    "Section",
    "GENERIC_SECTIONS",
    "UnitModel",
    "get_plant",
    "available_plants",
    "all_plants",
    "register_plant",
]

_REGISTRY: dict[str, Plant] = {}
#: Plants whose package failed to import, with the error. A half-built plant
#: must not take every other plant down with it, but asking for it by name
#: still raises the real error.
_BROKEN: dict[str, BaseException] = {}
_discovered = False


def register_plant(plant: Plant) -> Plant:
    existing = _REGISTRY.get(plant.name)
    if existing is not None and existing is not plant:
        raise ValueError(f"plant name {plant.name!r} is already registered")
    _REGISTRY[plant.name] = plant
    return plant


def _discover() -> None:
    global _discovered
    if _discovered:
        return
    _discovered = True
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        if not info.ispkg or info.name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"{__name__}.{info.name}")
        except Exception as exc:  # noqa: BLE001 -- reported, not swallowed
            import warnings

            _BROKEN[info.name] = exc
            warnings.warn(f"plant {info.name!r} failed to import: {exc!r}", stacklevel=2)
            continue
        plant = getattr(module, "PLANT", None)
        if isinstance(plant, Plant):
            if plant.name != info.name:
                raise ValueError(
                    f"plants/{info.name} defines PLANT named {plant.name!r}; "
                    "the folder and the plant name must match"
                )
            register_plant(plant)


def get_plant(name: str) -> Plant:
    _discover()
    if name in _BROKEN:
        raise ImportError(f"plant {name!r} failed to import") from _BROKEN[name]
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown plant {name!r}. Available: {sorted(_REGISTRY)}") from None


def available_plants() -> list[str]:
    _discover()
    return sorted(_REGISTRY)


def all_plants() -> list[Plant]:
    _discover()
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]
