"""Common interface for every brain, so the simulator treats them all identically."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class Observation:
    """What a brain is allowed to see at time step t (nothing from the future
    unless the brain was given forecasts at construction)."""
    t: int
    timestamp: pd.Timestamp
    load_kw: float
    pv_kw: float
    energy_kwh: float
    soc: float
    max_charge_kw: float
    max_discharge_kw: float


class Controller:
    name = "base"

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def decide(self, obs: Observation) -> float:
        """Return requested battery AC power in kW (+ discharge, - charge)."""
        raise NotImplementedError


class NoBattery(Controller):
    name = "none"

    def decide(self, obs: Observation) -> float:
        return 0.0
