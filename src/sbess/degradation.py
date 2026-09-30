"""Battery ageing: calendar + cycle capacity loss, scored AFTER a simulation.

Every brain is scored the same way: the simulator produces an hourly SOC and battery
temperature, then this module turns them into capacity loss. (Rainflow counting is not
smooth, so it cannot sit inside an optimiser; Brain D will use a simpler wear cost and still
be scored here. See DECISIONS D-014.)

Both paper models have the form  loss = stress * x^z  with x = time (calendar) or
throughput (cycle), and stress set by SOC / voltage, temperature, depth and C-rate.
When stress changes from step to step, the loss is continued with the "virtual x" method
(as in SimSES): find the x that would have produced today's loss at today's stress,
add this step's x, and evaluate again. Calendar and cycle losses are added.

Models (parameters in config/params/degradation.yaml):
    schmalstieg_nmc  calendar: alpha(V, T) * t_days^0.75     cycle: beta(V_avg, DOD) * Q_Ah^0.5
    naumann_lfp      calendar: k_T(T) * k_SOC(SOC) * t_s^0.5  cycle: k_C(C_rate) * k_DOD(DOD) * FEC^0.5 / 100
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import rainflow

GAS_CONSTANT = 8.3144598        # J/(mol K)
KELVIN = 273.15


@dataclass
class Cycles:
    """Rainflow cycles of the SOC path. count is 1.0 (full cycle) or 0.5 (half cycle)."""
    depth: np.ndarray
    mean_soc: np.ndarray
    count: np.ndarray
    c_rate: np.ndarray

    @property
    def fec(self) -> float:
        """Full equivalent cycles (a full cycle of depth d counts as d)."""
        return float((self.count * self.depth).sum())


@dataclass
class AgeingState:
    """Accumulated capacity loss as a fraction of rated capacity."""
    cal_loss: float = 0.0
    cyc_loss: float = 0.0

    @property
    def soh(self) -> float:
        return 1.0 - self.cal_loss - self.cyc_loss


# ------------------------------------------------------------------ helpers
def soc_boundaries(sim: pd.DataFrame, soc_init: float) -> np.ndarray:
    """SOC at every hour boundary: start value, then the value after each hour (n+1 points)."""
    return np.concatenate([[soc_init], sim["soc"].to_numpy()])


def find_cycles(soc_b: np.ndarray, dt: float) -> Cycles:
    """Rainflow-count the SOC path. C-rate = depth / hours in which SOC actually moved."""
    moving = np.abs(np.diff(soc_b)) > 1e-12
    moving_before = np.concatenate([[0], np.cumsum(moving)])      # moving steps before index i
    rows = []
    for rng, mean, count, i0, i1 in rainflow.extract_cycles(soc_b):
        a, b = min(i0, i1), max(i0, i1)
        active_h = (moving_before[b] - moving_before[a]) * dt
        rows.append((rng, mean, count, rng / active_h if active_h > 0 else 0.0))
    arr = np.array(rows, dtype=float).reshape(-1, 4)
    return Cycles(depth=arr[:, 0], mean_soc=arr[:, 1], count=arr[:, 2], c_rate=arr[:, 3])


def continue_loss(loss: float, stress: np.ndarray, dx: np.ndarray, z: float) -> float:
    """Advance loss = stress * x^z through a sequence of steps with changing stress."""
    inv_z = 1.0 / z
    for s, d in zip(stress.tolist(), dx.tolist()):
        if s <= 0.0 or d <= 0.0:
            continue
        x_virtual = (loss / s) ** inv_z
        loss = s * (x_virtual + d) ** z
    return loss


# ------------------------------------------------------------------ models
class AgeingModel:
    """Common interface. Subclasses supply stress factors and step sizes."""
    z_cal: float
    z_cyc: float

    def __init__(self, params: dict):
        self.p = params

    def calendar_stress(self, soc: np.ndarray, temp_c: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def calendar_dx(self, n: int, dt_h: float) -> np.ndarray:
        raise NotImplementedError

    def cycle_stress(self, cyc: Cycles) -> np.ndarray:
        raise NotImplementedError

    def cycle_dx(self, cyc: Cycles) -> np.ndarray:
        raise NotImplementedError


class SchmalstiegNMC(AgeingModel):
    def __init__(self, params: dict):
        super().__init__(params)
        self.z_cal = params["calendar"]["time_exponent"]
        self.z_cyc = params["cycle"]["throughput_exponent"]
        self._soc = np.asarray(params["ocv_soc"], dtype=float)
        self._v = np.asarray(params["ocv_v"], dtype=float)

    def ocv(self, soc) -> np.ndarray:
        return np.interp(soc, self._soc, self._v)

    def calendar_stress(self, soc, temp_c):
        c = self.p["calendar"]
        v = np.maximum(self.ocv(soc), c["v_floor"])
        t_k = np.asarray(temp_c) + KELVIN
        return np.maximum((c["a_v"] * v - c["b_v"]) * 1e6 * np.exp(-c["ea_over_r_k"] / t_k), 0.0)

    def calendar_dx(self, n, dt_h):
        return np.full(n, dt_h / 24.0)                          # days

    def cycle_stress(self, cyc):
        c = self.p["cycle"]
        v_avg = self.ocv(cyc.mean_soc)
        return c["a"] * (v_avg - c["v_ref"]) ** 2 + c["b"] + c["c"] * cyc.depth

    def cycle_dx(self, cyc):
        # a half cycle of depth d moves d * C_cell Ah through the cell; a full cycle twice that
        return 2.0 * cyc.count * cyc.depth * self.p["cell_capacity_ah"]


class NaumannLFP(AgeingModel):
    def __init__(self, params: dict):
        super().__init__(params)
        self.z_cal = params["calendar"]["time_exponent"]
        self.z_cyc = params["cycle"]["fec_exponent"]

    def calendar_stress(self, soc, temp_c):
        c = self.p["calendar"]
        t_k = np.asarray(temp_c) + KELVIN
        k_t = c["k_ref"] * np.exp(-c["ea_j_per_mol"] / GAS_CONSTANT * (1.0 / t_k - 1.0 / (c["t_ref_c"] + KELVIN)))
        k_soc = c["c_soc"] * (np.asarray(soc) - 0.5) ** 3 + c["d_soc"]
        return np.maximum(k_t * k_soc, 0.0)

    def calendar_dx(self, n, dt_h):
        return np.full(n, dt_h * 3600.0)                        # seconds

    def cycle_stress(self, cyc):
        c = self.p["cycle"]
        k_c = c["a_c"] * cyc.c_rate + c["b_c"]
        k_dod = c["c_dod"] * (cyc.depth - 0.6) ** 3 + c["d_dod"]
        return k_c * k_dod / 100.0                              # paper gives loss in %

    def cycle_dx(self, cyc):
        return cyc.count * cyc.depth                            # full equivalent cycles


MODELS = {"schmalstieg_nmc": SchmalstiegNMC, "naumann_lfp": NaumannLFP}


def make_ageing_model(cfg: dict) -> AgeingModel:
    params = cfg["battery"]["ageing"]
    return MODELS[params["model"]](params)


# ------------------------------------------------------------------ one year
@dataclass
class YearStress:
    """Everything needed to age the battery over one simulated year (reusable for extrapolation)."""
    cal_stress: np.ndarray
    cal_dx: np.ndarray
    cyc_stress: np.ndarray
    cyc_dx: np.ndarray
    fec: float


def year_stress(model: AgeingModel, soc_b: np.ndarray, temp_c: np.ndarray, dt: float) -> YearStress:
    soc_mid = 0.5 * (soc_b[:-1] + soc_b[1:])
    cyc = find_cycles(soc_b, dt)                                # in rainflow's detection order
    return YearStress(cal_stress=model.calendar_stress(soc_mid, temp_c),
                      cal_dx=model.calendar_dx(len(soc_mid), dt),
                      cyc_stress=model.cycle_stress(cyc),
                      cyc_dx=model.cycle_dx(cyc),
                      fec=cyc.fec)


def age(model: AgeingModel, state: AgeingState, ys: YearStress) -> AgeingState:
    """Return the state after one more year of the given stress."""
    return AgeingState(cal_loss=continue_loss(state.cal_loss, ys.cal_stress, ys.cal_dx, model.z_cal),
                       cyc_loss=continue_loss(state.cyc_loss, ys.cyc_stress, ys.cyc_dx, model.z_cyc))
