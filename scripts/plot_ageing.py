"""Plot both ageing models under lab-test-like conditions, to compare by eye with the papers' figures.

    uv run scripts/plot_ageing.py
Saves thesis/figures/ageing_model_check.png. Compare the curves with the measured points in
Schmalstieg et al. (2014) and Naumann et al. (2018, 2020); they should have the same shape and
roughly the same size. Conditions here are chosen to resemble the papers' test matrices; check
each paper for the exact conditions of the figure you compare against.
"""
import argparse

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

import _path  # noqa: F401,E402
from sbess.config import load_config, project_path  # noqa: E402
from sbess.degradation import Cycles, continue_loss, make_ageing_model  # noqa: E402


def calendar_curve(model, soc, temp_c, days):
    """Loss (%) after each number of days of storage at constant SOC and temperature."""
    stress = float(model.calendar_stress(np.array([soc]), np.array([temp_c]))[0])
    unit = float(model.calendar_dx(1, 24.0)[0])               # model time units per day
    return [100 * continue_loss(0.0, np.array([stress]), np.array([d * unit]), model.z_cal) for d in days]


def cycle_curve(model, depth, fec, c_rate=1.0, mean_soc=0.5):
    """Loss (%) after each number of full equivalent cycles at one depth."""
    one = Cycles(depth=np.array([depth]), mean_soc=np.array([mean_soc]), count=np.array([1.0]),
                 c_rate=np.array([c_rate]))
    stress, per_fec = model.cycle_stress(one), model.cycle_dx(one) / depth
    return [100 * continue_loss(0.0, stress, per_fec * f, model.z_cyc) for f in fec]


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    nmc = make_ageing_model(load_config(None, ["battery.model=powerwall2"]))
    lfp = make_ageing_model(load_config(None, ["battery.model=powerwall3"]))
    fig, ax = plt.subplots(2, 2, figsize=(11, 8), constrained_layout=True)

    days = np.linspace(0, 500, 101)
    for t in (35, 40, 50):
        for soc, ls in ((0.5, "-"), (1.0, "--")):
            ax[0, 0].plot(days, calendar_curve(nmc, soc, t, days), ls, label=f"{t} °C, SOC {soc:.0%}")
    ax[0, 0].set(title="NMC calendar (Schmalstieg 2014)", xlabel="storage time (days)")

    fec = np.linspace(0, 1500, 101)
    for dod in (0.1, 0.2, 0.5, 0.8, 1.0):
        ax[0, 1].plot(fec, cycle_curve(nmc, dod, fec), label=f"DOD {dod:.0%}")
    ax[0, 1].set(title="NMC cycle (Schmalstieg 2014), mean SOC 50 %", xlabel="full equivalent cycles")

    days = np.linspace(0, 29 * 30.4, 101)
    for t in (25, 40, 60):
        for soc, ls in ((0.5, "-"), (1.0, "--")):
            ax[1, 0].plot(days, calendar_curve(lfp, soc, t, days), ls, label=f"{t} °C, SOC {soc:.0%}")
    ax[1, 0].set(title="LFP calendar (Naumann 2018)", xlabel="storage time (days)")

    fec = np.linspace(0, 4000, 101)
    for dod in (0.2, 0.5, 0.8, 1.0):
        ax[1, 1].plot(fec, cycle_curve(lfp, dod, fec, c_rate=1.0), label=f"DOD {dod:.0%}, 1C")
    ax[1, 1].plot(fec, cycle_curve(lfp, 1.0, fec, c_rate=0.2), ":", label="DOD 100%, 0.2C")
    ax[1, 1].set(title="LFP cycle (Naumann 2020), 25 °C", xlabel="full equivalent cycles")

    for a in ax.ravel():
        a.set_ylabel("capacity loss (%)")
        a.grid(alpha=0.3)
        a.legend(fontsize=8)
    out = project_path("thesis/figures") / "ageing_model_check.png"
    fig.savefig(out, dpi=150)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
