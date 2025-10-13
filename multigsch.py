import math
import sys
import time
import threading
from pulp import (
    LpProblem, LpMinimize, LpVariable, LpBinary, lpSum,
    PULP_CBC_CMD, LpStatus, value
)

"""
GHSC network model — comments aligned with the course PDF guide
----------------------------------------------------------------
This file implements a single MILP that optimizes **dynamic design** (when to build)
and **dynamic operations** (per-period production/flows/inventory) simultaneously.

Mapping to the guide (slide numbers in the PDF):
- Indices (slide 10):
  e∈E (energy: wind, solar), i,j∈I (districts), l∈L (plant types), m∈M (storage types), t∈T (periods)
- Decision variables (slides 12–13):
  • z_prod[i,l,t], z_store[i,m,t] — binaries (facility available in period t; non-decreasing over t)
  • open_prod[i,l,t], open_store[i,m,t] — binaries (opening occurs in period t)
  • Pro[i,l,t], Inv[i,m,t], X[i,j,t], Y[i,j,t], v[j,t], ESD[e,i,t], n_PS[t], n_SD[t]
- Objective (slide 14): min TotalCost = Investment (only when opening) + Operating + Transport + Trailer penalties
- Constraints (slides 15–18):
  • Energy balance to production      → ElecReq (15.1)
  • Energy availability (no grid flows) → ElecLocalOnly (15.2–15.3)
  • Production flow to storage        → ProdFlow (16.2)
  • Storage inventory dynamics        → StorInvDyn (15.4 / 16.1)
  • Storage capacity                  → StorInvCap (18.2)
  • Shipping capacity to open arcs    → X_open / Y_open (complements 16.2 & 17.2)
  • Demand & penetration by period    → Demand / Penetration (17.1–17.3)
  • Storage outbound limited by stock → StorShipCap (17.2)
  • Trailer capacity constraints       → TrailerPSCap / TrailerSDCap
  • Facility availability monotone over time; CAPEX charged on opening only
"""

# Project-provided data (sets, parameters)
from data import (
    I, b, wind, solar, DIST,
    L, capex_prod_kEUR, prod_cap_tpd,
    Mtypes, capex_store_kEUR, store_cap_tpd
)

E_TYPES = ["wind", "solar"]

# -------- Research config (must exist in config.py) --------
from config import CONFIG as _CFG

TRANS_COST_EUR_PER_TKM         = _CFG["TRANS_COST_EUR_PER_TKM"]

ENERGY_GRID_COST_EUR_PER_GWHKM = _CFG["ENERGY_GRID_COST_EUR_PER_GWHKM"]

GAMMA_GWH_PER_TON              = _CFG["GAMMA_GWH_PER_TON"]
DAYS_PER_YEAR                  = _CFG["DAYS_PER_YEAR"]

TRAILER_PAYLOAD_TON            = _CFG["TRAILER_PAYLOAD_TON"]
TRIPS_PER_TRAILER_PER_YEAR     = _CFG["TRIPS_PER_TRAILER_PER_YEAR"]
TRAILER_COST_EUR               = _CFG["TRAILER_COST_EUR"]

T_PERIODS                      = _CFG["T_PERIODS"]
ALPHA_BY_T                     = _CFG["ALPHA_BY_T"]

# OPEX per tech/type; require keys to match sets from data.py
OPEX_PROD_EUR_PER_TON  = {l: _CFG["OPEX_PROD_EUR_PER_TON"].get(l, 0.0) for l in L}
OPEX_STORE_EUR_PER_TON = {m: _CFG["OPEX_STORE_EUR_PER_TON"].get(m, 0.0) for m in Mtypes}

# -------- Derived annual capacities --------
prod_cap_tpy  = {l: prod_cap_tpd[l]  * DAYS_PER_YEAR for l in L}
store_cap_tpy = {m: store_cap_tpd[m] * DAYS_PER_YEAR for m in Mtypes}

