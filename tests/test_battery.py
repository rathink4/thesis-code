import math

import pytest

from sbess.battery import Battery


def make(**kw):
    base = dict(capacity_kwh=10.0, p_charge_max_kw=5.0, p_discharge_max_kw=5.0,
                eta_charge=math.sqrt(0.9), eta_discharge=math.sqrt(0.9), soc_init=0.5)
    base.update(kw)
    return Battery(**base)


def test_power_limit():
    b = make()
    assert b.step(-20.0, 1.0)["charge_kw"] == pytest.approx(5.0)


def test_never_exceeds_capacity():
    b = make(soc_init=0.9)
    for _ in range(10):
        b.step(-5.0, 1.0)
    assert b.soc == pytest.approx(1.0)


def test_never_below_min():
    b = make(soc_min=0.1)
    for _ in range(10):
        b.step(5.0, 1.0)
    assert b.soc == pytest.approx(0.1)


def test_round_trip_efficiency():
    b = make(soc_init=0.0, capacity_kwh=100.0, p_charge_max_kw=10, p_discharge_max_kw=10)
    b.step(-10.0, 1.0)                       # put 10 kWh in from the AC side
    out = 0.0
    while b.energy_kwh > 1e-12:
        out += b.step(10.0, 1.0)["discharge_kw"]
    assert out / 10.0 == pytest.approx(0.9)


def test_from_config(cfg):
    b = Battery.from_config(cfg)
    n = cfg["battery"]["units"]
    assert b.capacity_kwh == pytest.approx(13.5 * n)
    assert b.eta_charge * b.eta_discharge == pytest.approx(cfg["battery"]["spec"]["round_trip_efficiency"])
