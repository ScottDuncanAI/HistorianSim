"""Historian tag definitions, plus ballast from neighbouring units.

A control loop is not one tag. It is PV, SP, OP and MODE at minimum, which is
why two loops and a cascade slave already come to twelve tags before a single
indicator is counted. Each plant declares its own tags with :class:`TagSpec`;
the ballast defined here is shared by every plant.

**Ballast matters more than total count.** What makes tag selection a real
problem is the ratio of relevant to irrelevant, not the absolute number. If
every tag in the dataset bears on the fault, retrieval is trivial and any agent
looks clever for no reason. Real plants have thousands of tags of which six
matter. The ballast units here run normally, have their own loops and their own
noise, and share only the ambient driver -- so they correlate with the real
tags just enough to be genuinely distracting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["TagSpec", "ballast_tags", "BALLAST_UNITS", "BALLAST_UNIT_NAMES"]

Role = Literal["PV", "SP", "OP", "MODE", "IND", "CALC", "STATUS"]


@dataclass(frozen=True)
class TagSpec:
    """One historian tag: where its value comes from and how it is measured."""

    name: str
    description: str
    units: str
    lo: float
    hi: float
    instrument: str
    role: Role = "IND"
    source: str | None = None        # series name in the SimResult
    loop: str | None = None
    node: str = "NODE-A"             # DCS node, for correlated dropouts
    transport_lag_s: float = 0.0
    ballast: bool = False

    @property
    def span(self) -> tuple[float, float]:
        return (self.lo, self.hi)


#: Neighbouring units that share only the weather. Each entry is
#: (prefix, description, number of loops).
BALLAST_UNITS = [
    ("CW", "Cooling water skid", 5),
    ("N2", "Nitrogen header", 4),
    ("SD", "Surge drum", 4),
    ("AIR", "Instrument air", 3),
]

#: Plant designations for the neighbouring units, written into the ``unit``
#: column of ``tags.csv``. Deliberately *not* the word "ballast": no real
#: historian labels a tag as irrelevant, and stamping the answer on 60 of the
#: 90 tags would hand over the tag-selection half of the exercise. Internal
#: code must test ``TagSpec.ballast`` instead, which stays authoritative.
BALLAST_UNIT_NAMES = {
    "CW": "CW-SKID",
    "N2": "N2-HDR",
    "SD": "SD-101",
    "AIR": "IA-SKID",
}

_BALLAST_KINDS = [
    ("FIC", "flow", "m3/h", 0.0, 200.0, "flow"),
    ("TIC", "temperature", "degC", 0.0, 150.0, "temperature"),
    ("PIC", "pressure", "barg", 0.0, 20.0, "pressure"),
    ("LIC", "level", "m", 0.0, 5.0, "level"),
]


def ballast_tags(count: int) -> list[TagSpec]:
    """Generate ``count`` tags of unrelated but plausible plant equipment.

    Four tags per loop, matching the real units, so the ballast does not stand
    out structurally either.
    """
    specs: list[TagSpec] = []
    loop_no = 0
    for prefix, description, n_loops in BALLAST_UNITS:
        for i in range(n_loops):
            if len(specs) >= count:
                break
            kind, kind_name, units, lo, hi, instrument = _BALLAST_KINDS[
                loop_no % len(_BALLAST_KINDS)
            ]
            loop = f"{prefix}-{kind}-{201 + i}"
            node = f"NODE-{chr(ord('D') + (loop_no % 3))}"
            specs.extend(
                [
                    TagSpec(f"{loop}.PV", f"{description} {kind_name}", units, lo, hi,
                            instrument, "PV", loop=loop, node=node, ballast=True),
                    TagSpec(f"{loop}.SP", f"{description} {kind_name} setpoint", units,
                            lo, hi, "status", "SP", loop=loop, node=node, ballast=True),
                    TagSpec(f"{loop}.OP", f"{description} {kind_name} output", "%",
                            0, 100, "valve", "OP", loop=loop, node=node, ballast=True),
                    TagSpec(f"{loop}.MODE", f"{description} {kind_name} mode", "-",
                            0, 2, "status", "MODE", loop=loop, node=node, ballast=True),
                ]
            )
            loop_no += 1
    return specs[:count]
