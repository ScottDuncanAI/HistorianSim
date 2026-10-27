"""Scenario configuration models.

A scenario is fully described by this structure plus a seed. Those two things
reproduce a dataset exactly, which is why generated data is a release artifact
rather than a repo contents (see .gitignore).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "TimeConfig",
    "LoopConfig",
    "AmbientConfig",
    "ChannelConfig",
    "DisturbanceConfig",
    "EpisodeConfig",
    "ScenarioConfig",
    "config_hash",
]


class _Base(BaseModel):
    # Typos in a YAML key should fail loudly rather than silently taking a
    # default. A mis-spelled gain that quietly reverts to 1.0 is a long
    # afternoon of debugging physics that was never wrong.
    model_config = ConfigDict(extra="forbid")


class TimeConfig(_Base):
    """Simulation clock: how long, how fast, and in what timezone.

    Two rates matter and they are not the same. ``dt_sim`` is the integration
    step, chosen for numerical stability against the fastest process time
    constant. ``dt_scan`` is how often the DCS executes controllers and holds
    their output. Real controllers run on a scan with a zero-order hold, and
    that is what produces the characteristic sawtooth in manipulated variables.
    """

    start: datetime = Field(
        default=datetime(2024, 3, 1, 0, 0, 0),
        description="Local wall-clock start of the run (naive; combined with `timezone`).",
    )
    timezone: str = Field(
        default="America/Chicago",
        description=(
            "Plant local timezone. Historian timestamps are stored UTC; operator "
            "logs and LIMS are local, so a DST transition inside the window is a "
            "feature rather than an accident."
        ),
    )
    days: float = Field(default=90.0, gt=0)
    dt_scan: float = Field(default=10.0, gt=0, description="DCS scan rate, seconds.")
    dt_sim: float = Field(
        default=5.0,
        gt=0,
        description=(
            "Integration step, seconds. 5 s is not a guess: a convergence study "
            "(tests/test_integrator.py) shows RK4 on this plant agrees with a "
            "0.5 s step to better than 1e-9, because the fastest time constant "
            "in the model is tens of seconds. Shorten it if a unit is added "
            "with faster dynamics."
        ),
    )

    @model_validator(mode="after")
    def _scan_is_multiple_of_sim(self) -> "TimeConfig":
        ratio = self.dt_scan / self.dt_sim
        if abs(ratio - round(ratio)) > 1e-9:
            raise ValueError(
                f"dt_scan ({self.dt_scan}s) must be an integer multiple of "
                f"dt_sim ({self.dt_sim}s); got ratio {ratio}"
            )
        if round(ratio) < 1:
            raise ValueError("dt_scan must be >= dt_sim")
        return self

    @property
    def n_sub(self) -> int:
        """Integration sub-steps per controller scan."""
        return int(round(self.dt_scan / self.dt_sim))

    @property
    def n_steps(self) -> int:
        """Number of controller scans in the run."""
        return int(round(self.days * 86400.0 / self.dt_scan))

    @property
    def duration_s(self) -> float:
        return self.n_steps * self.dt_scan


class LoopConfig(_Base):
    """A single PID loop.

    ``action`` follows plant convention rather than sign convention: a *reverse*
    acting controller raises its output when PV falls below setpoint, which is
    what a heating loop does. A *direct* acting controller raises output when PV
    rises above setpoint, which is what a cooling loop or a level loop draining
    a vessel does.
    """

    name: str = Field(description="Loop tag, e.g. TIC-101.")
    pv_source: str = Field(description="Name of the measured signal the loop reads.")
    mv_tag: str = Field(description="Output tag the loop writes, e.g. TV-101.")

    kc: float = Field(description="Proportional gain, output fraction per PV engineering unit.")
    ti: float = Field(default=0.0, ge=0, description="Integral time, seconds. 0 disables integral.")
    td: float = Field(default=0.0, ge=0, description="Derivative time, seconds.")

    sp: float = Field(description="Initial setpoint in PV engineering units.")
    action: Literal["reverse", "direct"] = "reverse"
    mode: Literal["AUTO", "MAN", "CAS"] = "AUTO"
    man_output: float = Field(default=0.5, description="Output held while in MAN.")

    out_min: float = 0.0
    out_max: float = 1.0
    out_rate_limit: float | None = Field(
        default=None,
        description="Max output change per second. None means unlimited.",
    )
    scan_s: float | None = Field(
        default=None,
        description="Loop scan period. None inherits the global dt_scan.",
    )
    sp_limits: tuple[float, float] | None = Field(
        default=None,
        description=(
            "Setpoint range in PV engineering units. Required on a cascade "
            "slave, since it maps the master's 0-1 output onto this range."
        ),
    )
    cascade_to: str | None = Field(
        default=None,
        description=(
            "Name of the slave loop this loop's output drives. The slave must "
            "be in CAS mode and declare sp_limits. A temperature loop cascaded "
            "onto steam flow is the usual arrangement, and it changes what the "
            "data looks like: the master's output is a flow setpoint in "
            "engineering units, not a valve position."
        ),
    )

    ratio_to: str | None = Field(
        default=None,
        description=(
            "Ratio control: the measured signal of the wild flow this loop "
            "follows. Every scan the setpoint becomes ratio x that reading. "
            "The loop must be in CAS mode, since its setpoint is remote."
        ),
    )
    ratio: float | None = Field(default=None, gt=0, description="Ratio for ratio_to.")

    @model_validator(mode="after")
    def _ratio_is_complete(self) -> "LoopConfig":
        if (self.ratio_to is None) != (self.ratio is None):
            raise ValueError(f"{self.name}: ratio_to and ratio must be given together")
        if self.ratio_to is not None and self.mode != "CAS":
            raise ValueError(f"{self.name} is a ratio station, so its mode must be CAS")
        return self

    @model_validator(mode="after")
    def _cascade_needs_a_target_range(self) -> "LoopConfig":
        if self.cascade_to is not None and self.cascade_to == self.name:
            raise ValueError(f"{self.name}: cannot cascade to itself")
        return self

    @model_validator(mode="after")
    def _limits_ordered(self) -> "LoopConfig":
        if self.out_max <= self.out_min:
            raise ValueError(f"{self.name}: out_max must exceed out_min")
        if not (self.out_min <= self.man_output <= self.out_max):
            raise ValueError(
                f"{self.name}: man_output {self.man_output} outside "
                f"[{self.out_min}, {self.out_max}]"
            )
        return self


class AmbientConfig(_Base):
    """Weather. The most important disturbance in the whole simulator.

    Ambient temperature reaches every heat balance in the plant, so it induces
    correlation between tags that have no causal connection at all. An analysis
    that mistakes that common-cause structure for a process relationship gets
    the wrong answer, which is precisely the trap worth building in.
    """

    annual_mean: float = Field(default=14.0, description="degC, yearly average.")
    annual_amplitude: float = Field(default=12.0, description="degC, summer peak above mean.")
    diurnal_amplitude: float = Field(default=6.0, description="degC, day-night swing.")
    diurnal_variability: float = Field(
        default=0.45,
        description="Fractional day-to-day variation in the diurnal swing (cloud cover).",
    )
    front_sigma: float = Field(default=3.2, description="degC, weather-front excursions.")
    front_tau_h: float = Field(default=40.0, description="Hours, front correlation time.")
    peak_hour: float = Field(default=15.0, description="Local hour of the daily maximum.")


class ChannelConfig(_Base):
    """One disturbance channel: a feed, a utility header, an upstream condition.

    Every channel is the same recipe -- a mean, an optional share of the
    ambient anomaly, an optional daily cycle, and coloured noise from its own
    RNG substream -- so a plant declares its channels as data rather than code.
    Configured in engineering units; ``si_divisor`` converts to what the unit
    model integrates in (3600 for a per-hour flow the model wants per second).
    """

    mean: float = Field(description="Nominal value, engineering units.")
    units: str = ""
    description: str = ""
    sigma: float = Field(default=0.0, ge=0, description="Short-term variability, 1 sigma.")
    tau_s: float = Field(default=3600.0, gt=0, description="Correlation time of the variability.")
    ambient_coupling: float = Field(
        default=0.0,
        description=(
            "Fraction of the ambient anomaly that reaches this channel. This is "
            "what makes unrelated temperatures share a diurnal component "
            "without either causing the other."
        ),
    )
    diurnal_amplitude: float = Field(default=0.0, description="Daily cycle amplitude.")
    diurnal_peak_hour: float = Field(default=15.0, description="Local hour of the daily maximum.")
    floor: float | None = Field(default=None, description="Clip below this, e.g. 0 for a flow.")
    si_divisor: float = Field(default=1.0, gt=0)
    rng_stream: str | None = Field(
        default=None, description="RNG substream name; defaults to the channel name."
    )


class DisturbanceConfig(_Base):
    ambient: AmbientConfig = Field(default_factory=AmbientConfig)
    channels: dict[str, ChannelConfig] = Field(
        default_factory=dict,
        description="Plant disturbance channels, filled from the plant's defaults.",
    )


class EpisodeConfig(_Base):
    """How fault episodes are laid out across the campaign.

    The shape matters as much as the content. A clean baseline long enough to
    train on, gaps wide enough that episodes do not smear together, a mix of
    severities so the dataset is not uniformly easy, some genuinely concurrent
    faults because plants have those, and benign anomalies so that "something
    moved" is not the same as "something is wrong".
    """

    baseline_days: float = Field(
        default=14.0,
        description="Fault-free days at the start. This is the PCA/ML training window.",
    )
    n_faults: int = Field(default=9, ge=0)
    min_gap_days: float = Field(
        default=2.0,
        description="Normal operation between episodes, so recovery is observable.",
    )
    n_benign: int = Field(
        default=3,
        description=(
            "Anomalies that are real but not faults: a deliberate rate change, "
            "an instrument recalibration, a planned shutdown. Without these "
            "there is no way to measure a false positive rate, and an agent "
            "that confidently finds a root cause in clean data is worse than "
            "useless in a control room."
        ),
    )
    n_concurrent: int = Field(
        default=2,
        description="Episodes deliberately overlapped; they break single-label classifiers.",
    )
    background_fouling: bool = Field(
        default=True,
        description=(
            "The plant's slow background degradation running underneath "
            "everything, reset at a cleaning. Ignored by plants without one."
        ),
    )
    difficulty: Literal["easy", "standard", "hard"] = "standard"
    severity_weights: dict[str, float] = Field(
        default_factory=lambda: {"subtle": 0.4, "moderate": 0.4, "obvious": 0.2}
    )
    symptom_weights: dict[str, float] = Field(
        default_factory=lambda: {"S1": 0.4, "S2": 0.2, "S3": 0.15, "S4": 0.25}
    )
    cause_ids: list[str] | None = Field(
        default=None,
        description=(
            "Pin the exact root causes, in onset order, instead of sampling them "
            "from symptom_weights. Sampling draws uniformly *with replacement* "
            "within a symptom class, so a nine-episode dataset reliably repeats "
            "causes -- fine for generating variety, wrong for a published "
            "benchmark where the label mix has to be fixed and comparable across "
            "seeds. When set, the seed still controls onset timing, severity, "
            "noise and weather; only the cause sequence is pinned. Length must "
            "equal n_faults, and symptom_weights is ignored."
        ),
    )
    severities: list[Literal["subtle", "moderate", "obvious"]] | None = Field(
        default=None,
        description=(
            "Pin the severity of each pinned cause, parallel to cause_ids. A "
            "benchmark needs its difficulty mix fixed, not drawn from the seed."
        ),
    )
    benign_kinds: list[str] | None = Field(
        default=None,
        description=(
            "Which of the plant's benign events to lay out, in order. Defaults "
            "to cycling through the plant's default list."
        ),
    )


class ScenarioConfig(_Base):
    """Top-level scenario definition.

    Extended one section at a time as layers come online: disturbances,
    degradation, faults, instruments, historian and context each add a field.
    """

    name: str = Field(description="Scenario identifier, e.g. exchanger-fouling.")
    unit: str = Field(description="Registered plant name, e.g. heated_stirred_tank.")
    recipe: str | None = Field(
        default=None,
        description="Dataset recipe the scenario was built from, e.g. rca-benchmark.",
    )
    description: str = ""
    seed: int = 42

    time: TimeConfig = Field(default_factory=TimeConfig)
    params: dict[str, float] = Field(
        default_factory=dict,
        description="Unit physical parameters; validated by the unit model itself.",
    )
    loops: list[LoopConfig] = Field(default_factory=list)
    disturbances: DisturbanceConfig = Field(default_factory=DisturbanceConfig)
    episodes: EpisodeConfig = Field(default_factory=EpisodeConfig)
    ballast_tags: int = Field(
        default=60,
        ge=0,
        description=(
            "Tags from neighbouring units that run normally and share only the "
            "weather. What drives difficulty is the ratio of relevant to "
            "irrelevant tags, not the total: with every tag bearing on the "
            "fault, retrieval is trivial."
        ),
    )

    @field_validator("loops")
    @classmethod
    def _unique_loop_names(cls, loops: list[LoopConfig]) -> list[LoopConfig]:
        names = [loop.name for loop in loops]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate loop names: {sorted(dupes)}")
        return loops

    @model_validator(mode="after")
    def _cascades_resolve(self) -> "ScenarioConfig":
        by_name = {loop.name: loop for loop in self.loops}
        for loop in self.loops:
            if loop.cascade_to is None:
                continue
            slave = by_name.get(loop.cascade_to)
            if slave is None:
                raise ValueError(
                    f"{loop.name} cascades to unknown loop {loop.cascade_to!r}"
                )
            if slave.sp_limits is None:
                raise ValueError(
                    f"{slave.name} is a cascade slave and must declare sp_limits"
                )
            if slave.mode != "CAS":
                raise ValueError(
                    f"{slave.name} is driven by {loop.name} so its mode must be CAS"
                )
        return self

    def loop(self, name: str) -> LoopConfig:
        for cfg in self.loops:
            if cfg.name == name:
                return cfg
        raise KeyError(f"no loop named {name!r}; have {[l.name for l in self.loops]}")


def config_hash(cfg: ScenarioConfig | dict[str, Any]) -> str:
    """Stable short hash of a configuration.

    Recorded in the dataset manifest so a dataset can be traced back to the
    exact configuration that produced it. Sorted keys and a fixed separator
    make it independent of field ordering.
    """
    if isinstance(cfg, BaseModel):
        payload = cfg.model_dump(mode="json")
    else:
        payload = cfg
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.blake2b(blob.encode("utf-8"), digest_size=8).hexdigest()
