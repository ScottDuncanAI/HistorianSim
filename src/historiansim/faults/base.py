"""Fault and degradation primitives.

**The one structural rule of this simulator.** A process fault is a modifier on
a *parameter*, never on a signal. Add a fault to a finished trend and you have
written a step change into a CSV, not simulated a process upset. Injected as a
parameter, the fault changes how state evolves, so the controller notices and
responds, the effect propagates downstream with the correct lag, and the
observable is partially masked. All of that falls out of the physics instead of
being scripted, which is the only way it comes out self-consistent.

Instrument faults are the exception, and the distinction is the main design
judgment in the whole simulator. A fouled orifice plate or a drifting
transmitter does not change the process at all -- it changes what one
transmitter reports about it. Those are :class:`InstrumentFault` and they are
applied in the measurement layer, where they will break an energy balance
without moving any real quantity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Protocol, Sequence

__all__ = [
    "Profile",
    "Step",
    "Linear",
    "Exponential",
    "Erratic",
    "ProcessFault",
    "InstrumentFault",
]


class Profile(Protocol):
    """Maps elapsed seconds since onset to a severity fraction in [0, 1]."""

    def __call__(self, elapsed_s: float) -> float: ...


@dataclass(frozen=True)
class Step:
    """Instantaneous arrival. A tripped breaker, a slammed valve."""

    def __call__(self, elapsed_s: float) -> float:
        return 1.0


@dataclass(frozen=True)
class Linear:
    """Constant-rate ramp to full severity, then held."""

    ramp_s: float

    def __call__(self, elapsed_s: float) -> float:
        if self.ramp_s <= 0:
            return 1.0
        return min(elapsed_s / self.ramp_s, 1.0)


@dataclass(frozen=True)
class Exponential:
    """First-order approach to an asymptote.

    The natural shape for fouling: deposition is fastest on a clean surface and
    slows as the layer insulates itself. It is also what makes fouling hard to
    catch early -- the first days move the valve by less than the daily ambient
    swing does.
    """

    tau_s: float

    def __call__(self, elapsed_s: float) -> float:
        if self.tau_s <= 0:
            return 1.0
        return 1.0 - math.exp(-elapsed_s / self.tau_s)


@dataclass(frozen=True)
class Erratic:
    """Exponential approach with a slugging oscillation on top.

    Condensate backup does not arrive smoothly. Liquid accumulates, a slug
    clears, and the coil partially recovers. That irregularity is the *only*
    thing in the raw trend separating backup from plain fouling before anyone
    looks at the condensate temperature, so it is worth modelling honestly.

    Built from incommensurable sinusoids rather than random draws, because this
    is evaluated inside the integration loop and must stay a pure function of
    time -- otherwise the no-fault twin diverges.
    """

    tau_s: float
    period_s: float = 5400.0
    depth: float = 0.35
    phase: float = 0.0

    def __call__(self, elapsed_s: float) -> float:
        envelope = 1.0 - math.exp(-elapsed_s / self.tau_s) if self.tau_s > 0 else 1.0
        wobble = (
            math.sin(2.0 * math.pi * elapsed_s / self.period_s + self.phase)
            + 0.6 * math.sin(2.0 * math.pi * elapsed_s / (self.period_s * 0.37) + 1.7)
        ) / 1.6
        return max(0.0, min(1.0, envelope * (1.0 + self.depth * wobble)))


@dataclass
class ProcessFault:
    """A layer-6 fault: it modifies one process parameter over time.

    Parameters
    ----------
    mode:
        ``scale`` multiplies the parameter by ``(1 - severity * magnitude)`` --
        the right form for a surviving-fraction parameter like coil UA.
        ``offset`` adds ``severity * magnitude`` -- the right form for a
        quantity that starts at zero, like flooded area or leak coefficient.

        Both compose: two faults touching the same parameter combine without
        either having to know about the other, which is what lets background
        degradation run underneath an injected fault.
    resets:
        Times at which the mechanism is undone -- a cleaning, a repair. The
        severity clock restarts from the most recent one, producing the
        sawtooth that real fouling data shows across turnarounds.
    """

    id: str
    param: str
    magnitude: float
    onset_s: float
    profile: Profile
    mode: Literal["scale", "offset"] = "scale"
    end_s: float | None = None
    resets: Sequence[float] = field(default_factory=tuple)
    label: str = ""

    def severity_at(self, t: float) -> float:
        """Severity fraction in [0, 1] at simulation time ``t``."""
        if t < self.onset_s:
            return 0.0
        if self.end_s is not None and t >= self.end_s:
            return 0.0

        start = self.onset_s
        for reset in self.resets:
            if self.onset_s < reset <= t:
                start = reset
        return float(self.profile(t - start))

    def apply(self, p: dict[str, float], t: float) -> None:
        severity = self.severity_at(t)
        if severity <= 0.0:
            return
        if self.mode == "scale":
            p[self.param] *= 1.0 - severity * self.magnitude
        else:
            p[self.param] += severity * self.magnitude

    def touched_params(self) -> tuple[str, ...]:
        return (self.param,)

    @property
    def layer(self) -> int:
        return 6


@dataclass
class DisturbanceFault:
    """An upstream or utility abnormality: it modifies a disturbance channel.

    Feed rate creeping up, the steam header sagging, feed arriving colder --
    none of these are wrong with *this* unit, but all of them are legitimate
    root causes for an investigation that starts here, and each produces the
    same first symptom as coil fouling.

    Applied to the precomputed channel array before the run rather than inside
    the loop. A disturbance is an input, so modifying it is exactly as physical
    as modifying a parameter, and doing it vectorized keeps the loop cheap.
    """

    id: str
    channel: str
    magnitude: float
    onset_s: float
    profile: Profile
    mode: Literal["scale", "offset"] = "offset"
    end_s: float | None = None
    label: str = ""

    def severity_at(self, t: float) -> float:
        if t < self.onset_s:
            return 0.0
        if self.end_s is not None and t >= self.end_s:
            return 0.0
        return float(self.profile(t - self.onset_s))

    def apply_channel(self, values, t_grid):
        """Return the channel with this abnormality superimposed."""
        import numpy as np

        severity = np.array([self.severity_at(float(t)) for t in t_grid])
        if self.mode == "scale":
            return values * (1.0 + severity * self.magnitude)
        return values + severity * self.magnitude

    def touched_params(self) -> tuple[str, ...]:
        return ()

    @property
    def layer(self) -> int:
        return 4


@dataclass
class ControlFault:
    """A control-system event: a loop put in manual, a setpoint moved.

    Layer 3, not layer 6. Nothing is wrong with the process or the
    instrumentation -- somebody changed how it is being controlled, usually
    during a shift and usually with a corresponding entry in the operator log.
    The dataset needs these because an agent that blames the process every time
    a trend moves will be wrong a good fraction of the time in a real plant.
    """

    id: str
    loop: str
    action: Literal["manual", "setpoint"]
    onset_s: float
    value: float = 0.0
    end_s: float | None = None
    label: str = ""
    _applied: bool = field(default=False, repr=False)
    _restore: float | None = field(default=None, repr=False)
    _restore_mode: str | None = field(default=None, repr=False)

    def active(self, t: float) -> bool:
        if t < self.onset_s:
            return False
        return self.end_s is None or t < self.end_s

    def apply_controls(self, t: float, loops: dict) -> None:
        """Invoked once per scan from the simulation's ``on_scan`` hook."""
        ctrl = loops.get(self.loop)
        if ctrl is None:
            return
        if self.active(t):
            if not self._applied:
                if self.action == "manual":
                    self._restore = ctrl.out
                    self._restore_mode = ctrl.mode
                    ctrl.set_mode("MAN", output=self.value or ctrl.out)
                else:
                    self._restore = ctrl.sp
                    ctrl.sp = self.value
                self._applied = True
        elif self._applied:
            if self.action == "manual":
                # Back to whatever it was in before -- a cascade slave returns
                # to CAS, not AUTO, or the mode tag lies for the rest of the run.
                ctrl.set_mode(self._restore_mode or "AUTO")
            elif self._restore is not None:
                ctrl.sp = self._restore
            self._applied = False

    def touched_params(self) -> tuple[str, ...]:
        return ()

    @property
    def layer(self) -> int:
        return 3


@dataclass
class InstrumentFault:
    """A layer-7 fault: it corrupts one tag's reading, not the process.

    Applied after the integration loop, in the measurement layer. The defining
    consequence is that a balance built from the affected tag stops closing
    while every real quantity is unchanged -- which is how it is told apart
    from a genuine process problem, and why it must never be applied as a
    parameter.
    """

    id: str
    tag: str
    magnitude: float
    onset_s: float
    profile: Profile
    mode: Literal["scale", "offset"] = "offset"
    end_s: float | None = None
    label: str = ""

    def severity_at(self, t: float) -> float:
        if t < self.onset_s:
            return 0.0
        if self.end_s is not None and t >= self.end_s:
            return 0.0
        return float(self.profile(t - self.onset_s))

    def touched_params(self) -> tuple[str, ...]:
        return ()

    @property
    def layer(self) -> int:
        return 7
