"""The forecasters' data: one continuous hourly table, and leak-free samples built from it.

Timing rule (DECISIONS D-017). A forecast is issued at the START of hour t, before hour t has
been measured, and covers hours t, t+1, ..., t+H-1 (lead 0 .. H-1). It may use only
    * measured load, PV and weather up to hour t-1,
    * the day-ahead weather forecast (NWP) for each target hour, issued about 24 h earlier,
    * the calendar.
The "same hour yesterday" value y[t+k-24] is always already measured because k <= 23,
which is why the horizon is capped at 24 h.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pvlib

from sbess.data.weather import load_nwp, load_weather
from sbess.load_model import build_loads
from sbess.pv_model import pv_ac_kw

NWP_COLS = ["ghi", "dni", "dhi", "temp_air", "wind_speed", "cloud_cover", "rh"]
HISTORY_H = 48            # rows needed before the first usable issue time (for the 48 h lag)


def hourly_table(cfg: dict, years: list[int]) -> pd.DataFrame:
    """Actual load and PV, measured weather, day-ahead weather forecast and calendar for
    consecutive years, as one hourly table."""
    frames = []
    for year in years:
        w = load_weather(cfg, year, quiet=True)
        nwp = load_nwp(cfg, year).reindex(w.index)
        f = pd.DataFrame(index=w.index)
        f["load"] = build_loads(w, cfg).sum(axis=1)
        f["pv"] = pv_ac_kw(w, cfg)
        f["obs_temp"], f["obs_ghi"] = w["temp_air"], w["ghi"]
        for c in NWP_COLS:
            f[f"nwp_{c}"] = nwp[c] if c in nwp else np.nan
        complete = nwp[["ghi", "dni", "dhi", "temp_air", "wind_speed"]].notna().all(axis=1)
        f["pv_nwp"] = np.nan                     # the pvlib model run on the weather forecast
        if complete.any():
            f.loc[complete, "pv_nwp"] = pv_ac_kw(nwp.loc[complete], cfg)
        frames.append(f)
    t = pd.concat(frames)
    step = pd.Timedelta(hours=cfg["simulation"]["timestep_h"])
    if not (t.index[1:] - t.index[:-1] == step).all():
        raise ValueError(f"Forecasting years {years} must be consecutive (the table needs a continuous time axis)")

    t["nwp_temp_6h"] = t["nwp_temp_air"].rolling(6, min_periods=1).mean()   # building thermal lag, forecast side
    t["obs_temp_24h"] = t["obs_temp"].rolling(24, min_periods=1).mean()     # recent measured heat
    site = cfg["site"]
    loc = pvlib.location.Location(site["latitude"], site["longitude"], site["timezone"], site["altitude_m"])
    zen = loc.get_solarposition(t.index + pd.Timedelta(minutes=30))["apparent_zenith"]
    t["clearsky_ghi"] = pvlib.clearsky.haurwitz(zen)["ghi"].fillna(0.0).to_numpy()
    hour, doy = t.index.hour.to_numpy(), t.index.dayofyear.to_numpy()
    t["hour_sin"], t["hour_cos"] = np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24)
    t["doy_sin"], t["doy_cos"] = np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)
    t["weekend"] = np.isin(t.index.dayofweek, cfg["homes"]["weekend_days"]).astype(float)
    return t


def issue_positions(table: pd.DataFrame, start, end) -> np.ndarray:
    """Row numbers of the issue times between start and end (inclusive) that have enough history."""
    idx = table.index

    def local(ts):
        ts = pd.Timestamp(ts)
        return ts if ts.tzinfo is not None else ts.tz_localize(idx.tz)
    sel = (idx >= local(start)) & (idx <= local(end))
    pos = np.flatnonzero(sel)
    return pos[pos >= HISTORY_H]


def target_matrix(table: pd.DataFrame, target: str, pos: np.ndarray, horizon: int) -> np.ndarray:
    """Actual values y[t+k] as an (n_issue, horizon) array; NaN beyond the end of the table."""
    y = table[target].to_numpy()
    j = pos[:, None] + np.arange(horizon)[None, :]
    out = np.full(j.shape, np.nan)
    ok = j < len(y)
    out[ok] = y[j[ok]]
    return out


# Target-hour features (known at issue time: forecast weather and calendar)
FUTURE_COLS = ["nwp_ghi", "nwp_dni", "nwp_dhi", "nwp_temp_air", "nwp_wind_speed", "nwp_cloud_cover",
               "nwp_rh", "nwp_temp_6h", "pv_nwp", "clearsky_ghi", "hour_sin", "hour_cos",
               "doy_sin", "doy_cos", "weekend"]


def tabular_features(table: pd.DataFrame, target: str, pos: np.ndarray, horizon: int) -> pd.DataFrame:
    """Long-format features: one row per (issue time, lead), lead-major order
    (all issue times for lead 0, then lead 1, ...). Used by XGBoost and persistence."""
    y = table[target].to_numpy()
    fut = table[FUTURE_COLS].to_numpy()
    n = len(table)
    last = y[pos - 1]                                      # latest measurement at issue time
    trend = y[pos - 1] - y[pos - 25]                       # vs the same hour yesterday
    obs_heat = table["obs_temp_24h"].to_numpy()[pos - 1]
    blocks = []
    for k in range(horizon):
        j = pos + k
        ok = j < n
        jj = np.where(ok, j, n - 1)
        block = pd.DataFrame(fut[jj], columns=FUTURE_COLS)
        block["lag24"], block["lag48"] = y[jj - 24], y[jj - 48]
        block["last"], block["last_trend"], block["obs_temp_24h"] = last, trend, obs_heat
        block["lead"] = float(k)
        block.loc[~ok, :] = np.nan
        blocks.append(block)
    return pd.concat(blocks, ignore_index=True)


PAST_COLS = ["obs_ghi", "obs_temp", "hour_sin", "hour_cos"]


def sequence_features(table: pd.DataFrame, target: str, pos: np.ndarray, horizon: int,
                      history: int) -> tuple[np.ndarray, np.ndarray]:
    """For the LSTM: past window (n, history, 1 + len(PAST_COLS)) of measured values up to
    hour t-1, and future (n, horizon, len(FUTURE_COLS) + 1) of forecast weather, calendar and
    the same-hour-yesterday value. NaN beyond the end of the table."""
    if pos.min() < history:
        raise ValueError("issue times need at least `history` hours before them")
    past_vals = np.column_stack([table[target].to_numpy(), table[PAST_COLS].to_numpy()])
    past = past_vals[pos[:, None] + np.arange(-history, 0)[None, :]]
    y = table[target].to_numpy()
    fut_vals = np.column_stack([table[FUTURE_COLS].to_numpy(), np.r_[np.full(24, np.nan), y[:-24]]])
    j = pos[:, None] + np.arange(horizon)[None, :]
    ok = j < len(table)
    future = np.full(j.shape + (fut_vals.shape[1],), np.nan)
    future[ok] = fut_vals[j[ok]]
    return past, future
