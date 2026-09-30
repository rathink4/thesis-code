"""Open-Meteo archived weather forecasts (used from Week 4 by the forecasters).

Two sources, because they mean different things (see DECISIONS D-007):
  * historical_forecast: stitched from the first hours of each model run.
    Close to observations -> NOT a realistic day-ahead forecast. Available from 2021.
  * previous_runs (lead_days=1): the value that was forecast 24 h earlier.
    This IS a realistic day-ahead forecast with real errors. Available from late Jan 2024.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import requests


def raw_path(cfg: dict, year: int, kind: str) -> Path:
    from sbess.config import project_path
    return project_path(cfg["data"]["raw_dir"]) / f"open_meteo_{kind}_{year}.json"


def _request(url: str, params: dict) -> dict:
    r = requests.get(url, params=params, timeout=180)
    if r.status_code != 200:
        raise RuntimeError(f"Open-Meteo error {r.status_code}: {r.text[:300]}")
    return r.json()


def download(cfg: dict, year: int, kind: str = "previous_runs", force: bool = False) -> Path:
    if kind not in ("previous_runs", "historical_forecast"):
        raise ValueError("kind must be previous_runs or historical_forecast")
    out = raw_path(cfg, year, kind)
    if out.exists() and not force:
        print(f"  cached: {out.name}")
        return out
    om, site = cfg["data"]["open_meteo"], cfg["site"]
    variables = list(om["hourly_variables"])
    if kind == "previous_runs":
        variables = [f"{v}_previous_day{om['lead_days']}" for v in variables]
        url = om["previous_runs_url"]
    else:
        url = om["historical_forecast_url"]

    # request quarter by quarter to keep responses small; start one day early because the API
    # works in GMT and local midnight (UTC+4) is 20:00 GMT the day before
    chunks = []
    for i, quarter in enumerate(pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="QS")):
        q_start = quarter - pd.Timedelta(days=1) if i == 0 else quarter
        q_end = min(quarter + pd.offsets.QuarterEnd(0), pd.Timestamp(f"{year + 1}-01-01"))
        params = {
            "latitude": site["latitude"],
            "longitude": site["longitude"],
            "hourly": ",".join(variables),
            "start_date": q_start.strftime("%Y-%m-%d"),
            "end_date": q_end.strftime("%Y-%m-%d"),
            "timezone": "GMT",
        }
        print(f"  requesting Open-Meteo {kind} {params['start_date']} .. {params['end_date']}")
        chunks.append(_request(url, params))

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(chunks), encoding="utf-8")
    print(f"  saved: {out.name}")
    return out


RENAME = {
    "shortwave_radiation": "ghi",
    "direct_normal_irradiance": "dni",
    "diffuse_radiation": "dhi",
    "temperature_2m": "temp_air",
    "wind_speed_10m": "wind_speed",
    "relative_humidity_2m": "rh",
    "cloud_cover": "cloud_cover",
}
RADIATION = ("ghi", "dni", "dhi")


def parse(path: Path, cfg: dict, year: int) -> pd.DataFrame:
    """Hourly forecast in local time with the same column names as the NASA weather
    (ghi, dni, dhi, temp_air, wind_speed [m/s], rh) plus cloud_cover [%].

    Open-Meteo radiation is the mean over the hour BEFORE its timestamp, while this project
    stamps the START of each hour, so radiation moves by radiation_shift_h (-1 h). Checked:
    the shift moves the daily GHI centre onto solar noon (DECISIONS D-016)."""
    chunks = json.loads(Path(path).read_text(encoding="utf-8"))
    frames = []
    for c in chunks:
        df = pd.DataFrame(c["hourly"])
        df.index = pd.to_datetime(df.pop("time"), utc=True)
        units = {k.split("_previous_day")[0]: v for k, v in c.get("hourly_units", {}).items()}
        if units.get("wind_speed_10m") == "km/h":
            df[[k for k in df.columns if k.startswith("wind_speed_10m")]] /= 3.6
        frames.append(df)
    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated(keep="first")]
    df.columns = [RENAME.get(c.split("_previous_day")[0], c) for c in df.columns]
    shift = pd.Timedelta(hours=cfg["data"]["open_meteo"]["radiation_shift_h"])
    rad = df[list(RADIATION)].copy()
    rad.index = rad.index + shift
    df[list(RADIATION)] = rad.reindex(df.index)
    df.index = df.index.tz_convert(cfg["site"]["timezone"])
    return df.loc[f"{year}-01-01":f"{year}-12-31"]
