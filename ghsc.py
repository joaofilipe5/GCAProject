# Green Hydrogen Supply Chain – Portugal 2050 (PuLP MILP)
# Self-contained: all tables embedded as Python dicts/lists (no Excel needed)

import math
from pulp import (
    LpProblem, LpMinimize, LpVariable, LpBinary, lpSum,
    PULP_CBC_CMD, LpStatus, value
)

# ----------------------------
# DATA IMPORT (from external data.py)
# ----------------------------
from data import (
    I, b, wind, solar, DIST,
    L, capex_prod_kEUR, prod_cap_tpd,
    Mtypes, capex_store_kEUR, store_cap_tpd
)

# Energy source types (as in the guidance: e ∈ {wind, solar})
E_TYPES = ["wind", "solar"]

# ----------------------------
# USER CONFIG
# ----------------------------

TRANS_COST_EUR_PER_TKM = 0.40     # choose 0.35 .. 0.50 SENSITIVITY ANALYSIS -> TODO
ENERGY_COST_EUR_PER_GWH = 89000     # set > 0 to monetize electricity
GAMMA_GWH_PER_TON = 0.051         # GWh per tonne H2 (electrolysis)
DAYS_PER_YEAR = 365

# Tube-trailer assumptions (very simple post-calc)
TRAILER_PAYLOAD_TON = 1.0         # tonnes per trip (placeholder)
TRIPS_PER_TRAILER_PER_YEAR = 300  # round trips per trailer per year (avg)

# Time periods (multi-period elementary model)
T_PERIODS = ["2030", "2040", "2050"]

# Penetration by period (Percentage of demand to be met by H2)
ALPHA_BY_T = {"2030": 0.05, "2040": 0.15, "2050": 0.25} 

# Electricity grid transport cost (€/GWh·km). Set 0.0 to ignore.
ENERGY_GRID_COST_EUR_PER_GWHKM = 0.0

# OPEX (€/t handled/produced) — placeholders; adjust as needed
OPEX_PROD_EUR_PER_TON = {l: 0.0 for l in L}
OPEX_STORE_EUR_PER_TON = {m: 0.0 for m in Mtypes}

# Trailer decision cost (tiny penalty so the solver picks the minimal feasible fleet)
TRAILER_COST_EUR = 1.0

# ----------------------------
# DERIVED CAPACITIES (annualized from data.py)
# NOTE: We interpret Table-4 "tons/day" for storage as a *stock cap* and scale to t/yr
#       to keep units consistent with annual flows in this single-period model.
# ----------------------------
prod_cap_tpy = {l: prod_cap_tpd[l] * DAYS_PER_YEAR for l in L}
store_cap_tpy = {m: store_cap_tpd[m] * DAYS_PER_YEAR for m in Mtypes}

# ----------------------------
# MODEL
# ----------------------------
# ----------------------------
# INDEX SET HELPERS (sparser networks)
# ----------------------------
# Exclude self-shipments to cut ~|I|*|T| variables/constraints per flow tensor
ARCS = [(i, j) for i in I for j in I if i != j]

# If grid transport is free (default 0.0), avoid creating Eflow variables at all
USE_EGRID = (ENERGY_GRID_COST_EUR_PER_GWHKM > 0.0)

