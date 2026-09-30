"""Train, evaluate and save the day-ahead forecasters.

Split by date, never at random (DECISIONS D-018):
    validation : whole calendar weeks of the training years (every Nth week, so all seasons are
                 represented), or with method "tail" the end of the training years. Used only to
                 decide when to stop training (early stopping).
    train      : the other issue times of the training years; issue times whose 24 h horizon
                 would reach into a validation week are dropped, so no target is shared
    test       : every hour of simulation.year. These forecasts are saved for the brains.
Training and validation use only issue times whose 24 target hours all have a weather forecast.

Saved forecast files (data/processed/forecasts/<nwp_source>/<target>_<model>_<year>.csv):
    one row per issue time (every hour of the year), columns h0..h23 = forecast for
    issue time + 0 h .. + 23 h, in kW. NaN where the target hour is past the end of the year.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from sbess.config import project_path
from sbess.data.weather import data_years
from sbess.forecast.data import FUTURE_COLS, hourly_table, issue_positions, target_matrix
from sbess.forecast.models import make_forecaster


# ------------------------------------------------------------------ splits
def split_positions(cfg: dict, table: pd.DataFrame) -> dict[str, np.ndarray]:
    fc, year = cfg["forecast"], cfg["simulation"]["year"]
    horizon, v = fc["horizon_h"], fc["validation"]
    if horizon > 24:
        raise ValueError("forecast.horizon_h must be <= 24 (the same-hour-yesterday input must already be measured)")
    if year in fc["train_years"]:
        raise ValueError("simulation.year must not be a training year: its forecasts must be out-of-sample")
    tz, step = table.index.tz, pd.Timedelta(hours=1)
    train_end = pd.Timestamp(f"{max(fc['train_years'])}-12-31 23:00", tz=tz)
    in_train_years = np.isin(table.index.year, fc["train_years"])
    if v["method"] == "blocks":
        week = table.index.isocalendar().week.to_numpy()
        val_hour = in_train_years & (week % v["every_nth_week"] == 0)
    elif v["method"] == "tail":
        val_hour = in_train_years & (table.index >= pd.Timestamp(v["from"], tz=tz))
    else:
        raise ValueError("forecast.validation.method must be blocks | tail")
    # every issue time in the training years whose whole horizon stays inside them ...
    candidates = issue_positions(table, f"{min(fc['train_years'])}-01-01", train_end - (horizon - 1) * step)
    j = candidates[:, None] + np.arange(horizon)[None, :]
    # ... goes to validation if its whole horizon is validation hours, to training if none of it is
    # (issue times straddling the boundary are dropped, so no target is shared between the two)
    val = candidates[val_hour[j].all(axis=1)]
    train = candidates[~val_hour[j].any(axis=1)]
    test = issue_positions(table, f"{year}-01-01", f"{year}-12-31 23:00")
    return {"train": complete_positions(table, train, horizon),
            "validation": complete_positions(table, val, horizon),
            "test": test}


def complete_positions(table: pd.DataFrame, pos: np.ndarray, horizon: int) -> np.ndarray:
    """Keep issue times whose whole horizon lies in the table and has weather forecasts."""
    ok_hour = table[FUTURE_COLS].notna().all(axis=1).to_numpy()
    j = pos[:, None] + np.arange(horizon)[None, :]
    inside = (j < len(table)).all(axis=1)
    keep = inside.copy()
    keep[inside] = ok_hour[j[inside]].all(axis=1)
    return pos[keep]


# ------------------------------------------------------------------ post-processing and scores
def postprocess(pred: np.ndarray, table: pd.DataFrame, target: str, pos: np.ndarray, cfg: dict) -> np.ndarray:
    """Physical limits: no negative values; PV zero at night and at most the inverter rating.
    NaN where the target hour is beyond the end of the table."""
    horizon = pred.shape[1]
    j = pos[:, None] + np.arange(horizon)[None, :]
    inside = j < len(table)
    jj = np.where(inside, j, len(table) - 1)
    out = np.clip(pred, 0.0, None)
    if target == "pv":
        ac_max = cfg["pv"]["capacity_kwp"] / cfg["pv"]["dc_ac_ratio"]
        out = np.minimum(out, ac_max)
        out[table["clearsky_ghi"].to_numpy()[jj] <= 0] = 0.0
    out[~inside] = np.nan
    return out


def scores(pred: np.ndarray, actual: np.ndarray, daytime: np.ndarray | None = None) -> dict:
    err = pred - actual
    ok = ~np.isnan(err)
    out = {"mae_kw": float(np.abs(err[ok]).mean()), "rmse_kw": float(np.sqrt((err[ok] ** 2).mean())),
           "nmae_pct": float(100 * np.abs(err[ok]).mean() / np.abs(actual[ok]).mean())}
    if daytime is not None:
        d = ok & daytime
        out["mae_daytime_kw"] = float(np.abs(err[d]).mean())
    return out


# ------------------------------------------------------------------ saving / loading for the brains
def forecast_path(cfg: dict, target: str, model: str, year: int | None = None) -> Path:
    """One folder per weather-forecast source, so [TEST] forecasts never mix with real ones."""
    year = year or cfg["simulation"]["year"]
    return project_path(cfg["forecast"]["forecast_dir"]) / cfg["forecast"]["nwp_source"] / f"{target}_{model}_{year}.csv"


def save_forecast(cfg: dict, target: str, model: str, index: pd.DatetimeIndex, pred: np.ndarray) -> Path:
    path = forecast_path(cfg, target, model)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(pred, index=index, columns=[f"h{k}" for k in range(pred.shape[1])]).to_csv(path)
    return path


def load_forecast(cfg: dict, target: str, model: str, year: int | None = None) -> pd.DataFrame:
    """Forecast matrix for the brains: row = issue time, column hK = forecast for issue time + K h."""
    path = forecast_path(cfg, target, model, year)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run: python scripts/train_forecasts.py")
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True).tz_convert(cfg["site"]["timezone"])
    return df


# ------------------------------------------------------------------ main entry
def run_forecasting(cfg: dict, out_dir: Path | None = None, save: bool = True, verbose: bool = True):
    """Train every model for every target, score on validation and test, save test-year forecasts.
    Returns (scores table, error-by-lead table, test predictions {(target, model): array}, table, splits)."""
    log = print if verbose else (lambda *a, **k: None)
    fc = cfg["forecast"]
    horizon = fc["horizon_h"]
    table = hourly_table(cfg, data_years(cfg))
    splits = split_positions(cfg, table)
    idx = table.index
    for name, pos in splits.items():
        log(f"  {name:<10} {len(pos):>5} issue times  {idx[pos[0]]:%Y-%m-%d} .. {idx[pos[-1]]:%Y-%m-%d}")

    rows, by_lead, preds = [], [], {}
    for target in fc["targets"]:
        actual = {s: target_matrix(table, target, splits[s], horizon) for s in ("validation", "test")}
        j_test = np.minimum(splits["test"][:, None] + np.arange(horizon)[None, :], len(table) - 1)
        daytime = table["clearsky_ghi"].to_numpy()[j_test] > 0 if target == "pv" else None
        for name in fc["models"]:
            model = make_forecaster(name, cfg).fit(table, target, splits["train"], splits["validation"])
            for split in ("validation", "test"):
                pred = postprocess(model.predict(table, target, splits[split]), table, target, splits[split], cfg)
                s = scores(pred, actual[split], daytime if split == "test" else None)
                rows.append({"target": target, "model": name, "split": split, **s, **model.info})
                if split == "test":
                    preds[(target, name)] = pred
                    err = np.abs(pred - actual["test"])
                    by_lead.append(pd.DataFrame({"target": target, "model": name, "lead_h": np.arange(horizon),
                                                 "mae_kw": np.nanmean(err, axis=0)}))
                    if save:
                        save_forecast(cfg, target, name, idx[splits["test"]], pred)
            log(f"  {target:<5} {name:<12} test MAE {rows[-1]['mae_kw']:.2f} kW  RMSE {rows[-1]['rmse_kw']:.2f} kW"
                + (f"  ({', '.join(f'{k} {v}' for k, v in model.info.items())})" if model.info else ""))

    table_scores = pd.DataFrame(rows)
    ref = table_scores[table_scores.model == "persistence"].set_index(["target", "split"])["rmse_kw"]
    table_scores["skill_vs_persistence_pct"] = [
        100 * (1 - r.rmse_kw / ref.get((r.target, r.split), np.nan)) for r in table_scores.itertuples()]
    lead_table = pd.concat(by_lead, ignore_index=True)
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        table_scores.to_csv(out_dir / "forecast_scores.csv", index=False)
        lead_table.to_csv(out_dir / "forecast_error_by_lead.csv", index=False)
        plot_results(cfg, table, splits["test"], preds, lead_table, out_dir)
    return table_scores, lead_table, preds, table, splits


def plot_results(cfg, table, test_pos, preds, lead_table, out_dir: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    targets = cfg["forecast"]["targets"]
    fig, ax = plt.subplots(1, len(targets), figsize=(5.5 * len(targets), 4), constrained_layout=True)
    for a, target in zip(np.atleast_1d(ax), targets):
        for name, g in lead_table[lead_table.target == target].groupby("model", sort=False):
            a.plot(g.lead_h, g.mae_kw, marker="o", ms=3, label=name)
        a.set(title=f"{target}: error by forecast lead (test year)", xlabel="hours ahead", ylabel="MAE (kW)")
        a.grid(alpha=0.3)
        a.legend()
    fig.savefig(out_dir / "forecast_error_by_lead.png", dpi=150)
    plt.close(fig)

    # one week of day-ahead forecasts issued at midnight, around the day persistence got worst for PV
    idx = table.index[test_pos]
    midnight = np.flatnonzero(idx.hour == 0)
    pv_t = "pv" if "pv" in targets else targets[0]
    actual_pv = target_matrix(table, pv_t, test_pos[midnight], 24)
    worst = int(np.nanargmax(np.nanmean(np.abs(preds[(pv_t, "persistence")][midnight] - actual_pv), axis=1)))
    days = midnight[max(worst - 3, 0): max(worst - 3, 0) + 7]
    times = np.concatenate([idx[d] + pd.to_timedelta(np.arange(24), "h") for d in days])
    fig, ax = plt.subplots(len(targets), 1, figsize=(11, 3.2 * len(targets)), constrained_layout=True, sharex=True)
    for a, target in zip(np.atleast_1d(ax), targets):
        a.plot(times, target_matrix(table, target, test_pos[days], 24).ravel(), color="black", lw=2, label="actual")
        for name in cfg["forecast"]["models"]:
            a.plot(times, preds[(target, name)][days].ravel(), lw=1.2, label=name)
        a.set(title=f"{target}: day-ahead forecasts issued at midnight", ylabel="kW")
        a.grid(alpha=0.3)
        a.legend(ncol=4, fontsize=8)
    fig.savefig(out_dir / "forecast_example_week.png", dpi=150)
    plt.close(fig)
