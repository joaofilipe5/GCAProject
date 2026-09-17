# Project summary

This Supply Chain Management project studies the economic design of Portugal's green hydrogen supply chain. It considers the geography of 18 districts, industrial hydrogen demand, wind and solar availability, production/storage sizes, and delivery through tube trailers.

The implementation develops two mixed integer models in Python with PuLP/CBC. Model 1 fixes the investment decision for the horizon and uses an availability-based electricity price. Model 2 adds commissioning decisions and persistent facility availability, using a uniform electricity price. Both account for capital expenditure, operations, hydrogen transport, electricity consumption/transmission and trailer capacity.

## Evidence from the final submission

The archived Model 1 solver log records an optimal objective of €1,211,893,128.92 with €81 million of investment. It selects small production facilities in Coimbra and Viseu and type 1 storage in Portalegre and Vila Real. Recorded electricity consumption is 33,493.026 GWh across the three representative periods, predominantly wind.

The archived Model 2 log records an optimal objective of €2,085,637,615.47 with €56 million of investment. It selects small production facilities in Évora and Setúbal and type 1 storage in Beja, all commissioned in 2030. Recorded electricity consumption is again 33,493.026 GWh, with a more balanced wind/solar allocation.

The numerical solver logs are used for these values because some slides in the PDF report have inconsistent electricity-cost totals. These results reflect the archived scenarios and should not be presented as a controlled comparison of commissioning strategies.

## Sensitivity experiment

The archived sensitivity CSV contains 15 Model 1 scenarios:

| Changed parameter | Scenarios | Archived finding |
| --- | --- | --- |
| Hydrogen transport rate | €0.35, €0.40, €0.45 and €0.50 per t-km | Objective rises from €1,211.89 million to €1,234.57 million; investment stays at €81 million |
| Renewable availability | -40%, -30%, -20%, -10%, -5% and baseline | Hydrogen transport and investment stay unchanged; electricity transfer cost rises as availability falls |
| District hydrogen demand | Baseline, +10%, +20%, +30% and +40% | Objective reaches €1,646.00 million at +40%; investment increases to €281.8 million starting at +10% |

Selected original demand PNG plots and the complete semicolon-delimited CSV are preserved in `results/archived-course-run/sensitivity/`. The current runner writes a comma-delimited CSV; readers should choose the separator that matches the file they are loading.

## Qualitative extensions

The report outlines the scope and data required for a cradle-to-gate life cycle assessment and compares water electrolysis with biomass routes. It also discusses liquid hydrogen transport tradeoffs. These are qualitative extensions; the repository does not claim a completed numerical life cycle assessment or optimization implementations for biomass and liquid transport.

## Attribution

Group 17: Margarida Sismeiro, João Filipe, Giovana Colnaghi, Marta Lourenço and Francisco Dias. Instituto Superior Técnico, Supply Chain Management, 2025/2026. Individual contributions are not separately recorded in the source report.
