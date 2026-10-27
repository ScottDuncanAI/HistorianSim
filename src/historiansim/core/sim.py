"""The integration loop: layers 2 through 6.

Everything in here changes how state evolves, so it has to live inside the
loop. Measurement and historian corruption (layers 7-9) are pure
post-processing on the finished arrays and must not appear anywhere below --
nothing about a quantized transmitter can be allowed to alter the physics.

The order within a scan mirrors a real DCS:

1. resolve disturbances for this instant
2. apply degradation and faults as *parameter modifiers*
3. execute controllers against what their sensors report
4. integrate, holding controller outputs constant across the scan
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol, Sequence

import numpy as np

from historiansim.config.schema import ScenarioConfig
from historiansim.core.integrator import integrate_scan
from historiansim.core.pid import PID
from historiansim.core.valve import Stiction
from historiansim.plants.unit import UnitModel

__all__ = [
    "SimResult",
    "simulate",
    "ConstantDisturbance",
    "MODE_CODES",
    "apply_disturbance_faults",
]

MODE_CODES = {"MAN": 0, "AUTO": 1, "CAS": 2}


class DisturbanceSource(Protocol):
    """Supplies the disturbance vector for a scan index."""

    names: tuple[str, ...]

    def resolve(self, k: int, t: float) -> dict[str, float]: ...


class ProcessFault(Protocol):
    """A layer-6 fault: it modifies parameters, never signals."""

    def apply(self, p: dict[str, float], t: float) -> None: ...

    def touched_params(self) -> tuple[str, ...]: ...


def _map_setpoint(output: float, limits: tuple[float, float] | None) -> float:
    """Map a master's 0-1 output onto a slave's setpoint range."""
    if limits is None:
        return output
    lo, hi = limits
    return lo + output * (hi - lo)


def _unmap_setpoint(sp: float, limits: tuple[float, float] | None) -> float:
    """Inverse of :func:`_map_setpoint`, for bumpless cascade initialisation."""
    if limits is None:
        return sp
    lo, hi = limits
    if hi == lo:
        return 0.0
    return min(max((sp - lo) / (hi - lo), 0.0), 1.0)


def _order_by_cascade(controllers: list[PID]) -> list[PID]:
    """Sort so every master executes before the slave it drives.

    Without this the slave acts on last scan's setpoint, which adds a scan of
    phantom deadtime to the cascade and quietly changes its stability.
    """
    remaining = list(controllers)
    ordered: list[PID] = []
    placed: set[str] = set()
    while remaining:
        # A loop can execute once nothing still waiting is cascading into it.
        ready = [
            c for c in remaining
            if all(o.cfg.cascade_to != c.name for o in remaining if o is not c)
        ]
        if not ready:
            raise ValueError(
                f"cascade loop detected among {[c.name for c in remaining]}"
            )
        for ctrl in ready:
            ordered.append(ctrl)
            placed.add(ctrl.name)
            remaining.remove(ctrl)
    return ordered


def apply_disturbance_faults(bundle, faults, t_grid):
    """Superimpose any disturbance-channel faults onto a precomputed bundle.

    Done before the run rather than inside it. A disturbance is an input, so
    modifying the array is exactly as physical as modifying a parameter, and it
    keeps the integration loop free of per-scan branching.
    """
    channels = dict(bundle.channels)
    for fault in faults:
        if not hasattr(fault, "apply_channel"):
            continue
        if fault.channel not in channels:
            raise KeyError(
                f"{fault.id} targets disturbance channel {fault.channel!r}, "
                f"which this bundle does not have: {sorted(channels)}"
            )
        channels[fault.channel] = fault.apply_channel(channels[fault.channel], t_grid)
    return type(bundle)(channels)


@dataclass
class ConstantDisturbance:
    """Fixed disturbance vector. Useful for physics checks, never for datasets."""

    values: dict[str, float]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self.values)

    def resolve(self, k: int, t: float) -> dict[str, float]:
        return dict(self.values)


@dataclass
class SimResult:
    """True process history on a clean, regular grid.

    This is what the measurement layer later corrupts. Keeping it pristine and
    separate is what makes it possible to state, in the ground truth manifest,
    exactly when a fault began versus when it first became observable.
    """

    t: np.ndarray
    states: np.ndarray
    signals: dict[str, np.ndarray]
    outputs: dict[str, np.ndarray]
    setpoints: dict[str, np.ndarray]
    modes: dict[str, np.ndarray]
    disturbances: dict[str, np.ndarray]
    params: dict[str, np.ndarray] = field(default_factory=dict)
    dt_scan: float = 1.0

    @property
    def n(self) -> int:
        return len(self.t)

    def series(self, name: str) -> np.ndarray:
        """Look a series up across signals, outputs, setpoints and disturbances."""
        for source in (
            self.signals,
            self.outputs,
            self.setpoints,
            self.modes,
            self.disturbances,
            self.params,
        ):
            if name in source:
                return source[name]
        raise KeyError(f"no series named {name!r}")

    def names(self) -> list[str]:
        out: list[str] = []
        for source in (
            self.signals,
            self.outputs,
            self.setpoints,
            self.modes,
            self.disturbances,
            self.params,
        ):
            out.extend(source)
        return out


def simulate(
    cfg: ScenarioConfig,
    disturbances: DisturbanceSource,
    unit: UnitModel | None = None,
    faults: Sequence[ProcessFault] = (),
    sensor_fn: Callable[[dict[str, float], int], dict[str, float]] | None = None,
    on_scan: Callable[[int, float, dict[str, PID]], None] | None = None,
    x0: np.ndarray | None = None,
    initial_outputs: dict[str, float] | None = None,
    progress: bool = False,
) -> SimResult:
    """Run the process forward and return its true history.

    Parameters
    ----------
    sensor_fn:
        Maps true signals to what the controllers' transmitters report. Sensor
        lag and noise belong *inside* the feedback loop, so this is applied
        before controllers execute rather than afterwards. Defaults to perfect
        measurement, which is only appropriate for physics checks.
    on_scan:
        Called before controllers execute, with the controllers keyed by loop
        name. This is where operator actions live -- setpoint moves, putting a
        loop in manual -- because those are things a person does to the control
        system, not disturbances the process experiences.
    """
    if unit is None:
        from historiansim.plants import get_plant

        unit = get_plant(cfg.unit).unit(cfg.params)

    tcfg = cfg.time
    n_steps, n_sub, dt_scan, dt_sim = tcfg.n_steps, tcfg.n_sub, tcfg.dt_scan, tcfg.dt_sim
    base_params = dict(unit.params)

    d0 = disturbances.resolve(0, 0.0)
    missing = set(unit.disturbance_names) - set(d0)
    if missing:
        raise ValueError(f"disturbance source is missing {sorted(missing)}")

    # -- initial condition -------------------------------------------------
    if initial_outputs is None:
        targets = {loop.pv_source: loop.sp for loop in cfg.loops}
        try:
            initial_outputs = unit.steady_inputs(targets, d0, base_params)
        except (NotImplementedError, KeyError):
            initial_outputs = {mv: 0.5 for mv in unit.mv_names}
    u = {mv: float(initial_outputs.get(mv, 0.5)) for mv in unit.mv_names}

    if x0 is None:
        x0 = unit.steady_state(u, d0, base_params)
    x = np.asarray(x0, dtype=float).copy()

    # -- controllers -------------------------------------------------------
    sig0 = unit.signals(0.0, x, u, d0, base_params)
    controllers: list[PID] = []
    for loop in cfg.loops:
        if loop.ratio_to is not None and loop.ratio_to not in sig0:
            raise ValueError(
                f"{loop.name}: ratio_to {loop.ratio_to!r} is not a signal of {unit.name}"
            )
        if loop.pv_source not in sig0:
            raise ValueError(
                f"{loop.name}: pv_source {loop.pv_source!r} is not a signal of "
                f"{unit.name}. Available: {sorted(sig0)}"
            )
        controllers.append(
            PID(loop, pv0=sig0[loop.pv_source], out0=u.get(loop.mv_tag))
        )
    controllers = _order_by_cascade(controllers)
    by_name = {c.name: c for c in controllers}

    # A cascade master's output is its slave's setpoint, so it must start at
    # the value that holds the slave where it already is -- otherwise the run
    # opens with a transient the clean baseline cannot afford.
    for ctrl in controllers:
        target = ctrl.cfg.cascade_to
        if target is not None:
            slave = by_name[target]
            ctrl.out = ctrl.integral = _unmap_setpoint(slave.sp, slave.cfg.sp_limits)

    # Sticking valves: created only where the unit declares a stiction
    # parameter and something has actually made it non-zero. A healthy valve
    # must cost nothing and, more importantly, must not perturb the RNG or the
    # signal path at all.
    stiction: dict[str, Stiction] = {}
    stiction_params = getattr(unit, "stiction_params", {})

    # Only log parameters something actually moves; copying the whole dict
    # every scan for 780k scans is wasted memory and time.
    dynamic_params: list[str] = sorted(
        {name for f in faults for name in f.touched_params()}
    )
    process_faults = [f for f in faults if hasattr(f, "apply")]
    control_faults = [f for f in faults if hasattr(f, "apply_controls")]

    # -- preallocate -------------------------------------------------------
    t_grid = np.arange(n_steps, dtype=float) * dt_scan
    states = np.empty((n_steps, len(unit.state_names)))
    signals = {k: np.empty(n_steps) for k in sig0}
    outputs = {mv: np.empty(n_steps) for mv in unit.mv_names}
    setpoints = {f"{c.name}.SP": np.empty(n_steps) for c in controllers}
    loop_outputs = {f"{c.name}.OP": np.empty(n_steps) for c in controllers}
    modes = {f"{c.name}.MODE": np.empty(n_steps, dtype=np.int8) for c in controllers}
    dist_out = {k: np.empty(n_steps) for k in d0}
    param_out = {f"PARAM-{k}": np.empty(n_steps) for k in dynamic_params}

    # -- main loop ---------------------------------------------------------
    for k in range(n_steps):
        t = t_grid[k]

        # layer 4
        d = disturbances.resolve(k, t)

        # layers 5 and 6: degradation and faults modify parameters only
        p = dict(base_params)
        for fault in process_faults:
            fault.apply(p, t)

        # layer 3: control-system events, then any caller-supplied action
        for fault in control_faults:
            fault.apply_controls(t, by_name)
        if on_scan is not None:
            on_scan(k, t, by_name)

        # layer 3: controllers see instruments, not truth
        true_sig = unit.signals(t, x, u, d, p)
        seen = sensor_fn(true_sig, k) if sensor_fn is not None else true_sig
        for ctrl in controllers:
            # A ratio station follows the measured wild flow while it is in
            # cascade; taken out of CAS it holds whatever setpoint it had.
            if ctrl.cfg.ratio_to is not None and ctrl.mode == "CAS":
                ctrl.sp = ctrl.cfg.ratio * seen[ctrl.cfg.ratio_to]
            out = ctrl.step(seen[ctrl.cfg.pv_source], dt_scan)
            target = ctrl.cfg.cascade_to
            if target is None:
                u[ctrl.mv_tag] = out
            else:
                # The master writes a setpoint, not a valve position.
                slave = by_name[target]
                slave.sp = _map_setpoint(out, slave.cfg.sp_limits)

        # A sticking stem sits between the controller and the process, so the
        # valve position the physics sees is not the position the loop asked
        # for. That gap is the whole signature.
        for mv, param in stiction_params.items():
            band = p.get(param, 0.0)
            if band <= 0.0:
                continue
            valve = stiction.get(mv)
            if valve is None:
                valve = stiction[mv] = Stiction(band, band * 0.5, position=u[mv])
            valve.deadband, valve.jump = band, band * 0.5
            u[mv] = valve(u[mv])

        # record the instant before integrating so signals, outputs and states
        # all refer to the same point in time
        states[k] = x
        for key, arr in signals.items():
            arr[k] = true_sig[key]
        for mv, arr in outputs.items():
            arr[k] = u[mv]
        for ctrl in controllers:
            setpoints[f"{ctrl.name}.SP"][k] = ctrl.sp
            loop_outputs[f"{ctrl.name}.OP"][k] = ctrl.out
            modes[f"{ctrl.name}.MODE"][k] = MODE_CODES[ctrl.mode]
        for key, arr in dist_out.items():
            arr[k] = d[key]
        for key in dynamic_params:
            param_out[f"PARAM-{key}"][k] = p[key]

        # layer 2: integrate with u held constant across the scan
        x = integrate_scan(
            lambda tt, xx: unit.derivatives(tt, xx, u, d, p), t, x, dt_sim, n_sub
        )

        if progress and n_steps >= 20 and k % (n_steps // 20) == 0:
            print(f"  {100 * k / n_steps:3.0f}%", end="\r", flush=True)

    if progress:
        print("  100%")

    return SimResult(
        t=t_grid,
        states=states,
        signals=signals,
        outputs={**outputs, **loop_outputs},
        setpoints=setpoints,
        modes=modes,
        disturbances=dist_out,
        params=param_out,
        dt_scan=dt_scan,
    )
