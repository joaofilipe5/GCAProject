
"""
GHSC sensitivity analysis (no model code changes)
=================================================
This script runs sensitivity studies for ghsc.py across three parameter groups:
1) Hydrogen transport cost (€/t·km): [0.35, 0.40, 0.45, 0.50]
2) Annual energy availability scaling for wind/solar: [-40%, -30%, -20%, -10%, -5%, 0%]
3) Annual demand scaling (b): [0%, +10%, +20%, +30%, +40%]

For each run, it collects:
- total objective (EUR)
- CAPEX (EUR)
- transport H2 total (EUR)
- energy grid transport total (EUR)

Outputs:
- CSV: ghsc_sensitivity/results.csv
- Individual PNG charts (one per panel, no subplots)
"""

from __future__ import annotations

import copy
import csv
from dataclasses import dataclass
from typing import Dict, Any, List

import importlib
import importlib.util
from pathlib import Path

@dataclass
class DataSnapshot:
    b: Dict[str, float]
    wind: Dict[str, float]
    solar: Dict[str, float]


def _import_module(name: str, path_hint: str) -> Any:
    try:
        return importlib.import_module(name)
    except Exception:
        spec = importlib.util.spec_from_file_location(name, path_hint)
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)  # type: ignore
        return mod


def snapshot_data(data_mod) -> DataSnapshot:
    return DataSnapshot(b=copy.deepcopy(data_mod.b),
                        wind=copy.deepcopy(data_mod.wind),
                        solar=copy.deepcopy(data_mod.solar))


def restore_data(data_mod, snap: DataSnapshot) -> None:
    data_mod.b.clear();     data_mod.b.update(copy.deepcopy(snap.b))
    data_mod.wind.clear();  data_mod.wind.update(copy.deepcopy(snap.wind))
    data_mod.solar.clear(); data_mod.solar.update(copy.deepcopy(snap.solar))


def scale_energy(data_mod, snap: DataSnapshot, pct: float) -> None:
    restore_data(data_mod, snap)
    f = 1.0 + pct
    for k in data_mod.wind:
        data_mod.wind[k] = snap.wind[k] * f
    for k in data_mod.solar:
        data_mod.solar[k] = snap.solar[k] * f


def scale_demand(data_mod, snap: DataSnapshot, pct: float) -> None:
    restore_data(data_mod, snap)
    f = 1.0 + pct
    for k in data_mod.b:
        data_mod.b[k] = snap.b[k] * f


def run_ghsc(alpha_by_t, c_trans=None, pmin=None, pmax=None):
    ghsc = _import_module("ghsc", "ghsc.py")
    res = ghsc.build_and_solve(alpha_by_t=alpha_by_t, c_trans=c_trans, pmin=pmin, pmax=pmax)
    if isinstance(res, dict):
        if res.get("status") != "Optimal":
            raise RuntimeError(f"Sensitivity scenario was not optimal: {res.get('status')}")
        return res
    return {"objective": getattr(res, "objective", None),
            "capex_eur": getattr(res, "capex_eur", None)}


def _get_cfg():
    cfg = _import_module("config", "config.py")
    return getattr(cfg, "CONFIG", {}), cfg


def _get_data():
    return _import_module("data", "data.py")


def _million(eur):
    return float(eur)/1e6 if eur is not None else float("nan")


