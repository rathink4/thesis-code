"""Cross-check the pvlib model against PVGIS for the same array and year.

    uv run scripts/validate_pv.py
Prints monthly and annual yield from both; the annual difference should be within ~5-10 %.
"""
import argparse

import pandas as pd

import _path  # noqa: F401
from sbess.config import load_config, project_path
from sbess.data import pvgis
from sbess.pv_model import pv_ac_kw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", dest="overrides", action="append", default=[])
    a = ap.parse_args()
    cfg = load_config(None, a.overrides)
    vyear = cfg["data"]["pvgis"]["validation_year"]
    wpath = project_path(cfg["data"]["processed_dir"]) / f"weather_{vyear}.csv"
    w = pd.read_csv(wpath, index_col=0, parse_dates=True)
    w.index = pd.to_datetime(w.index, utc=True).tz_convert(cfg["site"]["timezone"])

    ours = pv_ac_kw(w, cfg).resample("MS").sum()
    ref = pvgis.parse(pvgis.raw_path(cfg, vyear), cfg)["pv_ac_kw"].loc[str(vyear)].resample("MS").sum()
    table = pd.DataFrame({"pvlib_kwh": ours.values, "pvgis_kwh": ref.values},
                         index=ours.index.strftime("%b"))
    table["diff_pct"] = 100 * (table.pvlib_kwh - table.pvgis_kwh) / table.pvgis_kwh
    print(table.round(1).to_string())
    a_ours, a_ref = table.pvlib_kwh.sum(), table.pvgis_kwh.sum()
    kwp = cfg["pv"]["capacity_kwp"]
    print(f"\nAnnual: pvlib {a_ours:,.0f} kWh ({a_ours/kwp:,.0f} kWh/kWp) | "
          f"PVGIS {a_ref:,.0f} kWh ({a_ref/kwp:,.0f} kWh/kWp) | diff {100*(a_ours-a_ref)/a_ref:+.1f} %")
    out = project_path("results") / f"pv_validation_{vyear}.csv"
    table.to_csv(out)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
