# R-201 Propylene Glycol Reactor: plant design

Design document for `plants/exothermic_cstr`. It is written and approved before
any code exists, because this is where dataset quality is decided: the physics
determines what the data can show, and the fault catalog determines what a
diagnosis has to tell apart.

## 1. Service

R-201 is a continuous, jacketed, agitated reactor that hydrolyses propylene
oxide (PO) to propylene glycol (PG) with a large excess of water and a
dissolved sulphuric acid catalyst:

```
C3H6O + H2O  --(H+)-->  C3H8O2        dH_rx = -84.7 kJ/mol PO
```

With water at roughly 14x molar excess, the rate is pseudo-first-order in PO.
The kinetics are the published PO-hydration values (Fogler, *Elements of
Chemical Reaction Engineering*, the CSTR energy-balance examples), so a process
engineer can check them independently:

```
r = k * a_cat * C_PO        k = 16.96e12 * exp(-75,360 / (R T))  h^-1
```

`a_cat` is catalyst activity (1.0 = design acid strength). The reaction is
strongly exothermic (67 K adiabatic rise at design), so the cooling jacket is
what holds the reactor at temperature. That makes it a very different plant
from the steam-heated TK-101:

- it is cooled, not heated;
- heat generation feeds back on temperature through Arrhenius kinetics
  (+8 % rate per K);
- composition is measured by an analyzer with sample-system deadtime;
- two feeds are held in ratio.

## 2. Equipment and flow

```
 PO from storage (P-201)          process water (P-202, acid dosed upstream)
   | FV-201  FIC-201                 | FV-202  FFC-202 (ratio to FI-201)
   | TI-101                          | TI-102
   +---------------+   +-------------+
                   v   v
            +----------------+   CW supply (cooling tower)  PI-301 dP, TI-301
            |  R-201         |<== jacket <== TV-202 <== FI-301
            |  M-201 agitator|    TIC-202 jacket outlet temp (slave)
            |  TIC-201 / TI-204 bulk temp (two independent elements)
            |  LIC-201 level |==> CW return
            +-------+--------+
                    | LV-201  FI-203  TI-203  AI-201 (residual PO)
                    v
             to PG purification
```

## 3. Design point

| Quantity | Value |
|---|---|
| PO feed | 2.0 m3/h at 20 degC (830 kg/m3) |
| Water feed | 7.0 m3/h at 30 degC (ratio 3.5 v/v, ~14:1 molar) |
| Level / working volume | 1.8 m / 3.6 m3 (2.0 m2 cross-section, 3.0 m tall) |
| Residence time | 24 min |
| Reactor temperature | 60 degC |
| Conversion | 91 % (residual PO about 1.7 wt % in product) |
| Heat of reaction released | 613 kW |
| Sensible heat taken by feeds | 282 kW |
| Agitator heat input | 13 kW (15 kW motor) |
| Jacket duty | 331 kW |
| Jacket UA (clean) | 30 kW/K, jacket outlet at about 49 degC |
| Cooling water | 14.3 m3/h from a 29 degC supply (20 K rise), TV-202 near 50 % |

The open-loop energy balance is stable: heat generation rises 4.4 kW/K with
temperature while removal rises about 39 kW/K. Losing cooling therefore makes
the temperature climb and settle well above setpoint, rather than run away.
That keeps every episode physically recoverable.

## 4. States and physics

Four states: level `h`, PO concentration `C`, reactor temperature `T` and
jacket temperature `Tj`.

```
A dh/dt        = F_PO + F_W - F_out                      F_out = Cv x_LV sqrt(h)
V dC/dt        = F_PO C_PO,feed - (F_PO + F_W) C - k a_cat C V
rho cp V dT/dt = sum(rho_i cp_i F_i (T_i - T)) + (-dH) k a_cat C V
                 - UA_j (T - Tj) - UA_loss (T - T_amb) + Q_agit
rho_w cp_w Vj dTj/dt = rho_w cp_w F_cw (T_cw - Tj) + UA_j (T - Tj)

F_cw  = F_cw,max R^(x_TV - 1) sqrt(dP_cw / dP_design)   (equal %, R = 30)
F_PO  = Cv_PO x_FV201 sqrt(dP_PO)                        (linear trim)
F_W   = Cv_W  x_FV202 sqrt(dP_W)
UA_j  = UA_clean x (fouling factor) x (agitation factor)^0.6
P_agit= 15 kW x (0.3 + 0.7 x agitation factor)
```

The analyzer measures residual PO (wt %) on the product line through an
8-minute sample-system delay.

## 5. Control

| Loop | Measures | Moves | Notes |
|---|---|---|---|
| TIC-201 | reactor temp | TIC-202 setpoint | master; reverse acting |
| TIC-202 | jacket outlet temp | TV-202 (CW valve) | cascade slave; direct acting |
| FIC-201 | PO feed flow | FV-201 | production rate set here |
| FFC-202 | water feed flow | FV-202 | **ratio** slave: SP = 3.5 x FI-201 |
| LIC-201 | level | LV-201 | loose inventory loop, direct acting |

Two small engine additions, both generic:

1. **Ratio control.** A loop can declare `ratio_to` and `ratio`, and the
   engine then sets its setpoint every scan from the measured wild flow.
   Ratio stations are everywhere in chemical plants.
2. **A `power` instrument class** for motor power and current.

## 6. Disturbances (all sharing the weather)

- **Cooling water supply temperature.** Follows ambient through the cooling
  tower (strong coupling), so it has daily and seasonal cycles. This is the
  dominant common-cause driver in the dataset.
- **Cooling water header dP.** Shared utility, with a daily demand cycle.
- **PO and water supply pressures.** The flow loops absorb these.
- **PO and water feed temperatures.** Partly ambient-coupled.
- **Catalyst activity.** Slow +/-1 % wander from acid make-up variability,
  so conversion is never perfectly flat.

