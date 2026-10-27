"""Valve characteristics and stiction.

Two things here shape the dataset:

**Installed characteristic.** An equal-percentage valve's gain is proportional
to its own flow, so the temperature loop gets *more* aggressive as fouling
drives the valve open. That behaviour is emergent -- nobody schedules it -- and
it is the kind of detail that separates simulated data from generated data.

**Stiction.** A sticking valve produces a limit cycle that looks like bad
tuning on a trend but is not: the manipulated variable moves in square-ish
jumps while the controlled variable sweeps triangular between them. Plotting PV
against OP traces a parallelogram. That signature is how a diagnostician tells
stiction from an aggressive controller, so it has to be modelled properly
rather than approximated with a sine wave.
"""

from __future__ import annotations

import math

__all__ = ["linear", "equal_percentage", "quick_opening", "characteristic", "Stiction"]


def linear(opening: float) -> float:
    """Flow fraction proportional to travel."""
    return min(max(opening, 0.0), 1.0)


def equal_percentage(opening: float, rangeability: float = 50.0) -> float:
    """Equal-percentage trim: equal travel gives equal *percentage* flow change.

    ``f(x) = R**(x-1)``, so gain d f/dx = ln(R) * f(x) rises with flow.
    """
    x = min(max(opening, 0.0), 1.0)
    return rangeability ** (x - 1.0)


def quick_opening(opening: float) -> float:
    """Most of the flow arrives in the first part of travel."""
    return math.sqrt(min(max(opening, 0.0), 1.0))


_CHARACTERISTICS = {
    "linear": linear,
    "equal_percentage": equal_percentage,
    "quick_opening": quick_opening,
}


def characteristic(name: str):
    try:
        return _CHARACTERISTICS[name]
    except KeyError:
        raise KeyError(
            f"unknown valve characteristic {name!r}. "
            f"Available: {sorted(_CHARACTERISTICS)}"
        ) from None


def inverse_equal_percentage(flow_fraction: float, rangeability: float = 50.0) -> float:
    """Travel that produces a given flow fraction. Used to start at equilibrium."""
    f = min(max(flow_fraction, 1.0 / rangeability), 1.0)
    return 1.0 + math.log(f) / math.log(rangeability)


class Stiction:
    """Two-parameter stiction model (deadband plus slip-jump).

    ``S`` is the total static friction band the signal must cross before the
    stem moves at all; ``J`` is the jump it makes once it breaks free. With
    ``J < S`` the valve overshoots and undershoots around the demand, which is
    what sustains a limit cycle even with a well-tuned controller.

    Parameters are fractions of full travel. Typical field values for a
    neglected control valve are S of 2-10 % and J of roughly half of S.
    """

    def __init__(self, deadband: float, jump: float, position: float = 0.0):
        if deadband < 0 or jump < 0:
            raise ValueError("stiction parameters must be non-negative")
        self.deadband = float(deadband)
        self.jump = float(jump)
        self.position = float(position)
        self._moving = False

    def __call__(self, demand: float) -> float:
        """Map controller demand to actual stem position."""
        demand = min(max(demand, 0.0), 1.0)
        error = demand - self.position

        if self._moving:
            # Once sliding, the stem tracks until the signal reverses enough to
            # re-establish static friction.
            if abs(error) < self.jump * 0.5:
                self._moving = False
            else:
                self.position = demand
                return self.position

        if abs(error) > self.deadband:
            # Break free and slip past the deadband by the jump amount.
            direction = 1.0 if error > 0 else -1.0
            self.position = min(
                max(self.position + direction * max(self.jump, abs(error) - self.deadband), 0.0),
                1.0,
            )
            self._moving = True

        return self.position