def build_and_solve(alpha_by_t=None, c_trans=TRANS_COST_EUR_PER_TKM):
    prob = LpProblem("GHSC_Portugal_2050_INLINE", LpMinimize)

    # Periods and penetration targets
    T = T_PERIODS
    if alpha_by_t is None:
        alpha_by_t = ALPHA_BY_T
    # If a scalar is passed, apply it to all periods
    if not isinstance(alpha_by_t, dict):
        alpha_by_t = {t: float(alpha_by_t) for t in T}

    # Decision variables (multi-period)
    z_prod = {(i,l): LpVariable(f"z_prod_{i}_{l}", cat=LpBinary) for i in I for l in L}
    z_store = {(i,m): LpVariable(f"z_store_{i}_{m}", cat=LpBinary) for i in I for m in Mtypes}

    Pro = {(i,l,t): LpVariable(f"Pro_{i}_{l}_{t}", lowBound=0) for i in I for l in L for t in T}

    # Transport flows (only for i != j)
    X = {(i, j, t): LpVariable(f"X_{i}_{j}_{t}", lowBound=0) for (i, j) in ARCS for t in T}  # P -> S
    Y = {(i, j, t): LpVariable(f"Y_{i}_{j}_{t}", lowBound=0) for (i, j) in ARCS for t in T}  # S -> D

    # Electricity flows only if grid cost is modeled; otherwise, we keep it local
    if USE_EGRID:
        Eflow = {(e, i, j, t): LpVariable(f"Eflow_{e}_{i}_{j}_{t}", lowBound=0)
                 for e in E_TYPES for (i, j) in ARCS for t in T}
    else:
        Eflow = {}

    v = {(j,t): LpVariable(f"v_{j}_{t}", lowBound=0) for j in I for t in T}

    # Inventory at storage by location and tank type (end-of-period stock)
    Inv = {(i,m,t): LpVariable(f"Inv_{i}_{m}_{t}", lowBound=0) for i in I for m in Mtypes for t in T}

    # Daily energy source demand used at node i covered by source e (ESD in slides) [GWh]
    ESD = {(e,i,t): LpVariable(f"ESD_{e}_{i}_{t}", lowBound=0)
           for e in E_TYPES for i in I for t in T}

    # Trailer fleet (integer) per period for each leg
    n_PS = {t: LpVariable(f"n_trailers_PS_{t}", lowBound=0, cat="Integer") for t in T}
    n_SD = {t: LpVariable(f"n_trailers_SD_{t}", lowBound=0, cat="Integer") for t in T}

    # (Optional) convert capex k€ → € (set to 1000 if you want objective in €)
    K = 1000  # 1000 means objective in euros; set to 1 for k€

    capex_term = (
        lpSum(K * capex_prod_kEUR[l] * z_prod[i, l] for i in I for l in L) +
        lpSum(K * capex_store_kEUR[m] * z_store[i, m] for i in I for m in Mtypes)
    )

    transport_term = lpSum(c_trans * DIST[i, j] * (X[i, j, t] + Y[i, j, t]) for (i, j) in ARCS for t in T)

    elec_transport_term = (
        lpSum(ENERGY_GRID_COST_EUR_PER_GWHKM * DIST[i, j] * Eflow[e, i, j, t]
              for e in E_TYPES for (i, j) in ARCS for t in T)
        if USE_EGRID else 0
    )

    energy_term = lpSum(ENERGY_COST_EUR_PER_GWH * GAMMA_GWH_PER_TON * Pro[i, l, t] for i in I for l in L for t in T)

    # OPEX: production per technology + storage handling per node (only if some storage is installed)
    opex_prod = lpSum(OPEX_PROD_EUR_PER_TON[l] * Pro[i, l, t] for i in I for l in L for t in T)
    opex_store = lpSum(
        (lpSum(z_store[i, m] for m in Mtypes) >= 1) * 0  # placeholder to keep structure
        for i in I
    )  # NOTE: placeholder line to avoid syntax issues; replaced just below

    # Replace placeholder: charge storage opex once per node using the minimum nonzero cost across types
    min_store_opex = min(OPEX_STORE_EUR_PER_TON[m] for m in Mtypes) if len(Mtypes) > 0 else 0.0
    opex_store = lpSum(min_store_opex * lpSum(Y[i, j, t] for (i2, j) in ARCS if i2 == i) for i in I for t in T)
    opex_term = opex_prod + opex_store

    # Tiny penalty so the model picks the minimal feasible trailer fleet
    trailer_penalty = lpSum(TRAILER_COST_EUR * (n_PS[t] + n_SD[t]) for t in T)

    prob += capex_term + transport_term + elec_transport_term + energy_term + opex_term + trailer_penalty

    # 1) Electricity (per guidance): split by source e ∈ {wind, solar}
    # (a) Total energy required by electrolysis at node i equals the sum of source-specific uses
    for i in I:
        for t in T:
            prob += (
                lpSum(ESD[e, i, t] for e in E_TYPES)
                == GAMMA_GWH_PER_TON * lpSum(Pro[i, l, t] for l in L)
            ), f"ElecReq_{i}_{t}"

    if USE_EGRID:
        # With grid: local use cannot exceed availability plus net imports of that source
        for e in E_TYPES:
            for i in I:
                for t in T:
                    avail_e = wind[i] if e == "wind" else solar[i]
                    prob += (
                        ESD[e, i, t]
                        <= avail_e + lpSum(Eflow[e, k, i, t] for (k, i2) in ARCS if i2 == i)
                                   - lpSum(Eflow[e, i, j, t] for (i2, j) in ARCS if i2 == i)
                    ), f"ElecCover_{e}_{i}_{t}"
        # Export cap: exports cannot exceed local availability
        for e in E_TYPES:
            for i in I:
                for t in T:
                    avail_e = wind[i] if e == "wind" else solar[i]
                    prob += lpSum(Eflow[e, i, j, t] for (i2, j) in ARCS if i2 == i) <= avail_e, f"ElecExportCap_{e}_{i}_{t}"
    else:
        # No grid modeled: local electrolysis must use local availability only
        for e in E_TYPES:
            for i in I:
                for t in T:
                    avail_e = wind[i] if e == "wind" else solar[i]
                    prob += ESD[e, i, t] <= avail_e, f"ElecLocalOnly_{e}_{i}_{t}"

    # 2) Production capacity (plant must be open)
    for i in I:
        for l in L:
            for t in T:
                prob += Pro[i, l, t] <= prod_cap_tpy[l] * z_prod[i, l], f"ProdCap_{i}_{l}_{t}"

    # 3) Production mass balance per period: all production goes to storage
    for i in I:
        for t in T:
            prob += lpSum(X[i, j, t] for (i2, j) in ARCS if i2 == i) == lpSum(Pro[i, l, t] for l in L), f"ProdFlow_{i}_{t}"

    # 4) Storage inventory dynamics and capacity
    #    Sum_m Inv[i,m,t] = (t==first? 0 : Sum_m Inv[i,m,t-1]) + inflow - outflow
    for idx, t in enumerate(T):
        for i in I:
            inflow = lpSum(X[k, i, t] for (k, j2) in ARCS if j2 == i)
            outflow = lpSum(Y[i, j, t] for (i2, j) in ARCS if i2 == i)
            inv_sum_t = lpSum(Inv[i, m, t] for m in Mtypes)
            if idx == 0:
                prev = 0
            else:
                tprev = T[idx - 1]
                prev = lpSum(Inv[i, m, tprev] for m in Mtypes)
            prob += prev + inflow - outflow == inv_sum_t, f"StorInvDyn_{i}_{t}"

            # Inventory capacity: end-of-period stock limited by installed tanks
            cap_i = lpSum(store_cap_tpy[m] * z_store[i, m] for m in Mtypes)
            prob += inv_sum_t <= cap_i, f"StorInvCap_{i}_{t}"
 
    # 5) Feasibility linking for flows (storage must be open to send/receive H2)
    for (i, j) in ARCS:
        for t in T:
            cap_j = lpSum(store_cap_tpy[m] * z_store[j, m] for m in Mtypes)
            cap_i = lpSum(store_cap_tpy[m] * z_store[i, m] for m in Mtypes)
            prob += X[i, j, t] <= cap_j, f"X_open_{i}_{j}_{t}"
            prob += Y[i, j, t] <= cap_i, f"Y_open_{i}_{j}_{t}"

    # 6) Demand & penetration (per period)
    for j in I:
        for t in T:
            prob += lpSum(Y[i, j, t] for (i, j2) in ARCS if j2 == j) + v[j, t] == b[j], f"Demand_{j}_{t}"
            prob += v[j, t] <= (1.0 - alpha_by_t[t]) * b[j], f"Penetration_{j}_{t}"

    # Storage shipping cannot exceed stored amount (guidance slide 17, item 2)
    for i in I:
        for t in T:
            prob += lpSum(Y[i, j, t] for (i2, j) in ARCS if i2 == i) <= lpSum(Inv[i, m, t] for m in Mtypes), f"StorShipCap_{i}_{t}"

    # 7) Trailer capacity constraints (per period; fleet sized via integer n)
    cap_per_trailer_year = TRAILER_PAYLOAD_TON * TRIPS_PER_TRAILER_PER_YEAR
    for t in T:
        prob += lpSum(X[i, j, t] for (i, j) in ARCS) <= n_PS[t] * cap_per_trailer_year, f"TrailerPSCap_{t}"
        prob += lpSum(Y[i, j, t] for (i, j) in ARCS) <= n_SD[t] * cap_per_trailer_year, f"TrailerSDCap_{t}"

    # Solve
    solver = PULP_CBC_CMD(msg=False)  # Name of the solver to refer in the report
    prob.solve(solver)

    # Results
    status = LpStatus[prob.status]
    obj = value(prob.objective)

    prod_sites = [(i, l) for (i, l) in z_prod if value(z_prod[i, l]) > 0.5]
    stor_sites = [(i, m) for (i, m) in z_store if value(z_store[i, m]) > 0.5]

    print("\n=== Solve Status ===")
    print(status)
    print(f"Objective (Total Cost) = {obj:,.2f} {'EUR' if K==1000 else 'kEUR'}")
    print(f"Transport (H2): {c_trans:.2f} €/t·km | Grid (elec): {ENERGY_GRID_COST_EUR_PER_GWHKM:.2f} €/GWh·km")

    print("\n=== Production & Storage Facilities Chosen (static across periods) ===")
    if not prod_sites:
        print("  Plants: None")
    else:
        for (i, l) in prod_sites:
            cap = prod_cap_tpy[l]
            cost = capex_prod_kEUR[l] * 1000  # convert kEUR to EUR
            print(f"  - Plant {l} @ {i}: Cap = {cap:,} t/yr | Investment = {cost:,.0f} EUR")
    if not stor_sites:
        print("  Storage: None")
    else:
        for (i, m) in stor_sites:
            cost = capex_store_kEUR[m] * 1000  # convert kEUR to EUR
            print(f"  - Tank {m} @ {i}: Stock cap = {store_cap_tpy[m]:,} t | Investment = {cost:,.0f} EUR")

    # Per-period summaries
    total_X_all = 0.0
    total_Y_all = 0.0
    for t in T:
        total_X_t = sum(value(X[i, j, t]) for (i, j) in ARCS)
        total_Y_t = sum(value(Y[i, j, t]) for (i, j) in ARCS)
        total_X_all += total_X_t
        total_Y_all += total_Y_t
        print(f"\n=== Period {t} (alpha={alpha_by_t[t]:.2%}) ===")
        for i in I:
            pro_i = sum(value(Pro[i, l, t]) for l in L)
            inv_i = sum(value(Inv[i, m, t]) for m in Mtypes)
            print(f"  [Node {i}] Production={pro_i:>9,.1f} t  EndInv={inv_i:>9,.1f} t")
        print("  Demand satisfaction:")
        for j in I:
            delivered = sum(value(Y[i2, j, t]) for (i2, j2) in ARCS if j2 == j)
            unmet = value(v[j, t])
            target = b[j]*alpha_by_t[t]
            print(f"    - {j:17s}: demand={b[j]:>9,.1f}  delivered={delivered:>9,.1f}  unmet={unmet:>9,.1f}  target={target:>9,.1f}")
        print("  Transport:")
        print(f"    P->S flow X = {total_X_t:,.1f} t/yr | trailers = {int(value(n_PS[t]))}")
        print(f"    S->D flow Y = {total_Y_t:,.1f} t/yr | trailers = {int(value(n_SD[t]))}")

    inv_by_loc_last = {i: sum(value(Inv[i, m, T[-1]]) for m in Mtypes) for i in I}

    return dict(
        status=status, objective=obj, prod_sites=prod_sites, stor_sites=stor_sites,
        total_X=total_X_all, total_Y=total_Y_all,
        trailers_PS={t: int(value(n_PS[t])) for t in T},
        trailers_SD={t: int(value(n_SD[t])) for t in T},
        inventory_last_period=inv_by_loc_last
    )

if __name__ == "__main__":
    build_and_solve()

    # Create error handling for infinite optimization, 
    # Currently running for 287 minutes, we are cooked and I am drunk :)