"""Download raw data into data/raw (skips files already downloaded; use --force to refresh).

    python scripts/download_data.py                 # everything
    python scripts/download_data.py --only nasa
Years: the forecaster training years + simulation.year (weather and forecasts), and
data.pvgis.validation_year (PVGIS + its weather, for the PV check).
"""
import argparse

import _path  # noqa: F401
from sbess.config import load_config
from sbess.data import nasa_power, open_meteo, pvgis
from sbess.data.weather import data_years
from sbess.pv_model import total_loss_pct


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["nasa", "pvgis", "forecast"], default=None)
    ap.add_argument("--scenario", default=None)
    ap.add_argument("--set", dest="overrides", action="append", default=[])
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    cfg = load_config(a.scenario, a.overrides)
    years = data_years(cfg)

    if a.only in (None, "nasa"):
        print(f"NASA POWER (weather) {years}")
        for year in years:
            nasa_power.download(cfg, year, a.force)
    if a.only in (None, "pvgis"):
        vyear = cfg["data"]["pvgis"]["validation_year"]
        print(f"PVGIS (PV cross-check, year {vyear})")
        pvgis.download(cfg, vyear, total_loss_pct(cfg), a.force)
        if vyear not in years:
            print(f"NASA POWER for the PVGIS validation year {vyear}")
            nasa_power.download(cfg, vyear, a.force)
    if a.only in (None, "forecast"):
        print(f"Open-Meteo archived weather forecasts {years}")
        for year in years:
            for kind in ("previous_runs", "historical_forecast"):
                try:
                    open_meteo.download(cfg, year, kind, a.force)
                except Exception as exc:          # previous_runs has no data before 2024
                    print(f"  could not download {kind} for {year}: {exc}")


if __name__ == "__main__":
    main()
