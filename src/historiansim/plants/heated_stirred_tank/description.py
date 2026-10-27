"""The TK-101 sections of the process description.

Written from the model rather than by hand, so the design figures cannot drift
away from the parameters actually integrated. Every number below is computed
from :meth:`HeatedStirredTank.default_params`, the loop configuration and the
disturbance configuration.
"""

from __future__ import annotations

import math

import numpy as np

from historiansim.config.schema import ScenarioConfig
from historiansim.core.steam import ATM_BAR, h_fg, t_sat
from historiansim.plants.base import PlantDescription, Section
from historiansim.plants.heated_stirred_tank.loops import DESIGN_D
from historiansim.plants.heated_stirred_tank.model import HeatedStirredTank

__all__ = ["describe"]

#: Where each unit tag is measured and what it means physically.
TAG_NOTES = {
    "TIC-101.PV": "Bulk liquid temperature, thermowell in the vessel. Controlled variable of TIC-101.",
    "TIC-101.SP": "Operator-entered temperature setpoint.",
    "TIC-101.OP": "Master output, 0-100 %. Written to FIC-201 as its setpoint (0-100 % = 0-3000 kg/h).",
    "TIC-101.MODE": "Controller mode (0 MAN, 1 AUTO, 2 CAS). Normal: 1.",
    "FIC-201.PV": "Steam mass flow to the coil, orifice/DP meter downstream of TV-101.",
    "FIC-201.SP": "Remote setpoint from TIC-101 when in cascade; FIC-201.SP = 30 x TIC-101.OP.",
    "FIC-201.OP": "Slave output: demand signal to the TV-101 positioner.",
    "FIC-201.MODE": "Controller mode (0 MAN, 1 AUTO, 2 CAS). Normal: 2.",
    "LIC-101.PV": "Vessel level, primary DP-cell transmitter LI-101. Controlled variable of LIC-101.",
    "LIC-101.SP": "Operator-entered level setpoint.",
    "LIC-101.OP": "Demand signal to the LV-101 positioner.",
    "LIC-101.MODE": "Controller mode (0 MAN, 1 AUTO, 2 CAS). Normal: 1.",
    "TV-101.POS": "Stem position feedback from the TV-101 positioner.",
    "LV-101.POS": "Stem position feedback from the LV-101 positioner.",
    "FI-101": "Feed volumetric flow, on the inlet line from upstream storage, downstream of feed pump P-100.",
    "TI-100": "Feed temperature, on the inlet line.",
    "FI-102": "Product volumetric flow, on the outlet line downstream of LV-101.",
    "TI-102": "Product temperature, on the outlet line.",
    "LI-102": "Vessel level, second independent DP-cell transmitter on separate taps. Indication only.",
    "PI-201": "Steam header pressure, upstream of TV-101.",
    "TI-201": "Steam temperature at the header (saturated steam), upstream of TV-101.",
    "TI-202": "Condensate temperature on the condensate return line downstream of the coil's steam trap.",
    "TI-901": "Ambient air temperature at the unit.",
    "AI-101": "On-line purity analyzer on the product line (sample system and cycle time, see below).",
}


