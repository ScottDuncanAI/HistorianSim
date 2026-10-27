"""PID control, the way a DCS actually implements it.

Three details matter more than the algebra:

* **Derivative acts on PV, not error.** A setpoint change should not produce a
  derivative kick, because real controllers are built this way and operators
  step setpoints constantly.
* **Anti-windup by conditional integration.** When a fault drives a valve to
  its stop, the loop must sit saturated *without* accumulating integral. The
  recovery behaviour after the fault clears is a signature worth learning from,
  and a wound-up integrator destroys it.
* **The loop reads a sensor, not the truth.** This class only ever receives a
  measured PV. Sensor lag and noise belong inside the feedback loop, so they
  are the caller's responsibility to apply before calling :meth:`step`.
"""

from __future__ import annotations

from historiansim.config.schema import LoopConfig

__all__ = ["PID"]


def _clamp(value: float, low: float, high: float) -> float:
    """Scalar clamp.

    Deliberately not ``np.clip``: on single floats numpy's dispatch machinery
    costs around 25 us per call, and this runs several times per controller per
    scan for tens of millions of scans. Profiling put it at half the total
    runtime of the simulator.
    """
    if value < low:
        return low
    if value > high:
        return high
    return value


class PID:
    """Positional-form PID in the ISA dependent-gain arrangement.

    Parameters
    ----------
    cfg:
        Loop configuration -- gains, setpoint, action, limits.
    pv0:
        Initial process variable, used to seed the derivative history so the
        first scan does not see a false rate of change.
    out0:
        Initial output. Defaults to the steady-state bias implied by the
        configuration. Passing the true steady-state valve position starts the
        run without a transient, which matters when the first days of the
        dataset are meant to be a clean baseline.
    """

    def __init__(self, cfg: LoopConfig, pv0: float, out0: float | None = None):
        self.cfg = cfg
        self.name = cfg.name
        self.mv_tag = cfg.mv_tag

        self.kc = float(cfg.kc)
        self.ti = float(cfg.ti)
        self.td = float(cfg.td)
        self.sp = float(cfg.sp)
        self.mode = cfg.mode

        # Reverse acting raises output when PV falls below setpoint (heating).
        # Direct acting raises output when PV rises above setpoint (cooling).
        self._sign = 1.0 if cfg.action == "reverse" else -1.0

        self.out_min = float(cfg.out_min)
        self.out_max = float(cfg.out_max)
        self.rate_limit = cfg.out_rate_limit

        self.pv_prev = float(pv0)

        if out0 is None:
            out0 = cfg.man_output
        self.out = _clamp(float(out0), self.out_min, self.out_max)

        # Integral carries the bias: at steady state the proportional and
        # derivative terms vanish and the output is the integral alone.
        self.integral = self.out

        # A loop may scan slower than the simulation's global scan; between its
        # own executions the output is simply held.
        self.scan_s = cfg.scan_s
        self._since_exec = 0.0

    # -- mode handling ----------------------------------------------------

    def set_mode(self, mode: str, output: float | None = None) -> None:
        """Switch mode with a bumpless transfer.

        Going to AUTO back-calculates the integral so the output does not jump,
        which is what a real controller does and what an operator expects.
        """
        if mode == self.mode:
            return
        if mode == "MAN" and output is not None:
            self.out = _clamp(float(output), self.out_min, self.out_max)
        if mode in ("AUTO", "CAS"):
            self.integral = self.out  # P and D are ~0 at the moment of transfer
        self.mode = mode

    # -- execution --------------------------------------------------------

    def step(self, pv: float, dt: float) -> float:
        """Execute one scan and return the output, in output units (0-1).

        ``dt`` is the elapsed time since the previous call. If the loop has its
        own slower scan period the output is held (zero-order hold) until the
        period elapses, which is what produces the stair-stepping visible in
        real manipulated-variable trends.
        """
        self._since_exec += dt
        if self.scan_s is not None and self._since_exec < self.scan_s - 1e-9:
            return self.out
        step_dt = self._since_exec
        self._since_exec = 0.0

        if self.mode == "MAN":
            # Track the process so a later switch to AUTO is bumpless.
            self.pv_prev = pv
            self.integral = self.out
            return self.out

        err = self._sign * (self.sp - pv)

        p_term = self.kc * err
        d_term = 0.0
        if self.td > 0.0 and step_dt > 0.0:
            # Derivative on PV, negated, so a setpoint step produces no kick.
            d_term = -self._sign * self.kc * self.td * (pv - self.pv_prev) / step_dt

        out_unsat = p_term + self.integral + d_term
        out = _clamp(out_unsat, self.out_min, self.out_max)

        # Conditional integration: accumulate unless we are pinned against a
        # stop and the error would push us further into it. Integrating in the
        # relieving direction is allowed, so recovery is prompt rather than
        # waiting out an unwound integrator.
        if self.ti > 0.0:
            pinned_high = out_unsat > self.out_max and err > 0.0
            pinned_low = out_unsat < self.out_min and err < 0.0
            if not (pinned_high or pinned_low):
                self.integral += self.kc * step_dt / self.ti * err
                self.integral = _clamp(
                    self.integral, self.out_min - 1.0, self.out_max + 1.0
                )

        if self.rate_limit is not None:
            max_move = self.rate_limit * step_dt
            out = _clamp(out, self.out - max_move, self.out + max_move)

        self.pv_prev = pv
        self.out = out
        return out

    @property
    def saturated(self) -> bool:
        return self.out <= self.out_min + 1e-9 or self.out >= self.out_max - 1e-9

    def __repr__(self) -> str:
        return (
            f"PID({self.name}, mode={self.mode}, sp={self.sp:.3g}, "
            f"out={self.out:.3f}, kc={self.kc:.3g}, ti={self.ti:.4g})"
        )
