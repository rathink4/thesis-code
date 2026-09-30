# Shared PV + battery for four Dubai homes — simulation

MSc dissertation code. Four villas share one PV array and one battery; different
control "brains" are compared on cost, battery life and fairness.

## How to use this page

The page has two parts:

1. **[Setup](#setup-do-once)**: install everything. Do this once per computer.
2. **Week-by-week guides**: one section per stage of the project, in the order it was built.
   Each section says **what's new**, **what changed for you**, the **steps to run**, and
   **what you should see**. Work through them in order; each week builds on the one before.

| Section | What it adds |
|---|---|
| [Weeks 1–2](#weeks-12--data-solar-model-and-the-first-brain) | weather data, solar model, household demand, battery, bills, Brain A |
| [Week 3](#week-3--battery-temperature-and-ageing) | battery temperature, battery ageing, years until the battery wears out |
| [Weeks 4–5](#weeks-45--forecasting-tomorrows-demand-and-solar) | forecasts of the next 24 hours of demand and solar, for the smart brains |

The simulated year is **2025**. The forecasters learn from 2024, and the solar model is
checked on 2023. The reason is explained in [Weeks 4–5](#weeks-45--forecasting-tomorrows-demand-and-solar).

Commands are shown for **Windows** (PowerShell, the default terminal in VS Code), with the
macOS / Linux version where it differs.

---

# Setup (do once)

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
package into it. The first time it takes a few minutes, mostly for the machine-learning
package `torch`. It ends with a list of installed packages, e.g. `+ pandas==...`,
`+ torch==...`.

Run it again whenever the package list changes (for example after pulling someone else's
changes). A week's section will tell you if it needs this.

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

This runs all the automatic checks, which takes about 15 seconds. The last line should say
**`58 passed`** (the number grows as each week adds its own checks). If anything says
`failed`, stop here and fix it before going on.

Setup is done. Continue with Weeks 1–2.

---

# Weeks 1–2 — Data, solar model and the first brain

### What's new

- **Weather data** for Dubai from NASA POWER, plus PVGIS (an independent solar estimate,
  used as a cross-check) and archived weather forecasts (used from Weeks 4–5).
- **Solar model:** hourly output of the shared 32 kWp solar array.
- **Household demand:** made-up but realistic hourly electricity use for four villas, driven
  mostly by air conditioning.
- **Battery model:** three Tesla Powerwall 2 units (40.5 kWh together).
- **Bills:** each home's monthly DEWA bill (slab prices, fuel surcharge, VAT, net metering).
- **Brain A:** the simple rule-based controller: solar first, then battery, then grid.

### Steps

#### 1. Download the data

```powershell
python scripts/download_data.py
```

Downloads everything into `data/raw/`: weather for 2023, 2024 and 2025, the PVGIS estimate for
2023, and archived weather forecasts for 2024 and 2025. It takes about a minute. Each file
prints `saved: <file name>`. Running it again skips files you already have.

#### 2. Prepare the data

```powershell
python scripts/prepare_data.py
```

Cleans the downloads into hourly tables in `data/processed/`. For each year, check this line:

```text
  2025: solar-noon check: GHI centre is +0.02 h from solar noon -> OK
```

Every year must end in **`OK`**. That confirms the weather timestamps line up with the sun.
The forecast lines at the end are explained in Weeks 4–5.

#### 3. Check the solar model

```powershell
python scripts/validate_pv.py
```

Compares this project's solar model with PVGIS for 2023 (PVGIS has no later data), month by
month. The last lines look like:

```text
Annual: pvlib 51,236 kWh (1,601 kWh/kWp) | PVGIS 55,602 kWh (1,738 kWh/kWp) | diff -7.9 %
saved ...\results\pv_validation_2023.csv
```

An annual difference within about ±10 % is fine.

#### 4. Run the simulation

```powershell
python run.py
```

Simulates 2025 for three cases and prints each case's total yearly electricity bill for the
four homes:

- `grid_only`: no solar, no battery (the reference)
- `pv_only`: shared solar panels, no battery
- `brain_A`: solar panels plus battery, run by Brain A

Expected output (your numbers should be close):

```text
   grid_only    bill       44,460 AED
   pv_only      bill       27,058 AED
   brain_A      bill       27,250 AED
```

You will also see a `[4/5] battery ageing` line. That comes from Week 3 and is explained
there.

The results are saved in a new folder `results/<date-time>_default/`:

| File | What it contains |
|---|---|
| `summary.json` | yearly totals for each case: bills per home, energy, savings |
| `bills_<case>.csv` | monthly bill for each home |
| `timeseries_<case>.csv` | hour-by-hour energy flows (8,760 rows) |
| `home_loads_kw.csv` | hourly electricity demand of each home |
| `config_used.yaml` | the exact settings used, so the run can be repeated |

#### 5. Export files for HOMER Pro (optional)

```powershell
python scripts/export_homer.py
```

Writes four one-value-per-hour files (load, sunlight, temperature, solar output) to
`results/homer_inputs/`. These are loaded into HOMER Pro to cross-check the simulation. Skip
this step if you are not doing the HOMER comparison.

### What you should see

- [ ] Step 2 ends in `OK` for every year.
- [ ] Step 3 shows an annual difference within about ±10 %.
- [ ] Step 4: `pv_only` is much cheaper than `grid_only` (about 17,400 AED a year less).
- [ ] Step 4: `brain_A` costs **slightly more** than `pv_only` (about 190 AED). This is
  expected, not a bug. Under Dubai's net-metering rules the grid acts like a free battery,
  so a real battery only adds losses (see `DECISIONS.md`, D-006a).

---

# Week 3 — Battery temperature and ageing

### What's new

- **Battery temperature:** the battery warms up from its own losses and follows the air
  around it. Where the battery sits matters: an **outdoor garage** follows Dubai's outdoor
  heat, while **indoor** stays at 24 °C.
- **Battery ageing:** how much capacity the battery loses each year, using two published
  models:
  - Powerwall 2 (NMC chemistry): Schmalstieg et al. 2014.
  - Powerwall 3 (LFP chemistry): Naumann et al. 2018 and 2020.

  Ageing comes from two sources. **Calendar** ageing happens with time and is worse when the
  battery is hot or kept full. **Cycle** ageing comes from charging and discharging, and
  deeper swings hurt more.
- **Lifetime:** the number of years until the battery is down to 80 % of its original
  capacity (the usual "end of life").

### What changed for you

- **No new install and no new data.** Nothing to download; you don't need to run `uv sync`
  again.
- **`python run.py` prints more.** A new step `[4/5] battery ageing` appears, with one line
  per battery case.
- **New result files:** each run folder now also has `lifetime_<case>.csv`, and
  `timeseries_<case>.csv` has two new columns.
- **New settings** in `config/default.yaml`: the `battery.thermal` section (temperature
  model) and the `degradation` section (end of life at 80 %, lifetime method). The model
  numbers from the papers are in `config/params/degradation.yaml`.
- **24 new automatic checks** (in `tests/test_degradation.py` and `tests/test_config.py`).
- **New script:** `scripts/plot_ageing.py`, which draws the ageing models.

### Steps

Activate the environment first (Setup, Step 3). You need the Weeks 1–2 data in place.

#### 1. Run the new checks

```powershell
pytest tests/test_degradation.py
```

Expect **`23 passed`**. These confirm, among other things, that the code gives exactly the
papers' formulas, that 45 °C ages a battery faster than 25 °C, and that deep cycles hurt more
than shallow ones.

#### 2. Run the simulation and read the ageing line

```powershell
python run.py
```

After the bills you now see:

```text
[4/5] battery ageing (Schmalstieg et al. 2014 (NMC), outdoor_garage, extrapolate)
   brain_A      year-1 capacity loss 12.98 % (calendar 2.12, cycle 10.85), mean battery temp 31.2 C, years to 80 % health: 2.2
```

How to read it:

| Part | Meaning |
|---|---|
| `Schmalstieg et al. 2014 (NMC), outdoor_garage, extrapolate` | which ageing model, where the battery sits, and how the lifetime was worked out |
| `year-1 capacity loss 12.98 %` | capacity lost in the first year |
| `calendar 2.12, cycle 10.85` | how much of that came from time and heat vs from use |
| `mean battery temp 31.2 C` | average battery temperature over the year |
| `years to 80 % health: 2.2` | estimated battery life |

The bills printed above it are unchanged from Weeks 1–2. Ageing is worked out *after* the
simulation, so it does not change the bills.

#### 3. Compare battery types and placements

Run each command and compare the `brain_A` ageing line with the expected values:

| Command | What changes | Expected (approx.) |
|---|---|---|
| `python run.py` | Powerwall 2 (NMC) in the garage | 13.0 % loss, 2.2 years |
| `python run.py --scenario indoor` | battery indoors (cooler) | 12.1 % loss, 2.6 years |
| `python run.py --scenario pw3_lfp` | Powerwall 3 (LFP) in the garage | 4.7 % loss, 18.5 years |
| `python run.py --scenario pw3_lfp --set battery.placement=indoor` | Powerwall 3 indoors | 4.3 % loss, 21.7 years |
| `python run.py --scenario pw3_lfp --set degradation.lifetime_method=multi_year` | re-simulates every year with the aged battery (a few seconds slower) | 4.7 % loss, 17.5 years |

About the lifetime methods: the default, `extrapolate`, repeats year 1's battery use every
year. `multi_year` re-runs the simulation each year with the smaller, aged battery, which is
more realistic.

#### 4. Look at the new result files

Open the newest folder in `results/`:

- **`lifetime_brain_A.csv`:** one row per year until the battery reaches 80 %. Columns:
  health at the start and end of the year (`soh_start`, `soh_end`, where 1.0 = new), total
  calendar and cycle loss so far in %, cycles per year (`fec`), and mean and maximum battery
  temperature.
- **`timeseries_brain_A.csv`:** two new columns at the end. `batt_ambient_c` is the air
  temperature around the battery; `batt_temp_c` is the battery's own temperature.

#### 5. Check the ageing models against the papers

```powershell
python scripts/plot_ageing.py
```

Saves `thesis/figures/ageing_model_check.png` with four charts: calendar and cycle ageing for
each chemistry, under lab-test-like conditions. Open it and check that hotter, fuller (higher
SOC) and deeper-cycled batteries lose capacity faster. Then compare the curves with the
measured results in the Schmalstieg (2014) and Naumann (2018, 2020) papers; they should have a
similar shape and size.

### What you should see

- [ ] `pytest tests/test_degradation.py` reports `23 passed`.
- [ ] `python run.py` shows the ageing line with about 13.0 % loss and 2.2 years.
- [ ] Indoor lasts longer than the garage, for both batteries.
- [ ] Powerwall 3 (LFP) lasts much longer than Powerwall 2 (NMC): about 18 vs 2 years.
- [ ] In `lifetime_brain_A.csv`, `soh_end` goes down every year, and the loss per year gets
  smaller over time (ageing slows down as the battery gets older).
- [ ] The maximum battery temperature in the garage is about 46 °C in summer.
- [ ] The figure from step 5 shows the patterns described there.

Two things that may look odd but are expected:

- **The 2-year Powerwall 2 life is very short.** Tesla warrants 70 % after 10 years. The
  NMC model comes from a 2014 lab cell that lasts only about 600 full cycles, so it is much
  harsher than a real Powerwall. This is an open decision in `DECISIONS.md` (D-013a), not a
  bug.
- **Cycle counts differ slightly.** `fec` in `lifetime_brain_A.csv` (about 156) is a little
  higher than `equivalent_full_cycles` in `summary.json` (about 148). The first counts charge
  swings inside the battery, the second counts energy delivered to the homes, which is lower
  because of losses.

---

# Weeks 4–5 — Forecasting tomorrow's demand and solar

### What's new

The smart brains (Weeks 6–7) plan the battery ahead, so they need to know what is coming.
Weeks 4–5 build **forecasts of the next 24 hours** of the four homes' total demand (`load`)
and the solar output (`pv`). A new forecast is made every hour, as a real controller would
do.

- **Three forecasting methods**, compared on the same unseen year:
  - **Persistence:** "tomorrow will be like today", i.e. the same hour yesterday. This is the
    simple baseline that the others must beat.
  - **XGBoost:** a machine-learning model built from many small decision trees.
  - **LSTM:** a neural network that reads the last 48 hours of measurements.
- **Inputs the learned models use:** the real day-ahead weather forecast for each hour
  (sunshine, temperature, cloud, wind, humidity), the solar model run on that weather
  forecast, the time of day and year, weekends, and recent measurements. They never see
  anything measured after the moment the forecast is made; an automatic check tests this.
- **Split by date:** the models learn from **2024** and are tested on **all of 2025**, which
  they have never seen. One week in every five of 2024 is held back to tell the models when to
  stop training.
- **Saved forecasts** for every hour of 2025, ready for the brains to read.

### What changed for you

- **The simulated year is now 2025 instead of 2023.** Real day-ahead weather forecasts only
  exist from January 2024, so the forecasters learn from 2024 and the simulation runs on 2025
  (`DECISIONS.md`, D-007). All the numbers in the Weeks 1–3 sections above have been updated
  to 2025; they are slightly different from before.
- **New packages** (XGBoost, PyTorch, scikit-learn): run `uv sync` once (step 1 below).
- **More data:** the download and prepare scripts now fetch 2024 and 2025 as well, so run
  them again (step 2 below).
- **New settings:** the `forecast` section in `config/default.yaml`.
- **11 new automatic checks** (`tests/test_forecast.py`), 58 in total.
- **New script:** `scripts/train_forecasts.py`.

### Steps

#### 1. Install the new packages

```powershell
uv sync
```

This adds XGBoost, PyTorch and scikit-learn. PyTorch is large, so it takes a few minutes the
first time. If your terminal was already activated, it stays activated.

#### 2. Download and prepare the extra years

```powershell
python scripts/download_data.py
python scripts/prepare_data.py
```

Files you already have are skipped, so only the new years are downloaded. At the end of the
prepare step, check the weather-forecast lines:

```text
  saved forecast_previous_runs_2024.csv: 8336 of 8784 hours complete (from 2024-01-19), solar-noon check -0.02 h
  saved forecast_historical_forecast_2024.csv: 8784 of 8784 hours complete (from 2024-01-01), solar-noon check +0.00 h
  saved forecast_previous_runs_2025.csv: 8760 of 8760 hours complete (from 2025-01-01), solar-noon check -0.01 h
  saved forecast_historical_forecast_2025.csv: 8760 of 8760 hours complete (from 2025-01-01), solar-noon check +0.01 h
```

- `previous_runs` are the **real day-ahead forecasts** (made 24 hours in advance). These are
  the ones the project uses. For 2024 they start on 19 January, so the first weeks of 2024 are
  simply not used for training.
- `historical_forecast` is a near-perfect version, kept only for comparison.
- **2025 must be complete (8760 of 8760)**, because the brains need a forecast for every hour.
- The solar-noon checks should all be close to 0 h.

#### 3. Run the new checks

```powershell
pytest tests/test_forecast.py
```

Expect **`11 passed`** (about 10 seconds). These check that no forecast uses measurements from
the future, that training and test data never overlap, that forecasts stay physically
possible (no negative values, no solar at night), and that the learned models beat
persistence.

#### 4. Train and test the forecasters

```powershell
python scripts/train_forecasts.py
```

This takes about a minute. It first shows how the data was split:

```text
  train       6403 issue times  2024-01-19 .. 2024-12-31
  validation  1450 issue times  2024-01-29 .. 2024-12-15
  test        8760 issue times  2025-01-01 .. 2025-12-31
```

An "issue time" is a moment when a 24-hour forecast is made (every hour). Then it trains each
model and ends with a score table for 2025:

```text
                    mae_kw  rmse_kw  nmae_pct  skill_vs_persistence_pct  mae_daytime_kw
target model
load   persistence    1.63     2.33     10.49                      0.00             NaN
       xgboost        1.03     1.38      6.65                     40.56             NaN
       lstm           0.97     1.28      6.26                     45.02             NaN
pv     persistence    0.78     1.93     13.45                      0.00            1.54
       xgboost        0.58     1.33      9.98                     31.05            1.15
       lstm           0.60     1.34     10.32                     30.97            1.19
```

How to read it (lower errors are better):

| Column | Meaning |
|---|---|
| `mae_kw` | average size of the error, in kW |
| `rmse_kw` | like MAE, but big misses count extra |
| `nmae_pct` | the average error as a % of the average value |
| `skill_vs_persistence_pct` | how much smaller the RMSE is than persistence's (0 % = no better, higher = better) |
| `mae_daytime_kw` | solar only: average error during daylight hours (night hours are easy zeros) |

The LSTM can differ a little from run to run on another computer; XGBoost and persistence
should match closely.

#### 5. Look at the figures

Open the new folder `results/<date-time>_default_forecast/`:

- **`forecast_example_week.png`:** one week of 2025 around the day persistence got worst for
  solar, with the actual values in black and each model's forecast made at midnight. Look at
  the cloudy or dusty day: persistence misses it, because yesterday was sunny, while XGBoost
  and LSTM see it coming from the weather forecast.
- **`forecast_error_by_lead.png`:** the average error for each hour ahead (0 to 23). Lower
  lines are better.
- **`forecast_scores.csv`** and **`forecast_error_by_lead.csv`:** the same numbers as tables.

#### 6. Find the saved forecasts

The forecasts for 2025 are in `data/processed/forecasts/previous_runs/`, one file per target
and model (e.g. `load_lstm_2025.csv`, `pv_xgboost_2025.csv`). Each row is one issue time (one
hour of 2025); columns `h0` to `h23` are the forecast for that hour and the 23 hours after it,
in kW. The last 23 rows are partly empty because those hours fall in 2026. The brains in
Weeks 6–7 read these files.

### What you should see

- [ ] The prepare step shows 2025 forecasts `8760 of 8760 hours complete`.
- [ ] `pytest tests/test_forecast.py` reports `11 passed`, and `pytest` reports `58 passed`.
- [ ] XGBoost and LSTM both beat persistence: about 40–45 % better for load and about 30 %
  better for solar.
- [ ] In the example-week figure, the learned models follow the black line more closely than
  persistence, especially on cloudy or dusty days.
- [ ] Forecast files exist in `data/processed/forecasts/previous_runs/`.

Three things that may look odd but are expected:

- **The errors hardly grow with hours ahead** (the lines in `forecast_error_by_lead.png` are
  nearly flat). The weather forecast used for every hour was made about a day earlier, so the
  forecast for hour 23 is about as good as the one for hour 0.
- **The near-perfect weather forecasts would barely help.** Training with
  `historical_forecast` instead improves the scores by only about 2 %. Most of the remaining
  error comes from differences between the weather model and NASA's satellite data, not from
  forecasting ahead (`DECISIONS.md`, D-019).
- **The load forecasts may look better than real life.** The demand being forecast is the
  project's made-up demand, which follows temperature more neatly than real households do
  (`DECISIONS.md`, D-020).

---

# Next time you open the project

Setup is done. Each new session you only need to:

1. Open a terminal in the project folder.
2. Activate the environment (Setup, Step 3), and check for `(sbess)` at the start of the
   prompt.
3. Run what you need, e.g. `python run.py`.

# If something goes wrong

| Message | Fix |
|---|---|
| `uv is not recognized` | Close and reopen VS Code / the terminal after installing uv (Setup, Step 1). |
| `running scripts is disabled on this system` | Run the `Set-ExecutionPolicy` command in Setup, Step 3. |
| `ModuleNotFoundError: No module named ...` (e.g. `xgboost`, `torch`) | The environment isn't active: look for `(sbess)` and redo Setup, Step 3. If it is active, run `uv sync`. |
| `weather_2025.csv not found` or `forecast_previous_runs_2025.csv not found` | Run the download and prepare scripts (Weeks 1–2, steps 1 and 2). |
| `load_xgboost_2025.csv not found` (or another forecast file) | Run `python scripts/train_forecasts.py` (Weeks 4–5, step 4). |
| No internet connection | `python run.py --scenario synthetic_test` and `python scripts/train_forecasts.py --scenario synthetic_test` run on made-up weather to test that the code works. **Never use those numbers in the thesis.** |
