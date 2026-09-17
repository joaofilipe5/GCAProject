# Model assumptions and limitations

## Formulation

The model represents a production-to-storage-to-demand network. Binary variables select production/storage types and, in Model 2, the opening period. Continuous variables represent production, hydrogen flows, inventories, renewable electricity use and electricity transfers; integer variables represent trailer counts.

The electricity-production equality uses 0.051 GWh per tonne of hydrogen. Renewable generation has district availability limits, and inter-district transfers incur a distance-dependent cost. Hydrogen transport is charged on both production-to-storage and storage-to-demand arcs. Facility capacities are converted from tonnes per day to tonnes per year using 365 days.

Demand constraints allow an unmet amount relative to full district demand, while requiring delivered hydrogen to reach a configured penetration fraction. The default targets are 3.5%, 12.5% and 22.5% for the three periods. This is a minimum adoption target, not a requirement to serve all baseline demand.

Model 1's district electricity price is:

```text
availability[i] = (wind[i] + solar[i]) / max_district(wind + solar)
price[i] = maximum_price - (maximum_price - minimum_price) * availability[i]
```

The default band is €20,000-€60,000 per GWh. Model 2 uses the configured uniform price, €50,000 per GWh. Electricity is charged at the consuming district's price in Model 1, including when it is imported. This is an experimental availability-based pricing assumption, rather than electricity market clearing.

## Reading the results

- The horizon contains three representative periods. Operations are not expanded into every intervening year, discounted, or weighted by the decade length. The objective is a sum of the modelled period costs and investment, not a discounted 2030-2050 cash flow forecast.
- Inventory is carried between the representative periods. Outbound shipments are constrained by **end-of-period** inventory in addition to the inventory balance. This can induce persistent stock and production above same-period deliveries; inventory and capacity units deserve further modelling review before practical use.
- Transport arcs exclude self-loops. Production, storage and demand at the same district cannot exchange hydrogen through a same-district arc in this implementation.
- Plant and storage binaries are defined independently by type; the formulation does not generally limit a district to one plant type or one storage type.
- The configured trailer coefficient is €1 per modelled trailer. The source's old comment refers to a different amount; the operative value is the numeric coefficient. Trailer counts and transport-rate costs should be interpreted separately.
- Dynamic electricity pricing is always calculated in Model 1. Its retained `dynamic_energy_pricing` argument controls a reporting message rather than switching the objective to uniform prices.
- The facility decisions and electricity prices both differ between the two models. The archived higher Model 2 objective cannot be attributed solely to its investment timing.
- Model 2 permits gradual commissioning, but the archived optimal solution opens every selected facility in 2030. The archive does not demonstrate later openings.
- Final local source and historical logs do not contain a complete reproducibility snapshot. The final configuration has a type 1 storage cost of €420/t, whereas the archived storage costs imply €200/t. New default runs should therefore not be expected to equal the archived objectives.

The source formulations are retained as the academic project. No emissions constraints, measured life cycle assessment, uncertainty model, biomass production implementation, or liquid hydrogen logistics implementation is claimed. Those subjects were discussed qualitatively in the report.
