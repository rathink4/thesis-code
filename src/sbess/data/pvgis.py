"""PVGIS hourly PV output — the 'second opinion' on solar yield.

Requests PV output for the same array (size, tilt, azimuth, losses) so it can be
compared directly with the pvlib model (scripts/validate_pv.py).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import requests


def raw_path(cfg: dict, year: int) -> Path:
    from sbess.config import project_path
    return project_path(cfg["data"]["raw_dir"]) / f"pvgis_{year}.json"


def download(cfg: dict, year: int, total_loss_pct: float, force: bool = False) -> Path:
    out = raw_path(cfg, year)
    if out.exists() and not force:
        print(f"  cached: {out.name}")
        return out
    pv, site, pg = cfg["pv"], cfg["site"], cfg["data"]["pvgis"]
    params = {
        "lat": site["latitude"],
        "lon": site["longitude"],
        "startyear": year,
        "endyear": year,
        "pvcalculation": 1,
        "peakpower": pv["capacity_kwp"],
        "loss": round(total_loss_pct, 2),
        "angle": pv["tilt_deg"],
        # PVGIS aspect: 0 = south, -90 = east, 90 = west. pvlib azimuth: 180 = south.
        "aspect": pv["azimuth_deg"] - 180.0,
        "raddatabase": pg["raddatabase"],
        "components": 1,
        "outputformat": "json",
    }
    print(f"  requesting PVGIS {year} ...")
    r = requests.get(pg["base_url"], params=params, timeout=180)
    if r.status_code != 200:
        raise RuntimeError(f"PVGIS error {r.status_code}: {r.text[:300]}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(r.text, encoding="utf-8")
    print(f"  saved: {out.name}")
    return out


def parse(path: Path, cfg: dict) -> pd.DataFrame:
    """Return hourly AC power in kW, local time. PVGIS timestamps are UTC (hh:10)."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    df = pd.DataFrame(payload["outputs"]["hourly"])
    df.index = pd.to_datetime(df["time"], format="%Y%m%d:%H%M", utc=True)
    df.index = df.index.floor("h").tz_convert(cfg["site"]["timezone"])
    out = pd.DataFrame({"pv_ac_kw": df["P"].astype(float) / 1000.0})
    return out
