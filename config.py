# Research config (overrides). Keep project-provided tables in data.py.

CONFIG = {
        
    # Logistics
    "TRANS_COST_EUR_PER_TKM": 0.35,
    "ENERGY_GRID_COST_EUR_PER_GWHKM": 0.01,  # €/GWh·km

    # Power & process
    "GAMMA_GWH_PER_TON": 0.051,

    # Time
    "T_PERIODS": ["2030", "2040", "2050"],
    "ALPHA_BY_T": {"2030": 0.035, "2040": 0.125, "2050": 0.225},

    # Trailers
    "TRAILER_PAYLOAD_TON": 0.70,
    "TRIPS_PER_TRAILER_PER_YEAR": 250,
    "TRAILER_COST_EUR": 1,  # Academic objective coefficient in EUR per trailer

    # OPEX (€/t) — keys must match data.py sets
    "OPEX_PROD_EUR_PER_TON": {
        "S": 350,   # €/t
        "M": 250,   # €/t
        "L": 195,    # €/t
    },

    # Type-specific handling costs charged on storage outflow (€/t)
    "OPEX_STORE_EUR_PER_TON": {
        "1": 420,    # €/t handled
        "2": 250,
        "3": 230,
        "4": 210,
        "5": 200,
    },

    "DAYS_PER_YEAR": 365,

}

# --- Dynamic electricity pricing (single price, range-linear) ---
# Prices decrease with higher total local availability (wind+solar), normalized by the max across nodes.
# Method = "range_linear_single": c_i = p_max - (p_max - p_min) * A_i,  A_i in [0,1]
# where A_i = (wind_i + solar_i) / max_j (wind_j + solar_j)

CONFIG["ELECTRICITY_PRICING"] = {
    "DYNAMIC": True,
    "METHOD": "range_linear_single",
    "P_MIN_EUR_PER_GWH": 20000.0,   # lower bound €/GWh
    "P_NORM_EUR_PER_GWH": 50000.0,   # mid-point €/GWh (not used in "single" method)
    "P_MAX_EUR_PER_GWH": 60000.0    # upper bound €/GWh
}
