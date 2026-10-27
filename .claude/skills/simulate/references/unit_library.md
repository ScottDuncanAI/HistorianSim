# Unit library: physics templates

Starting points for `model.py`. Each is a lumped, few-state model that runs
fast at a 5 s integration step and carries the nonlinearity that makes data
realistic. Adapt the details to the user's process. Keep states to 2–6, and
treat anything with a time constant under about 20 s as quasi-steady.

General patterns, used in both reference plants:

- **Valves.** Linear: `F = Cv x sqrt(dP)`. Equal percentage:
  `F = F_max R^(x-1) sqrt(dP/dP_design)`. Clip `x` to [0, 1] and `dP` at 0.
- **Gravity outflow.** `F = Cv x sqrt(h)`. Loop gain then varies with level,
  which is free and real.
- **Ambient.** Enters every heat-loss term `UA_loss (T - T_amb)`, so
  temperatures pick up a diurnal component without one being scripted.
- **Faults.** A parameter that is a surviving fraction (`fouling_factor`,
  `agit_factor`, `cat_factor`, default 1.0) is faulted with `mode="scale"`.
  A zero-based one (`leak_coeff`, `tv_stiction`, default 0.0) uses
  `mode="offset"`. Declare `stiction_params = {mv: param}` and the engine
  inserts a sticking stem between controller and process.
- **`steady_inputs` / `steady_state`.** Solve the design point analytically
  where possible; use `scipy.optimize.fsolve` for the coupled part (see
  `exothermic_cstr/model.py`).

## Jacketed CSTR, exothermic (reference: `exothermic_cstr`)

States `h, C, T, Tj`. First-order Arrhenius kinetics, jacket as a well-mixed
volume, cascade TIC (reactor) to TIC (jacket) to the CW valve, ratioed feeds.
Faults: jacket fouling, agitator degradation (UA and motor power together),
catalyst activity, CW supply temperature or pressure, valve stiction,
temperature element drift, flowmeter drift, analyzer drift. Keep the design
point open-loop stable unless runaway is the point: generation slope
`(-dH) F C_in X(1-X) E/RT^2` must be less than removal `sum(rho cp F) + UA`.

## Heated tank, steam coil (reference: `heated_stirred_tank`)

States `h, T`. Steam side quasi-steady: `T_sat(P_header)`; equal-percentage
valve times coil UA; condensate subcooling as a trap-health signal. Faults:
coil fouling, condensate backup, trap blow-through, header pressure, feed
temperature and rate, valve stiction, level DP cell plugging, flowmeter
drift, vessel leak.

## Shell-and-tube heat exchanger train

States: outlet temperatures of each side per shell, as lumped first-order
volumes. `Q = UA * LMTD`, or the effectiveness-NTU form for speed. Bypass
valve control on the cold-side outlet temperature. Faults: fouling (UA,
plus a dP rise via `dP proportional to F^2 / fouling`), tube leak (a small
cross-flow between sides, shows in composition or conductivity), bypass
valve stiction, utility temperature change, flow transmitter drift.

## Distillation column (simplified)

Do not do tray-by-tray. Use 4–6 states:
- reboiler holdup and composition;
- condenser/reflux drum holdup and composition;
- one or two lumped section compositions.

Constant relative volatility for VLE: `y = a x / (1 + (a-1) x)`. Controls:
reflux drum level to distillate, sump level to bottoms, tray temperature to
reboiler steam (cascade to steam flow), reflux on flow. Overhead analyzer
with 5–10 min deadtime. Faults: reboiler fouling, feed composition change,
reflux flow meter drift, condenser cooling loss (pressure rises), tray
temperature element drift, flooding as a soft rise in dP, reflux valve
stiction.

## Centrifugal pump with seal and cavitation

Algebraic hydraulics: pump curve `H = H0 - k Q^2` intersected with the
system curve. One or two thermal states (bearing temperature, seal
temperature). Vibration as a derived signal: band energy grows with
cavitation (NPSH margin below threshold) and with bearing wear. Faults:
suction strainer plugging (NPSHa falls, so cavitation becomes intermittent),
bearing wear (vibration and temperature rise), seal leak, discharge valve
stiction, motor current drift.

## Fired heater or boiler drum

Drum level with **shrink and swell**: a feedwater increase drops indicated
level before raising it. Model it with a void-fraction term that responds
to pressure and steam demand. States: drum pressure, water inventory, steam
volume fraction, flue gas temperature. Three-element level control.
Faults: fuel gas pressure disturbance, burner fouling (O2 rises), feedwater
valve stiction, level transmitter drift, tube fouling (stack temperature
rises).

## Packed-bed or tubular reactor (plug flow)

Discretise into 4–8 well-mixed cells in series. That gives the right lag
and a hot spot that moves, without PDE machinery. Coolant on the shell.
Faults: catalyst deactivation (hot spot moves downstream), coolant flow
loss, feed composition, thermocouple drift on one cell, channelling (a
fraction of flow bypasses).
