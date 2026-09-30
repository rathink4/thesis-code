"""Ageing model checks: the paper formulas, the direction of every stress factor, rainflow counting,
the thermal model and the lifetime loop."""
import numpy as np
import pandas as pd
import pytest

from sbess.config import load_config
from sbess.degradation import (AgeingState, Cycles, NaumannLFP, SchmalstiegNMC, age, continue_loss,
                               find_cycles, make_ageing_model, year_stress)
from sbess.lifetime import battery_lifetime
from sbess.thermal import battery_temperature_c, placement_ambient_c

HOURS = 8760


@pytest.fixture(scope="module")
def nmc():
    return make_ageing_model(load_config("synthetic_test"))


@pytest.fixture(scope="module")
def lfp():
    return make_ageing_model(load_config("synthetic_test", ["battery.model=powerwall3"]))


def calendar_loss(model, soc, temp_c, hours=HOURS):
    """One year of storage at constant SOC and temperature."""
    ys = year_stress(model, np.full(hours + 1, soc), np.full(hours, temp_c), 1.0)
    return age(model, AgeingState(), ys).cal_loss


def cycle_loss(model, depth, fec, c_rate=0.5):
    """Capacity loss from `fec` full equivalent cycles made of full cycles of one depth."""
    n = fec / depth
    cyc = Cycles(depth=np.full(1, depth), mean_soc=np.full(1, 0.5), count=np.full(1, 1.0), c_rate=np.full(1, c_rate))
    stress, dx = model.cycle_stress(cyc), model.cycle_dx(cyc) * n
    return continue_loss(0.0, stress, dx, model.z_cyc)


def test_models_match_config(nmc, lfp):
    assert isinstance(nmc, SchmalstiegNMC) and isinstance(lfp, NaumannLFP)


# ---- formulas: constant stress must reproduce the closed-form paper equations
def test_schmalstieg_calendar_closed_form(nmc):
    v = float(nmc.ocv(0.5))
    alpha = (7.543 * v - 23.75) * 1e6 * np.exp(-6976 / (25 + 273.15))
    assert calendar_loss(nmc, 0.5, 25.0) == pytest.approx(alpha * 365 ** 0.75, rel=1e-9)


def test_naumann_calendar_closed_form(lfp):
    k = 1.2571e-5 * (2.8575 * (0.8 - 0.5) ** 3 + 0.60225)       # 25 degC -> k_T = k_ref
    assert calendar_loss(lfp, 0.8, 25.0) == pytest.approx(k * np.sqrt(365 * 86400), rel=1e-9)


def test_schmalstieg_cycle_closed_form(nmc):
    beta = 7.348e-3 * (float(nmc.ocv(0.5)) - 3.667) ** 2 + 7.6e-4 + 4.081e-3 * 0.8
    q_ah = 100 * 2 * 2.05                                      # 100 FEC through a 2.05 Ah cell
    assert cycle_loss(nmc, 0.8, 100) == pytest.approx(beta * np.sqrt(q_ah), rel=1e-9)


def test_naumann_cycle_closed_form(lfp):
    k = (0.0630 * 0.5 + 0.0971) * (4.0253 * (0.8 - 0.6) ** 3 + 1.0923)
    assert cycle_loss(lfp, 0.8, 100) == pytest.approx(k * np.sqrt(100) / 100, rel=1e-9)


def test_virtual_continuation_splits_consistently(nmc):
    """Ageing in 12 chunks at constant stress = ageing in one go."""
    s, z = np.array([1e-3]), nmc.z_cal
    one = continue_loss(0.0, s, np.array([365.0]), z)
    many = continue_loss(0.0, np.full(12, 1e-3), np.full(12, 365 / 12), z)
    assert many == pytest.approx(one, rel=1e-12)


# ---- direction of each stress factor (the Week 3 plan checks)
@pytest.mark.parametrize("name", ["nmc", "lfp"])
def test_hot_ages_faster_than_cool(name, request):
    m = request.getfixturevalue(name)
    assert calendar_loss(m, 0.5, 45.0) > 1.5 * calendar_loss(m, 0.5, 25.0)


@pytest.mark.parametrize("name", ["nmc", "lfp"])
def test_high_soc_ages_faster(name, request):
    m = request.getfixturevalue(name)
    assert calendar_loss(m, 0.95, 25.0) > calendar_loss(m, 0.5, 25.0) > calendar_loss(m, 0.1, 25.0)


@pytest.mark.parametrize("name", ["nmc", "lfp"])
def test_deep_cycles_hurt_more_than_shallow(name, request):
    """Same energy throughput (FEC), delivered as deep or as shallow cycles."""
    m = request.getfixturevalue(name)
    assert cycle_loss(m, 0.9, 500) > cycle_loss(m, 0.5, 500) > cycle_loss(m, 0.1, 500)


