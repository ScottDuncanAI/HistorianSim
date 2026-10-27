# Processes to recommend

Offer three or four of these when the user asks for a recommendation. Each
one has a rich diagnostic story: several causes share one symptom, the
control system masks faults, and something non-obvious separates them.

| Process | One-line pitch | Build effort |
|---|---|---|
| **Jacketed exothermic CSTR** (shipped: `cstr-rca`) | Reaction heat feeds back on temperature, and a drifting thermocouple makes the reactor quietly run hot. | ready now |
| **Steam-heated hold tank** (shipped: `tank-rca`) | Six causes open the steam valve while temperature sits perfectly on setpoint. | ready now |
| **Shell-and-tube exchanger train with bypass control** | Fouling, a tube leak and a utility change all look like "the bypass is closing". | moderate |
| **Binary distillation column** | Feed composition, reboiler fouling and reflux meter drift all move the tray temperature, and the analyzer is 8 minutes late. | high |
| **Packed-bed reactor with a hot spot** | Catalyst deactivation walks the hot spot downstream, and one drifting thermocouple can fake it. | moderate-high |
| **Boiler drum with three-element level control** | Shrink and swell make level move the wrong way first, so causality is easy to get backwards. | high |
| **Centrifugal pump station** | Strainer plugging produces intermittent cavitation in the vibration band before any flow loss. | moderate |
| **Fermenter (fed-batch run as continuous)** | Dissolved oxygen control masks a failing sparger, an agitator problem and a contaminated feed. | moderate |

When presenting, keep each to two lines. Say which is fastest: the shipped
plants generate immediately, and anything new needs a design, an
implementation and validation, typically an hour or two of work with
Claude. Ask which they want, or if they have their own.
