"""The R-201 sections of the process description.

Every figure is computed from :class:`ExothermicCSTR` and the loop and
disturbance configuration, so the document cannot drift from the model.
"""

from __future__ import annotations

import math

from historiansim.config.schema import ScenarioConfig
from historiansim.plants.base import PlantDescription, Section
from historiansim.plants.exothermic_cstr.loops import DESIGN_D, DESIGN_TARGETS, RATIO, design_point

__all__ = ["describe"]

TAG_NOTES = {
    "TIC-201.PV": "Bulk reactor temperature from element TE-201 in a thermowell. Controlled variable of TIC-201.",
    "TIC-201.SP": "Operator-entered reactor temperature setpoint.",
    "TIC-201.OP": "Master output, 0-100 %. Written to TIC-202 as its setpoint (see 5.1).",
    "TIC-201.MODE": "Controller mode (0 MAN, 1 AUTO, 2 CAS). Normal: 1.",
    "TIC-202.PV": "Jacket outlet temperature, on the cooling water return nozzle. Controlled variable of TIC-202.",
    "TIC-202.SP": "Remote setpoint from TIC-201 when in cascade.",
    "TIC-202.OP": "Slave output: demand to the TV-202 positioner.",
    "TIC-202.MODE": "Controller mode. Normal: 2 (CAS).",
    "FIC-201.PV": "PO feed flow, Coriolis meter FT-201 downstream of FV-201.",
    "FIC-201.SP": "Operator-entered PO feed rate: this sets the production rate.",
    "FIC-201.OP": "Demand to the FV-201 positioner.",
    "FIC-201.MODE": "Controller mode. Normal: 1.",
    "FFC-202.PV": "Process water flow, magnetic flowmeter FT-202 downstream of FV-202.",
    "FFC-202.SP": f"Ratio setpoint: {RATIO:g} x FIC-201.PV, recomputed every scan while in CAS.",
    "FFC-202.OP": "Demand to the FV-202 positioner.",
    "FFC-202.MODE": "Controller mode. Normal: 2 (CAS, ratio).",
    "LIC-201.PV": "Reactor level, DP transmitter LT-201. Controlled variable of LIC-201.",
    "LIC-201.SP": "Operator-entered level setpoint.",
    "LIC-201.OP": "Demand to the LV-201 positioner.",
    "LIC-201.MODE": "Controller mode. Normal: 1.",
    "TV-202.POS": "Stem position feedback from the TV-202 positioner.",
    "FV-201.POS": "Stem position feedback from the FV-201 positioner.",
    "FV-202.POS": "Stem position feedback from the FV-202 positioner.",
    "LV-201.POS": "Stem position feedback from the LV-201 positioner.",
    "TI-204": "Bulk reactor temperature, second element TE-204 in its own thermowell at a different elevation. Indication only.",
    "TI-101": "PO feed temperature, on the PO line from storage.",
    "TI-102": "Process water temperature, on the water line.",
    "FI-203": "Product flow, magnetic flowmeter FT-203 downstream of LV-201.",
    "TI-203": "Product line temperature, downstream of LV-201.",
    "AI-201": "On-line analyzer: residual PO in the product, wt % (sample system and cycle time in section 8).",
    "TI-301": "Cooling water supply temperature at the unit battery limit.",
    "PI-301": "Cooling water differential pressure, supply minus return header, across the jacket circuit.",
    "FI-301": "Cooling water flow to the jacket, downstream of TV-202.",
    "JI-201": "Agitator M-201 motor power from the drive.",
    "TI-901": "Ambient air temperature at the unit.",
}


