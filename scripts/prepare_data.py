"""Turn raw downloads into clean hourly files in data/processed and run sanity checks.

    python scripts/prepare_data.py
"""
import argparse

import pandas as pd

import _path  # noqa: F401
from sbess.config import load_config, project_path
from sbess.data import nasa_power, open_meteo
from sbess.data.weather import check_solar_noon, data_years, nwp_path, processed_path, year_index


def prepare_weather(cfg, year):
    df = nasa_power.parse(nasa_power.raw_path(cfg, year), cfg, year)
    if cfg["data"]["nasa_power"]["timestamp_convention"] == "end":
        df.index = df.index - pd.Timedelta(hours=1)       # make stamps mark the start of each hour
    df = df.reindex(year_index(cfg, year)).interpolate(limit_direction="both")
    offset = check_solar_noon(df, cfg)
    status = "OK" if abs(offset) <= 0.75 else "CHECK timestamp_convention in config!"
    print(f"  {year}: solar-noon check: GHI centre is {offset:+.2f} h from solar noon -> {status}")
    print(f"  {year}: GHI {df['ghi'].sum()/1000:.0f} kWh/m2/yr, mean T {df['temp_air'].mean():.1f} C, "
          f"max T {df['temp_air'].max():.1f} C")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default=None)
    ap.add_argument("--set", dest="overrides", action="append", default=[])
    a = ap.parse_args()
    cfg = load_config(a.scenario, a.overrides)
    years = data_years(cfg)
    project_path(cfg["data"]["processed_dir"]).mkdir(parents=True, exist_ok=True)

    print("Weather (NASA POWER)")
    vyear = cfg["data"]["pvgis"]["validation_year"]
    for year in sorted({*years, vyear}):
        if not nasa_power.raw_path(cfg, year).exists():
            print(f"  (no NASA POWER file for {year})")
            continue
        prepare_weather(cfg, year).to_csv(processed_path(cfg, year))
        print(f"  saved {processed_path(cfg, year).name}")

    print("Weather forecasts (Open-Meteo)")
    for year in years:
        for kind in ("previous_runs", "historical_forecast"):
            p = open_meteo.raw_path(cfg, year, kind)
            if not p.exists():
                print(f"  (no {kind} file for {year})")
                continue
            f = open_meteo.parse(p, cfg, year)
            out = nwp_path(cfg, year, kind)
            f.to_csv(out)
            complete = f.notna().all(axis=1)
            first = complete.idxmax().strftime("%Y-%m-%d") if complete.any() else "-"
            print(f"  saved {out.name}: {int(complete.sum())} of {len(f)} hours complete (from {first}), "
                  f"solar-noon check {check_solar_noon(f, cfg):+.2f} h")


if __name__ == "__main__":
    main()
