"""Turn raw downloads into clean hourly files in data/processed and run sanity checks.

    uv run scripts/prepare_data.py
"""
import argparse

import pandas as pd

import _path  # noqa: F401
from sbess.config import load_config, project_path
from sbess.data import nasa_power, open_meteo
from sbess.data.weather import check_solar_noon, processed_path, year_index


def prepare_weather(cfg, year):
    df = nasa_power.parse(nasa_power.raw_path(cfg, year), cfg, year)
    if cfg["data"]["nasa_power"]["timestamp_convention"] == "end":
        df.index = df.index - pd.Timedelta(hours=1)       # make stamps mark the start of each hour
    expected = year_index({**cfg, "simulation": {**cfg["simulation"], "year": year}})
    df = df.reindex(expected).interpolate(limit_direction="both")
    offset = check_solar_noon(df, cfg)
    status = "OK" if abs(offset) <= 0.75 else "CHECK timestamp_convention in config!"
    print(f"  solar-noon check: GHI centre is {offset:+.2f} h from solar noon -> {status}")
    print(f"  {year}: GHI {df['ghi'].sum()/1000:.0f} kWh/m2/yr, mean T {df['temp_air'].mean():.1f} C, "
          f"max T {df['temp_air'].max():.1f} C")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default=None)
    ap.add_argument("--set", dest="overrides", action="append", default=[])
    a = ap.parse_args()
    cfg = load_config(a.scenario, a.overrides)
    year = cfg["simulation"]["year"]
    out = project_path(cfg["data"]["processed_dir"])
    out.mkdir(parents=True, exist_ok=True)

    print("Weather (NASA POWER)")
    w = prepare_weather(cfg, year)
    w.to_csv(processed_path(cfg))
    print(f"  saved {processed_path(cfg).name}")

    vyear = cfg["data"]["pvgis"]["validation_year"]
    if vyear != year and nasa_power.raw_path(cfg, vyear).exists():
        prepare_weather(cfg, vyear).to_csv(out / f"weather_{vyear}.csv")

    print("Forecasts (Open-Meteo)")
    for kind in ("previous_runs", "historical_forecast"):
        p = open_meteo.raw_path(cfg, year, kind)
        if p.exists():
            f = open_meteo.parse(p, cfg, year)
            f.to_csv(out / f"forecast_{kind}_{year}.csv")
            print(f"  saved forecast_{kind}_{year}.csv ({f.notna().all(axis=1).sum()} complete hours)")
        else:
            print(f"  (no {kind} file for {year})")


if __name__ == "__main__":
    main()