def describe(cfg: ScenarioConfig) -> PlantDescription:
    unit = HeatedStirredTank()
    p = unit.params
    d = dict(DESIGN_D)
    u = unit.steady_inputs({"LI-101": 2.0, "TI-101": 75.0}, d, p)
    sig = unit.signals(0.0, np.array([2.0, 75.0]), u, d, p)

    feed_m3h = d["feed_flow"] * 3600.0
    level = 2.0
    volume = p["area"] * level
    residence_min = volume / d["feed_flow"] / 60.0
    p_hdr = d["steam_header_P"]
    t_steam = float(t_sat(p_hdr))
    latent_kj = float(h_fg(t_steam)) / 1000.0
    duty_kw = float(sig["CALC-DUTY"])
    steam_kgh = float(sig["FI-201"])
    ua_eff = float(sig["CALC-UA"])
    tv_design = u["TV-101"] * 100.0
    lv_design = u["LV-101"] * 100.0
    cv_m3h = p["Cv_out"] * 3600.0
    loss_kw = p["UA_loss"] * (75.0 - d["T_amb"]) / 1000.0
    diameter = 2.0 * math.sqrt(p["area"] / math.pi)
    R = p["valve_rangeability"]
    ua_clean_kw = p["UA_coil"] / 1000.0
    rho, cp = p["rho"], p["cp"]
    cp_kj = cp / 1000.0

    loops = {lp.name: lp for lp in cfg.loops}
    tic, fic, lic = loops["TIC-101"], loops["FIC-201"], loops["LIC-101"]
    fic_lo, fic_hi = fic.sp_limits
    dt_scan = cfg.time.dt_scan
    amb = cfg.disturbances.ambient
    channels = cfg.disturbances.channels
    steam = channels.get("steam_header_P")
    feed_flow = channels.get("feed_flow")
    feed_temp = channels.get("feed_temp")

    # =====================================================================
    s1: list[str] = []
    w = s1.append
    w("TK-101 is a continuous, agitated hold tank heated by a submerged steam")
    w("coil. It receives a dilute aqueous process stream (about 6 wt % dissolved")
    w("organics, the balance water) from upstream reaction storage, holds it at")
    w("temperature so that a residual intermediate completes hydrolysis, and")
    w("passes it on to downstream recovery.")
    w("")
    w("Conversion depends on temperature and residence time together, and the")
    w("product specification is a temperature *window* rather than a minimum:")
    w("")
    w("- **Too cold:** hydrolysis is incomplete within the available residence")
    w("  time and unconverted intermediate carries forward.")
    w("- **Too hot:** product thermally degrades to coloured by-products.")
    w("")
    w("Product purity (mass fraction of desired product in the dissolved")
    w("organics) is described by the empirical correlation")
    w("")
    w("```")
    w(f"purity [%] = 99.4 - {p['purity_curvature']:g} x (T - {p['purity_peak_T']:g})^2      T = bulk temperature, degC")
    w("```")
    w("")
    w("| Bulk temperature, degC | 60 | 65 | 70 | 75 | 78 | 82 | 88 |")
    w("|---|---|---|---|---|---|---|---|")
    vals = " | ".join(f"{unit.product_purity(t, p):.2f}" for t in (60, 65, 70, 75, 78, 82, 88))
    w(f"| Purity, % | {vals} |")
    w("")
    w("The unit is normally operated at **75 degC**, deliberately on the cool")
    w("side of the 78 degC optimum: over-temperature damage is irreversible,")
    w("whereas unconverted material can be handled downstream. Sustained")
    w("operation below about 65 degC (purity below about 96 %) is off")
    w("specification.")
    w("")
    w("The purity correlation is the only composition model. There is no species")
    w("balance, so purity cannot be reconciled against anything other than bulk")
    w("temperature.")

    # =====================================================================
    s2: list[str] = []
    w = s2.append
    w("```")
    w("  steam header (shared utility)              feed from upstream storage")
    w("     |                                             |")
    w("     |                                          (P-100) feed transfer pump")
    w("     |  PI-201 pressure                            |  FI-101 flow")
    w("     |  TI-201 temperature                         |  TI-100 temperature")
    w("     |                                             v")
    w("   [TV-101] steam control valve        +-------------------------------+")
    w("     |  FIC-201 steam flow             |  TK-101  agitated vessel      |")
    w("     +-------------------------------->|   E-101  submerged steam coil |")
    w("                                       |   LI-101 level (LIC-101)      |")
    w("                                       |   LI-102 level (independent)  |")
    w("                                       |   TI-101 bulk temp (TIC-101)  |")
    w("                                       +------+----------------+-------+")
    w("                                              |                |")
    w("                                   condensate |                | product (single outlet)")
    w("                                              v                v")
    w("                                        steam trap         [LV-101] level control valve")
    w("                                              |                |  FI-102 flow")
    w("                                    TI-202 temperature         |  TI-102 temperature")
    w("                                              v                |  AI-101 purity analyzer")
    w("                                     condensate return         v")
    w("                                                         downstream recovery")
    w("```")
    w("")
    w("- **TK-101**: vertical cylindrical vessel, "
      f"{diameter:.1f} m diameter ({p['area']:.2f} m2 cross-section), {p['h_max']:.1f} m tall,")
    w("  well mixed by an agitator, so the outlet is at bulk conditions.")
    w("- **E-101**: submerged steam coil. Steam from the site header passes")
    w("  through control valve TV-101, condenses in the coil, and the condensate")
    w("  drains through a steam trap to the condensate return system.")
    w("- **LV-101**: control valve on the single liquid outlet. The vessel")
    w("  drains under its own hydrostatic head; there is no outlet pump.")
    w("- **P-100**: centrifugal feed transfer pump, belonging to the upstream")
    w("  unit, that pumps from upstream storage to TK-101. It runs at fixed speed")
    w("  and TK-101 has no control over it. Its own instrumentation is on the")
    w("  upstream unit and is not in this extract; `FI-101` and `TI-100` are on")
    w("  the TK-101 inlet line, downstream of it.")
    w("- **Feed** is not controlled by this unit. It is whatever P-100 delivers")
    w("  from upstream storage; TK-101 accepts it and passes it on.")
    w("- There is one liquid outlet. `FI-102`, `TI-102` and `AI-101` are")
    w("  three instruments on the same product line.")

    # =====================================================================
    s3: list[str] = []
    w = s3.append
    w("| Quantity | Value |")
    w("|---|---|")
    w(f"| Feed rate | {feed_m3h:.1f} m3/h |")
    w(f"| Feed temperature | {d['feed_temp']:.0f} degC nominal |")
    w("| Bulk temperature setpoint | 75 degC |")
    w(f"| Level setpoint | {level:.1f} m ({volume:.2f} m3 working volume) |")
    w(f"| Mean residence time at design | {residence_min:.0f} min |")
    w(f"| Steam header pressure | {p_hdr:.1f} barg ({t_steam:.1f} degC saturation) |")
    w(f"| Latent heat at header conditions | {latent_kj:,.0f} kJ/kg |")
    w(f"| Coil duty at design | {duty_kw:,.0f} kW |")
    w(f"| Steam flow at design | {steam_kgh:,.0f} kg/h |")
    w(f"| Clean coil UA, steam valve fully open | {ua_clean_kw:.0f} kW/K |")
    w(f"| TV-101 position at design | {tv_design:.0f} % |")
    w(f"| LV-101 position at design | {lv_design:.0f} % |")
    w(f"| Vessel heat loss coefficient | {p['UA_loss']:.0f} W/K (about {loss_kw:.0f} kW at design) |")
    w(f"| Fluid density / heat capacity | {rho:.0f} kg/m3 / {cp_kj:.2f} kJ/kg.K (water-like; within 2-3 % for this stream) |")
    w("")
    w("At the design point both control valves sit near mid-travel, leaving each")
    w("loop usable range in both directions.")

    # =====================================================================
    s4: list[str] = []
    w = s4.append
    w("All the relationships below are the ones the unit actually obeys. Symbols:")
    w("h level (m), T bulk temperature (degC), A vessel cross-section (m2),")
    w("F flows (m3/s), x valve position as a fraction of travel (0-1).")
    w("")
    w("### 4.1 Liquid inventory")
    w("")
    w("```")
    w("A dh/dt = F_feed - F_out")
    w(f"F_out   = Cv x x_LV x sqrt(h)          Cv = {p['Cv_out']:.4f} m3/s = {cv_m3h:.2f} m3/h per unit opening per m^0.5")
    w("```")
    w("")
    w("Outflow is gravity-driven, so it rises with the square root of level as")
    w("well as with valve opening. At steady state the outlet flow equals the")
    w("feed flow and the level is constant; any persistent difference between")
    w("liquid in and liquid out must appear as a change in level.")
    w("")
    w("### 4.2 Energy")
    w("")
    w("```")
    w("rho cp V dT/dt = rho cp F_feed (T_feed - T) + Q_coil - UA_loss (T - T_ambient)")
    w("```")
    w("")
    w("At steady state the coil supplies the sensible heat to raise the feed to")
    w("bulk temperature plus the vessel's heat loss to the surroundings")
    w(f"(UA_loss = {p['UA_loss']:.0f} W/K).")
    w("")
    w("### 4.3 Steam coil heat transfer")
    w("")
    w("TV-101 throttles the steam admitted to the coil: the further it opens, the")
    w("higher the pressure and condensing temperature inside the coil and the")
    w("more of the coil is working. The combination of valve and coil therefore")
    w("behaves as an equal-percentage heat-transfer element. With the coil in its")
    w("as-commissioned condition, the heat delivered is")
    w("")
    w("```")
    w(f"Q_coil = UA_clean x R^(x_TV - 1) x (T_sat - T)        UA_clean = {ua_clean_kw:.0f} kW/K,  R = {R:g}")
    w("```")
    w("")
    w("where `T_sat` is the saturation temperature of the header steam and `x_TV`")
    w("is the TV-101 position (fraction). The term `UA_clean x R^(x_TV - 1)` is")
    w("the coil's *effective* UA at that valve position: about "
      f"{ua_eff:,.0f} W/K at the design position of {tv_design:.0f} %, rising to {ua_clean_kw:.0f},000 W/K at")
    w("full travel. Rearranged, it gives the valve position the coil should need")
    w("for a given duty:")
    w("")
    w("```")
    w("x_TV,expected = 1 + ln( Q_coil / (UA_clean x (T_sat - T)) ) / ln(R)")
    w("```")
    w("")
    w("Steam is consumed at `w_steam = Q_coil / h_fg(T_sat)`. All condensed")
    w("steam leaves through the trap as condensate.")
    w("")
    w("### 4.4 Steam properties")
    w("")
    w("The plant uses the following correlations (DCS calculations use the same):")
    w("")
    w("```")
    w(f"T_sat [degC]   = 100 x (P_header [barg] + {ATM_BAR})^0.25")
    w("h_fg  [kJ/kg]  = 2500 - 2.4 x T_sat [degC]")
    w("```")
    w("")
    w("Both fall as header pressure falls: lower pressure means a lower")
    w("condensing temperature and therefore less driving force across the coil.")
    w("")
    w("### 4.5 Condensate")
    w("")
    w("With the coil draining normally the steam trap discharges condensate a")
    w(f"little below saturation: `TI-202` reads about {p['subcool_base']:.0f} K below `TI-201`")
    w("(after the 4-minute transport delay on the condensate line).")
    w("")
    w("### 4.6 Product line")
    w("")
    w("The vessel is well mixed, so product temperature equals bulk temperature")
    w("(`TI-102` = `TIC-101.PV` after the 3-minute line delay) and product purity")
    w("follows the correlation in section 1 at bulk temperature.")

    # =====================================================================
    s5: list[str] = []
    w = s5.append
    w("Three PI controllers. Mode codes on every `.MODE` tag: **0 = MAN, 1 = AUTO,")
    w("2 = CAS** (remote setpoint from a master controller).")
    w("")
    w("| Loop | Normal mode | Measured variable | Manipulated | Action | Gain (Kc) | Integral (Ti) |")
    w("|---|---|---|---|---|---|---|")
    w(f"| TIC-101 | AUTO (1) | TIC-101.PV, degC | FIC-201.SP | reverse | {tic.kc * 100:.1f} % output per degC ({tic.kc * (fic_hi - fic_lo):.0f} kg/h per degC) | {tic.ti / 60:.0f} min |")
    w(f"| FIC-201 | CAS (2) | FIC-201.PV, kg/h | TV-101 | reverse | {fic.kc * 100:.3f} % output per kg/h | {fic.ti / 60:.0f} min |")
    w(f"| LIC-101 | AUTO (1) | LIC-101.PV, m | LV-101 | direct | {lic.kc * 100:.0f} % output per m | {lic.ti / 60:.0f} min |")
    w("")
    w("None of the loops use derivative action. Controllers execute every")
    w(f"{dt_scan:.0f} s scan. Integrators are clamped at the output limits")
    w("(0-100 %), and mode changes are bumpless. Setpoints change only by operator")
    w("entry, except where a loop is in cascade.")
    w("")
    w("### 5.1 Temperature: TIC-101 cascaded onto steam flow FIC-201")
    w("")
    w("TIC-101 does not move the steam valve. Its output is the setpoint of the")
    w("steam flow controller FIC-201, mapped linearly:")
    w("")
    w("```")
    w(f"FIC-201.SP [kg/h] = {fic_lo:.0f} + (TIC-101.OP [%] / 100) x {fic_hi - fic_lo:.0f}")
    w("```")
    w("")
    w("FIC-201 is a fast inner loop that moves TV-101 to deliver that steam flow.")
    w("TIC-101 is slow, tuned to the vessel's thermal time constant. The")
    w("practical consequences for reading the data:")
    w("")
    w("- While both loops are in their normal modes, bulk temperature is held at")
    w("  setpoint and changes in heat demand appear in the steam flow")
    w("  (`FIC-201.SP` / `.PV`) and the steam valve (`FIC-201.OP`, `TV-101.POS`),")
    w("  not in the temperature.")
    w("- The inner loop also compensates for anything that changes how much")
    w("  steam flow, or how much heat, a given valve position produces. Such")
    w("  changes show up as a change in valve position for an otherwise")
    w("  unchanged steam flow.")
    w("- When TIC-101 is in MAN its output, and so the steam flow setpoint, is")
    w("  held at the last value; FIC-201 keeps controlling steam flow to it, and")
    w("  bulk temperature is no longer regulated.")
    w("- When FIC-201 is in MAN or AUTO the cascade is broken and TIC-101 no")
    w("  longer acts on the process.")
    w("")
    w("### 5.2 Level: LIC-101")
    w("")
    w("Level is controlled on the outlet, in the direction of flow: feed rate is")
    w("set upstream, so the tank absorbs mismatches in its inventory and passes")
    w("the flow on. LIC-101 is direct acting (level above setpoint opens LV-101)")
    w("and is deliberately tuned loosely. It is an inventory loop for surge")
    w("damping, not a quality loop, and tight tuning would pass every feed")
    w("fluctuation straight to the downstream unit.")
    w("")
    w("Because outflow varies with `sqrt(h)`, the loop's process gain changes")
    w("with operating level.")
    w("")
    w("### 5.3 Control valves")
    w("")
    w(f"- **TV-101**: equal-percentage trim, rangeability {R:g} (see 4.3).")
    w("- **LV-101**: linear trim; flow per section 4.1.")
    w("")
    w("Both valves have smart positioners. The controller output (`.OP`) is the")
    w("demand sent to the positioner. `TV-101.POS` and `LV-101.POS` are the")
    w("measured stem positions read back from the positioners, in the same 0-100 %")
    w("scale. A healthy positioner follows its demand within a few seconds")
    w("(3 s first-order response), so position and demand normally agree to")
    w("within the resolution of the readback.")

    # =====================================================================
    s9: list[str] = []
    w = s9.append
    if steam is not None:
        w(f"**Steam header.** Shared with other plant units. Nominal {steam.mean:.1f} barg; it")
        w(f"wanders by about +/-{steam.sigma:.2f} bar over periods of half an hour or more as")
        w(f"other users swing, and has a daily cycle of about +/-{steam.diurnal_amplitude:.2f} bar")
        w("(highest in the early morning, lowest mid-afternoon, plant local time).")
    w("Saturation temperature follows header pressure (section 4.4).")
    w("")
    w("**Ambient temperature** (`TI-901`). Follows the season (the record")
    w("starts in early spring and warms through it), a daily cycle of about")
    w(f"+/-{amb.diurnal_amplitude:.0f} degC peaking mid-afternoon local time whose size varies from day")
    w("to day with cloud cover, and multi-day weather swings of a few degrees. Ambient")
    w("reaches TK-101 through vessel heat loss and through the feed.")
    w("")
    if feed_flow is not None and feed_temp is not None:
        w(f"**Feed.** Flow averages {feed_flow.mean:.0f} m3/h with short-term variability of about")
        w(f"+/-{feed_flow.sigma:.1f} m3/h over periods of roughly {feed_flow.tau_s / 60:.0f} minutes, set by the upstream")
        w(f"unit. Feed temperature averages about {feed_temp.mean:.0f} degC; it partly follows ambient")
        w(f"(through upstream storage, roughly {feed_temp.ambient_coupling:.2f} degC per degC of ambient")
        w(f"departure from its mean) and partly varies independently by about +/-{feed_temp.sigma:.1f} degC")
        w("over hours.")
        w("")
    w("Because the weather reaches many TK-101 tags at once, tags with no causal")
    w("connection to each other often correlate through ambient temperature.")
    w("Warmer weather means warmer feed and lower heat loss, so less steam is")
    w("needed and the steam valve sits lower.")

    calc_notes = [
        "- `CALC-DUTY-PROC` is the sensible heat taken up by the feed only; it",
        "  excludes vessel heat loss. At steady state `CALC-EBAL` therefore sits at a",
        "  small positive value, not at zero: the vessel heat loss",
        f"  (`{p['UA_loss']:.0f} W/K x (T - T_ambient)`, about {loss_kw:.0f} kW at 20 degC ambient)",
        "  plus the combined calibration offsets of the four instruments involved.",
        "  In normal operation in this record it runs at roughly 33-37 kW as weekly",
        "  averages, varying with ambient temperature. Transients in bulk",
        "  temperature also move it, because stored heat is not included.",
        "- `CALC-UA` is the *effective* UA at the current valve position (section",
        f"  4.3), about {ua_eff:,.0f} W/K at design, not the clean full-open figure. While",
        "  temperature is held at setpoint it is set mainly by the heat demand and",
        "  the approach temperature.",
        "- `CALC-MBAL` uses the product flow, which lags the vessel by 2 minutes,",
        "  so it shows short-lived excursions whenever flows change. The level",
        "  controller holds level, so liquid in and liquid out balance over any",
        "  period long compared with the level loop's response. The two flowmeters",
        "  are independent instruments and agree only to within their accuracy, so",
        "  the long-run residual is a small offset rather than exactly zero.",
    ]

    return PlantDescription(
        title="TK-101 Hydrolysis Hold Tank: Process Description",
        intro=[],
        sections=[
            Section("Service and product requirements", s1),
            Section("Equipment and process flow", s2),
            Section("Design basis", s3),
            Section("Process physics", s4),
            Section("Control strategy", s5),
            "tags",
            "calcs",
            "instruments",
            Section("Utilities and external influences", s9),
            "neighbours",
            "files",
        ],
        tag_notes=TAG_NOTES,
        calc_definitions=[
            ("CALC-DUTY", "kW", "Steam-side coil duty: `FIC-201.PV / 3600 x (2500 - 2.4 x TI-201)`"),
            ("CALC-DUTY-PROC", "kW", f"Process-side duty: `FI-101 / 3600 x {rho:.0f} x {cp_kj:.2f} x (TIC-101.PV - TI-100)`"),
            ("CALC-EBAL", "kW", "Energy balance gap: `CALC-DUTY - CALC-DUTY-PROC`"),
            ("CALC-APPROACH", "K", "Steam-to-bulk temperature approach: `TI-201 - TIC-101.PV`"),
            ("CALC-UA", "W/K", "Effective coil UA: `1000 x CALC-DUTY / CALC-APPROACH`"),
            ("CALC-MBAL", "m3/h", "Liquid balance residual: `FI-101 - FI-102`"),
        ],
        calc_notes=calc_notes,
        instrument_notes=[
            "- **Analyzer** `AI-101` updates once every 5 minutes and holds its value",
            "  between updates. It is coarsely quantized and carries an 8-minute",
            "  sample-system delay on top of its 90 s response.",
        ],
        timezone_label="US Central",
        diurnal_sources="ambient and the steam header",
    )
