"""Forecasting checks on synthetic data: no peeking at the future, clean date splits,
physical limits, file round trip, and an end-to-end run with small models."""
import numpy as np
import pandas as pd
import pytest

from sbess.config import load_config
from sbess.data.weather import data_years
from sbess.forecast.data import hourly_table, sequence_features, tabular_features, target_matrix
from sbess.forecast.models import Persistence
from sbess.forecast.pipeline import (load_forecast, postprocess, run_forecasting, save_forecast,
                                     split_positions)

SMALL = ["forecast.xgboost.n_estimators=100", "forecast.lstm.epochs=2", "forecast.lstm.hidden=8"]


@pytest.fixture(scope="module")
def cfg():
    return load_config("synthetic_test", SMALL)


@pytest.fixture(scope="module")
def table(cfg):
    return hourly_table(cfg, data_years(cfg))


# ---- no peeking at the future
@pytest.mark.parametrize("target", ["load", "pv"])
def test_features_do_not_use_measurements_from_issue_time_onwards(cfg, table, target):
    """Changing every measurement at or after the issue time must not change its features."""
    t = 5000
    pos = np.array([t])
    tampered = table.copy()
    for col in ("load", "pv", "obs_temp", "obs_ghi", "obs_temp_24h"):
        tampered.iloc[t:, tampered.columns.get_loc(col)] = -999.0
    pd.testing.assert_frame_equal(tabular_features(table, target, pos, 24), tabular_features(tampered, target, pos, 24))
    for a, b in zip(sequence_features(table, target, pos, 24, 48), sequence_features(tampered, target, pos, 24, 48)):
        np.testing.assert_array_equal(a, b)


def test_persistence_is_same_hour_yesterday(cfg, table):
    pos = np.array([1000, 2000])
    pred = Persistence(cfg).predict(table, "load", pos)
    y = table["load"].to_numpy()
    assert pred[0, 0] == y[1000 - 24] and pred[1, 23] == y[2000 + 23 - 24]


def test_target_matrix_alignment(table):
    pos = np.array([100, len(table) - 5])
    m = target_matrix(table, "pv", pos, 24)
    assert m[0, 7] == table["pv"].iloc[107]
    assert np.isnan(m[1, 5:]).all() and not np.isnan(m[1, :5]).any()     # past the end -> NaN


# ---- splits by date
def test_splits_are_separate_and_in_the_right_years(cfg, table):
    s = split_positions(cfg, table)
    years = table.index.year.to_numpy()
    assert set(years[s["train"]]) == set(years[s["validation"]]) == {2024}
    assert set(years[s["test"]]) == {2025} and len(s["test"]) == 8760
    assert not set(s["train"]) & set(s["validation"])
    # no training target hour is a validation target hour
    train_h = set((s["train"][:, None] + np.arange(24)).ravel())
    val_h = set((s["validation"][:, None] + np.arange(24)).ravel())
    assert not train_h & val_h
    assert 0.1 < len(s["validation"]) / (len(s["train"]) + len(s["validation"])) < 0.3


def test_tail_validation_is_the_end_of_the_training_year():
    cfg = load_config("synthetic_test", ["forecast.validation.method=tail"])
    table = hourly_table(cfg, data_years(cfg))
    s = split_positions(cfg, table)
    assert table.index[s["validation"]].min() >= pd.Timestamp("2024-11-01", tz="Asia/Dubai")
    assert table.index[s["train"]].max() < pd.Timestamp("2024-11-01", tz="Asia/Dubai")


def test_test_year_cannot_be_a_training_year():
    cfg = load_config("synthetic_test", ["forecast.train_years=[2024, 2025]"])
    with pytest.raises(ValueError):
        split_positions(cfg, hourly_table(cfg, data_years(cfg)))


# ---- physical limits and files
def test_postprocess_limits(cfg, table):
    pos = np.array([len(table) - 30])
    raw = np.full((1, 24), 100.0)
    out = postprocess(raw, table, "pv", pos, cfg)
    j = pos[0] + np.arange(24)
    night = table["clearsky_ghi"].to_numpy()[np.minimum(j, len(table) - 1)] <= 0
    ac_max = cfg["pv"]["capacity_kwp"] / cfg["pv"]["dc_ac_ratio"]
    inside = j < len(table)
    assert (out[0, inside & night] == 0).all()
    assert (out[0, inside & ~night] <= ac_max).all()
    assert postprocess(-raw, table, "load", np.array([100]), cfg).min() == 0.0


def test_forecast_file_round_trip(tmp_path):
    cfg = load_config("synthetic_test", [f"forecast.forecast_dir={tmp_path.as_posix()}"])
    idx = pd.date_range("2025-01-01", periods=3, freq="h", tz="Asia/Dubai")
    pred = np.arange(72, dtype=float).reshape(3, 24)
    path = save_forecast(cfg, "load", "xgboost", idx, pred)
    assert path.parent.name == "synthetic"                       # test forecasts kept apart from real ones
    back = load_forecast(cfg, "load", "xgboost")
    np.testing.assert_allclose(back.to_numpy(), pred)
    assert back.index.equals(idx)


# ---- end to end with small models
@pytest.fixture(scope="module")
def run(cfg):
    return run_forecasting(cfg, out_dir=None, save=False, verbose=False)


def test_every_model_forecasts_every_test_hour(cfg, run):
    _, _, preds, _, splits = run
    for (target, model), p in preds.items():
        assert p.shape == (8760, 24)
        assert np.isfinite(p[:-23]).all()                          # only the year-end tail is NaN


def test_learned_model_beats_persistence(run):
    scores = run[0]
    test = scores[scores.split == "test"].set_index(["target", "model"])["rmse_kw"]
    for target in ("load", "pv"):
        assert test[(target, "xgboost")] < test[(target, "persistence")]
