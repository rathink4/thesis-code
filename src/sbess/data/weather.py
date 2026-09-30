"""Weather access for the simulation and the forecasters.

load_weather() returns an hourly, local-time DataFrame with columns
    ghi, dni, dhi [W/m2], temp_air [degC], wind_speed [m/s]
from either the processed NASA POWER file or a synthetic generator ([TEST] only).
load_nwp() returns the day-ahead weather FORECAST for a year with the same columns
(plus cloud_cover, rh), from Open-Meteo or a synthetic generator ([TEST] only).
Both take an optional year; the default is simulation.year.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pvlib

from sbess.config import project_path

# [TEST] Approximate Dubai monthly mean air temperature, degC — only for synthetic weather
_DUBAI_MONTHLY_MEAN_T = [19.5, 20.5, 23.5, 27.5, 32.0, 34.0, 36.0, 36.0, 33.5, 30.0, 25.5, 21.5]


def data_years(cfg: dict) -> list[int]:
    """Every year of weather the project needs: forecaster training years + the simulation year."""
    return sorted({*cfg["forecast"]["train_years"], cfg["simulation"]["year"]})


def year_index(cfg: dict, year: int | None = None) -> pd.DatetimeIndex:
    year = year or cfg["simulation"]["year"]
    return pd.date_range(f"{year}-01-01 00:00", f"{year}-12-31 23:00", freq="h",
                         tz=cfg["site"]["timezone"])


def processed_path(cfg: dict, year: int | None = None):
    return project_path(cfg["data"]["processed_dir"]) / f"weather_{year or cfg['simulation']['year']}.csv"


def nwp_path(cfg: dict, year: int, kind: str | None = None):
    kind = kind or cfg["forecast"]["nwp_source"]
    return project_path(cfg["data"]["processed_dir"]) / f"forecast_{kind}_{year}.csv"


def _read_local_csv(path, cfg: dict) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True).tz_convert(cfg["site"]["timezone"])
    return df


def synthetic_weather(cfg: dict, year: int | None = None) -> pd.DataFrame:
    """[TEST] Plausible Dubai-like weather so the pipeline runs without internet.
    Clear-sky irradiance x random daily cloudiness; seasonal + daily temperature cycle."""
    year = year or cfg["simulation"]["year"]
    rng = np.random.default_rng([cfg["project"]["seed"], year])
    idx = year_index(cfg, year)
    site = cfg["site"]
    loc = pvlib.location.Location(site["latitude"], site["longitude"], site["timezone"], site["altitude_m"])
    mid = idx + pd.Timedelta(minutes=30)
    solpos = loc.get_solarposition(mid)
    cs = pvlib.clearsky.haurwitz(solpos["apparent_zenith"])

    n_days = len(idx) // 24 + 1
    daily_clear = np.clip(rng.beta(8, 1.5, n_days), 0.3, 1.0)       # mostly clear, some hazy days
    kt = np.repeat(daily_clear, 24)[: len(idx)] * np.clip(1 + 0.05 * rng.standard_normal(len(idx)), 0.8, 1.1)
    ghi = (cs["ghi"].to_numpy() * kt).clip(min=0)
    dec = pvlib.irradiance.erbs(ghi, solpos["zenith"].to_numpy(), idx.dayofyear.to_numpy())

    doy = idx.dayofyear.to_numpy()
    month_mid_doy = np.array([15, 46, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349])
    t_season = np.interp(doy, np.r_[month_mid_doy - 365, month_mid_doy, month_mid_doy + 365],
                         np.tile(_DUBAI_MONTHLY_MEAN_T, 3))
    hour = idx.hour.to_numpy()
    t_daily = 4.5 * np.cos(2 * np.pi * (hour - 15) / 24)
    noise = np.zeros(len(idx))
    for i in range(1, len(idx)):
        noise[i] = 0.9 * noise[i - 1] + 0.4 * rng.standard_normal()

    return pd.DataFrame({
        "ghi": ghi,
        "dni": np.nan_to_num(dec["dni"]).clip(min=0),
        "dhi": np.nan_to_num(dec["dhi"]).clip(min=0),
        "temp_air": t_season + t_daily + noise,
        "wind_speed": np.clip(3.5 + rng.standard_normal(len(idx)), 0.2, None),
    }, index=idx)


def load_weather(cfg: dict, year: int | None = None, quiet: bool = False) -> pd.DataFrame:
    source = cfg["simulation"]["weather_source"]
    if source == "synthetic":
        if not quiet:
            print("  NOTE: using SYNTHETIC weather — pipeline test only, not thesis results")
        return synthetic_weather(cfg, year)
    if source == "nasa_power":
        path = processed_path(cfg, year)
        if not path.exists():
            raise FileNotFoundError(
                f"{path} not found. Run: python scripts/download_data.py then "
                f"python scripts/prepare_data.py  (or use --scenario synthetic_test)")
        return _read_local_csv(path, cfg)
    raise ValueError(f"Unknown simulation.weather_source '{source}'")


def synthetic_nwp(cfg: dict, year: int | None = None) -> pd.DataFrame:
    """[TEST] A 'forecast' made by adding day-to-day errors to the synthetic weather."""
    year = year or cfg["simulation"]["year"]
    w = synthetic_weather(cfg, year)
    rng = np.random.default_rng([cfg["project"]["seed"], year, 1])
    n_days = len(w) // 24 + 1
    cloud_err = np.repeat(np.clip(1 + 0.15 * rng.standard_normal(n_days), 0.5, 1.3), 24)[: len(w)]
    out = w.copy()
    for col in ("ghi", "dni", "dhi"):
        out[col] = (w[col] * cloud_err).clip(lower=0)
    out["temp_air"] = w["temp_air"] + np.repeat(1.2 * rng.standard_normal(n_days), 24)[: len(w)]
    out["cloud_cover"] = np.clip(100 * (1.2 - cloud_err), 0, 100)
    out["rh"] = 50.0
    return out


def load_nwp(cfg: dict, year: int | None = None) -> pd.DataFrame:
    """Day-ahead weather forecast for one year (NaN where the archive has no data)."""
    year = year or cfg["simulation"]["year"]
    kind = cfg["forecast"]["nwp_source"]
    if kind == "synthetic":
        return synthetic_nwp(cfg, year)
    path = nwp_path(cfg, year, kind)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run: python scripts/download_data.py then "
                                f"python scripts/prepare_data.py")
    return _read_local_csv(path, cfg).reindex(year_index(cfg, year))


def check_solar_noon(weather: pd.DataFrame, cfg: dict) -> float:
    """Timestamp sanity check: hour of mean-peak GHI vs solar noon.
    Returns the offset in hours (should be within about +/-0.75 h)."""
    site = cfg["site"]
    loc = pvlib.location.Location(site["latitude"], site["longitude"], site["timezone"])
    profile = weather["ghi"].groupby(weather.index.hour).mean()
    # centroid of the daily GHI profile (+0.5 because each value covers hour h..h+1)
    peak_hour = float((profile * (profile.index + 0.5)).sum() / profile.sum())
    transit = loc.get_sun_rise_set_transit(weather.index[::24][:365:30], method="spa")["transit"]
    noon = float(np.mean([t.hour + t.minute / 60 for t in transit]))
    return peak_hour - noon
