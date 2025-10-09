"""
GHSC Sensitivity Analysis Runner
--------------------------------
This script imports the base GHSC model (`ghsc.py`) and runs
a 15-scenario sensitivity analysis using parameters in `config.py`.

Scenarios:
1. Transport cost: 5 values between 0.35–0.50 €/t·km
2. Energy cost: ±25%, ±10%, 0% (same delta for both wind & solar)
3. Penetration: 5 aligned tuples across 2030/2040/2050

Produces three plots (one per parameter group) showing total cost (EUR).
"""

import argparse
from config import CONFIG as _CFG
from ghsc import build_and_solve, ENERGY_COST_WIND_EUR_PER_GWH, ENERGY_COST_SOLAR_EUR_PER_GWH

# ----------------------------
# Sensitivity Analysis Helpers
# ----------------------------

def _linspace(a, b, n):
    """Inclusive linspace with n points between a and b."""
    if n <= 1:
        return [float(a)]
    step = (b - a) / (n - 1)
    return [a + i * step for i in range(n)]


def _apply_energy_delta(base_wind, base_solar, delta):
    """Apply the same percentage delta to both wind and solar costs."""
    return base_wind * (1.0 + delta), base_solar * (1.0 + delta)


def run_sensitivity(show_plots=True):
    """
    Run 15 scenarios in 3 groups of 5 and plot total cost results.
    """

    # --- Baselines ---
    base_trans = _CFG["TRANS_COST_EUR_PER_TKM"]
    base_wind = _CFG["ENERGY_COST_WIND_EUR_PER_GWH"]
    base_solar = _CFG["ENERGY_COST_SOLAR_EUR_PER_GWH"]
    base_alpha = _CFG["ALPHA_BY_T"].copy()

    # --- Settings ---
    t_lo, t_hi = _CFG.get("SENS_TRANS_COST_RANGE", [0.35, 0.50])
    t_pts = int(_CFG.get("SENS_TRANS_POINTS", 5))
    energy_deltas = list(_CFG.get("SENS_ENERGY_PCT_DELTAS", [-0.25, -0.10, 0.0, 0.10, 0.25]))
    pen_ranges = _CFG.get("SENS_PENETRATION_RANGES", {
        "2030": [0.02, 0.05],
        "2040": [0.10, 0.15],
        "2050": [0.20, 0.25],
    })
    pen_pts = int(_CFG.get("SENS_PEN_POINTS", 5))

    results = {"transport": [], "energy": [], "penetration": []}

    print("\n=== Running Sensitivity Analysis ===")

    # --- (1) Transport cost ---
    print("\n→ Transport cost sensitivity...")
    for val in _linspace(float(t_lo), float(t_hi), t_pts):
        out = build_and_solve(alpha_by_t=base_alpha, c_trans=val)
        results["transport"].append((f"{val:.3f}", out["objective"]))

    # --- (2) Energy cost ---
    print("\n→ Energy cost sensitivity (wind + solar)...")
    global ENERGY_COST_WIND_EUR_PER_GWH, ENERGY_COST_SOLAR_EUR_PER_GWH
    for d in energy_deltas:
        w, s = _apply_energy_delta(base_wind, base_solar, d)
        old_w, old_s = ENERGY_COST_WIND_EUR_PER_GWH, ENERGY_COST_SOLAR_EUR_PER_GWH
        ENERGY_COST_WIND_EUR_PER_GWH, ENERGY_COST_SOLAR_EUR_PER_GWH = w, s
        try:
            out = build_and_solve(alpha_by_t=base_alpha)
            results["energy"].append((f"{int(d*100)}%", out["objective"]))
        finally:
            ENERGY_COST_WIND_EUR_PER_GWH, ENERGY_COST_SOLAR_EUR_PER_GWH = old_w, old_s

    # --- (3) Penetration ---
    print("\n→ Penetration sensitivity...")
    rng2030 = _linspace(*pen_ranges.get("2030", [0.02, 0.05]), pen_pts)
    rng2040 = _linspace(*pen_ranges.get("2040", [0.10, 0.15]), pen_pts)
    rng2050 = _linspace(*pen_ranges.get("2050", [0.20, 0.25]), pen_pts)
    for i in range(pen_pts):
        alpha = {"2030": float(rng2030[i]), "2040": float(rng2040[i]), "2050": float(rng2050[i])}
        out = build_and_solve(alpha_by_t=alpha)
        lbl = f"({alpha['2030']*100:.1f}%,{alpha['2040']*100:.1f}%,{alpha['2050']*100:.1f}%)"
        results["penetration"].append((lbl, out["objective"]))

    # Try to import matplotlib only if we need plots (avoids NumPy ABI issues)
    if show_plots:
        try:
            import matplotlib.pyplot as plt  # lazy import
        except Exception as e:
            print("\n[warn] Could not import matplotlib for plotting (", e, ") — continuing without plots.")
            show_plots = False

    # --- Plotting ---
    if show_plots:
        def _plot_group(ax, title, data, xlabel):
            labels = [k for k, _ in data]
            costs = [v for _, v in data]
            ax.plot(range(1, len(costs)+1), costs, marker='o')
            ax.set_title(title)
            ax.set_xlabel(xlabel)
            ax.set_ylabel("Total cost (EUR)")
            ax.set_xticks(range(1, len(labels)+1))
            ax.set_xticklabels(labels, rotation=0)

        fig1 = plt.figure()
        _plot_group(fig1.add_subplot(111), "Sensitivity: Transport cost (€/t·km)", results["transport"], "TRANS_COST_EUR_PER_TKM")

        fig2 = plt.figure()
        _plot_group(fig2.add_subplot(111), "Sensitivity: Energy costs (both wind & solar)", results["energy"], "% delta vs base")

        fig3 = plt.figure()
        _plot_group(fig3.add_subplot(111), "Sensitivity: Penetration (2030,2040,2050)", results["penetration"], "(%,%,%)")

        plt.show()

    print("\n=== Sensitivity Analysis Complete ===")
    for key, vals in results.items():
        print(f"\n{key.upper()} RESULTS:")
        for lbl, cost in vals:
            print(f"  {lbl:>10s}: {cost:,.0f} EUR")

    return results


# --- CLI Interface ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run GHSC sensitivity analysis", add_help=True)
    parser.add_argument("--no-plots", action="store_true", help="Run without showing plots")
    # In Jupyter/VSCode, extra args like --f=... get passed; ignore them safely
    args, _unknown = parser.parse_known_args()

    run_sensitivity(show_plots=not args.no_plots)