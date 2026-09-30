"""Battery 'brains'. Every controller implements Controller.decide()."""
from sbess.controllers.base import Controller, Observation, NoBattery
from sbess.controllers.rule_based import RuleBased

REGISTRY = {
    "none": NoBattery,
    "rule_based": RuleBased,       # Brain A
    # "perfect_foresight": ...     # Brain B  (Weeks 6-7)
    # "mpc": ...                   # Brain C
    # "mpc_degradation": ...       # Brain D
}


def make_controller(name: str, cfg: dict) -> Controller:
    if name not in REGISTRY:
        raise ValueError(f"Unknown controller '{name}'. Available: {list(REGISTRY)}")
    return REGISTRY[name](cfg)
