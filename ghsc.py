import time
import threading
from pulp import (
    LpProblem, LpMinimize, LpVariable, LpBinary, lpSum,
    PULP_CBC_CMD, LpStatus, value
)

"""
GHSC network model — static facility design + dynamic operations
----------------------------------------------------------------
This MILP chooses which production/storage facilities to open (static across T)
and optimizes period-by-period production, flows, inventory, energy use, and
trailers. Electricity is local (no grid flow); price is node-specific via
CONFIG["ELECTRICITY_PRICING"] (single price, range-linear).

Sets (from data.py):
- i,j ∈ I      nodes (districts)
- l ∈ L        plant types
- m ∈ Mtypes   storage types
- e ∈ {wind, solar}
- t ∈ T_PERIODS

Key features:
- Static design binaries: z_prod[i,l], z_store[i,m]   (NOT time-indexed)
- Dynamic ops: Pro, X, Y, Inv, v, ESD, n_PS, n_SD     (time-indexed)
- Objective: CAPEX + Transport + Energy (node-specific €/GWh) + OPEX(prod) + OPEX(storage) + Trailer penalties
- Energy: local availability only; dynamic €/GWh decreases with higher local availability if enabled.
"""

# ---- Data & configuration ----------------------------------------------------
from data import (
    I, b, wind, solar, DIST,
    L, capex_prod_kEUR, prod_cap_tpd,
    Mtypes, capex_store_kEUR, store_cap_tpd
)

E_TYPES = ["wind", "solar"]

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

# OPEX per tech/type
OPEX_PROD_EUR_PER_TON  = {l: _CFG["OPEX_PROD_EUR_PER_TON"].get(l, 0.0) for l in L}
OPEX_STORE_EUR_PER_TON = {m: _CFG["OPEX_STORE_EUR_PER_TON"].get(m, 0.0) for m in Mtypes}

# Derived annual capacities
prod_cap_tpy  = {l: prod_cap_tpd[l]  * DAYS_PER_YEAR for l in L}
store_cap_tpy = {m: store_cap_tpd[m] * DAYS_PER_YEAR for m in Mtypes}

# Shipping arcs (no self-loop)
ARCS = [(i, j) for i in I for j in I if i != j]


# ---- Optional: console spinner during CBC solve ------------------------------
def _spinner(stop_event, label="Solving MILP (CBC)..."):
    glyphs = "|/-\\"
    k = 0
    while not stop_event.is_set():
        try:
            print(f"\r{label} {glyphs[k % len(glyphs)]}", end="", flush=True)
        except Exception:
            pass
        time.sleep(0.1)
        k += 1
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


