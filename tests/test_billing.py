import pandas as pd
import pytest

from sbess.billing import bill_home, slab_charge
from sbess.config import load_config

SLABS = [[2000, 0.23], [4000, 0.28], [6000, 0.32], [None, 0.38]]


def test_slab_charge():
    assert slab_charge(1000, SLABS) == pytest.approx(230.0)
    assert slab_charge(5000, SLABS) == pytest.approx(2000 * .23 + 2000 * .28 + 1000 * .32)
    assert slab_charge(7000, SLABS) == pytest.approx(2000 * .23 + 2000 * .28 + 2000 * .32 + 1000 * .38)


def _two_months(imp_jan, exp_jan, imp_feb, exp_feb):
    idx = pd.date_range("2023-01-01", "2023-02-28 23:00", freq="h", tz="Asia/Dubai")
    jan = idx.month == 1
    imp = pd.Series(0.0, index=idx); exp = pd.Series(0.0, index=idx)
    imp[jan] = imp_jan / jan.sum(); exp[jan] = exp_jan / jan.sum()
    imp[~jan] = imp_feb / (~jan).sum(); exp[~jan] = exp_feb / (~jan).sum()
    return imp, exp


def test_net_metering_carry_forward():
    cfg = load_config(None, ["tariff.export_mode=net_metering"])
    imp, exp = _two_months(500, 800, 1000, 0)         # Jan surplus of 300 kWh
    b = bill_home(imp, exp, cfg)
    assert b.loc[0, "billed_kwh"] == pytest.approx(0.0)
    assert b.loc[1, "billed_kwh"] == pytest.approx(700.0)


def test_no_credit_ignores_exports():
    cfg = load_config(None, ["tariff.export_mode=no_credit"])
    imp, exp = _two_months(500, 800, 1000, 0)
    b = bill_home(imp, exp, cfg)
    assert b["billed_kwh"].tolist() == pytest.approx([500.0, 1000.0])


def test_vat_and_fuel():
    cfg = load_config(None, ["tariff.export_mode=no_credit"])
    imp, exp = _two_months(1000, 0, 0, 0)
    total = bill_home(imp, exp, cfg).loc[0, "total_aed"]
    assert total == pytest.approx((1000 * 0.23 + 1000 * 0.06) * 1.05)
