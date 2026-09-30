"""Export 8760-hour files for the HOMER Pro cross-check of Brain A.

    uv run scripts/export_homer.py [--scenario ...] [--set ...]
Writes to results/homer_inputs/: community load (kW), GHI (kW/m2), temperature (C),
and our own PV output (kW) — one value per line, no header, as HOMER expects.
"""
import argparse

import _path  # noqa: F401
from sbess.config import load_config, project_path
from sbess.data.weather import load_weather
from sbess.load_model import build_loads
from sbess.pv_model import pv_ac_kw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default=None)
    ap.add_argument("--set", dest="overrides", action="append", default=[])
    a = ap.parse_args()
    cfg = load_config(a.scenario, a.overrides)
    w = load_weather(cfg)
    out = project_path("results") / "homer_inputs"
    out.mkdir(parents=True, exist_ok=True)
    series = {
        "community_load_kw.txt": build_loads(w, cfg).sum(axis=1),
        "ghi_kw_per_m2.txt": w["ghi"] / 1000.0,
        "temperature_c.txt": w["temp_air"],
        "pv_output_kw.txt": pv_ac_kw(w, cfg),
    }
    for fname, s in series.items():
        s = s.iloc[:8760]                     # HOMER wants exactly 8760 values
        (out / fname).write_text("\n".join(f"{v:.4f}" for v in s.to_numpy()), encoding="utf-8")
        print(f"  {fname}: {len(s)} values")
    print(f"saved to {out}")


if __name__ == "__main__":
    main()
