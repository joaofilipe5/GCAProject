# Research config (overrides). Keep project-provided tables in data.py.

CONFIG = {
    
    # Logistics
    "TRANS_COST_EUR_PER_TKM": 0.40,
    "ENERGY_GRID_COST_EUR_PER_GWHKM": 0.01,

    # Power & process
    "ENERGY_COST_WIND_EUR_PER_GWH": 3000, # This values are not changing the total cost, and the total cost is brutally high compared to last years project references
    "ENERGY_COST_SOLAR_EUR_PER_GWH": 3000,
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
        "S": 1000,   # €/t
        "M": 500,   # €/t
        "L": 250,    # €/t
    },

    # If keeping the model’s “charge on outflow” approach, use small numbers (≈2–10 €/t)
    "OPEX_STORE_EUR_PER_TON": {
        "1": 5,    # €/t handled
        "2": 7,
        "3": 9,
        "4": 11,
        "5": 13,
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