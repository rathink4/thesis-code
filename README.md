# Shared PV + battery for four Dubai homes — simulation

MSc dissertation code. Four villas share one PV array and one battery; different
control "brains" are compared on cost, battery life and fairness.

This page walks you through the first-time setup and the first simulation run, one step at a
time. Do the steps in order. Commands are shown for **Windows** (PowerShell, the default
terminal in VS Code), with the macOS / Linux version where it differs.

## Before you start

You need an internet connection and a terminal opened **in the project folder**
(`thesis-code`):

- **In VS Code:** open the `thesis-code` folder (File → Open Folder), then choose
  Terminal → New Terminal. The terminal opens in the project folder.
- **Anywhere else:** open PowerShell and go to the folder, for example
  `cd C:\Users\<you>\Documents\thesis-code`.

Type each command below into that terminal and press Enter.

## Step 1 — Install uv

[uv](https://docs.astral.sh/uv/) is the tool that installs Python and all the packages this
project needs. First check whether you already have it:

```powershell
uv --version
```

If it prints a version number (e.g. `uv 0.10.11`), go to Step 2. If it says *"uv is not
recognized"*, install it:

```powershell
# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then **close VS Code (or the terminal) completely and open it again**, so the terminal can
find `uv`. Run `uv --version` again to confirm.

## Step 2 — Install the project's packages

```powershell
uv sync
```

This does everything in one go: downloads the right Python version if you don't have it,
creates a private environment for this project in a folder called `.venv`, and installs every
package into it. The first time it takes a minute or two. It ends with a list of installed
packages, e.g. `+ pandas==...`, `+ pvlib==...`.

You only need to run it again if the package list changes (for example after pulling someone
else's changes).

## Step 3 — Activate the virtual environment

Activating tells this terminal to use the project's Python from `.venv`. Run the line for your
terminal:

| Terminal | Command |
|---|---|
| Windows PowerShell (VS Code default) | `.venv\Scripts\Activate.ps1` |
| Windows Command Prompt (cmd) | `.venv\Scripts\activate.bat` |
| Git Bash on Windows | `source .venv/Scripts/activate` |
| macOS / Linux | `source .venv/bin/activate` |

It worked if the prompt now starts with **`(sbess)`**, like this:

```text
(sbess) PS C:\Users\<you>\Documents\thesis-code>
```

Activation only lasts for that terminal window. **Every time you open a new terminal, activate
again** before running anything. To stop, type `deactivate`.

If PowerShell says *"running scripts is disabled on this system"*, run this once, then try
activating again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Tip for VS Code: press Ctrl+Shift+P, type **Python: Select Interpreter**, and choose
`.venv\Scripts\python.exe`. After that, every new VS Code terminal activates automatically.

## Step 4 — Check that the installation works

```powershell
pytest
```

This runs the automatic checks. The last line should say something like
**`47 passed`**. If anything says `failed`, stop here and fix it before going on.

## Step 5 — Download the data

```powershell
python scripts/download_data.py
```

Downloads a year of Dubai weather (NASA POWER), a reference solar output (PVGIS) and archived
weather forecasts (Open-Meteo) into `data/raw/`. It takes under a minute. Each source prints
`saved: <file name>`. Running it again skips files you already have.

## Step 6 — Prepare the data

```powershell
python scripts/prepare_data.py
```

Cleans the downloads into hourly tables in `data/processed/`. Check this line in the output:

```text
solar-noon check: GHI centre is +0.01 h from solar noon -> OK
```

It must end in **`OK`**. That confirms the weather timestamps line up with the sun. It is
normal to see `forecast_previous_runs_2023.csv (0 complete hours)`, because that forecast
archive only starts in 2024.

## Step 7 — Check the solar model

```powershell
python scripts/validate_pv.py
```

Compares this project's solar-panel model with PVGIS, an independent EU tool, month by month.
The last lines look like:

```text
Annual: pvlib 51,236 kWh (1,601 kWh/kWp) | PVGIS 55,602 kWh (1,738 kWh/kWp) | diff -7.9 %
saved ...\results\pv_validation_2023.csv
```

An annual difference within about ±10 % is fine.

## Step 8 — Run the simulation

```powershell
python run.py
```

Simulates one year for three cases, prints each case's total yearly electricity bill for the
four homes, then works out how fast the battery wears out:

- `grid_only`: no solar, no battery (the reference)
- `pv_only`: shared solar panels, no battery
- `brain_A`: solar panels plus battery, run by the simple rule-based controller

Expected output (your numbers should be close):

```text
   grid_only    bill       44,469 AED
   pv_only      bill       26,949 AED
   brain_A      bill       27,152 AED
[4/5] battery ageing (Schmalstieg et al. 2014 (NMC), outdoor_garage, extrapolate)
   brain_A      year-1 capacity loss 13.56 % (calendar 2.17, cycle 11.39), mean battery temp 31.3 C, years to 80 % health: 2.0
```

The ageing line says how much battery capacity is lost in the first year, split into
*calendar* ageing (from time, heat and charge level) and *cycle* ageing (from use), and how
many years until the battery is down to 80 % of its capacity.

To compare battery types, placements and lifetime methods, run each of these and compare the
`brain_A` ageing line:

| Command | What changes | Expected ageing line (approx.) |
|---|---|---|
| `python run.py` | Powerwall 2 (NMC) in the garage | 13.6 % loss, 2.0 years |
| `python run.py --scenario indoor` | battery indoors (cooler) | 12.7 % loss, 2.4 years |
| `python run.py --scenario pw3_lfp` | Powerwall 3 (LFP) in the garage | 4.8 % loss, 17.4 years |
| `python run.py --scenario pw3_lfp --set battery.placement=indoor` | Powerwall 3 indoors | 4.4 % loss, 20.4 years |
| `python run.py --scenario pw3_lfp --set degradation.lifetime_method=multi_year` | re-simulates every year with the aged battery (slower) | 4.8 % loss, 16.6 years |

Cooler placement and LFP chemistry should both give a longer life. The very short NMC life is
a known issue with the lab-cell model, not a bug (see DECISIONS.md, D-013a).

The results are saved in a new folder `results/<date-time>_default/`:

| File | What it contains |
|---|---|
| `summary.json` | yearly totals for each case: bills per home, energy, savings |
| `bills_<case>.csv` | monthly bill for each home |
| `timeseries_<case>.csv` | hour-by-hour energy flows (8,760 rows); battery cases also have battery temperature |
| `lifetime_<case>.csv` | battery health at the end of each year until it reaches 80 % |
| `home_loads_kw.csv` | hourly electricity demand of each home |
| `config_used.yaml` | the exact settings used, so the run can be repeated |

## Step 9 — Check the battery ageing models

```powershell
python scripts/plot_ageing.py
```

Draws both ageing models under lab-test conditions and saves
`thesis/figures/ageing_model_check.png`. Open the image and check the curves behave as
expected: hotter, fuller (higher SOC) and deeper-cycled batteries lose capacity faster. Then
compare them with the measured results in the Schmalstieg (2014) and Naumann (2018, 2020)
papers.

## Step 10 — Export files for HOMER Pro

```powershell
python scripts/export_homer.py
```

Writes four one-value-per-hour files (load, sunlight, temperature, solar output) to
`results/homer_inputs/`. These are loaded into HOMER Pro to cross-check the simulation.
Skip this step if you are not doing the HOMER comparison.

## Next time you open the project

Setup is done. Each new session you only need to:

1. Open a terminal in the project folder.
2. Activate the environment (Step 3), and check for `(sbess)` at the start of the prompt.
3. Run what you need, e.g. `python run.py`.

## If something goes wrong

| Message | Fix |
|---|---|
| `uv is not recognized` | Close and reopen VS Code / the terminal after installing uv (Step 1). |
| `running scripts is disabled on this system` | Run the `Set-ExecutionPolicy` command in Step 3. |
| `ModuleNotFoundError: No module named ...` | The environment isn't active: look for `(sbess)` and redo Step 3. If it is active, run `uv sync`. |
| `weather_2023.csv not found` | Run Steps 5 and 6 first. |
| No internet connection | `python run.py --scenario synthetic_test` runs on made-up weather to test that the code works. **Never use those numbers in the thesis.** |
