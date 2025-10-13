# Research config (overrides). Keep project-provided tables in data.py.

CONFIG = {
        
    # Logistics
    "TRANS_COST_EUR_PER_TKM": 0.35,
    "ENERGY_GRID_COST_EUR_PER_GWHKM": 0.01,  # €/GWh·km

    # Power & process
    "GAMMA_GWH_PER_TON": 0.051,

    # Time
    "T_PERIODS": ["2030", "2040", "2050"],
    "ALPHA_BY_T": {"2030": 0.05, "2040": 0.15, "2050": 0.25},

    # Trailers
    "TRAILER_PAYLOAD_TON": 0.90,
    "TRIPS_PER_TRAILER_PER_YEAR": 250,
    "TRAILER_COST_EUR": 1,  # €10,000

    # OPEX (€/t) — keys must match data.py sets
    "OPEX_PROD_EUR_PER_TON": {
        "S": 600,   # €/t
        "M": 400,   # €/t
        "L": 200,    # €/t
    },

    # If keeping the model’s “charge on outflow” approach, use small numbers (≈2–10 €/t)
    "OPEX_STORE_EUR_PER_TON": {
        "1": 250,    # €/t handled
        "2": 200,
        "3": 150,
        "4": 120,
        "5": 100,
    },

    "DAYS_PER_YEAR": 365,
    
    # --- Sensitivity analysis settings ---
    # Transport cost range (inclusive) and number of points
    "SENS_TRANS_COST_RANGE": [0.35, 0.50],
    "SENS_TRANS_POINTS": 5,

    # Energy cost % deltas applied to BOTH wind and solar simultaneously
    # e.g., -0.25 => reduce both by 25%
    "SENS_ENERGY_PCT_DELTAS": [-0.25, -0.10, 0.0, 0.10, 0.25],

    # Penetration ranges per year and number of points (same index across all years)
    "SENS_PENETRATION_RANGES": {
        "2030": [0.02, 0.05],
        "2040": [0.10, 0.15],
        "2050": [0.20, 0.25]
    },
    "SENS_PEN_POINTS": 5,
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

