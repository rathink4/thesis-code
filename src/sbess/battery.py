"""Battery as a 'digital bucket'.

Sign convention (AC side):  p > 0 discharge (battery -> homes),  p < 0 charge.
Internal energy update per step of dt hours:
    E_next = E + eta_c * P_charge * dt - P_discharge * dt / eta_d - self_discharge * E
Limits: power (charge/discharge separately) and energy (soc_min..soc_max x capacity).
`soh` (state of health, 1.0 = new) scales usable capacity; the degradation model
will update it from Week 3.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Battery:
    capacity_kwh: float           # usable energy when new (all units combined)
    p_charge_max_kw: float
    p_discharge_max_kw: float
    eta_charge: float
    eta_discharge: float
    soc_min: float = 0.0
    soc_max: float = 1.0
    soc_init: float = 0.5
    self_discharge_per_h: float = 0.0
    soh: float = 1.0
    energy_kwh: float = field(init=False)

    def __post_init__(self):
        if not 0 <= self.soc_min < self.soc_max <= 1:
            raise ValueError("Need 0 <= soc_min < soc_max <= 1")
        if not self.soc_min <= self.soc_init <= self.soc_max:
            raise ValueError("soc_init must lie between soc_min and soc_max")
        self.energy_kwh = self.soc_init * self.capacity_now

    # ---- construction from config ----------------------------------------
    @classmethod
    def from_config(cls, cfg: dict) -> "Battery":
        b, spec = cfg["battery"], cfg["battery"]["spec"]
        n = b["units"]
        rte = spec["round_trip_efficiency"]
        if b["efficiency_split"] != "symmetric":
            raise ValueError("Only efficiency_split: symmetric is implemented")
        eta = math.sqrt(rte)
        return cls(capacity_kwh=n * spec["usable_kwh"],
                   p_charge_max_kw=n * spec["p_charge_max_kw"],
                   p_discharge_max_kw=n * spec["p_discharge_max_kw"],
                   eta_charge=eta, eta_discharge=eta,
                   soc_min=b["soc_min"], soc_max=b["soc_max"], soc_init=b["soc_init"],
                   self_discharge_per_h=b["self_discharge_per_h"])

    # ---- state --------------------------------------------------------------
    @property
    def capacity_now(self) -> float:
        return self.capacity_kwh * self.soh

    @property
    def soc(self) -> float:
        return self.energy_kwh / self.capacity_now

    @property
    def e_min(self) -> float:
        return self.soc_min * self.capacity_now

    @property
    def e_max(self) -> float:
        return self.soc_max * self.capacity_now

    def max_charge_kw(self, dt: float) -> float:
        headroom = max(self.e_max - self.energy_kwh, 0.0)
        return min(self.p_charge_max_kw, headroom / (self.eta_charge * dt))

    def max_discharge_kw(self, dt: float) -> float:
        available = max(self.energy_kwh - self.e_min, 0.0)
        return min(self.p_discharge_max_kw, available * self.eta_discharge / dt)

    # ---- one time step ----------------------------------------------------
    def step(self, p_request_kw: float, dt: float) -> dict:
        """Apply a requested AC power, clipped to limits. Returns what actually happened."""
        e_before = self.energy_kwh
        if p_request_kw >= 0:
            p_dis = min(p_request_kw, self.max_discharge_kw(dt))
            p_ch = 0.0
        else:
            p_ch = min(-p_request_kw, self.max_charge_kw(dt))
            p_dis = 0.0

        stored = self.eta_charge * p_ch * dt
        removed = p_dis * dt / self.eta_discharge
        e_mid = e_before + stored - removed
        self_loss = self.self_discharge_per_h * dt * e_mid
        self.energy_kwh = min(max(e_mid - self_loss, 0.0), self.capacity_now)

        conversion_loss = (p_ch * dt - stored) + (removed - p_dis * dt)
        return {
            "p_batt_kw": p_dis - p_ch,
            "charge_kw": p_ch,
            "discharge_kw": p_dis,
            "e_before_kwh": e_before,
            "e_after_kwh": self.energy_kwh,
            "loss_kwh": conversion_loss + self_loss,
            "clipped": abs((p_dis - p_ch) - p_request_kw) > 1e-9,
        }
