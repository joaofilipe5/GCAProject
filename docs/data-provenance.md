# Data provenance

The district and facility values in `data.py` were already published in the original `GCAProject` repository. They are retained to preserve the working project and its public interface. They include demand in tonnes per year, annual wind and solar availability in GWh, inter-district distances in kilometres, and plant/storage capital expenditure and capacity tables.

The source file labels facility values as project tables. The local project directory also contains course-provided Excel inputs, an additional group workbook and course handouts. Those spreadsheets and handouts are not added here because their redistribution terms are not documented. No open data license or independently verified external source is claimed for the retained numerical inputs.

`config.py` is the final local scenario configuration. It specifies 2030/2040/2050 penetration targets of 3.5%, 12.5% and 22.5%, 0.051 GWh of electricity per tonne of hydrogen and a hydrogen transport rate of €0.35 per tonne-kilometre. Parameters describe an academic case, rather than a current investment recommendation or independently validated national forecast.

The archived solver logs come from the local final submission's `Output-Model1` and `Output-Model2` files. The sensitivity CSV and plots come from the local `Sens_Model1` directory. Their exact generation environment was not recorded. The PDF report supports the project context and authorship, but is replaced here by a summary that excludes student identifiers.

For exact historical reproduction, the contemporaneous parameter snapshot and solver environment would also be needed. In particular, the archived type 1 storage operating cost is consistent with €200 per tonne delivered, while the final source configuration contains €420. That discrepancy is documented rather than silently changing either source.
