"""Split community grid flows between homes, then bill each home monthly.

Allocation (allocation.method = pro_rata_hourly_load):
    home_import_i[h] = community_import[h] * load_i[h] / load_total[h]
    home_export_i[h] = community_export[h] * export_share_i
Each home keeps its own DEWA account, so slabs and net-metering credits are per home.

Export treatment (tariff.export_mode):
    net_metering : exported kWh offset imported kWh in the same month; any surplus
                   carries forward to later months (Shams Dubai). Under a TOU tariff the
                   offset is valued in AED at the hourly price.
    no_credit    : exports earn nothing.
    feed_in      : exports paid tariff.feed_in_aed_per_kwh.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------- allocation
def allocate(sim: pd.DataFrame, loads: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    method = cfg["allocation"]["method"]
    if method != "pro_rata_hourly_load":
        raise ValueError(f"allocation.method '{method}' not implemented")
    dt = cfg["simulation"]["timestep_h"]
    total = loads.sum(axis=1).replace(0.0, np.nan)
    share = loads.div(total, axis=0).fillna(1.0 / loads.shape[1])
    imports = share.mul(sim["grid_import_kw"] * dt, axis=0)
    shares = pd.Series(cfg["allocation"]["export_shares"], index=loads.columns)
    exports = pd.DataFrame(np.outer(sim["grid_export_kw"] * dt, shares),
                           index=loads.index, columns=loads.columns)
    return imports, exports          # kWh per hour per home


# ---------------------------------------------------------------- tariffs
def slab_charge(kwh: float, slabs: list) -> float:
    """Energy charge (AED) for one month's billed kWh under an increasing-block tariff."""
    cost, lower = 0.0, 0.0
    for upper, price in slabs:
        top = np.inf if upper is None else float(upper)
        if kwh <= lower:
            break
        cost += (min(kwh, top) - lower) * price
        lower = top
    return cost


def tou_price_series(index: pd.DatetimeIndex, spec: dict) -> pd.Series:
    price = np.full(len(index), np.nan)
    hours = index.hour.to_numpy()
    for p in spec["periods"]:
        start, end = p["hours"]
        price[(hours >= start) & (hours < end)] = p["price"]
    if np.isnan(price).any():
        raise ValueError("TOU periods do not cover all 24 hours")
    return pd.Series(price, index=index)


def bill_home(imp_kwh: pd.Series, exp_kwh: pd.Series, cfg: dict) -> pd.DataFrame:
    """Monthly bill for one home. Returns one row per month (AED)."""
    spec, mode = cfg["tariff"]["spec"], cfg["tariff"]["export_mode"]
    fuel, vat, fixed = spec["fuel_surcharge_aed_per_kwh"], spec["vat"], spec["fixed_aed_per_month"]
    months = imp_kwh.index.tz_localize(None).to_period("M")
    rows, carry = [], 0.0                     # carry: kWh (slab) or AED (tou)

    if spec["type"] == "tou":
        price = tou_price_series(imp_kwh.index, spec)
    for m in months.unique():
        sel = months == m
        imp, exp = float(imp_kwh[sel].sum()), float(exp_kwh[sel].sum())
        credit_aed = 0.0

        if spec["type"] == "slab":
            if mode == "net_metering":
                net = imp - exp - carry
                billed = max(net, 0.0)
                carry = max(-net, 0.0) if spec["net_metering_carry_forward"] else 0.0
            else:
                billed = imp
                if mode == "feed_in":
                    credit_aed = exp * cfg["tariff"]["feed_in_aed_per_kwh"]
            energy = slab_charge(billed, spec["slabs"])
        elif spec["type"] == "tou":
            p = price[sel].to_numpy()
            gross = float((imp_kwh[sel].to_numpy() * p).sum())
            billed = imp
            if mode == "net_metering":
                value = gross - float((exp_kwh[sel].to_numpy() * p).sum()) - carry
                energy = max(value, 0.0)
                carry = max(-value, 0.0) if spec["net_metering_carry_forward"] else 0.0
                billed = max(imp - exp, 0.0)          # for fuel surcharge only
            else:
                energy = gross
                if mode == "feed_in":
                    credit_aed = exp * cfg["tariff"]["feed_in_aed_per_kwh"]
        else:
            raise ValueError(f"Unknown tariff type {spec['type']}")

        fuel_aed = billed * fuel
        subtotal = energy + fuel_aed + fixed
        total = subtotal * (1 + vat) - credit_aed
        rows.append({"month": str(m), "import_kwh": imp, "export_kwh": exp, "billed_kwh": billed,
                     "energy_aed": energy, "fuel_aed": fuel_aed, "vat_aed": subtotal * vat,
                     "feed_in_credit_aed": credit_aed, "total_aed": total,
                     "carry_forward": carry})
    return pd.DataFrame(rows)


def bill_all(imports: pd.DataFrame, exports: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    frames = []
    for home in imports.columns:
        b = bill_home(imports[home], exports[home], cfg)
        b.insert(0, "home", home)
        frames.append(b)
    return pd.concat(frames, ignore_index=True)