def main(create_plots=True):
    out_dir = Path("ghsc_sensitivity")
    out_dir.mkdir(parents=True, exist_ok=True)

    CONFIG, _ = _get_cfg()
    data_mod = _get_data()
    snap = snapshot_data(data_mod)

    eprice = CONFIG.get("ELECTRICITY_PRICING", {}) or {}
    pmin_cfg = float(eprice.get("P_MIN_EUR_PER_GWH", 80.0))
    pmax_cfg = float(eprice.get("P_MAX_EUR_PER_GWH", 120.0))
    alpha_by_t = CONFIG.get("ALPHA_BY_T")

    rows: List[Dict[str, Any]] = []

    # 1) Transport cost sweep
    for c_trans in [0.35, 0.40, 0.45, 0.50]:
        restore_data(data_mod, snap)
        res = run_ghsc(alpha_by_t=alpha_by_t, c_trans=c_trans, pmin=pmin_cfg, pmax=pmax_cfg)
        rows.append({
            "block": "transport_cost",
            "x_label": f"{c_trans:.2f}",
            "x_value": c_trans,
            "objective_meur": _million(res.get("objective")),
            "capex_meur": _million(res.get("capex_eur")),
            "energy_grid_meur": _million(res.get("energy_grid_total") or sum(v["energy_grid"] for v in res.get("per_period_costs", {}).values())),
            "transport_h2_meur": _million(res.get("transport_h2_total") or sum(v["transport_h2"] for v in res.get("per_period_costs", {}).values())),
        })

    # 2) Energy availability sweep
    for pct in [-0.40, -0.30, -0.20, -0.10, -0.05, 0.0]:
        scale_energy(data_mod, snap, pct)
        res = run_ghsc(alpha_by_t=alpha_by_t, c_trans=CONFIG.get("TRANS_COST_EUR_PER_TKM", 0.4), pmin=pmin_cfg, pmax=pmax_cfg)
        rows.append({
            "block": "energy_availability",
            "x_label": f"{int(pct*100)}%",
            "x_value": pct,
            "objective_meur": _million(res.get("objective")),
            "capex_meur": _million(res.get("capex_eur")),
            "energy_grid_meur": _million(res.get("energy_grid_total") or sum(v["energy_grid"] for v in res.get("per_period_costs", {}).values())),
            "transport_h2_meur": _million(res.get("transport_h2_total") or sum(v["transport_h2"] for v in res.get("per_period_costs", {}).values())),
        })
    restore_data(data_mod, snap)

    # 3) Demand sweep
    for pct in [0.0, 0.10, 0.20, 0.30, 0.40]:
        scale_demand(data_mod, snap, pct)
        res = run_ghsc(alpha_by_t=alpha_by_t, c_trans=CONFIG.get("TRANS_COST_EUR_PER_TKM", 0.4), pmin=pmin_cfg, pmax=pmax_cfg)
        rows.append({
            "block": "demand",
            "x_label": f"{int(pct*100)}%",
            "x_value": pct,
            "objective_meur": _million(res.get("objective")),
            "capex_meur": _million(res.get("capex_eur")),
            "energy_grid_meur": _million(res.get("energy_grid_total") or sum(v["energy_grid"] for v in res.get("per_period_costs", {}).values())),
            "transport_h2_meur": _million(res.get("transport_h2_total") or sum(v["transport_h2"] for v in res.get("per_period_costs", {}).values())),
        })
    restore_data(data_mod, snap)

    # Save tabular results without requiring a plotting/dataframe import.
    csv_path = out_dir / "results.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    # Plots (no subplots)
    def plot_block(block: str, y_col: str, title: str, ylabel: str, outfile: str):
        if not create_plots:
            return
        sub = [row for row in rows if row["block"] == block]
        if not sub:
            return
        sub.sort(key=lambda row: row["x_value"])
        x = [row["x_label"] for row in sub]
        y = [row[y_col] for row in sub]
        import matplotlib.pyplot as plt
        plt.figure()
        plt.plot(x, y, marker="o")
        plt.title(title)
        plt.xlabel("")
        plt.ylabel(ylabel)
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(out_dir / outfile, dpi=150)
        plt.close()

    # Transport cost
    plot_block("transport_cost", "objective_meur",    "Custo total (M€) — Custo de transporte de H₂",        "M€", "transport_total.png")
    plot_block("transport_cost", "capex_meur",        "Custo de instalação (M€) — Custo de transporte de H₂","M€", "transport_capex.png")
    plot_block("transport_cost", "energy_grid_meur",  "Custo transporte energia elétrica (M€) — H₂",         "M€", "transport_egrid.png")
    plot_block("transport_cost", "transport_h2_meur", "Custo transporte de hidrogénio (M€) — H₂",            "M€", "transport_h2.png")

    # Energy availability
    plot_block("energy_availability", "objective_meur",    "Custo total (M€) — Disponibilidade energia",     "M€", "energy_total.png")
    plot_block("energy_availability", "capex_meur",        "Custo de instalação (M€) — Disponibilidade",     "M€", "energy_capex.png")
    plot_block("energy_availability", "energy_grid_meur",  "Custo transporte energia elétrica (M€) — Disp.", "M€", "energy_egrid.png")
    plot_block("energy_availability", "transport_h2_meur", "Custo transporte de hidrogénio (M€) — Disp.",    "M€", "energy_h2.png")

    # Demand
    plot_block("demand", "objective_meur",    "Custo total (M€) — Procura anual",        "M€", "demand_total.png")
    plot_block("demand", "capex_meur",        "Custo de instalação (M€) — Procura anual","M€", "demand_capex.png")
    plot_block("demand", "energy_grid_meur",  "Custo transporte energia elétrica (M€) — Procura","M€", "demand_egrid.png")
    plot_block("demand", "transport_h2_meur", "Custo transporte de hidrogénio (M€) — Procura", "M€", "demand_h2.png")

    print(f"Saved CSV to: {csv_path}")
    if create_plots:
        print(f"Saved charts to: {out_dir}")

if __name__ == "__main__":
    main()
