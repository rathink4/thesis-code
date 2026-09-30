"""Configuration loading.

Order of precedence (later wins):
    config/default.yaml  ->  config/scenarios/<name>.yaml  ->  --set key=value overrides

Then library entries are resolved:
    battery.model  -> config/params/batteries.yaml   (+ battery.spec_override)
    tariff.name    -> config/params/tariffs.yaml     (+ tariff.spec_override)
    homes archetypes -> config/params/load_archetypes.yaml

Unknown keys raise an error, so a typo in --set never silently does nothing.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"

# Keys under these paths may contain new sub-keys (free-form dictionaries).
_FREEFORM = ("battery.spec_override", "tariff.spec_override")


class ConfigError(ValueError):
    pass


def _read_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _merge(base: dict, new: dict, path: str = "", strict: bool = True) -> dict:
    """Recursively merge `new` into a copy of `base`."""
    out = copy.deepcopy(base)
    for key, val in new.items():
        full = f"{path}.{key}" if path else key
        freeform = any(full.startswith(p) for p in _FREEFORM)
        if strict and not freeform and key not in out:
            raise ConfigError(f"Unknown config key '{full}'. Check spelling against config/default.yaml.")
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], val, full, strict)
        else:
            out[key] = copy.deepcopy(val)
    return out


def parse_override(text: str) -> dict:
    """'battery.units=2' -> {'battery': {'units': 2}}. Values are parsed as YAML
    so numbers, booleans and lists get the right type."""
    if "=" not in text:
        raise ConfigError(f"Override '{text}' must look like key.subkey=value")
    key, raw = text.split("=", 1)
    value = yaml.safe_load(raw)
    nested: Any = value
    for part in reversed(key.strip().split(".")):
        nested = {part: nested}
    return nested


def load_config(scenario: str | None = None, overrides: list[str] | None = None,
                config_dir: Path = CONFIG_DIR) -> dict:
    cfg = _read_yaml(config_dir / "default.yaml")

    if scenario:
        scen_path = config_dir / "scenarios" / f"{scenario}.yaml"
        if not scen_path.exists():
            raise ConfigError(f"Scenario file not found: {scen_path}")
        cfg = _merge(cfg, _read_yaml(scen_path))
    for ov in overrides or []:
        cfg = _merge(cfg, parse_override(ov))

    cfg["_meta"] = {"scenario": scenario or "default", "overrides": list(overrides or [])}
    return resolve_library(cfg, config_dir)


def resolve_library(cfg: dict, config_dir: Path = CONFIG_DIR) -> dict:
    """Attach datasheet / tariff / archetype details referenced by name."""
    params = config_dir / "params"
    cfg = copy.deepcopy(cfg)

    batteries = _read_yaml(params / "batteries.yaml")
    model = cfg["battery"]["model"]
    if model not in batteries:
        raise ConfigError(f"battery.model '{model}' not in batteries.yaml ({list(batteries)})")
    spec = copy.deepcopy(batteries[model])
    spec.update(cfg["battery"].get("spec_override") or {})
    cfg["battery"]["spec"] = spec

    tariffs = _read_yaml(params / "tariffs.yaml")
    name = cfg["tariff"]["name"]
    if name not in tariffs:
        raise ConfigError(f"tariff.name '{name}' not in tariffs.yaml ({list(tariffs)})")
    tspec = copy.deepcopy(tariffs[name])
    tspec.update(cfg["tariff"].get("spec_override") or {})
    cfg["tariff"]["spec"] = tspec
    if cfg["tariff"]["export_mode"] not in ("net_metering", "no_credit", "feed_in"):
        raise ConfigError("tariff.export_mode must be net_metering | no_credit | feed_in")

    archetypes = _read_yaml(params / "load_archetypes.yaml")
    for home in cfg["homes"]["profiles"]:
        if home["archetype"] not in archetypes:
            raise ConfigError(f"Archetype '{home['archetype']}' not in load_archetypes.yaml")
    cfg["homes"]["archetypes"] = archetypes

    n_homes = len(cfg["homes"]["profiles"])
    shares = cfg["allocation"]["export_shares"]
    if len(shares) != n_homes or abs(sum(shares) - 1.0) > 1e-9:
        raise ConfigError(f"allocation.export_shares must have {n_homes} values summing to 1")
    return cfg


def save_snapshot(cfg: dict, path: Path) -> None:
    """Write the exact configuration used for a run (for reproducibility)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)


def project_path(relative: str) -> Path:
    return PROJECT_ROOT / relative
