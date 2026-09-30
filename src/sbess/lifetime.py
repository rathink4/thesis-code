"""Battery life: age the battery year by year until it reaches end of life (degradation.eol_soh).

lifetime_method (config degradation.lifetime_method):
    extrapolate : simulate year 1 once, then apply the same year of stress again and again.
                  Fast; ignores that an aged battery holds less energy and so cycles differently.
    multi_year  : re-simulate every year with the aged battery (usable capacity x SOH), looping
                  the same weather and load year. Slower, more rigorous.
In both cases the paper models' sqrt / power-law shape is kept by the virtual-x continuation,
so ageing slows down over the years (it is not simply year-1 loss x N).
"""
from __future__ import annotations

from typing import Callable

import pandas as pd

from sbess.degradation import AgeingState, age, make_ageing_model, soc_boundaries, year_stress
from sbess.thermal import battery_temperature_c


def battery_lifetime(simulate_year: Callable[[float], pd.DataFrame], ambient_c: pd.Series,
                     cfg: dict) -> tuple[dict, pd.DataFrame, pd.Series]:
    """simulate_year(soh) must return the simulator output for a battery with that SOH.

    Returns (summary numbers, one row per simulated year, year-1 battery temperature)."""
    d, b = cfg["degradation"], cfg["battery"]
    dt = cfg["simulation"]["timestep_h"]
    model = make_ageing_model(cfg)
    state, rows = AgeingState(), []
    ys = temp = temp_year1 = None
    years_to_eol = None

    for year in range(1, d["max_years"] + 1):
        if ys is None or d["lifetime_method"] == "multi_year":
            sim = simulate_year(state.soh)
            temp = battery_temperature_c(sim["loss_kwh"], ambient_c, cfg)
            ys = year_stress(model, soc_boundaries(sim, b["soc_init"]), temp.to_numpy(), dt)
            if temp_year1 is None:
                temp_year1 = temp
        soh_before = state.soh
        state = age(model, state, ys)
        rows.append({"year": year, "soh_start": soh_before, "soh_end": state.soh,
                     "calendar_loss_pct": 100 * state.cal_loss, "cycle_loss_pct": 100 * state.cyc_loss,
                     "fec": ys.fec, "batt_temp_mean_c": float(temp.mean()),
                     "batt_temp_max_c": float(temp.max())})
        if state.soh <= d["eol_soh"]:
            years_to_eol = year - 1 + (soh_before - d["eol_soh"]) / (soh_before - state.soh)
            break

    table = pd.DataFrame(rows)
    y1 = table.iloc[0]
    hot_limit = b["spec"]["recommended_temp_c"][1]
    summary = {
        "degradation_model": b["ageing"]["model"],
        "placement": b["placement"],
        "battery_temp_mean_c": round(float(temp_year1.mean()), 1),
        "battery_temp_max_c": round(float(temp_year1.max()), 1),
        "battery_hours_above_recommended": int((temp_year1 > hot_limit).sum()),
        "soh_after_year1": round(float(y1["soh_end"]), 4),
        "capacity_loss_year1_pct": round(100 * (1 - float(y1["soh_end"])), 2),
        "calendar_loss_year1_pct": round(float(y1["calendar_loss_pct"]), 2),
        "cycle_loss_year1_pct": round(float(y1["cycle_loss_pct"]), 2),
        "lifetime_method": d["lifetime_method"],
        "years_to_eol": round(years_to_eol, 1) if years_to_eol is not None else None,
        "eol_note": "" if years_to_eol is not None else f"SOH still above {d['eol_soh']} after {d['max_years']} years",
    }
    return summary, table, temp_year1
