"""Hourly simulation of the shared PV + battery system.

Two energy balances are checked EVERY hour; any violation stops the run:
  AC bus:   pv + grid_import + discharge = load + grid_export + charge
  Battery:  E_after = E_before + eta_c*charge*dt - discharge*dt/eta_d - self_loss
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from sbess.battery import Battery
from sbess.controllers.base import Controller, Observation


class EnergyBalanceError(RuntimeError):
    pass


def simulate(load_total_kw: pd.Series, pv_kw: pd.Series, battery: Battery | None,
             controller: Controller, cfg: dict) -> pd.DataFrame:
    dt = cfg["simulation"]["timestep_h"]
    tol = cfg["simulation"]["energy_balance_tolerance_kwh"]
    if not load_total_kw.index.equals(pv_kw.index):
        raise ValueError("load and pv must share the same time index")

    n = len(load_total_kw)
    load = load_total_kw.to_numpy(dtype=float)
    pv = pv_kw.to_numpy(dtype=float)
    cols = {k: np.zeros(n) for k in
            ("charge_kw", "discharge_kw", "energy_kwh", "soc", "loss_kwh",
             "grid_import_kw", "grid_export_kw", "bus_residual_kwh", "batt_residual_kwh")}
    clipped = np.zeros(n, dtype=bool)

    for t in range(n):
        if battery is not None:
            obs = Observation(t=t, timestamp=load_total_kw.index[t], load_kw=load[t], pv_kw=pv[t],
                              energy_kwh=battery.energy_kwh, soc=battery.soc,
                              max_charge_kw=battery.max_charge_kw(dt),
                              max_discharge_kw=battery.max_discharge_kw(dt))
            res = battery.step(controller.decide(obs), dt)
            ch, dis = res["charge_kw"], res["discharge_kw"]
            e_before, e_after, loss = res["e_before_kwh"], res["e_after_kwh"], res["loss_kwh"]
            clipped[t] = res["clipped"]
            batt_resid = (e_before + battery.eta_charge * ch * dt - dis * dt / battery.eta_discharge
                          - battery.self_discharge_per_h * dt
                          * (e_before + battery.eta_charge * ch * dt - dis * dt / battery.eta_discharge)
                          - e_after)
            soc = battery.soc
        else:
            ch = dis = e_after = loss = soc = batt_resid = 0.0

        net = load[t] + ch - pv[t] - dis              # what the grid must supply (+) or absorb (-)
        imp, exp = max(net, 0.0), max(-net, 0.0)
        bus_resid = (pv[t] + imp + dis - load[t] - exp - ch) * dt

        if abs(bus_resid) > tol or abs(batt_resid) > tol:
            raise EnergyBalanceError(
                f"Energy balance broken at {load_total_kw.index[t]}: "
                f"bus residual {bus_resid:.3e} kWh, battery residual {batt_resid:.3e} kWh")

        cols["charge_kw"][t], cols["discharge_kw"][t] = ch, dis
        cols["energy_kwh"][t], cols["soc"][t], cols["loss_kwh"][t] = e_after, soc, loss
        cols["grid_import_kw"][t], cols["grid_export_kw"][t] = imp, exp
        cols["bus_residual_kwh"][t], cols["batt_residual_kwh"][t] = bus_resid, batt_resid

    out = pd.DataFrame(cols, index=load_total_kw.index)
    out.insert(0, "pv_kw", pv)
    out.insert(0, "load_kw", load)
    out["clipped"] = clipped
    return out
