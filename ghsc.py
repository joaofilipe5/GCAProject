import math
import sys
import time
import threading
from pulp import (
    LpProblem, LpMinimize, LpVariable, LpBinary, lpSum,
    PULP_CBC_CMD, LpStatus, value
)

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

ENERGY_COST_WIND_EUR_PER_GWH   = _CFG["ENERGY_COST_WIND_EUR_PER_GWH"]
ENERGY_COST_SOLAR_EUR_PER_GWH  = _CFG["ENERGY_COST_SOLAR_EUR_PER_GWH"]
GAMMA_GWH_PER_TON              = _CFG["GAMMA_GWH_PER_TON"]
DAYS_PER_YEAR                  = _CFG["DAYS_PER_YEAR"]

TRAILER_PAYLOAD_TON            = _CFG["TRAILER_PAYLOAD_TON"]
TRIPS_PER_TRAILER_PER_YEAR     = _CFG["TRIPS_PER_TRAILER_PER_YEAR"]
TRAILER_COST_EUR               = _CFG["TRAILER_COST_EUR"]

T_PERIODS                      = _CFG["T_PERIODS"]
ALPHA_BY_T                     = _CFG["ALPHA_BY_T"]

ENERGY_GRID_COST_EUR_PER_GWHKM = _CFG["ENERGY_GRID_COST_EUR_PER_GWHKM"]

# OPEX per tech/type; require keys to match sets from data.py
OPEX_PROD_EUR_PER_TON  = {l: _CFG["OPEX_PROD_EUR_PER_TON"].get(l, 0.0) for l in L}
OPEX_STORE_EUR_PER_TON = {m: _CFG["OPEX_STORE_EUR_PER_TON"].get(m, 0.0) for m in Mtypes}

# -------- Derived annual capacities --------
prod_cap_tpy  = {l: prod_cap_tpd[l]  * DAYS_PER_YEAR for l in L}
store_cap_tpy = {m: store_cap_tpd[m] * DAYS_PER_YEAR for m in Mtypes}

# -------- Network helpers --------
ARCS = [(i, j) for i in I for j in I if i != j]
USE_EGRID = (ENERGY_GRID_COST_EUR_PER_GWHKM > 0.0)


# --- Solve spinner helper (optional visual feedback while CBC runs) ---
# Shows a non-blocking console spinner until the solver finishes.
# This does not require knowing the number of B&B nodes a priori.

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
    # clear the spinner line
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


