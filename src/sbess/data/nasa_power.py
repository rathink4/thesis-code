"""NASA POWER hourly weather (the 'measured' weather for the simulation).

Fetches in UTC and converts to local time, so a local calendar year is complete.
Output columns: ghi, dni, dhi [W/m2], temp_air [degC], wind_speed [m/s], rh [%]
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests

RENAME = {
    "ALLSKY_SFC_SW_DWN": "ghi",
    "ALLSKY_SFC_SW_DNI": "dni",
    "ALLSKY_SFC_SW_DIFF": "dhi",
    "T2M": "temp_air",
    "WS10M": "wind_speed",
    "RH2M": "rh",
}
FILL_VALUE = -999.0


def raw_path(cfg: dict, year: int) -> Path:
    from sbess.config import project_path
    return project_path(cfg["data"]["raw_dir"]) / f"nasa_power_{year}.json"


def download(cfg: dict, year: int, force: bool = False) -> Path:
    out = raw_path(cfg, year)
    if out.exists() and not force:
        print(f"  cached: {out.name}")
        return out
    npcfg, site = cfg["data"]["nasa_power"], cfg["site"]
    params = {
        "parameters": ",".join(npcfg["parameters"]),
        "community": npcfg["community"],
        "latitude": site["latitude"],
        "longitude": site["longitude"],
        # one day either side so the local-time year is complete after the UTC shift
        "start": f"{year - 1}1231",
        "end": f"{year + 1}0101",
        "format": "JSON",
        "time-standard": "UTC",
    }
    print(f"  requesting NASA POWER {year} ...")
    r = requests.get(npcfg["base_url"], params=params, timeout=180)
    r.raise_for_status()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(r.text, encoding="utf-8")
    print(f"  saved: {out.name}")
    return out


def parse(path: Path, cfg: dict, year: int) -> pd.DataFrame:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    block = payload["properties"]["parameter"]
    df = pd.DataFrame(block)
    df.index = pd.to_datetime(df.index, format="%Y%m%d%H", utc=True)
    df = df.rename(columns=RENAME).replace(FILL_VALUE, np.nan).sort_index()

    tz = cfg["site"]["timezone"]
    df.index = df.index.tz_convert(tz)
    df = df.loc[f"{year}-01-01":f"{year}-12-31"]

    n_missing = int(df.isna().sum().sum())
    if n_missing:
        print(f"  WARNING: {n_missing} missing values filled by time interpolation")
        df = df.interpolate(method="time", limit_direction="both")
    for col in ("ghi", "dni", "dhi"):
        df[col] = df[col].clip(lower=0.0)
    return df[[c for c in RENAME.values() if c in df.columns]]