def describe(cfg: ScenarioConfig) -> PlantDescription:
    unit, u, x, sig = design_point()
    p = unit.params
    d = dict(DESIGN_D)
    h, conc, temp, tj = (float(v) for v in x)
    f_po = DESIGN_TARGETS["FI-201"]
    f_w = DESIGN_TARGETS["FI-202"]
    f_tot = f_po + f_w
    area = p["area"]
    volume = area * h
    tau_min = volume / f_tot * 60.0
    diameter = 2.0 * math.sqrt(area / math.pi)
    k_design = unit.rate_constant(temp, d, p) * 3600.0
    conv = sig["CALC-CONV"]
    c_feed = p["rho_po"] / p["mw_po"]
    q_rx = -p["dH"] * unit.rate_constant(temp, d, p) * conc * volume / 1000.0
    q_sens = (p["rho_po"] * p["cp_po"] * f_po / 3600 * (temp - d["T_po"])
              + p["rho_w"] * p["cp_w"] * f_w / 3600 * (temp - d["T_w"])) / 1000.0
    q_agit = p["agit_to_fluid"] * p["P_agit"] / 1000.0
    q_loss = p["UA_loss"] * (temp - d["T_amb"]) / 1000.0
    q_j = sig["CALC-QJ"]
    ua = p["UA_clean"] / 1000.0
    cw = sig["FI-301"]
    mass_flow = f_po * p["rho_po"] + f_w * p["rho_w"]
    po_in_wt = 100.0 * f_po * p["rho_po"] / mass_flow
    mcp_flow = (p["rho_po"] * p["cp_po"] * f_po + p["rho_w"] * p["cp_w"] * f_w) / 3600 / 1000
    adiabatic = q_rx / mcp_flow
    cv_out = p["Cv_out"] * 3600.0
    cv_po = p["Cv_po"] * 3600.0
    cv_w = p["Cv_w"] * 3600.0
    fcw_max = p["F_cw_max"] * 3600.0
    R = p["cw_rangeability"]
    e_kj = p["E"] / 1000.0
    k0_h = p["k0"] * 3600.0
    sens = p["E"] / (8.314 * (temp + 273.15) ** 2) * 100.0

    loops = {lp.name: lp for lp in cfg.loops}
    tic, tjc, fic, ffc, lic = (loops[n] for n in ("TIC-201", "TIC-202", "FIC-201", "FFC-202", "LIC-201"))
    tj_lo, tj_hi = tjc.sp_limits
    ch = cfg.disturbances.channels
    amb = cfg.disturbances.ambient

    # =====================================================================
    s1: list[str] = []
    w = s1.append
    w("R-201 is a continuous, agitated, jacketed reactor that hydrolyses propylene")
    w("oxide (PO) to monopropylene glycol (PG). PO and process water are fed")
    w("continuously; the process water carries a dilute sulphuric acid catalyst,")
    w("dosed upstream at a fixed strength. The reactor product goes on to the PG")
    w("purification train, which strips unreacted PO and water.")
    w("")
    w("```")
    w("C3H6O (PO) + H2O  --(H+)-->  C3H8O2 (PG)        dH_rx = "
      f"{p['dH'] / 1000:.1f} kJ/mol PO")
    w("```")
    w("")
    w("Water is fed in large molar excess (about 14:1), which suppresses heavier")
    w("glycols and makes the rate first order in PO. The reaction is strongly")
    w(f"exothermic: at design the reaction alone would heat the feed by about {adiabatic:.0f} K")
    w("if no heat were removed. The cooling jacket is therefore what holds the")
    w("reactor at temperature.")
    w("")
    w("Product quality is expressed as residual PO in the product (wt %), measured")
    w("on line by `AI-201`. Lower is better: unreacted PO is recovered downstream at")
    w("an energy cost. The unit runs at **60 degC**; hotter operation converts more")
    w("PO but makes more by-products and runs closer to the jacket's cooling limit.")

    # =====================================================================
    s2: list[str] = []
    w = s2.append
    w("```")
    w("  PO from storage (pump P-201)              process water, acid dosed (pump P-202)")
    w("     |  TI-101                                    |  TI-102")
    w("   [FV-201]  FIC-201 (FT-201)                   [FV-202]  FFC-202 (FT-202), ratio to FT-201")
    w("     +-------------------+    +--------------------+")
    w("                         v    v")
    w("                 +--------------------+        cooling water supply (cooling tower)")
    w("                 |  R-201             |          |  TI-301 temperature")
    w("                 |  M-201 agitator    |          |  PI-301 header dP")
    w("                 |  JI-201 power      |   [TV-202]  FI-301 flow")
    w("                 |  TIC-201 (TE-201)  |<== jacket <=+")
    w("                 |  TI-204  (TE-204)  |==> jacket outlet: TIC-202 ==> cooling water return")
    w("                 |  LIC-201 (LT-201)  |")
    w("                 +---------+----------+")
    w("                           | [LV-201]  FI-203 flow, TI-203 temperature, AI-201 residual PO")
    w("                           v")
    w("                    PG purification")
    w("```")
    w("")
    w(f"- **R-201**: vertical cylindrical vessel, {diameter:.2f} m diameter ({area:.1f} m2")
    w(f"  cross-section), {p['h_max']:.1f} m tall, fully mixed by agitator M-201, so the outlet")
    w("  is at bulk conditions. Two independent temperature elements: TE-201")
    w("  (control) and TE-204 (indication), in separate thermowells.")
    w("- **Jacket**: a single-pass cooling jacket with its own volume of water")
    w(f"  ({p['V_jacket']:.1f} m3). Cooling water from the site cooling tower enters through")
    w("  TV-202 and returns to the cooling water return header.")
    w("- **M-201**: fixed-speed agitator. The impeller sweeps liquid past the jacket")
    w("  wall; the process-side heat-transfer coefficient depends on it.")
    w("- **Feeds**: PO from storage via pump P-201 and FV-201; process water via")
    w("  P-202 and FV-202. Both pumps belong to the supplying units, run at fixed")
    w("  speed, and are not instrumented in this extract. Both feed valves have")
    w("  linear trim.")
    w("- **LV-201**: control valve on the single liquid outlet. The reactor drains")
    w("  under its own head; there is no outlet pump.")
    w("- There is one liquid outlet. `FI-203`, `TI-203` and `AI-201` are on the same")
    w("  product line.")

    # =====================================================================
    s3: list[str] = []
    w = s3.append
    w("| Quantity | Value |")
    w("|---|---|")
    w(f"| PO feed | {f_po:.1f} m3/h at {d['T_po']:.0f} degC ({p['rho_po']:.0f} kg/m3, {p['cp_po'] / 1000:.2f} kJ/kg.K) |")
    w(f"| Process water feed | {f_w:.1f} m3/h at {d['T_w']:.0f} degC (ratio {RATIO:g} m3 water per m3 PO) |")
    w(f"| PO in combined feed | {po_in_wt:.1f} wt % ({c_feed * f_po / f_tot:,.0f} mol/m3) |")
    w(f"| Level setpoint / working volume | {h:.1f} m / {volume:.1f} m3 |")
    w(f"| Mean residence time | {tau_min:.0f} min |")
    w(f"| Reactor temperature setpoint | {temp:.0f} degC |")
    w(f"| Rate constant at design | {k_design:.1f} 1/h |")
    w(f"| PO conversion | {conv:.1f} % (residual PO {sig['AI-201']:.2f} wt %) |")
    w(f"| Heat released by reaction | {q_rx:,.0f} kW |")
    w(f"| Sensible heat taken up by the feeds | {q_sens:,.0f} kW |")
    w(f"| Agitator heat input | {q_agit:.0f} kW ({p['P_agit'] / 1000:.0f} kW motor) |")
    w(f"| Heat loss to ambient | {q_loss:.0f} kW |")
    w(f"| Jacket duty | {q_j:,.0f} kW |")
    w(f"| Jacket UA | {ua:.1f} kW/K |")
    w(f"| Jacket outlet temperature | {tj:.1f} degC |")
    w(f"| Cooling water | {cw:.0f} m3/h at {d['T_cw']:.0f} degC supply, {d['dP_cw']:.1f} bar header dP |")
    w(f"| TV-202 / FV-201 / FV-202 / LV-201 at design | {u['TV-202'] * 100:.0f} / {u['FV-201'] * 100:.0f} / {u['FV-202'] * 100:.0f} / {u['LV-201'] * 100:.0f} % |")
    w(f"| Reactor contents | {p['rho']:.0f} kg/m3, {p['cp'] / 1000:.2f} kJ/kg.K |")
    w("")
    w("All four control valves sit near mid-travel at design.")

    # =====================================================================
    s4: list[str] = []
    w = s4.append
    w("Symbols: h level (m), A cross-section (m2), V = A h, C PO concentration")
    w("(mol/m3), T reactor temperature, Tj jacket (outlet) temperature, F volumetric")
    w("flows (m3/s), x valve travel as a fraction (0-1). Every relationship below")
    w("is one the unit actually obeys.")
    w("")
    w("### 4.1 Kinetics")
    w("")
    w("```")
    w("r = k a C                          mol/m3/s")
    w(f"k = {k0_h:.4g} x exp(-{e_kj:.2f} kJ/mol / (R T))   1/h,   T in K")
    w("```")
    w("")
    w(f"`a` is catalyst activity, 1.0 at the design acid strength; it wanders by")
    w(f"about +/-{ch['cat_activity'].sigma * 100:.0f} % over hours with the acid make-up. At {temp:.0f} degC the rate")
    w(f"rises about {sens:.0f} % per kelvin.")
    w("")
    w("### 4.2 Material balances")
    w("")
    w("```")
    w("A dh/dt  = F_PO + F_W - F_out")
    w(f"F_out    = Cv x_LV sqrt(h)          Cv = {cv_out:.2f} m3/h per unit opening per m^0.5")
    w("V dC/dt  = F_PO C_PO,feed - (F_PO + F_W) C - k a C V")
    w(f"C_PO,feed = {c_feed:,.0f} mol/m3 (pure PO)")
    w("```")
    w("")
    w("At steady state the conversion is `X = k a tau / (1 + k a tau)` with")
    w("`tau = V / (F_PO + F_W)`. Volumes are taken as additive. Residual PO in")
    w("the product is `wt % = 100 x C x 0.05808 / " f"{p['rho']:.0f}`.")
    w("")
    w("### 4.3 Energy")
    w("")
    w("```")
    w("rho cp V dT/dt = sum_i rho_i cp_i F_i (T_i - T)          (feeds)")
    w("               + (-dH_rx) k a C V                         (reaction)")
    w("               - Q_jacket - UA_loss (T - T_ambient) + Q_agitator")
    w("```")
    w("")
    w(f"`UA_loss` = {p['UA_loss']:.0f} W/K. About {p['agit_to_fluid'] * 100:.0f} % of the agitator motor power ends up")
    w("in the liquid as heat.")
    w("")
    w("Heat generation rises with temperature through the rate constant, but at the")
    w("design point heat removal (feeds plus jacket) rises several times faster, so")
    w("the reactor has a single, stable operating point.")
    w("")
    w("### 4.4 Jacket heat transfer")
    w("")
    w("```")
    w("Q_jacket = UA (T - Tj)")
    w("rho_w cp_w V_j dTj/dt = rho_w cp_w F_cw (T_cw,supply - Tj) + Q_jacket")
    w("```")
    w("")
    w("The jacket is well mixed, so its outlet temperature is `Tj`. At steady state")
    w("the cooling water flow needed for a given duty is")
    w("")
    w("```")
    w("F_cw = Q_jacket / (rho_w cp_w (Tj - T_cw,supply))")
    w("```")
    w("")
    w(f"`UA` is {ua:.1f} kW/K as commissioned. It combines the cooling-water film, the")
    w("wall and the process-side film. The process-side film is set by the")
    w("agitator: it varies with the impeller's pumping capacity to about the 0.6")
    w("power. The agitator's power draw at fixed speed is proportional to the work")
    w(f"the impeller does on the liquid, plus a fixed {0.3 * p['P_agit'] / 1000:.1f} kW of drive and seal losses.")
    w("")
    w("### 4.5 Valves")
    w("")
    w("```")
    w(f"F_cw = {fcw_max:.0f} m3/h x {R:g}^(x_TV - 1) x sqrt(dP_cw / {p['dP_cw_design']:g} bar)   (TV-202, equal percentage)")
    w(f"F_PO = {cv_po:.3f} m3/h x x_FV201 x sqrt(dP_PO)                     (FV-201, linear)")
    w(f"F_W  = {cv_w:.3f} m3/h x x_FV202 x sqrt(dP_W)                      (FV-202, linear)")
    w("```")
    w("")
    w("with pressures in bar. Both feed supply pressures are set by the supplying")
    w(f"units and sit near {d['dP_po']:.0f} bar.")

    # =====================================================================
    s5: list[str] = []
    w = s5.append
    w("Five PI controllers. Mode codes on every `.MODE` tag: **0 = MAN, 1 = AUTO,")
    w("2 = CAS** (remote setpoint).")
    w("")
    w("| Loop | Normal mode | Measured variable | Manipulated | Action | Gain (Kc) | Integral (Ti) |")
    w("|---|---|---|---|---|---|---|")
    w(f"| TIC-201 | AUTO (1) | TIC-201.PV, degC | TIC-202.SP | reverse | {tic.kc * 100:.1f} % output per degC ({tic.kc * (tj_hi - tj_lo):.2f} degC of jacket setpoint per degC) | {tic.ti / 60:.0f} min |")
    w(f"| TIC-202 | CAS (2) | TIC-202.PV, degC | TV-202 | direct | {tjc.kc * 100:.1f} % output per degC | {tjc.ti / 60:.0f} min |")
    w(f"| FIC-201 | AUTO (1) | FIC-201.PV, m3/h | FV-201 | reverse | {fic.kc * 100:.0f} % output per m3/h | {fic.ti:.0f} s |")
    w(f"| FFC-202 | CAS (2) | FFC-202.PV, m3/h | FV-202 | reverse | {ffc.kc * 100:.1f} % output per m3/h | {ffc.ti:.0f} s |")
    w(f"| LIC-201 | AUTO (1) | LIC-201.PV, m | LV-201 | direct | {lic.kc * 100:.0f} % output per m | {lic.ti / 60:.0f} min |")
    w("")
    w("None of the loops use derivative action. Controllers execute every")
    w(f"{cfg.time.dt_scan:.0f} s scan; integrators are clamped at the output limits and mode")
    w("changes are bumpless.")
    w("")
    w("### 5.1 Reactor temperature: TIC-201 cascaded onto jacket temperature TIC-202")
    w("")
    w("TIC-201 does not move the cooling valve. Its output is the setpoint of the")
    w("jacket temperature controller, mapped linearly:")
    w("")
    w("```")
    w(f"TIC-202.SP [degC] = {tj_lo:.0f} + (TIC-201.OP [%] / 100) x {tj_hi - tj_lo:.0f}")
    w("```")
    w("")
    w("TIC-202 is a fast inner loop that moves TV-202 to hold the jacket outlet")
    w("temperature. Consequences for reading the data:")
    w("")
    w("- While both loops are in their normal modes the reactor is held at")
    w("  setpoint. A change in how much heat must be removed, or in how easily it")
    w("  can be removed, shows in the jacket temperature (`TIC-202.SP` / `.PV`),")
    w("  the cooling valve (`TIC-202.OP`, `TV-202.POS`) and the cooling water")
    w("  flow, not in the reactor temperature.")
    w("- The inner loop also absorbs anything that changes how much cooling a")
    w("  given valve position delivers.")
    w("- When TIC-201 is in MAN, the jacket setpoint is held; TIC-202 keeps the")
    w("  jacket at it, and the reactor temperature is no longer regulated.")
    w("")
    w("### 5.2 Feeds: FIC-201 and ratio station FFC-202")
    w("")
    w("The production rate is set by the PO flow setpoint `FIC-201.SP`. The water")
    w("flow follows by ratio: every scan FFC-202 takes its setpoint from the")
    w("*measured* PO flow,")
    w("")
    w("```")
    w(f"FFC-202.SP = {RATIO:g} x FIC-201.PV")
    w("```")
    w("")
    w("so a rate change moves both feeds together and keeps the molar excess of")
    w("water constant. Each flow loop moves its own valve to hold its flow")
    w("against changes in its supply pressure.")
    w("")
    w("### 5.3 Level: LIC-201")
    w("")
    w("Level is controlled on the outlet, direct acting, and loosely tuned. It")
    w("absorbs feed changes rather than passing them straight to purification.")
    w("Because outflow varies with `sqrt(h)`, the loop's gain changes with level.")
    w("")
    w("### 5.4 Control valves")
    w("")
    w("All four valves have smart positioners. `.OP` is the demand sent to the")
    w("positioner and `.POS` the stem position read back from it. A healthy")
    w("positioner follows its demand within a few seconds (3 s first-order), so")
    w("position and demand normally agree to within the readback resolution.")

    # =====================================================================
    s9: list[str] = []
    w = s9.append
    cwt, cwp = ch["T_cw"], ch["dP_cw"]
    w(f"**Cooling water.** Supplied from the site cooling tower at about {cwt.mean:.0f} degC. A")
    w("cooling tower cools to near the wet-bulb temperature, so the supply follows")
    w(f"the weather: roughly {cwt.ambient_coupling:.2f} degC per degC of ambient departure from")
    w(f"its mean, plus about +/-{cwt.sigma:.1f} degC of its own variation over an hour or so. The")
    w(f"header differential pressure is shared with other units: nominal {cwp.mean:.1f} bar,")
    w(f"wandering by about +/-{cwp.sigma:.2f} bar, with a daily demand cycle of about")
    w(f"+/-{cwp.diurnal_amplitude:.2f} bar.")
    w("")
    w("**Ambient temperature** (`TI-901`). Follows the season (the record starts in")
    w(f"early spring and warms through it), a daily cycle of about +/-{amb.diurnal_amplitude:.0f} degC peaking")
    w("mid-afternoon local time that varies day to day with cloud cover, and")
    w("multi-day weather swings of a few degrees.")
    w("")
    w(f"**Feeds.** PO arrives from storage at about {ch['T_po'].mean:.0f} degC and process water at about")
    w(f"{ch['T_w'].mean:.0f} degC; both partly follow ambient through their storage and piping. The")
    w(f"feed supply pressures vary by about +/-{ch['dP_po'].sigma:.2f} bar over tens of minutes. The")
    w("acid strength in the process water varies slightly with the dosing upstream")
    w("(section 4.1).")
    w("")
    w("Because the weather reaches the cooling water, the feeds and the vessel's")
    w("heat loss, many R-201 tags correlate through ambient temperature with no")
    w("causal link between them. Warmer weather means warmer cooling water, so")
    w("more of it is needed and the cooling valve sits higher in the afternoon.")

    calc_notes = [
        "- `CALC-QJ` is the heat actually carried away by the cooling water. Because",
        "  the jacket is well mixed, the return temperature equals the jacket",
        "  temperature `TIC-202.PV`.",
        "- `CALC-UA` is the jacket UA implied by that duty and the reactor-to-jacket",
        f"  approach; about {ua:.1f} kW/K at design. It inherits the noise of four",
        "  measurements and moves briefly during transients, because the jacket",
        "  stores heat. Because it divides by two temperature differences, it also",
        "  amplifies the slow calibration drift of its four inputs, and can wander",
        "  by a few percent over months with nothing changing in the jacket.",
        "- `CALC-MBAL` compares the two feed meters with the product meter. The",
        "  product meter lags the vessel by 1 minute and the level loop is loose, so",
        "  it shows short excursions whenever flows change. Over periods long",
        "  compared with the level loop it closes to within the meters' accuracy.",
        "- `CALC-CONV` estimates conversion as `1 - AI-201 / w_PO,in`, where",
        "  `w_PO,in` is the PO mass fraction in the combined feed from the two flow",
        "  meters. It inherits the analyzer's delay and sampling.",
    ]

    return PlantDescription(
        title="R-201 Propylene Glycol Reactor: Process Description",
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
            ("CALC-QJ", "kW", "Jacket duty, cooling water side: `FI-301 / 3600 x 1000 x 4.18 x (TIC-202.PV - TI-301)`"),
            ("CALC-UA", "kW/K", "Jacket UA: `CALC-QJ / (TIC-201.PV - TIC-202.PV)`"),
            ("CALC-MBAL", "m3/h", "Liquid balance residual: `FIC-201.PV + FFC-202.PV - FI-203`"),
            ("CALC-RATIO", "-", "Measured feed ratio: `FFC-202.PV / FIC-201.PV`"),
            ("CALC-CONV", "%", "Conversion: `100 x (1 - AI-201 / w_PO,in)`, `w_PO,in = 100 x 830 FIC-201.PV / (830 FIC-201.PV + 1000 FFC-202.PV)`"),
        ],
        calc_notes=calc_notes,
        instrument_notes=[
            "- **Analyzer** `AI-201` updates once every 5 minutes and holds its value",
            "  between updates. It is coarsely quantized and carries an 8-minute",
            "  sample-system delay on top of its 90 s response.",
            "- **Motor power** `JI-201` is fast and carries ripple from the liquid's",
            "  turbulence.",
        ],
        timezone_label="US Central",
        diurnal_sources="ambient and the cooling water",
    )