# -------- Network helpers --------
ARCS = [(i, j) for i in I for j in I if i != j]


# --- Solve spinner helper (optional visual feedback while CBC runs) ---
def _spinner(stop_event, label="Solving MILP (CBC)..."):
    glyphs = "|/-\\"
    i = 0
    while not stop_event.is_set():
        try:
            print(f"\r{label} {glyphs[i % len(glyphs)]}", end="", flush=True)
        except Exception:
            pass
        time.sleep(0.1)
        i += 1
    try:
        print("\r" + " " * (len(label) + 4) + "\r", end="", flush=True)
    except Exception:
        pass


def _solve_with_spinner(prob, solver, label="Solving MILP (CBC)...", show=True):
    if not show:
        return prob.solve(solver)
    stop = threading.Event()

    def _target():
        try:
            prob.solve(solver)
        finally:
            stop.set()

    t_solver = threading.Thread(target=_target, daemon=True)
    t_solver.start()

    t_spin = threading.Thread(target=_spinner, args=(stop, label), daemon=True)
    t_spin.start()

    t_solver.join()
    stop.set()
    t_spin.join()


def build_and_solve(alpha_by_t=None, c_trans=TRANS_COST_EUR_PER_TKM, energy_cost_wind=None, energy_cost_solar=None):
    start_time = time.time()
    prob = LpProblem("GHSC_Portugal_2050", LpMinimize)

    T = T_PERIODS
    if alpha_by_t is None:
        alpha_by_t = ALPHA_BY_T
    if not isinstance(alpha_by_t, dict):
        alpha_by_t = {t: float(alpha_by_t) for t in T}

    # --- Vars ---
    # Dynamic facility decisions (by period) + opening indicators
    z_prod  = {(i,l,t): LpVariable(f"z_prod_{i}_{l}_{t}", cat=LpBinary) for i in I for l in L for t in T}
    z_store = {(i,m,t): LpVariable(f"z_store_{i}_{m}_{t}", cat=LpBinary) for i in I for m in Mtypes for t in T}
    open_prod  = {(i,l,t): LpVariable(f"open_prod_{i}_{l}_{t}", cat=LpBinary) for i in I for l in L for t in T}
    open_store = {(i,m,t): LpVariable(f"open_store_{i}_{m}_{t}", cat=LpBinary) for i in I for m in Mtypes for t in T}

    Pro = {(i,l,t): LpVariable(f"Pro_{i}_{l}_{t}", lowBound=0) for i in I for l in L for t in T}

    X = {(i, j, t): LpVariable(f"X_{i}_{j}_{t}", lowBound=0) for (i, j) in ARCS for t in T}
    Y = {(i, j, t): LpVariable(f"Y_{i}_{j}_{t}", lowBound=0) for (i, j) in ARCS for t in T}

    # Energy grid flows between districts (guide 15.2–15.3): x_e[i->j,t] in GWh; no self-loops
    EGRID = {(e, i, j, t): LpVariable(f"xgrid_{e}_{i}_{j}_{t}", lowBound=0)
             for e in E_TYPES for (i, j) in ARCS for t in T}

    v   = {(j,t): LpVariable(f"v_{j}_{t}", lowBound=0) for j in I for t in T}
    Inv = {(i,m,t): LpVariable(f"Inv_{i}_{m}_{t}", lowBound=0) for i in I for m in Mtypes for t in T}
    ESD = {(e,i,t): LpVariable(f"ESD_{e}_{i}_{t}", lowBound=0) for e in E_TYPES for i in I for t in T}

    n_PS = {t: LpVariable(f"n_trailers_PS_{t}", lowBound=0, cat="Integer") for t in T}
    n_SD = {t: LpVariable(f"n_trailers_SD_{t}", lowBound=0, cat="Integer") for t in T}

    # Type-specific outbound handled by storage type m at node i in period t (Option A)
    OUT = {(i,m,t): LpVariable(f"out_{i}_{m}_{t}", lowBound=0) for i in I for m in Mtypes for t in T}

    # Fresh energy costs each call (allow overrides and avoid stale module-level values)
