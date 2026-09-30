# Shared PV + battery for four Dubai homes — simulation

MSc dissertation code. Four villas share one PV array and one battery; different
control "brains" are compared on cost, battery life and fairness.

## Folders

| Folder | Contents |
|---|---|
| `config/` | `default.yaml` (all settings), `params/` (datasheets, tariffs, household shapes), `scenarios/` (variations) |
| `src/sbess/` | the model: PV, homes, battery, simulator, billing, brains |
| `scripts/` | download data, prepare data, validate PV, export HOMER inputs |
| `tests/` | automatic checks (`pytest`) |
| `data/raw`, `data/processed` | downloaded and cleaned data (created by the scripts) |
| `results/` | one folder per run, including the exact config used |
| `thesis/` | writing and figures |
| `DECISIONS.md` | every modelling choice and its source → methodology chapter |
| `pyproject.toml`, `uv.lock` | package list and the exact locked versions (commit both) |
| `.python-version` | Python version uv uses for this project (3.13) |

## Setup (once)

The project uses [uv](https://docs.astral.sh/uv/) to manage Python, the virtual environment
and packages. `uv.lock` pins every package version, so every machine gets an identical setup.

1. **Install uv** (skip if `uv --version` already works):

   ```bash
   # Windows (PowerShell)
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   # macOS / Linux
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

   Open a new terminal afterwards so `uv` is on the PATH.

2. **Create the environment and install packages** from the project folder:

   ```bash
   uv sync
   ```

   This downloads Python 3.13 if it isn't installed, creates `.venv/`, and installs the
   Weeks 1–3 packages, `pytest`, and this project (`sbess`) in editable mode.

3. **Check that everything works:**

   ```bash
   uv run pytest                   # should report all tests passed
   ```

4. **Activate the virtual environment (optional).** Once activated, `python` and `pytest` in
   that terminal use the project's `.venv`, so you can type `python run.py` instead of
   `uv run run.py`. Run the line for your terminal from the project folder:

   | Terminal | Activate |
   |---|---|
   | Windows PowerShell (VS Code default) | `.venv\Scripts\Activate.ps1` |
   | Windows Command Prompt (cmd) | `.venv\Scripts\activate.bat` |
   | Git Bash on Windows | `source .venv/Scripts/activate` |
   | macOS / Linux | `source .venv/bin/activate` |

   The prompt then starts with `(sbess)`. To check, run `python -c "import sbess"`, which
   should print nothing. Activation only lasts for that terminal, so repeat it in every new
   one. Type `deactivate` to leave.

   If PowerShell says *"running scripts is disabled on this system"*, allow local scripts
   once, then activate again:

   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
   ```

   VS Code can activate it for you: press Ctrl+Shift+P → "Python: Select Interpreter" → choose
   `.venv\Scripts\python.exe`. Every new VS Code terminal then activates the environment
   automatically.

Later weeks need extra packages, kept in optional groups so the first install stays small:

```bash
uv sync --group forecast        # Weeks 4–5: scikit-learn, xgboost, torch
uv sync --group mpc             # Weeks 6–7: cvxpy, highspy
uv sync --all-groups            # everything
```

Note: a plain `uv sync` removes any group you didn't ask for, so repeat the flags (or use
`--all-groups`) once you need them.

**Running commands.** Put `uv run` in front of any command. It uses the project's `.venv`
and syncs it first if `pyproject.toml` changed, so you never need to activate anything. In an
activated terminal (step 4) you can drop the `uv run` prefix, but run `uv sync` yourself
after changing packages.

**Adding or removing a package:** `uv add <package>` (or `uv add --group forecast <package>`),
`uv remove <package>`. Both update `pyproject.toml` and `uv.lock`. Don't edit versions by hand.

## Weeks 1–2 workflow

```bash
uv run scripts/download_data.py       # NASA POWER, PVGIS, Open-Meteo -> data/raw
uv run scripts/prepare_data.py        # clean hourly files + timestamp check -> data/processed
uv run scripts/validate_pv.py         # pvlib vs PVGIS, monthly and annual
uv run run.py                         # grid-only, PV-only and Brain A for the default setup
uv run scripts/export_homer.py        # 8760-hour files for the HOMER Pro cross-check
```

No internet? `uv run run.py --scenario synthetic_test` runs everything on synthetic weather
(pipeline test only — never use those numbers in the thesis).

## Changing settings

```bash
uv run run.py --scenario pw3_lfp                                  # use a scenario file
uv run run.py --set battery.units=2                               # one-off change
uv run run.py --set tariff.name=tou_hypothetical --set tariff.export_mode=no_credit
uv run run.py --set "battery.spec_override={round_trip_efficiency: 0.88}"
```

Misspelt keys are rejected with an error. Each run folder contains `config_used.yaml`,
`summary.json`, hourly `timeseries_<case>.csv` and monthly `bills_<case>.csv`.
