"""Solar PV model: weather -> AC power of the shared array (kW), using pvlib.

Chain: solar position (mid-hour) -> plane-of-array irradiance (Hay-Davies)
       -> cell temperature (Faiman) -> DC power (PVWatts) -> system losses
       -> inverter (PVWatts inverter model).
Timestamps mark the START of each hour, so the sun position is taken at hh:30.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pvlib


def total_loss_pct(cfg: dict) -> float:
    """Combined system losses (%), same formula PVWatts uses."""
    return float(pvlib.pvsystem.pvwatts_losses(**cfg["pv"]["losses_pct"]))


def pv_ac_kw(weather: pd.DataFrame, cfg: dict) -> pd.Series:
    pv, site = cfg["pv"], cfg["site"]
    loc = pvlib.location.Location(site["latitude"], site["longitude"], site["timezone"], site["altitude_m"])
    mid = weather.index + pd.Timedelta(minutes=30)
    solpos = loc.get_solarposition(mid)

    poa = pvlib.irradiance.get_total_irradiance(
        surface_tilt=pv["tilt_deg"],
        surface_azimuth=pv["azimuth_deg"],
        solar_zenith=solpos["apparent_zenith"].to_numpy(),
        solar_azimuth=solpos["azimuth"].to_numpy(),
        dni=weather["dni"].to_numpy(),
        ghi=weather["ghi"].to_numpy(),
        dhi=weather["dhi"].to_numpy(),
        dni_extra=pvlib.irradiance.get_extra_radiation(mid).to_numpy(),
        albedo=pv["albedo"],
        model=pv["transposition_model"],
    )
    poa_global = np.nan_to_num(np.asarray(poa["poa_global"], dtype=float)).clip(min=0)

    t_cell = pvlib.temperature.faiman(poa_global, weather["temp_air"].to_numpy(),
                                      weather["wind_speed"].to_numpy())
    pdc0_w = pv["capacity_kwp"] * 1000.0
    pdc = pvlib.pvsystem.pvwatts_dc(poa_global, t_cell, pdc0_w, pv["gamma_pdc_per_c"])
    pdc = np.asarray(pdc) * (1.0 - total_loss_pct(cfg) / 100.0)

    ac_rating_w = pdc0_w / pv["dc_ac_ratio"]
    inv_pdc0 = ac_rating_w / pv["inverter_eta_nom"]
    pac = pvlib.inverter.pvwatts(pdc, inv_pdc0, eta_inv_nom=pv["inverter_eta_nom"])
    pac = np.nan_to_num(np.asarray(pac, dtype=float)).clip(min=0.0, max=ac_rating_w)

    return pd.Series(pac / 1000.0, index=weather.index, name="pv_kw")