# --- Electricity price setup (single uniform price, no variation) ---
# Use ELECTRICITY_PRICING.P_MAX_EUR_PER_GWH as the base electricity price (fallback: max of wind/solar static costs)
    try:
        from config import CONFIG as _CFG_FRESH
    except Exception:
        _CFG_FRESH = _CFG

    pr_cfg = _CFG_FRESH.get("ELECTRICITY_PRICING", {}) or {}
    # Require explicit electricity price; no fallback allowed
    if "P_NORM_EUR_PER_GWH" not in pr_cfg:
        raise KeyError("ELECTRICITY_PRICING must contain 'P_NORM_EUR_PER_GWH' (fallback removed).")
    EC_ELEC = float(pr_cfg["P_NORM_EUR_PER_GWH"])
    cost_elec_by_i = {i: EC_ELEC for i in I}

    # --- Objective ---
    K = 1000  # kEUR→EUR

    # CAPEX charged only when a facility opens (by period)
    capex_term = (
        lpSum(K * capex_prod_kEUR[l]  * open_prod[i, l, t]  for i in I for l in L for t in T) +
        lpSum(K * capex_store_kEUR[m] * open_store[i, m, t] for i in I for m in Mtypes for t in T)
    )

    transport_term = lpSum(c_trans * DIST[i, j] * (X[i, j, t] + Y[i, j, t]) for (i, j) in ARCS for t in T)

    # Energy costs: single electricity price by node (consumption) + grid transport
    energy_term = (
        lpSum(cost_elec_by_i[i] * (ESD['wind', i, t] + ESD['solar', i, t]) for i in I for t in T) +
        lpSum(ENERGY_GRID_COST_EUR_PER_GWHKM * DIST[i, j] * EGRID[e, i, j, t]
              for e in E_TYPES for (i, j) in ARCS for t in T)
    )

    opex_prod = lpSum(OPEX_PROD_EUR_PER_TON[l] * Pro[i, l, t] for i in I for l in L for t in T)

    # storage handling: type-specific cost per ton, charged on outbound handled by type m (Option A)
    opex_store = lpSum(OPEX_STORE_EUR_PER_TON[m] * OUT[i, m, t] for i in I for m in Mtypes for t in T)

    trailer_penalty = lpSum(TRAILER_COST_EUR * (n_PS[t] + n_SD[t]) for t in T)

    # Objective: Investment (openings) + Operating + Transport + Energy + Trailer penalties
    prob += capex_term + transport_term + energy_term + opex_prod + opex_store + trailer_penalty

    # --- Constraints ---

    # Energy balance to production (guide 15.1):
    #   ∑_e ESD[e,i,t] = γ · ∑_l Pro[i,l,t]
    for i in I:
        for t in T:
            prob += (lpSum(ESD[e, i, t] for e in E_TYPES)
                     == GAMMA_GWH_PER_TON * lpSum(Pro[i, l, t] for l in L)), f"ElecReq_{i}_{t}"

    # --- Grid energy flow constraints (guide 15.2–15.3) ---
    # Let avail_e(i) denote local RES availability by source. Define imports and exports at node i.
    for e in E_TYPES:
        for i in I:
            for t in T:
                avail_e = wind[i] if e == "wind" else solar[i]
                imports = lpSum(EGRID[e, k, i, t] for (k, j2) in ARCS if j2 == i)
                exports = lpSum(EGRID[e, i, j, t] for (i2, j) in ARCS if i2 == i)
                # (15.2) Node energy demand must be met by local avail + net imports
                prob += ESD[e, i, t] <= avail_e - exports + imports, f"GridCover_{e}_{i}_{t}"
                # (15.3) Total exports from a node cannot exceed its availability (defensive cap)
                prob += exports <= avail_e, f"GridExportCap_{e}_{i}_{t}"

    # Production capacity (guide 18.1): Pro[i,l,t] ≤ u_l · z_prod[i,l,t]
    for i in I:
        for l in L:
            for t in T:
                prob += Pro[i, l, t] <= prod_cap_tpy[l] * z_prod[i, l, t], f"ProdCap_{i}_{l}_{t}"

    # Production outflow balance (guide 16.2):
    for i in I:
        for t in T:
            prob += lpSum(X[i, j, t] for (i2, j) in ARCS if i2 == i) == lpSum(Pro[i, l, t] for l in L), f"ProdFlow_{i}_{t}"

    # Storage inventory dynamics (guide 15.4 / 16.1) + capacity
    for idx, t in enumerate(T):
        for i in I:
            inflow  = lpSum(X[k, i, t] for (k, j2) in ARCS if j2 == i)
            outflow = lpSum(Y[i, j, t] for (i2, j) in ARCS if i2 == i)
            inv_t   = lpSum(Inv[i, m, t] for m in Mtypes)
            prev = 0 if idx == 0 else lpSum(Inv[i, m, T[idx-1]] for m in Mtypes)
            prob += prev + inflow - outflow == inv_t, f"StorInvDyn_{i}_{t}"
            # Storage capacity in period t: sum_m Inv[i,m,t] ≤ ∑_m u_m · z_store[i,m,t]
            cap_i = lpSum(store_cap_tpy[m] * z_store[i, m, t] for m in Mtypes)
            prob += inv_t <= cap_i, f"StorInvCap_{i}_{t}"

    # Outbound-by-type split and feasibility links (Option A)
    # Sum of per-type outbound equals total outbound from node i in period t
    for i in I:
        for t in T:
            prob += (
                lpSum(OUT[i, m, t] for m in Mtypes)
                == lpSum(Y[i, j, t] for (i2, j) in ARCS if i2 == i)
            ), f"OutSplit_{i}_{t}"

    # Per-type outbound cannot exceed available inventory of that type
    for i in I:
        for m in Mtypes:
            for t in T:
                prob += OUT[i, m, t] <= Inv[i, m, t], f"OutLeInv_{i}_{m}_{t}"

    # Arc enabling by open storage in period t
    for (i, j) in ARCS:
        for t in T:
            cap_j = lpSum(store_cap_tpy[m] * z_store[j, m, t] for m in Mtypes)
            cap_i = lpSum(store_cap_tpy[m] * z_store[i, m, t] for m in Mtypes)
            prob += X[i, j, t] <= cap_j, f"X_open_{i}_{j}_{t}"
            prob += Y[i, j, t] <= cap_i, f"Y_open_{i}_{j}_{t}"

    # Demand and penetration (guide 17.1–17.3)
    for j in I:
        for t in T:
            prob += lpSum(Y[i, j, t] for (i, j2) in ARCS if j2 == j) + v[j, t] == b[j], f"Demand_{j}_{t}"
            prob += v[j, t] <= (1.0 - alpha_by_t[t]) * b[j], f"Penetration_{j}_{t}"

    # Storage outbound limited by stock (guide 17.2)
    for i in I:
        for t in T:
            prob += lpSum(Y[i, j, t] for (i2, j) in ARCS if i2 == i) <= lpSum(Inv[i, m, t] for m in Mtypes), f"StorShipCap_{i}_{t}"

    # Trailer capacity per year
    cap_per_trailer_year = TRAILER_PAYLOAD_TON * TRIPS_PER_TRAILER_PER_YEAR
    for t in T:
        prob += lpSum(X[i, j, t] for (i, j) in ARCS) <= n_PS[t] * cap_per_trailer_year, f"TrailerPSCap_{t}"
        prob += lpSum(Y[i, j, t] for (i, j) in ARCS) <= n_SD[t] * cap_per_trailer_year, f"TrailerSDCap_{t}"

    # Monotonic availability of facilities and opening decisions (open once, stays open)
    for i in I:
        for l in L:
            for idx, t in enumerate(T):
                if idx == 0:
                    prob += open_prod[i, l, t] >= z_prod[i, l, t], f"OpenProd_ge_z_{i}_{l}_{t}"
                    prob += open_prod[i, l, t] <= z_prod[i, l, t], f"OpenProd_le_z_{i}_{l}_{t}"
                else:
                    t_prev = T[idx-1]
                    prob += z_prod[i, l, t] >= z_prod[i, l, t_prev], f"zProd_monotone_{i}_{l}_{t}"
                    prob += open_prod[i, l, t] >= z_prod[i, l, t] - z_prod[i, l, t_prev], f"OpenProd_diff_ge_{i}_{l}_{t}"
                    prob += open_prod[i, l, t] <= z_prod[i, l, t], f"OpenProd_diff_le_z_{i}_{l}_{t}"
                    prob += open_prod[i, l, t] <= 1 - z_prod[i, l, t_prev], f"OpenProd_diff_le_1minusPrev_{i}_{l}_{t}"
        for m in Mtypes:
            for idx, t in enumerate(T):
                if idx == 0:
                    prob += open_store[i, m, t] >= z_store[i, m, t], f"OpenStore_ge_z_{i}_{m}_{t}"
                    prob += open_store[i, m, t] <= z_store[i, m, t], f"OpenStore_le_z_{i}_{m}_{t}"
                else:
                    t_prev = T[idx-1]
                    prob += z_store[i, m, t] >= z_store[i, m, t_prev], f"zStore_monotone_{i}_{m}_{t}"
                    prob += open_store[i, m, t] >= z_store[i, m, t] - z_store[i, m, t_prev], f"OpenStore_diff_ge_{i}_{m}_{t}"
                    prob += open_store[i, m, t] <= z_store[i, m, t], f"OpenStore_diff_le_z_{i}_{m}_{t}"
                    prob += open_store[i, m, t] <= 1 - z_store[i, m, t_prev], f"OpenStore_diff_le_1minusPrev_{i}_{m}_{t}"

    # --- Solve ---
    solver = PULP_CBC_CMD(msg=False)
    _solve_with_spinner(prob, solver, label="Solving MILP (CBC)...", show=True)

    # --- Report ---
    status = LpStatus[prob.status]
    obj = value(prob.objective)

    print("\n=== Solve Status ===")
    print(status)
    print(f"Objective (Total Cost) = {obj:,.2f} EUR")
    print(f"Transport (H2): {c_trans:.2f} €/t·km")
    print(f"Electricity: {EC_ELEC:,.0f} €/GWh (uniform; base=P_MAX_EUR_PER_GWH) | grid transport={ENERGY_GRID_COST_EUR_PER_GWHKM:.3f} €/GWh·km")
    

    # Energy usage (no costs)
    total_esd = sum(value(ESD[e, i, t]) for e in E_TYPES for i in I for t in T)
    total_esd_wind = sum(value(ESD['wind', i, t]) for i in I for t in T)
    total_esd_solar = sum(value(ESD['solar', i, t]) for i in I for t in T)
    print(f"Energy used: {total_esd:,.3f} GWh  (wind {total_esd_wind:,.3f} | solar {total_esd_solar:,.3f})")
    est_energy_cost = sum(cost_elec_by_i[i] * sum(value(ESD['wind', i, t]) + value(ESD['solar', i, t]) for t in T) for i in I)
    print(f"Estimated electricity cost (consumption + uniform price): {est_energy_cost:,.0f} EUR")

    # === Facilities opened and active by period ===
    print("\n=== Facilities Opened By Period ===")
    any_open = False
    for t in T:
        prod_opens = [(i,l) for (i,l,tt) in open_prod if tt == t and value(open_prod[i,l,t]) > 0.5]
        stor_opens = [(i,m) for (i,m,tt) in open_store if tt == t and value(open_store[i,m,t]) > 0.5]
        if prod_opens or stor_opens:
            any_open = True
            print(f"Period {t}:")
            if prod_opens:
                print("  Production opened:")
                for (i,l) in prod_opens:
                    print(f"    - {i:15s} | {l:8s} | cap {prod_cap_tpy[l]:,.0f} t/yr")
            if stor_opens:
                print("  Storage opened:")
                for (i,m) in stor_opens:
                    print(f"    - {i:15s} | {m:8s} | cap {store_cap_tpy[m]:,.0f} t/yr")
    if not any_open:
        print("(no facilities opened in any period)")

    print("\n=== Active Facilities By Period (cumulative) ===")
    for t in T:
        prod_active = [(i,l) for (i,l,tt) in z_prod if tt == t and value(z_prod[i,l,t]) > 0.5]
        stor_active = [(i,m) for (i,m,tt) in z_store if tt == t and value(z_store[i,m,t]) > 0.5]
        print(f"Period {t}:")
        if prod_active:
            print("  Production active:")
            for (i,l) in prod_active:
                print(f"    - {i:15s} | {l:8s} | cap {prod_cap_tpy[l]:,.0f} t/yr")
        else:
            print("  (no active production)")
        if stor_active:
            print("  Storage active:")
            for (i,m) in stor_active:
                print(f"    - {i:15s} | {m:8s} | cap {store_cap_tpy[m]:,.0f} t/yr")
        else:
            print("  (no active storage)")

    # === Per-period cost breakdown (transport, OPEX, trailers, CAPEX) ===
    print("\n=== Per-period cost breakdown (EUR) ===")
    capex_eur = (
        sum(1000 * capex_prod_kEUR[l]  * (1 if value(open_prod[i,l,t])  > 0.5 else 0) for i in I for l in L for t in T) +
        sum(1000 * capex_store_kEUR[m] * (1 if value(open_store[i,m,t]) > 0.5 else 0) for i in I for m in Mtypes for t in T)
    )
    print(f"CAPEX (sum over openings): {capex_eur:,.0f} EUR")

    header = f"{'Period':>8s} | {'Transport':>14s} | {'Energy':>12s} | {'OPEX_prod':>12s} | {'OPEX_store':>12s} | {'Trailers':>10s} | {'CAPEX':>12s} | {'Total no CAPEX':>16s} | {'Total incl CAPEX':>16s}"
    print(header)
    print("-" * len(header))
    per_period_costs = {}
    for t in T:
        transport_t = sum(c_trans * DIST[i, j] * (value(X[i, j, t]) + value(Y[i, j, t])) for (i, j) in ARCS)
        energy_t = (
            sum(cost_elec_by_i[i] * (value(ESD['wind', i, t]) + value(ESD['solar', i, t])) for i in I) +
            sum(ENERGY_GRID_COST_EUR_PER_GWHKM * DIST[i, j] * value(EGRID[e, i, j, t])
                for e in E_TYPES for (i, j) in ARCS)
        )
        opex_prod_t = sum(OPEX_PROD_EUR_PER_TON[l] * value(Pro[i, l, t]) for i in I for l in L)
        opex_store_t = sum(OPEX_STORE_EUR_PER_TON[m] * value(OUT[i, m, t]) for i in I for m in Mtypes)
        trailer_t = TRAILER_COST_EUR * (int(value(n_PS[t])) + int(value(n_SD[t])))
        capex_t = (
            sum(1000 * capex_prod_kEUR[l]  * (1 if value(open_prod[i,l,t])  > 0.5 else 0) for i in I for l in L) +
            sum(1000 * capex_store_kEUR[m] * (1 if value(open_store[i,m,t]) > 0.5 else 0) for i in I for m in Mtypes)
        )
        total_no_capex = transport_t + energy_t + opex_prod_t + opex_store_t + trailer_t
        total_incl_capex = total_no_capex + capex_t
        per_period_costs[t] = dict(
            transport=transport_t, energy=energy_t, opex_prod=opex_prod_t, opex_store=opex_store_t,
            trailer=trailer_t, capex=capex_t,
            total_no_capex=total_no_capex, total_incl_capex=total_incl_capex
        )
        print(f"{t:>8s} | {transport_t:14,.0f} | {energy_t:12,.0f} | {opex_prod_t:12,.0f} | {opex_store_t:12,.0f} | {trailer_t:10,.0f} | {capex_t:12,.0f} | {total_no_capex:16,.0f} | {total_incl_capex:16,.0f}")

    # Reporting per period t: operations summary
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
            print(f"    - {j:15s}: delivered={delivered:,.1f} t  unmet={unmet:,.1f} t  (target α·b={target:,.1f} t)")
        print("  Transport:")
        print(f"    P->S flow X = {total_X_t:,.1f} t/yr | trailers = {int(value(n_PS[t]))}")
        print(f"    S->D flow Y = {total_Y_t:,.1f} t/yr | trailers = {int(value(n_SD[t]))}")
        opens_prod_t = sum(1 for (i2,l2,tt) in open_prod if tt == t and value(open_prod[i2,l2,t]) > 0.5)
        opens_store_t = sum(1 for (i2,m2,tt) in open_store if tt == t and value(open_store[i2,m2,t]) > 0.5)
        print(f"  Openings this period: prod={opens_prod_t}, storage={opens_store_t}")

    inv_by_loc_last = {i: sum(value(Inv[i, m, T[-1]]) for m in Mtypes) for i in I}

    # --- Timing ---
    end_time = time.time()
    runtime_sec = end_time - start_time
    runtime_min = int(runtime_sec // 60)
    runtime_rem_sec = runtime_sec % 60
    print(f"\n=== Runtime ===\nTotal runtime: {runtime_min} min {runtime_rem_sec:.2f} sec")

    # For backward-compat: provide 'prod_sites'/'stor_sites' as active in last period
    prod_sites_last = [(i,l) for (i,l,tt) in z_prod if tt == T[-1] and value(z_prod[i,l,T[-1]]) > 0.5]
    stor_sites_last = [(i,m) for (i,m,tt) in z_store if tt == T[-1] and value(z_store[i,m,T[-1]]) > 0.5]

    return dict(
        status=status, objective=obj,
        capex_total_eur=capex_eur, capex_eur=capex_eur,
        per_period_costs=per_period_costs,
        trailers_PS={t: int(value(n_PS[t])) for t in T},
        trailers_SD={t: int(value(n_SD[t])) for t in T},
        prod_openings_by_t={t: [(i,l) for (i,l,tt) in open_prod if tt == t and value(open_prod[i,l,t]) > 0.5] for t in T},
        store_openings_by_t={t: [(i,m) for (i,m,tt) in open_store if tt == t and value(open_store[i,m,t]) > 0.5] for t in T},
        prod_active_by_t={t: [(i,l) for (i,l,tt) in z_prod if tt == t and value(z_prod[i,l,t]) > 0.5] for t in T},
        store_active_by_t={t: [(i,m) for (i,m,tt) in z_store if tt == t and value(z_store[i,m,t]) > 0.5] for t in T},
        # Backward compatibility keys:
        prod_sites=prod_sites_last, stor_sites=stor_sites_last,
        total_X=total_X_all, total_Y=total_Y_all,
        inventory_last_period=inv_by_loc_last,
        energy_cost_electricity_by_node=cost_elec_by_i,
    )

if __name__ == "__main__":
    build_and_solve()