def test_lfp_faster_c_rate_hurts_more(lfp):
    assert cycle_loss(lfp, 0.8, 500, c_rate=1.0) > cycle_loss(lfp, 0.8, 500, c_rate=0.2)


@pytest.mark.parametrize("name", ["nmc", "lfp"])
def test_calendar_stress_never_negative(name, request):
    m = request.getfixturevalue(name)
    soc, temp = np.meshgrid(np.linspace(0, 1, 21), np.linspace(-10, 60, 15))
    assert np.all(m.calendar_stress(soc.ravel(), temp.ravel()) >= 0)


# ---- rainflow
def test_rainflow_counts_daily_cycles():
    day = [0.1, 0.3, 0.5, 0.7, 0.9, 0.9, 0.7, 0.5, 0.3, 0.1]   # 0.1 -> 0.9 -> 0.1, 4 h each way
    soc = np.array(day * 30 + [0.1])
    cyc = find_cycles(soc, 1.0)
    assert cyc.fec == pytest.approx(30 * 0.8, rel=0.02)
    assert np.all(np.isclose(cyc.depth, 0.8))
    assert np.all(np.isclose(cyc.c_rate, 0.2))                 # 0.8 SOC over 4 moving hours


def test_rainflow_ignores_rest():
    cyc = find_cycles(np.full(50, 0.5), 1.0)
    assert cyc.fec == 0.0


# ---- thermal
def test_indoor_idle_battery_sits_at_room_temperature():
    cfg = load_config("indoor", ["simulation.weather_source=synthetic"])
    idx = pd.date_range("2023-01-01", periods=48, freq="h", tz="Asia/Dubai")
    w = pd.DataFrame({"temp_air": np.full(48, 40.0)}, index=idx)
    t = battery_temperature_c(pd.Series(0.0, index=idx), placement_ambient_c(w, cfg), cfg)
    assert np.allclose(t, 24.0)


def test_losses_heat_the_battery_to_r_times_q():
    cfg = load_config("indoor", ["simulation.weather_source=synthetic"])
    units, r = cfg["battery"]["units"], cfg["battery"]["thermal"]["r_th_k_per_kw"]
    idx = pd.date_range("2023-01-01", periods=48, freq="h", tz="Asia/Dubai")
    w = pd.DataFrame({"temp_air": np.full(48, 40.0)}, index=idx)
    loss = pd.Series(0.3 * units, index=idx)                   # 0.3 kW of heat per unit
    t = battery_temperature_c(loss, placement_ambient_c(w, cfg), cfg)
    assert t.iloc[-1] == pytest.approx(24.0 + r * 0.3, abs=1e-6)


def test_garage_follows_outdoor_with_lag():
    cfg = load_config("synthetic_test")
    idx = pd.date_range("2023-01-01", periods=48, freq="h", tz="Asia/Dubai")
    w = pd.DataFrame({"temp_air": np.r_[np.full(24, 30.0), np.full(24, 40.0)]}, index=idx)
    amb = placement_ambient_c(w, cfg)
    off = cfg["battery"]["thermal"]["placements"]["outdoor_garage"]["offset_c"]
    assert amb.iloc[24] < 40.0 + off                          # lags the step
    assert amb.iloc[-1] == pytest.approx(40.0 + off, abs=0.01)


# ---- lifetime loop
def _fake_year(soc_path_fn):
    idx = pd.date_range("2023-01-01", periods=HOURS, freq="h", tz="Asia/Dubai")

    def simulate_year(soh):
        soc = soc_path_fn(np.arange(HOURS))
        return pd.DataFrame({"soc": soc, "loss_kwh": np.zeros(HOURS)}, index=idx)
    return simulate_year, pd.Series(30.0, index=idx)


@pytest.mark.parametrize("method", ["extrapolate", "multi_year"])
def test_lifetime_reaches_end_of_life_monotonically(method):
    cfg = load_config("synthetic_test", [f"degradation.lifetime_method={method}"])
    daily = lambda h: 0.5 + 0.4 * np.sin(2 * np.pi * h / 24)          # noqa: E731  one 0.8-deep cycle a day
    simulate_year, amb = _fake_year(daily)
    summary, table, _ = battery_lifetime(simulate_year, amb, cfg)
    assert (np.diff(table["soh_end"]) < 0).all()
    assert summary["years_to_eol"] is not None
    assert len(table) - 1 < summary["years_to_eol"] <= len(table)
    assert table["soh_end"].iloc[-1] <= cfg["degradation"]["eol_soh"] < table["soh_start"].iloc[-1]


def test_idle_battery_ages_only_by_calendar():
    cfg = load_config("synthetic_test")
    simulate_year, amb = _fake_year(lambda h: np.full(len(h), 0.5))
    summary, _, _ = battery_lifetime(simulate_year, amb, cfg)
    assert summary["cycle_loss_year1_pct"] == 0.0 and summary["calendar_loss_year1_pct"] > 0.0
