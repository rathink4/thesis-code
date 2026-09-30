"""Train the day-ahead forecasters, score them on the test year, and save forecasts for the brains.

    python scripts/train_forecasts.py
    python scripts/train_forecasts.py --scenario synthetic_test      # offline pipeline test
Needs the data from download_data.py and prepare_data.py for every forecast year.
Writes forecasts to data/processed/forecasts/ and scores + figures to results/<date-time>_forecast/.
"""
import argparse
from datetime import datetime

import _path  # noqa: F401
from sbess.config import load_config, project_path, save_snapshot
from sbess.forecast.pipeline import run_forecasting


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default=None)
    ap.add_argument("--set", dest="overrides", action="append", default=[])
    a = ap.parse_args()
    cfg = load_config(a.scenario, a.overrides)
    fc = cfg["forecast"]
    name = "_".join(x for x in (datetime.now().strftime("%Y%m%d-%H%M%S"), cfg["_meta"]["scenario"], "forecast") if x)
    out = project_path(cfg["run"]["results_dir"]) / name
    out.mkdir(parents=True, exist_ok=True)
    save_snapshot(cfg, out / "config_used.yaml")
    print(f"Results -> {out}")
    v = fc["validation"]
    val = f"every {v['every_nth_week']}th week" if v["method"] == "blocks" else f"from {v['from']}"
    print(f"Training years {fc['train_years']} (validation: {val}), "
          f"test year {cfg['simulation']['year']}, weather forecasts: {fc['nwp_source']}")

    scores, *_ = run_forecasting(cfg, out)

    test = scores[scores.split == "test"].set_index(["target", "model"])
    cols = ["mae_kw", "rmse_kw", "nmae_pct", "skill_vs_persistence_pct"] + \
        (["mae_daytime_kw"] if "mae_daytime_kw" in test else [])
    print("\nTest-year scores (skill = RMSE improvement over persistence):")
    print(test[cols].round(2).to_string())
    print(f"\nForecasts saved to {project_path(fc['forecast_dir'])}")
    print(f"Scores and figures saved to {out}")


if __name__ == "__main__":
    main()
