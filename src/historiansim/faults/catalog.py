"""The structure every plant's fault catalog is written in.

Organised the way a diagnosis actually proceeds: by **symptom**, not by cause.
Each symptom class is a set of root causes that produce the same first
observable, so identifying the symptom narrows nothing. The work is
discrimination, and the discrimination matrix records exactly which other tag
settles each question.

A plant supplies a :class:`FaultCatalog`; nothing else in the engine knows
which causes exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Literal

__all__ = [
    "Evidence",
    "RootCause",
    "SymptomClass",
    "FaultCatalog",
    "SEVERITIES",
    "Severity",
]

Severity = Literal["subtle", "moderate", "obvious"]
SEVERITIES: tuple[str, ...] = ("subtle", "moderate", "obvious")


@dataclass(frozen=True)
class Evidence:
    """One piece of discriminating evidence.

    ``rules_out`` is the important field. Diagnosis here is mostly elimination:
    a flat feed flow does not prove fouling, it eliminates feed creep.
    """

    tag: str
    #: ``flat`` means the fault does not affect this tag -- the workhorse of
    #: elimination. ``frozen`` is different and easy to conflate with it: the
    #: tag *stops responding* while the plant around it keeps moving, which is
    #: a positive observation rather than an absence of one. A controller left
    #: in manual freezes its output; that is not the same as the output being
    #: unaffected, and reading it as such loses the diagnosis.
    expectation: Literal["rises", "falls", "flat", "frozen", "erratic", "steps"]
    note: str
    rules_in: tuple[str, ...] = ()
    rules_out: tuple[str, ...] = ()


@dataclass(frozen=True)
class RootCause:
    """A single candidate explanation, with the recipe to inject it.

    ``mechanism`` and ``component`` are what "unique" means in a benchmark: no
    two episodes may share a failure mechanism or a failed component, or the
    second is a repeat of the first in all but name. ``walkthrough`` is the
    reasoning path from the shipped data to the cause, written for the answer
    key, and ``competitors`` names the explanations it has to rule out.
    """

    id: str
    name: str
    label: str
    symptom: str
    layer: int
    mechanism: str
    build: Callable[[float, str], object] = field(repr=False)
    evidence: tuple[Evidence, ...] = ()
    masked_by_control: bool = True
    component: str = ""
    grade: str = ""
    walkthrough: str = ""
    competitors: tuple[str, ...] = ()

    def make(self, onset_s: float, severity: str = "moderate"):
        if severity not in SEVERITIES:
            raise ValueError(f"unknown severity {severity!r}; use one of {SEVERITIES}")
        return self.build(onset_s, severity)


@dataclass(frozen=True)
class SymptomClass:
    """A first observable shared by several root causes.

    ``tempo`` sets how long an episode of this class runs before someone acts:
    ``slow`` degradations run for days, ``cycling`` misbehaviour gets noticed
    within a few days, and ``acute`` excursions are responded to within hours.
    """

    id: str
    label: str
    first_observable: str
    description: str
    tempo: Literal["slow", "cycling", "acute"] = "slow"


class FaultCatalog:
    """Symptom classes and the root causes that compete within each."""

    def __init__(self, symptoms: dict[str, SymptomClass], causes: Iterable[RootCause]):
        self.symptoms = dict(symptoms)
        self.causes: dict[str, RootCause] = {}
        for cause in causes:
            if cause.id in self.causes:
                raise ValueError(f"duplicate root cause id {cause.id!r}")
            if cause.symptom not in self.symptoms:
                raise ValueError(
                    f"{cause.id} belongs to unknown symptom class {cause.symptom!r}"
                )
            self.causes[cause.id] = cause

    def __contains__(self, cause_id: str) -> bool:
        return cause_id in self.causes

    def __len__(self) -> int:
        return len(self.causes)

    def get(self, cause_id: str) -> RootCause:
        try:
            return self.causes[cause_id]
        except KeyError:
            raise KeyError(
                f"unknown root cause {cause_id!r}. Available: {sorted(self.causes)}"
            ) from None

    def causes_for(self, symptom: str) -> tuple[RootCause, ...]:
        """Every candidate explanation for a symptom class -- the confusion set."""
        if symptom not in self.symptoms:
            raise KeyError(
                f"unknown symptom class {symptom!r}; have {sorted(self.symptoms)}"
            )
        return tuple(c for c in self.causes.values() if c.symptom == symptom)

    def discrimination_matrix(self, symptom: str) -> dict[str, dict[str, str]]:
        """Tag-by-cause table of what each candidate does to each evidence tag.

        Emitted into the answer key so a diagnosis can be graded on its
        reasoning rather than only on its final label.
        """
        causes = self.causes_for(symptom)
        tags = sorted({e.tag for c in causes for e in c.evidence})
        table: dict[str, dict[str, str]] = {}
        for tag in tags:
            row: dict[str, str] = {}
            for cause in causes:
                match = next((e for e in cause.evidence if e.tag == tag), None)
                row[cause.id] = match.expectation if match else "unspecified"
            table[tag] = row
        return table
