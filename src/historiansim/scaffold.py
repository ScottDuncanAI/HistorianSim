"""``historiansim new-plant``: copy the plant template into a new package."""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["scaffold_plant"]

_TEMPLATE = Path(__file__).parent / "plants" / "_template"


def scaffold_plant(name: str, equipment: str) -> Path:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ValueError("plant name must be snake_case: lowercase letters, digits, underscores")
    target = Path(__file__).parent / "plants" / name
    if target.exists():
        raise FileExistsError(f"{target} already exists")
    class_name = "".join(part.capitalize() for part in name.split("_"))
    scenario = f"{name.replace('_', '-')}-rca"
    target.mkdir(parents=True)
    for template in sorted(_TEMPLATE.glob("*.tmpl")):
        text = (
            template.read_text(encoding="utf-8")
            .replace("{{NAME}}", name)
            .replace("{{EQUIPMENT}}", equipment)
            .replace("{{CLASS}}", class_name)
            .replace("{{SCENARIO}}", scenario)
        )
        (target / template.name.removesuffix(".tmpl")).write_text(text, encoding="utf-8")
    return target
