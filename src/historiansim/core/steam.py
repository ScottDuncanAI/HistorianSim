"""Saturated steam properties.

Correlations rather than a steam table, deliberately. The dataset needs steam
temperature to *move correctly with header pressure* -- that coupling is what
makes "steam header pressure decline" a competing explanation for a rising
steam valve, and it has to fall out of physics rather than be scripted. Absolute
accuracy of a degree or two changes nothing about the diagnostic structure.

Valid over roughly 1-15 bar absolute, which covers any plant utility header.
"""

from __future__ import annotations

import numpy as np

__all__ = ["ATM_BAR", "t_sat", "h_fg"]

ATM_BAR = 1.013  # bar, to convert gauge to absolute


def t_sat(p_gauge_bar: float | np.ndarray) -> float | np.ndarray:
    """Saturation temperature of steam, degC, from gauge pressure in bar.

    ``T = 100 * P_abs**0.25`` is exact at atmospheric pressure and stays within
    about 2 degC of steam-table values up to 10 bar absolute.
    """
    p_abs = np.maximum(p_gauge_bar + ATM_BAR, 1e-6)
    return 100.0 * p_abs**0.25


def h_fg(t_sat_c: float | np.ndarray) -> float | np.ndarray:
    """Latent heat of vaporisation, J/kg, from saturation temperature in degC.

    Linear in temperature: 2257 kJ/kg at 100 degC falling to ~2066 kJ/kg at
    165 degC. Within about 2 % of steam-table values across the useful range.

    It matters that this *falls* with pressure. Steam mass flow is duty divided
    by latent heat, so a header pressure change moves the indicated steam flow
    even at constant duty -- a small effect, but one that shows up in a careful
    energy balance and would be missing if latent heat were a constant.
    """
    return (2500.0 - 2.4 * np.asarray(t_sat_c, dtype=float)) * 1000.0
