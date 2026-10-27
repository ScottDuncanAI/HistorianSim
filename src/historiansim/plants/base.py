"""The contract a process plant fulfils.

A plant is everything about one simulated process that is *not* shared: its
physics, its tags, its control loops, the disturbances it sees, the ways it can
fail, and the words that describe it. Control, measurement, historian
compression, ground truth and validation are identical for every plant and live
outside this package.

Adding a process means writing one folder under ``historiansim/plants/`` that builds
a :class:`Plant` and registering it in :mod:`historiansim.plants`. Nothing in the
engine needs to change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Union

if TYPE_CHECKING:
    from historiansim.config.schema import ChannelConfig, LoopConfig, ScenarioConfig
    from historiansim.faults.base import ControlFault
    from historiansim.faults.catalog import FaultCatalog
    from historiansim.plants.unit import UnitModel
    from historiansim.tags import TagSpec

__all__ = ["Plant", "BenignEvent", "Section", "PlantDescription", "GENERIC_SECTIONS"]


@dataclass(frozen=True)
class BenignEvent:
    """An abnormal-looking event that is not a fault: an intended operator move.

    ``build(event_id, onset_s, end_s)`` returns the control action. ``why`` is
    the answer-key explanation of why it is benign.
    """

    kind: str
    duration_days: tuple[float, float]
    build: Callable[[str, float, float], "ControlFault"] = field(repr=False)
    note: str
    why: str = ""


@dataclass(frozen=True)
class Section:
    """One plant-specific section of the process description."""

    title: str
    lines: list[str]


#: Sections the engine writes itself, from the tag list and instrument classes.
#: A plant places them in its section list by name.
GENERIC_SECTIONS = {
    "tags": "Instrumentation and tag list",
    "calcs": "Calculated (DCS) tags",
    "instruments": "Instrument and historian behaviour",
    "neighbours": "Neighbouring equipment in the extract",
    "files": "Data files",
}


@dataclass
class PlantDescription:
    """What the plant contributes to ``PROCESS_DESCRIPTION.md``.

    The document must give an analyst everything needed to reason from first
    principles -- balances, heat-transfer and kinetic relations, how each loop
    is wired, how every calculated tag is formed -- while saying nothing about
    which abnormal events occur. In particular it never lists failure modes: a
    catalogue of things that can go wrong is a candidate list, and a candidate
    list is half an answer.
    """

    title: str
    intro: list[str]
    #: Ordered; plain strings name a :data:`GENERIC_SECTIONS` entry.
    sections: list[Union[Section, str]]
    tag_notes: dict[str, str] = field(default_factory=dict)
    #: (tag, units, definition) rows for the calculated-tag table.
    calc_definitions: list[tuple[str, str, str]] = field(default_factory=list)
    calc_notes: list[str] = field(default_factory=list)
    #: Plant-specific bullets after the instrument-class table.
    instrument_notes: list[str] = field(default_factory=list)
    timezone_label: str | None = None
    #: What follows the local-time daily cycle, for the data-files notes.
    diurnal_sources: str = "ambient"


@dataclass
class Plant:
    """One simulated process, as the engine sees it."""

    #: Registry key; also ``ScenarioConfig.unit``.
    name: str
    #: Equipment designation, e.g. ``TK-101``. Written into ``tags.csv``.
    equipment: str
    #: One-line description for ``historiansim list``.
    summary: str
    unit_cls: type["UnitModel"]
    tags: Callable[[], list["TagSpec"]]
    loops: Callable[[], list["LoopConfig"]]
    channels: Callable[[], dict[str, "ChannelConfig"]]
    catalog: "FaultCatalog"
    describe: Callable[["ScenarioConfig"], PlantDescription]
    scenarios: dict[str, dict[str, Any]]

    #: Rebuild CALC-* tags in place from measured values; ``(values, params)``.
    recompute_calcs: Callable[[dict, dict | None], None] | None = None
    benign_events: dict[str, BenignEvent] = field(default_factory=dict)
    default_benign_kinds: tuple[str, ...] = ()
    #: ``(baseline_end_s, total_s) -> (faults, cleanings_s)`` for the slow
    #: degradation that runs under a whole campaign. ``None`` if the plant has
    #: none.
    background_degradation: Callable[[float, float], tuple[list, tuple[float, ...]]] | None = None
    #: Discriminating tags removed on ``--difficulty hard``.
    hard_mode_withheld: tuple[str, ...] = ()
    #: Signals (true-value names) whose sums form the liquid balance:
    #: ``(inflows, outflows)``. Checked by the validation battery.
    mass_balance: tuple[tuple[str, ...], tuple[str, ...]] | None = None
    #: Plant-specific background behaviour the answer key should mention as
    #: *not* a fault, e.g. a slowly wandering balance offset.
    background_notes: str = ""

    def unit(self, params: dict[str, float] | None = None) -> "UnitModel":
        return self.unit_cls(params)

    def tag_names(self) -> set[str]:
        return {t.name for t in self.tags()}
