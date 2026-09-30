"""Synthetic hourly electricity demand for each home (kW).

Each home = base load (always on)
          + appliance load   (archetype hourly shape, weekday/weekend)
          + cooling load     (proportional to how far a thermally-lagged outdoor
                              temperature is above the balance temperature, times
                              the archetype's cooling-occupancy shape)
          x correlated random noise.
Appliance and cooling parts are scaled so that the annual total and the cooling
share match the values in config (homes.profiles). All shapes are [ASSUMPTION]s.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _lagged_temperature(temp: pd.Series, lag_h: float) -> np.ndarray:
    """First-order lag: the building 'feels' outdoor temperature with a delay."""
    if lag_h <= 0:
        return temp.to_numpy()
    alpha = 1.0 - np.exp(-1.0 / lag_h)
    return temp.ewm(alpha=alpha, adjust=False).mean().to_numpy()


def _ar1_noise(n: int, sigma: float, rho: float, rng: np.random.Generator) -> np.ndarray:
    e = rng.standard_normal(n) * sigma * np.sqrt(1 - rho ** 2)
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = rho * x[i - 1] + e[i]
    return np.exp(x - sigma ** 2 / 2)       # multiplicative, mean ~1


def build_loads(weather: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    hc = cfg["homes"]
    idx = weather.index
    hour = idx.hour.to_numpy()
    is_weekend = np.isin(idx.dayofweek.to_numpy(), hc["weekend_days"])
    t_lag = _lagged_temperature(weather["temp_air"], hc["thermal_lag_h"])
    degree = np.clip(t_lag - hc["balance_temp_c"], 0.0, None)
    # different noise every year, so a forecaster trained on one year cannot memorise the next
    rng = np.random.default_rng([cfg["project"]["seed"], int(idx[0].year)])
    hours_per_year = len(idx) * cfg["simulation"]["timestep_h"]

    loads = {}
    for home in hc["profiles"]:
        arch = hc["archetypes"][home["archetype"]]
        app_shape = np.where(is_weekend, np.asarray(arch["appliance_weekend"])[hour],
                             np.asarray(arch["appliance_weekday"])[hour])
        cool_shape = np.where(is_weekend, np.asarray(arch["cooling_weekend"])[hour],
                              np.asarray(arch["cooling_weekday"])[hour])
        cool_raw = degree * cool_shape

        e_total = float(home["annual_kwh"])
        e_base = home["base_kw"] * hours_per_year
        e_cool = home["cooling_share"] * e_total
        e_app = e_total - e_cool - e_base
        if e_app <= 0:
            raise ValueError(f"{home['name']}: base_kw x hours + cooling share exceed annual_kwh")

        app = app_shape * e_app / app_shape.sum()
        cool = cool_raw * e_cool / cool_raw.sum()
        noise = _ar1_noise(len(idx), hc["noise_sigma"], hc["noise_autocorr"], rng)
        kw = (home["base_kw"] + (app + cool) * noise)
        kw *= e_total / (kw.sum() * cfg["simulation"]["timestep_h"])   # exact annual total
        loads[home["name"]] = kw

    return pd.DataFrame(loads, index=idx)
