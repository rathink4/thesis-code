"""Run the simulation for every case listed in config (run.cases).

Examples
    uv run run.py                                   # defaults
    uv run run.py --scenario pw3_lfp                # a scenario file
    uv run run.py --set battery.units=2 --set tariff.export_mode=no_credit
    uv run run.py --scenario synthetic_test         # offline pipeline test
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import pandas as pd  # noqa: E402

from sbess.battery import Battery  # noqa: E402
from sbess.billing import allocate, bill_all  # noqa: E402
from sbess.config import load_config, project_path, save_snapshot  # noqa: E402
from sbess.controllers import make_controller  # noqa: E402
from sbess.data.weather import load_weather  # noqa: E402
from sbess.load_model import build_loads  # noqa: E402
from sbess.metrics import summarise  # noqa: E402
from sbess.pv_model import pv_ac_kw  # noqa: E402
from sbess.simulate import simulate  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", default=None, help="name of a file in config/scenarios/ (without .yaml)")
    ap.add_argument("--set", dest="overrides", action="append", default=[], help="key.subkey=value")
    ap.add_argument("--tag", default="", help="optional label added to the results folder name")
    args = ap.parse_args(argv)

    cfg = load_config(args.scenario, args.overrides)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = "_".join(x for x in (stamp, cfg["_meta"]["scenario"], args.tag) if x)
    out_dir = project_path(cfg["run"]["results_dir"]) / name
    out_dir.mkdir(parents=True, exist_ok=True)
    save_snapshot(cfg, out_dir / "config_used.yaml")
    print(f"Results -> {out_dir}")

    print("[1/4] weather")
    weather = load_weather(cfg)
    print("[2/4] PV and home loads")
    pv = pv_ac_kw(weather, cfg)
    loads = build_loads(weather, cfg)
    loads.to_csv(out_dir / "home_loads_kw.csv")
    load_total = loads.sum(axis=1).rename("load_kw")

    print("[3/4] simulating cases")
    summary = {"scenario": cfg["_meta"]["scenario"], "overrides": cfg["_meta"]["overrides"], "cases": {}}
    zero_pv = pv * 0.0
    for case in cfg["run"]["cases"]:
        battery = Battery.from_config(cfg) if (case["battery"] and cfg["battery"]["enabled"]) else None
        controller = make_controller(case["controller"] if battery else "none", cfg)
        sim = simulate(load_total, pv if case["pv"] else zero_pv, battery, controller, cfg)
        imports, exports = allocate(sim, loads, cfg)
        bills = bill_all(imports, exports, cfg)
        cap = battery.capacity_kwh if battery else 0.0
        summary["cases"][case["name"]] = summarise(sim, bills, cfg, cap)
        sim.to_csv(out_dir / f"timeseries_{case['name']}.csv")
        bills.to_csv(out_dir / f"bills_{case['name']}.csv", index=False)
        print(f"   {case['name']:<12} bill {summary['cases'][case['name']]['annual_bill_total_aed']:>12,.0f} AED")

    print("[4/4] savings")
    cases = summary["cases"]
    if "grid_only" in cases:
        ref = cases["grid_only"]
        for c in cases.values():
            c["saving_vs_grid_only_aed"] = round(ref["annual_bill_total_aed"] - c["annual_bill_total_aed"], 2)
            c["saving_per_home_vs_grid_only_aed"] = {
                h: round(ref["annual_bill_per_home_aed"][h] - v, 2)
                for h, v in c["annual_bill_per_home_aed"].items()}
    if "pv_only" in cases:
        ref = cases["pv_only"]
        for c in cases.values():
            c["saving_vs_pv_only_aed"] = round(ref["annual_bill_total_aed"] - c["annual_bill_total_aed"], 2)

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    table = pd.DataFrame(cases).T[["annual_bill_total_aed", "grid_import_kwh", "grid_export_kwh",
                                   "self_sufficiency_pct", "equivalent_full_cycles"]
                                  + [k for k in ("saving_vs_grid_only_aed", "saving_vs_pv_only_aed")
                                     if k in next(iter(cases.values()))]]
    print(table.to_string())
    return out_dir, summary


if __name__ == "__main__":
    main()
