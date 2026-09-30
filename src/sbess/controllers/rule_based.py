"""Brain A — the simple rule-follower (self-consumption maximisation).

1. Sun power serves the homes first.
2. Extra sun charges the battery (up to power and capacity limits).
3. When sun is short, the battery covers the gap (up to its limits).
4. The grid covers whatever is left. The battery never charges from the grid
   and never discharges to the grid.
"""
from __future__ import annotations

from sbess.controllers.base import Controller, Observation


class RuleBased(Controller):
    name = "rule_based"

    def decide(self, obs: Observation) -> float:
        net = obs.load_kw - obs.pv_kw           # > 0: deficit, < 0: surplus
        if net > 0:
            return min(net, obs.max_discharge_kw)
        return -min(-net, obs.max_charge_kw)
