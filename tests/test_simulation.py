"""Full-year checks on synthetic data: energy balance, Brain A behaviour, sensible totals."""
import numpy as np
import pytest

from sbess.battery import Battery
from sbess.billing import allocate
from sbess.controllers import make_controller
from sbess.data.weather import load_weather, check_solar_noon
from sbess.load_model import build_loads
from sbess.pv_model import pv_ac_kw
from sbess.simulate import simulate


@pytest.fixture(scope="module")
def year(request):
    from sbess.config import load_config
    cfg = load_config("synthetic_test")
    w = load_weather(cfg)
    loads = build_loads(w, cfg)
    pv = pv_ac_kw(w, cfg)
    sim = simulate(loads.sum(axis=1), pv, Battery.from_config(cfg), make_controller("rule_based", cfg), cfg)
    return cfg, w, loads, pv, sim


def test_full_year_length(year):
    _, w, loads, pv, sim = year
    assert len(sim) in (8760, 8784)


def test_energy_balance_every_hour(year):
    sim = year[4]
    assert sim["bus_residual_kwh"].abs().max() < 1e-6
    assert sim["batt_residual_kwh"].abs().max() < 1e-6


def test_annual_energy_conservation(year):
    sim = year[4]
    lhs = sim.pv_kw.sum() + sim.grid_import_kw.sum() + sim.discharge_kw.sum()
    rhs = sim.load_kw.sum() + sim.grid_export_kw.sum() + sim.charge_kw.sum()
    assert lhs == pytest.approx(rhs, rel=1e-9)


def test_brain_a_never_grid_charges_or_exports_battery(year):
    sim = year[4]
    assert (sim.charge_kw <= sim.pv_kw + 1e-9).all()                       # charge only from PV
    assert not ((sim.discharge_kw > 1e-9) & (sim.grid_export_kw > 1e-9)).any()
    assert not ((sim.charge_kw > 1e-9) & (sim.grid_import_kw > 1e-9)).any()


def test_home_totals_match_config(year):
    cfg, _, loads, _, _ = year
    for home in cfg["homes"]["profiles"]:
        assert loads[home["name"]].sum() == pytest.approx(home["annual_kwh"], rel=1e-9)


def test_summer_load_higher_than_winter(year):
    loads = year[2].sum(axis=1)
    assert loads[loads.index.month == 7].mean() > 1.5 * loads[loads.index.month == 1].mean()


def test_pv_zero_at_night_and_plausible_yield(year):
    cfg, _, _, pv, _ = year
    assert pv[(pv.index.hour < 5) | (pv.index.hour > 20)].max() == 0.0
    specific = pv.sum() / cfg["pv"]["capacity_kwp"]
    assert 1200 < specific < 2100            # kWh/kWp/yr, plausible for Dubai


def test_allocation_conserves_energy(year):
    cfg, _, loads, _, sim = year
    imp, exp = allocate(sim, loads, cfg)
    assert imp.to_numpy().sum() == pytest.approx(sim.grid_import_kw.sum())
    assert exp.to_numpy().sum() == pytest.approx(sim.grid_export_kw.sum())


def test_timestamp_check_on_synthetic(year):
    cfg, w, *_ = year
    assert abs(check_solar_noon(w, cfg)) < 0.75
