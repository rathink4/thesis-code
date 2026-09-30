"""Yearly summary numbers for one simulated case."""
from __future__ import annotations

import pandas as pd


def summarise(sim: pd.DataFrame, bills: pd.DataFrame, cfg: dict, battery_capacity_kwh: float) -> dict:
    dt = cfg["simulation"]["timestep_h"]
    e = lambda col: float(sim[col].sum() * dt)                       # noqa: E731
    load, pv = e("load_kw"), e("pv_kw")
    imp, exp = e("grid_import_kw"), e("grid_export_kw")
    ch, dis = e("charge_kw"), e("discharge_kw")
    local_supply = load - imp                                         # served by PV or battery
    pv_used = pv - exp - ch                                           # PV consumed directly
    per_home = bills.groupby("home")["total_aed"].sum().round(2).to_dict()
    return {
        "annual_bill_total_aed": round(float(bills["total_aed"].sum()), 2),
        "annual_bill_per_home_aed": per_home,
        "load_kwh": round(load, 1),
        "pv_generation_kwh": round(pv, 1),
        "grid_import_kwh": round(imp, 1),
        "grid_export_kwh": round(exp, 1),
        "battery_charge_kwh": round(ch, 1),
        "battery_discharge_kwh": round(dis, 1),
        "battery_losses_kwh": round(float(sim["loss_kwh"].sum()), 1),
        "equivalent_full_cycles": round(dis / battery_capacity_kwh, 1) if battery_capacity_kwh else 0.0,
        "self_consumption_pct": round(100 * (pv - exp) / pv, 1) if pv else 0.0,
        "self_sufficiency_pct": round(100 * local_supply / load, 1) if load else 0.0,
        "pv_direct_use_kwh": round(pv_used, 1),
        "hours_battery_request_clipped": int(sim["clipped"].sum()),
        "max_abs_bus_residual_kwh": float(sim["bus_residual_kwh"].abs().max()),
        "max_abs_battery_residual_kwh": float(sim["batt_residual_kwh"].abs().max()),
    }