## 7. Fault catalog

There are 15 causes in 4 symptom classes. Each class holds several causes
that share a first symptom, so a diagnosis has to discriminate between them.
"Component" is the failed item; no two benchmark episodes may share one.

### S1: cooling valve opening, reactor temperature on setpoint (slow)

| ID | Cause | Layer | Component | What separates it |
|---|---|---|---|---|
| RC-A1 | Jacket heat-transfer fouling | process | R-201 jacket wall | `CALC-UA` falls; CW supply temp, CW dP, agitator power and `AI-201` all flat |
| RC-A2 | Cooling-water supply temperature rise (cooling tower degraded) | utility | cooling tower | `TI-301` rises; `CALC-UA` flat; jacket temp nearly unchanged |
| RC-A3 | Agitator impeller damage | process | M-201 agitator | `JI-201` power falls, together with `CALC-UA` |
| RC-A4 | Acid catalyst over-dosing | upstream | acid dosing | `AI-201` residual PO falls; `CALC-UA` flat |
| RC-A5 | Cooling-water header pressure decline | utility | CW header | `PI-301` falls; CW flow held; `CALC-UA` flat |

### S2: oscillation on the cooling or feed side (cycling)

| ID | Cause | Layer | Component | What separates it |
|---|---|---|---|---|
| RC-B1 | TV-202 cooling valve stiction | process | TV-202 | `TV-202.POS` sticks and jumps against a smooth `TIC-202.OP`; CW dP steady |
| RC-B2 | CW header pressure surging | utility | CW header | `PI-301` oscillates first; valve tracks its demand |
| RC-B3 | PO feed pump P-201 surging | upstream | P-201 | `FIC-201.OP` and `FI-201` cycle; water follows through the ratio |

### S3: reactor temperature off setpoint (acute)

| ID | Cause | Layer | Component | What separates it |
|---|---|---|---|---|
| RC-C1 | TIC-201 left in manual | control | TIC-201 | `TIC-201.MODE` = 0; `TIC-202.SP` frozen; reactor temp wanders with load and weather |
| RC-C2 | Cooling-water supply loss | utility | CW header | `PI-301` collapses; TV-202 pinned open |

### S4: product quality or balance drifting, loops normal (slow)

| ID | Cause | Layer | Component | What separates it |
|---|---|---|---|---|
| RC-D1 | Catalyst deactivation (alkaline contamination in process water) | process | acid catalyst | `AI-201` rises, and cooling demand falls with it (`TV-202.POS` closes) |
| RC-D2 | Analyzer AI-201 calibration drift | instrument | AI-201 | `AI-201` rises with no change in heat release (TV-202, `CALC-QJ` flat) |
| RC-D3 | Reactor temperature element TE-201 drifting low | instrument | TE-201 | `TI-204` (independent element) rises away from `TIC-201.PV`; `AI-201` falls; cooling up |
| RC-D4 | Water flow transmitter FT-202 reading high | instrument | FT-202 | `CALC-MBAL` opens; `FI-203` falls; level steady |
| RC-D5 | Product flow transmitter FT-203 zero shift | instrument | FT-203 | `CALC-MBAL` steps; LV-201 and level unchanged |

## 8. The benchmark scenario: `cstr-rca` (recipe `rca-benchmark`)

There are 90 days at a 10 s scan, plus the 60 s grid. The first 14 days are
clean. Then come nine unique, non-overlapping faults, each with at least 2
days of normal operation either side, and two benign operator moves.

| # | Cause | Class | Layer | Severity |
|---|---|---|---|---|
| 1 | RC-A1 jacket fouling | S1 | process | moderate |
| 2 | RC-B1 TV-202 stiction | S2 | process (valve) | subtle |
| 3 | RC-D1 catalyst deactivation | S4 | process | moderate |
| 4 | RC-A2 cooling tower degraded | S1 | utility | moderate |
| 5 | RC-D3 temperature element drift | S4 | instrument | subtle |
| 6 | RC-C1 TIC-201 left in manual | S3 | control | obvious |
| 7 | RC-A3 agitator impeller damage | S1 | process | moderate |
| 8 | RC-D4 water flowmeter reading high | S4 | instrument | moderate |
| 9 | RC-B3 PO feed pump surging | S2 | upstream | obvious |

All 9 have distinct components. They cover all four symptom classes and four
injection layers. Each one sits next to at least two same-symptom
competitors that are *not* in the dataset, which a diagnosis has to rule out.

The two benign events are:
- a reactor temperature setpoint raised 60 to 63 degC for a day;
- a production-rate increase, with the FIC-201 setpoint raised 2.0 to
  2.3 m3/h and water following through the ratio.

Hard mode withholds `TI-204` (the second temperature element) and `JI-201`
(agitator power).

## 8a. Revisions after the first per-cause sweep

- Jacket UA raised from 18.4 to 30 kW/K. With 18.4 kW/K the cooling water
  rose only 13 K across the jacket, so moderate fouling or a warmer supply
  drove TV-202 to within a few percent of its stop. Once it saturated, the
  "flat" evidence moved. With 30 kW/K the water rises 20 K and every S1 cause
  moves the valve by a few percent, comparable to the daily weather swing.
- Cooling-water supply loss uses a negative scale magnitude. A
  `DisturbanceFault` in scale mode multiplies by `1 + severity x magnitude`.

## 9. Acceptance

The plant must pass all of the following before the dataset is accepted:

- `historiansim check-plant exothermic_cstr` stages 1 to 5;
- the full validation battery on the 90-day run;
- the recipe checks;
- the answer-leak audit;
- a blind diagnosis by an agent that gets only the dataset root.
