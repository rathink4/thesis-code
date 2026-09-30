"""Battery temperature: a first-order thermal model (one lumped mass per unit).

    C_th * dT/dt = (T_amb - T) / R_th + Q_loss

T_amb is the air around the battery (set by battery.placement): lagged outdoor air for a
garage, or a fixed room temperature indoors. Q_loss is the battery's own conversion loss per
unit, which ends up as heat. The equation is solved exactly over each hour, so it is stable
for any time constant tau = R_th * C_th. Ageing uses the hour-average temperature.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def placement_ambient_c(weather: pd.DataFrame, cfg: dict) -> pd.Series:
    """Air temperature around the battery for the configured placement."""
    th = cfg["battery"]["thermal"]
    p = th["placements"][cfg["battery"]["placement"]]
    if p["ambient"] == "fixed":
        return pd.Series(float(p["temp_c"]), index=weather.index, name="batt_ambient_c")
    if p["ambient"] == "outdoor":
        t = weather["temp_air"]
        if p.get("lag_h", 0) > 0:
            alpha = 1.0 - np.exp(-cfg["simulation"]["timestep_h"] / p["lag_h"])
            t = t.ewm(alpha=alpha, adjust=False).mean()
        return (t + p.get("offset_c", 0.0)).rename("batt_ambient_c")
    raise ValueError(f"Unknown ambient type '{p['ambient']}'")


def battery_temperature_c(loss_kwh: pd.Series, ambient_c: pd.Series, cfg: dict) -> pd.Series:
    """Hour-average battery temperature (degC) from hourly losses of the whole battery."""
    th, b = cfg["battery"]["thermal"], cfg["battery"]
    dt = cfg["simulation"]["timestep_h"]
    c_th = b["spec"]["mass_kg"] * th["heat_capacity_kj_per_kg_k"] / 3600.0   # kWh/K per unit
    r_th = th["r_th_k_per_kw"]                                               # K/kW per unit
    tau = r_th * c_th                                                        # hours
    decay = np.exp(-dt / tau)
    avg_factor = tau / dt * (1.0 - decay)        # mean of the exponential over one step

    q_kw = loss_kwh.to_numpy() / dt / b["units"]  # heat per unit
    t_amb = ambient_c.to_numpy()
    t_ss = t_amb + r_th * q_kw                    # where the temperature is heading in each hour
    out = np.empty(len(t_ss))
    t = t_amb[0] if th["t_init_c"] is None else float(th["t_init_c"])
    for i in range(len(t_ss)):
        out[i] = t_ss[i] + (t - t_ss[i]) * avg_factor
        t = t_ss[i] + (t - t_ss[i]) * decay
    return pd.Series(out, index=loss_kwh.index, name="batt_temp_c")