def build_and_solve(alpha_by_t=None, c_trans=TRANS_COST_EUR_PER_TKM,
                    energy_cost_wind=None, energy_cost_solar=None):
    start_time = time.time()
    prob = LpProblem("GHSC_Portugal_2050", LpMinimize)

    T = T_PERIODS
    if alpha_by_t is None:
        alpha_by_t = ALPHA_BY_T
    if not isinstance(alpha_by_t, dict):
        alpha_by_t = {t: float(alpha_by_t) for t in T}

    # --- Vars ---
    z_prod  = {(i,l): LpVariable(f"z_prod_{i}_{l}", cat=LpBinary) for i in I for l in L}
    z_store = {(i,m): LpVariable(f"z_store_{i}_{m}", cat=LpBinary) for i in I for m in Mtypes}

    Pro = {(i,l,t): LpVariable(f"Pro_{i}_{l}_{t}", lowBound=0) for i in I for l in L for t in T}

    X = {(i, j, t): LpVariable(f"X_{i}_{j}_{t}", lowBound=0) for (i, j) in ARCS for t in T}
    Y = {(i, j, t): LpVariable(f"Y_{i}_{j}_{t}", lowBound=0) for (i, j) in ARCS for t in T}

    if USE_EGRID:
        Eflow = {(e, i, j, t): LpVariable(f"Eflow_{e}_{i}_{j}_{t}", lowBound=0)
                 for e in E_TYPES for (i, j) in ARCS for t in T}
    else:
        Eflow = {}

    v   = {(j,t): LpVariable(f"v_{j}_{t}", lowBound=0) for j in I for t in T}
    Inv = {(i,m,t): LpVariable(f"Inv_{i}_{m}_{t}", lowBound=0) for i in I for m in Mtypes for t in T}
    ESD = {(e,i,t): LpVariable(f"ESD_{e}_{i}_{t}", lowBound=0) for e in E_TYPES for i in I for t in T}

    n_PS = {t: LpVariable(f"n_trailers_PS_{t}", lowBound=0, cat="Integer") for t in T}
    n_SD = {t: LpVariable(f"n_trailers_SD_{t}", lowBound=0, cat="Integer") for t in T}

    # Fresh energy costs each call (allow overrides and avoid stale module-level values)
    try:
        from config import CONFIG as _CFG_FRESH
    except Exception:
        _CFG_FRESH = _CFG
    EC_WIND = energy_cost_wind if energy_cost_wind is not None else _CFG_FRESH.get("ENERGY_COST_WIND_EUR_PER_GWH", ENERGY_COST_WIND_EUR_PER_GWH)
    EC_SOLAR = energy_cost_solar if energy_cost_solar is not None else _CFG_FRESH.get("ENERGY_COST_SOLAR_EUR_PER_GWH", ENERGY_COST_SOLAR_EUR_PER_GWH)

    # --- Objective ---
    K = 1000  # kEUR→EUR

    capex_term = (
        lpSum(K * capex_prod_kEUR[l] * z_prod[i, l]  for i in I for l in L) +
        lpSum(K * capex_store_kEUR[m] * z_store[i, m] for i in I for m in Mtypes)
    )
    transport_term = lpSum(c_trans * DIST[i, j] * (X[i, j, t] + Y[i, j, t]) for (i, j) in ARCS for t in T)
    elec_transport_term = (
        lpSum(ENERGY_GRID_COST_EUR_PER_GWHKM * DIST[i, j] * Eflow[e, i, j, t]
              for e in E_TYPES for (i, j) in ARCS for t in T)
        if USE_EGRID else 0
    )
    # Price electricity by source e using ESD[e,i,t] directly (no double-counting with GAMMA)
    energy_cost_map = {"wind": EC_WIND, "solar": EC_SOLAR}
    energy_term = lpSum(energy_cost_map[e] * ESD[e, i, t] for e in E_TYPES for i in I for t in T)
    opex_prod = lpSum(OPEX_PROD_EUR_PER_TON[l] * Pro[i, l, t] for i in I for l in L for t in T)
    # storage handling charged once per node, proportional to outflow
    min_store_opex = min(OPEX_STORE_EUR_PER_TON[m] for m in Mtypes) if Mtypes else 0.0
    opex_store = lpSum(min_store_opex * lpSum(Y[i, j, t] for (i2, j) in ARCS if i2 == i) for i in I for t in T)
    trailer_penalty = lpSum(TRAILER_COST_EUR * (n_PS[t] + n_SD[t]) for t in T)

    prob += capex_term + transport_term + elec_transport_term + energy_term + opex_prod + opex_store + trailer_penalty

    # --- Constraints ---
    for i in I:
        for t in T:
            prob += (lpSum(ESD[e, i, t] for e in E_TYPES)
                     == GAMMA_GWH_PER_TON * lpSum(Pro[i, l, t] for l in L)), f"ElecReq_{i}_{t}"

    if USE_EGRID:
        for e in E_TYPES:
            for i in I:
                for t in T:
                    avail_e = wind[i] if e == "wind" else solar[i]
                    prob += (ESD[e, i, t] <=
                             avail_e + lpSum(Eflow[e, k, i, t] for (k, i2) in ARCS if i2 == i)
                                      - lpSum(Eflow[e, i, j, t] for (i2, j) in ARCS if i2 == i)), f"ElecCover_{e}_{i}_{t}"
        for e in E_TYPES:
            for i in I:
                for t in T:
                    avail_e = wind[i] if e == "wind" else solar[i]
                    prob += lpSum(Eflow[e, i, j, t] for (i2, j) in ARCS if i2 == i) <= avail_e, f"ElecExportCap_{e}_{i}_{t}"
    else:
        for e in E_TYPES:
            for i in I:
                for t in T:
                    avail_e = wind[i] if e == "wind" else solar[i]
                    prob += ESD[e, i, t] <= avail_e, f"ElecLocalOnly_{e}_{i}_{t}"

    for i in I:
        for l in L:
            for t in T:
                prob += Pro[i, l, t] <= prod_cap_tpy[l] * z_prod[i, l], f"ProdCap_{i}_{l}_{t}"

    for i in I:
        for t in T:
            prob += lpSum(X[i, j, t] for (i2, j) in ARCS if i2 == i) == lpSum(Pro[i, l, t] for l in L), f"ProdFlow_{i}_{t}"

    for idx, t in enumerate(T):
        for i in I:
            inflow  = lpSum(X[k, i, t] for (k, j2) in ARCS if j2 == i)
            outflow = lpSum(Y[i, j, t] for (i2, j) in ARCS if i2 == i)
            inv_t   = lpSum(Inv[i, m, t] for m in Mtypes)
            prev = 0 if idx == 0 else lpSum(Inv[i, m, T[idx-1]] for m in Mtypes)
            prob += prev + inflow - outflow == inv_t, f"StorInvDyn_{i}_{t}"
            cap_i = lpSum(store_cap_tpy[m] * z_store[i, m] for m in Mtypes)
            prob += inv_t <= cap_i, f"StorInvCap_{i}_{t}"

    for (i, j) in ARCS:
        for t in T:
            cap_j = lpSum(store_cap_tpy[m] * z_store[j, m] for m in Mtypes)
            cap_i = lpSum(store_cap_tpy[m] * z_store[i, m] for m in Mtypes)
            prob += X[i, j, t] <= cap_j, f"X_open_{i}_{j}_{t}"
            prob += Y[i, j, t] <= cap_i, f"Y_open_{i}_{j}_{t}"

    for j in I:
        for t in T:
            prob += lpSum(Y[i, j, t] for (i, j2) in ARCS if j2 == j) + v[j, t] == b[j], f"Demand_{j}_{t}"
            prob += v[j, t] <= (1.0 - alpha_by_t[t]) * b[j], f"Penetration_{j}_{t}"

    for i in I:
        for t in T:
            prob += lpSum(Y[i, j, t] for (i2, j) in ARCS if i2 == i) <= lpSum(Inv[i, m, t] for m in Mtypes), f"StorShipCap_{i}_{t}"

    cap_per_trailer_year = TRAILER_PAYLOAD_TON * TRIPS_PER_TRAILER_PER_YEAR
    for t in T:
        prob += lpSum(X[i, j, t] for (i, j) in ARCS) <= n_PS[t] * cap_per_trailer_year, f"TrailerPSCap_{t}"
        prob += lpSum(Y[i, j, t] for (i, j) in ARCS) <= n_SD[t] * cap_per_trailer_year, f"TrailerSDCap_{t}"

    # --- Solve ---
    solver = PULP_CBC_CMD(msg=False)
    _solve_with_spinner(prob, solver, label="Solving MILP (CBC)...", show=True)

    # --- Report ---
    status = LpStatus[prob.status]
    obj = value(prob.objective)

    prod_sites = [(i, l) for (i, l) in z_prod  if value(z_prod[i, l])  > 0.5]
    stor_sites = [(i, m) for (i, m) in z_store if value(z_store[i, m]) > 0.5]

    print("\n=== Solve Status ===")
    print(status)
    print(f"Objective (Total Cost) = {obj:,.2f} EUR")
    print(f"Transport (H2): {c_trans:.2f} €/t·km | Grid (elec): {ENERGY_GRID_COST_EUR_PER_GWHKM:.2f} €/GWh·km")
    print(f"Energy cost: wind={EC_WIND:,.0f} €/GWh | solar={EC_SOLAR:,.0f} €/GWh")
    # Energy usage & cost breakdown (helps verify sensitivity impact)
    total_esd = sum(value(ESD[e, i, t]) for e in E_TYPES for i in I for t in T)
    total_esd_wind = sum(value(ESD['wind', i, t]) for i in I for t in T)
    total_esd_solar = sum(value(ESD['solar', i, t]) for i in I for t in T)
    est_energy_cost = EC_WIND * total_esd_wind + EC_SOLAR * total_esd_solar
    print(f"Energy used: {total_esd:,.3f} GWh  (wind {total_esd_wind:,.3f} | solar {total_esd_solar:,.3f})  → est. energy cost = {est_energy_cost:,.2f} EUR")

    print("\n=== Production & Storage Facilities Chosen (static across periods) ===")
    if not prod_sites: print("  Plants: None")
    else:
        for (i, l) in prod_sites:
            print(f"  - Plant {l} @ {i}: Cap = {prod_cap_tpy[l]:,} t/yr | Investment = {capex_prod_kEUR[l]*1000:,.0f} EUR")
    if not stor_sites: print("  Storage: None")
    else:
        for (i, m) in stor_sites:
            print(f"  - Tank {m} @ {i}: Stock cap = {store_cap_tpy[m]:,} t | Investment = {capex_store_kEUR[m]*1000:,.0f} EUR")

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
            tol = 1e-4
            is_met = (delivered + tol) >= target
            print(f"    - {j:17s}: demand={b[j]:>9,.1f}  delivered={delivered:>9,.1f}  unmet={unmet:>9,.1f}  target = {'met' if is_met else 'unmet'}")
        print("  Transport:")
        print(f"    P->S flow X = {total_X_t:,.1f} t/yr | trailers = {int(value(n_PS[t]))}")
        print(f"    S->D flow Y = {total_Y_t:,.1f} t/yr | trailers = {int(value(n_SD[t]))}")

    inv_by_loc_last = {i: sum(value(Inv[i, m, T[-1]]) for m in Mtypes) for i in I}

    # --- Timing ---
    end_time = time.time()
    runtime_sec = end_time - start_time
    runtime_min = int(runtime_sec // 60)
    runtime_rem_sec = runtime_sec % 60
    print(f"\n=== Runtime ===\nTotal runtime: {runtime_min} min {runtime_rem_sec:.2f} sec")

    return dict(
        status=status, objective=obj, prod_sites=prod_sites, stor_sites=stor_sites,
        total_X=total_X_all, total_Y=total_Y_all,
        trailers_PS={t: int(value(n_PS[t])) for t in T},
        trailers_SD={t: int(value(n_SD[t])) for t in T},
        inventory_last_period=inv_by_loc_last
    )

if __name__ == "__main__":
    build_and_solve()