# ---- Model builder/solver ----------------------------------------------------
def build_and_solve(
    alpha_by_t=None,
    c_trans=TRANS_COST_EUR_PER_TKM,
    energy_cost_wind=None,  # interpreted as base electricity price if provided
    energy_cost_solar=None, # ignored (compat)
    dynamic_energy_pricing=True,
):
    start_time = time.time()
    prob = LpProblem("GHSC_Portugal_2050", LpMinimize)

    T = T_PERIODS
    if alpha_by_t is None:
        alpha_by_t = ALPHA_BY_T
    if not isinstance(alpha_by_t, dict):
        alpha_by_t = {t: float(alpha_by_t) for t in T}

    # --- Variables ------------------------------------------------------------
    # Static design
    z_prod  = {(i,l): LpVariable(f"z_prod_{i}_{l}", cat=LpBinary) for i in I for l in L}
    z_store = {(i,m): LpVariable(f"z_store_{i}_{m}", cat=LpBinary) for i in I for m in Mtypes}

    # Dynamic ops
    Pro = {(i,l,t): LpVariable(f"Pro_{i}_{l}_{t}", lowBound=0) for i in I for l in L for t in T}
    X   = {(i,j,t): LpVariable(f"X_{i}_{j}_{t}",   lowBound=0) for (i,j) in ARCS for t in T}
    Y   = {(i,j,t): LpVariable(f"Y_{i}_{j}_{t}",   lowBound=0) for (i,j) in ARCS for t in T}
    Inv = {(i,m,t): LpVariable(f"Inv_{i}_{m}_{t}", lowBound=0) for i in I for m in Mtypes for t in T}
    v   = {(j,t):   LpVariable(f"v_{j}_{t}",       lowBound=0) for j in I for t in T}
    ESD = {(e,i,t): LpVariable(f"ESD_{e}_{i}_{t}", lowBound=0) for e in E_TYPES for i in I for t in T}
    n_PS = {t: LpVariable(f"n_trailers_PS_{t}", lowBound=0, cat="Integer") for t in T}
    n_SD = {t: LpVariable(f"n_trailers_SD_{t}", lowBound=0, cat="Integer") for t in T}

    # Energy grid flows between districts (GWh). No self-loops (ARCS already excludes i==j)
    EGRID = {(e, i, j, t): LpVariable(f"xgrid_{e}_{i}_{j}_{t}", lowBound=0)
            for e in E_TYPES for (i, j) in ARCS for t in T}

    # Outbound handled by storage type m at node i in period t (Option A)
    OUT = {(i,m,t): LpVariable(f"out_{i}_{m}_{t}", lowBound=0) for i in I for m in Mtypes for t in T}

    # --- Energy price setup (single electricity price, node-specific) -------------
    # Fresh config read (in case caller modified CONFIG at runtime)
    try:
        from config import CONFIG as _CFG_FRESH
    except Exception:
        _CFG_FRESH = _CFG
    # --- Always-Dynamic Electricity Pricing (range-linear by local RES availability) ---

    # Read optional pricing config
    eprice_cfg = (_CFG_FRESH.get("ELECTRICITY_PRICING") or {}) if isinstance(_CFG_FRESH.get("ELECTRICITY_PRICING"), dict) else {}

    # Choose a neutral base price (NOT the wind price):
    # 1) try a generic base from config, 2) fall back to a plain numeric, 3) last-resort: old wind const
    BASE_EPRICE = (
        eprice_cfg.get("BASE_ELEC_PRICE_EUR_PER_GWH")
        or _CFG_FRESH.get("BASE_ELEC_PRICE_EUR_PER_GWH")
        or 100.0
    )

    # Price band; if not provided, default to ±20% around BASE_EPRICE
    pmin = eprice_cfg.get("P_MIN_EUR_PER_GWH", 0.8 * BASE_EPRICE)
    pmax = eprice_cfg.get("P_MAX_EUR_PER_GWH", 1.2 * BASE_EPRICE)
    pmin, pmax = min(pmin, pmax), max(pmin, pmax)

    # Normalize by local total RES availability (wind + solar), NOT by any wind price
    total_avail_by_i = {i: float(wind[i] + solar[i]) for i in I}
    max_total_avail = max(total_avail_by_i.values(), default=0.0)

    # Always dynamic: c_i = pmax - (pmax - pmin) * A_i, where A_i in [0,1]
    cost_elec_by_i = {}
    for i in I:
        A_i = (total_avail_by_i[i] / max_total_avail) if max_total_avail > 1e-12 else 0.0
        c_i = pmax - (pmax - pmin) * A_i
        # guard against numerical noise
        cost_elec_by_i[i] = min(max(c_i, pmin), pmax)

    # --- Objective ------------------------------------------------------------
    #   Z = CAPEX + Transport + Energy + OPEX(prod) + OPEX(store) + Trailer penalties
    K = 1000  # kEUR -> EUR

    capex_term = (
        lpSum(K * capex_prod_kEUR[l] * z_prod[i, l]  for i in I for l in L) +
        lpSum(K * capex_store_kEUR[m] * z_store[i, m] for i in I for m in Mtypes)
    )

    transport_term = lpSum(c_trans * DIST[i, j] * (X[i, j, t] + Y[i, j, t]) for (i, j) in ARCS for t in T)

    # price electricity with node-specific €/GWh (single electricity price)
    # price electricity with node-specific €/GWh (single electricity price) + grid transport cost
    energy_term = (
        lpSum(cost_elec_by_i[i] * (ESD['wind', i, t] + ESD['solar', i, t]) for i in I for t in T)
        + lpSum(ENERGY_GRID_COST_EUR_PER_GWHKM * DIST[i, j] * EGRID[e, i, j, t]
                for e in E_TYPES for (i, j) in ARCS for t in T)
    )
    opex_prod = lpSum(OPEX_PROD_EUR_PER_TON[l] * Pro[i, l, t] for i in I for l in L for t in T)

    # storage handling: type-specific cost per ton, charged on outbound handled by type m (Option A)
    opex_store = lpSum(OPEX_STORE_EUR_PER_TON[m] * OUT[i, m, t] for i in I for m in Mtypes for t in T)

    trailer_penalty = lpSum(TRAILER_COST_EUR * (n_PS[t] + n_SD[t]) for t in T)

    prob += capex_term + transport_term + energy_term + opex_prod + opex_store + trailer_penalty

    # --- Constraints ----------------------------------------------------------
    # Energy linked to production: sum_e ESD[e,i,t] = GAMMA * sum_l Pro[i,l,t]
    for i in I:
        for t in T:
            prob += (
                lpSum(ESD[e, i, t] for e in E_TYPES)
                == GAMMA_GWH_PER_TON * lpSum(Pro[i, l, t] for l in L)
            ), f"ElecReq_{i}_{t}"

    # Energy availability with grid imports/exports (guide 15.2–15.3)
    for e in E_TYPES:
        for i in I:
            for t in T:
                avail_e = wind[i] if e == "wind" else solar[i]
                imports = lpSum(EGRID[e, k, i, t] for (k, j2) in ARCS if j2 == i)
                exports = lpSum(EGRID[e, i, j, t] for (i2, j) in ARCS if i2 == i)
                # Node demand must be covered by local availability plus net imports
                prob += ESD[e, i, t] <= avail_e - exports + imports, f"GridCover_{e}_{i}_{t}"
                # Defensive cap: total exports cannot exceed local availability
                prob += exports <= avail_e, f"GridExportCap_{e}_{i}_{t}"

    # Production capacity enabling
    for i in I:
        for l in L:
            for t in T:
                prob += Pro[i, l, t] <= prod_cap_tpy[l] * z_prod[i, l], f"ProdCap_{i}_{l}_{t}"

    # Production outflow balance: all produced must go into X out of i
    for i in I:
        for t in T:
            prob += (
                lpSum(X[i, j, t] for (i2, j) in ARCS if i2 == i)
                == lpSum(Pro[i, l, t] for l in L)
            ), f"ProdFlow_{i}_{t}"

    # Inventory dynamics and capacity
    for idx, t in enumerate(T):
        for i in I:
            inflow  = lpSum(X[k, i, t] for (k, j2) in ARCS if j2 == i)
            outflow = lpSum(Y[i, j, t] for (i2, j) in ARCS if i2 == i)
            inv_t   = lpSum(Inv[i, m, t] for m in Mtypes)
            prev = 0 if idx == 0 else lpSum(Inv[i, m, T[idx-1]] for m in Mtypes)
            # carryover balance
            prob += prev + inflow - outflow == inv_t, f"StorInvDyn_{i}_{t}"
            # storage capacity
            cap_i = lpSum(store_cap_tpy[m] * z_store[i, m] for m in Mtypes)
            prob += inv_t <= cap_i, f"StorInvCap_{i}_{t}"

    # Outbound-by-type split and feasibility links (Option A)
    # Sum of per-type outbound equals total outbound from node i in period t
    for i in I:
        for t in T:
            prob += (
                lpSum(OUT[i, m, t] for m in Mtypes)
                == lpSum(Y[i, j, t] for (i2, j) in ARCS if i2 == i)
            ), f"OutSplit_{i}_{t}"

    # Per-type outbound cannot exceed available inventory of that type (and implicitly requires z_store via Inv cap)
    for i in I:
        for m in Mtypes:
            for t in T:
                prob += OUT[i, m, t] <= Inv[i, m, t], f"OutLeInv_{i}_{m}_{t}"

    # Arc enabling by open storage (architectural)
    for (i, j) in ARCS:
        for t in T:
            cap_j = lpSum(store_cap_tpy[m] * z_store[j, m] for m in Mtypes)
            cap_i = lpSum(store_cap_tpy[m] * z_store[i, m] for m in Mtypes)
            prob += X[i, j, t] <= cap_j, f"X_open_{i}_{j}_{t}"
            prob += Y[i, j, t] <= cap_i, f"Y_open_{i}_{j}_{t}"

    # Demand satisfaction and penetration
    for j in I:
        for t in T:
            prob += lpSum(Y[i, j, t] for (i, j2) in ARCS if j2 == j) + v[j, t] == b[j], f"Demand_{j}_{t}"
            prob += v[j, t] <= (1.0 - alpha_by_t[t]) * b[j], f"Penetration_{j}_{t}"

    # Outbound limited by stock
    for i in I:
        for t in T:
            prob += lpSum(Y[i, j, t] for (i2, j) in ARCS if i2 == i) <= lpSum(Inv[i, m, t] for m in Mtypes), f"StorShipCap_{i}_{t}"

    # Trailer capacity per year
    cap_per_trailer_year = TRAILER_PAYLOAD_TON * TRIPS_PER_TRAILER_PER_YEAR
    for t in T:
        prob += lpSum(X[i, j, t] for (i, j) in ARCS) <= n_PS[t] * cap_per_trailer_year, f"TrailerPSCap_{t}"
        prob += lpSum(Y[i, j, t] for (i, j) in ARCS) <= n_SD[t] * cap_per_trailer_year, f"TrailerSDCap_{t}"

    # --- Solve ----------------------------------------------------------------
    solver = PULP_CBC_CMD(msg=False)
    _solve_with_spinner(prob, solver, label="Solving MILP (CBC)...", show=True)

    # --- Report ---------------------------------------------------------------
    status = LpStatus[prob.status]
    obj = value(prob.objective)

    prod_sites = [(i, l) for (i, l) in z_prod  if value(z_prod[i, l])  > 0.5]
    stor_sites = [(i, m) for (i, m) in z_store if value(z_store[i, m]) > 0.5]

    print("\n=== Solve Status ===")
    print(status)
    print(f"Objective (Total Cost) = {obj:,.2f} EUR")
    print(f"Transport (H2): {c_trans:.2f} €/t·km")
    print(f"Electricity base: {EC_ELEC:,.0f} €/GWh (single price)")
    if dynamic_energy_pricing:
        min_i = min(cost_elec_by_i.values()) if cost_elec_by_i else 0.0
        max_i = max(cost_elec_by_i.values()) if cost_elec_by_i else 0.0
        print(f"Dynamic pricing active (range_linear_single) → electricity €/GWh range: {min_i:,.0f}–{max_i:,.0f}")

    # Energy usage & cost breakdown
    total_esd_wind  = sum(value(ESD['wind',  i, t]) for i in I for t in T)
    total_esd_solar = sum(value(ESD['solar', i, t]) for i in I for t in T)
    total_esd       = total_esd_wind + total_esd_solar

    # Use node-specific prices for the estimate (matches objective)
    est_energy_cost = sum(
        cost_elec_by_i[i] * sum(value(ESD['wind',  i, t]) + value(ESD['solar', i, t]) for t in T)
        for i in I
    )
    print(f"Energy used: {total_esd:,.3f} GWh  (wind {total_esd_wind:,.3f} | solar {total_esd_solar:,.3f})"
          f"  → est. energy cost = {est_energy_cost:,.2f} EUR")
    
    total_grid_flow = sum(value(EGRID[e, i, j, tt]) for e in E_TYPES for (i, j) in ARCS for tt in T)
    print(f"Grid electricity transferred: {total_grid_flow:,.3f} GWh (grid transport cost included above)")

    # Facilities
    print("\n=== Production & Storage Facilities Chosen (static across periods) ===")
    if prod_sites:
        print("Production sites (i, type, capacity t/yr):")
        for (i, l) in prod_sites:
            print(f"  - {i:15s} | {l:8s} | {prod_cap_tpy[l]:,.0f}")
    else:
        print("(no production sites opened)")
    if stor_sites:
        print("Storage sites (i, type, capacity t/yr):")
        for (i, m) in stor_sites:
            print(f"  - {i:15s} | {m:8s} | {store_cap_tpy[m]:,.0f}")
    else:
        print("(no storage sites opened)")

    # Per-period cost table (no CAPEX)
    print("\n=== Per-period cost breakdown (EUR) ===")
    capex_eur = (
        sum(1000 * capex_prod_kEUR[l]  * (1 if value(z_prod[i,l])  > 0.5 else 0) for i in I for l in L) +
        sum(1000 * capex_store_kEUR[m] * (1 if value(z_store[i,m]) > 0.5 else 0) for i in I for m in Mtypes)
    )
    print(f"CAPEX (static, reported once): {capex_eur:,.0f} EUR")

    header = f"{'Period':>8s} | {'Transport':>14s} | {'Energy':>14s} | {'OPEX_prod':>14s} | {'OPEX_store':>14s} | {'Total (no CAPEX)':>18s}"
    print(header)
    print("-" * len(header))
    per_period_costs = {}
    for t in T:
        transport_t = sum(c_trans * DIST[i, j] * (value(X[i, j, t]) + value(Y[i, j, t])) for (i, j) in ARCS)
        energy_t = sum(cost_elec_by_i[i] * (value(ESD['wind',  i, t]) + value(ESD['solar', i, t])) for i in I)
        opex_prod_t = sum(OPEX_PROD_EUR_PER_TON[l] * value(Pro[i, l, t]) for i in I for l in L)
        opex_store_t = sum(OPEX_STORE_EUR_PER_TON[m] * value(OUT[i, m, t]) for i in I for m in Mtypes)
        total_t = transport_t + energy_t + opex_prod_t + opex_store_t
        per_period_costs[t] = dict(transport=transport_t, energy=energy_t, opex_prod=opex_prod_t, opex_store=opex_store_t, total=total_t)
        print(f"{t:>8s} | {transport_t:14,.0f} | {energy_t:14,.0f} | {opex_prod_t:14,.0f} | {opex_store_t:14,.0f} | {total_t:18,.0f}")

    # Quick per-period ops snapshot
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
        print("  Transport:")
        print(f"    P->S flow X = {total_X_t:,.1f} t/yr | trailers = {int(value(n_PS[t]))}")
        print(f"    S->D flow Y = {total_Y_t:,.1f} t/yr | trailers = {int(value(n_SD[t]))}")

    inv_by_loc_last = {i: sum(value(Inv[i, m, T[-1]]) for m in Mtypes) for i in I}

    # --- Timing ---------------------------------------------------------------
    runtime_sec = time.time() - start_time
    runtime_min = int(runtime_sec // 60)
    runtime_rem_sec = runtime_sec % 60
    print(f"\n=== Runtime ===\nTotal runtime: {runtime_min} min {runtime_rem_sec:.2f} sec")

    # Return a structured result dict
    return dict(
        status=status, objective=obj, prod_sites=prod_sites, stor_sites=stor_sites,
        total_X=total_X_all, total_Y=total_Y_all,
        trailers_PS={t: int(value(n_PS[t])) for t in T},
        trailers_SD={t: int(value(n_SD[t])) for t in T},
        inventory_last_period=inv_by_loc_last,
        capex_eur=capex_eur,
        per_period_costs=per_period_costs,
        energy_cost_electricity_by_node=cost_elec_by_i,
    )


if __name__ == "__main__":
    build_and_solve()