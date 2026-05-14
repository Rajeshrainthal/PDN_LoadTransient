# PDN Load Transient Test — Automated

> Automated load transient test for a satellite payload **Power Distribution Network (PDN)**.
> Built for the **Digantara Junior Hardware Test Engineer** assessment.

Drives a Keithley 2230 supply, a Keithley 2380 electronic load, a Keysight DSOX6004A oscilloscope, and a Keithley DMM6500 over **SCPI / PyVISA** — capturing waveforms, logging results to CSV, computing statistics, and generating a per-board PDF report.

---

## Table of Contents

- [What It Does](#what-it-does)
- [Repo Layout](#repo-layout)
- [Running](#running)
- [Outputs](#outputs)
- [Safety](#safety)

---

## What It Does

1. Reads `config/test_config.yaml` — rails, load step, slew, repeats, and pass criteria.
2. Initialises all four instruments and sanity-checks each with `*IDN?`.
3. For **every rail**, for **every repeat**:
   - Sets the supply to **+5 V** at a safe current limit.
   - Programs the e-load to step between `i_low` and `i_high` at the configured slew.
   - Arms the scope on the e-load trigger output, captures the transient window, and saves the raw waveform as `.npz` with a UTC timestamp.
   - Computes **undershoot**, **overshoot**, **settling time** (within ±2 % of nominal), and **steady-state DC**.
   - Applies pass criteria and logs a row to the CSV.
4. After all rails are done, computes **mean / std / min / max** per rail and writes a one-page PDF report with annotated transient plots.

---

## Repo Layout

```
pdn_loadtransient/
├── README.md
├── requirements.txt
├── run_test.py                  # Entry point
├── config/
│   └── test_config.yaml         # Rails, limits, pass criteria
├── instrument_drivers/
│   ├── __init__.py
│   ├── base.py                  # Thin PyVISA wrapper + mock backend
│   ├── power_supply.py          # Keithley 2230
│   ├── electronic_load.py       # Keithley 2380
│   ├── oscilloscope.py          # Keysight DSOX6004A
│   └── dmm.py                   # Keithley DMM6500
├── test_sequencer.py            # Orchestrates the test
├── measurements.py              # Waveform math (undershoot, settling, etc.)
├── reporter.py                  # CSV + PDF report
├── waveforms/                   # Per-run captures (.npz)
└── reports/                     # Per-run CSV + PDF
```

---

## Running

Install dependencies:

```bash
pip install -r requirements.txt
```

Run against real hardware:

```bash
python run_test.py --serial SN017 --config config/test_config.yaml
```

Dry-run with the **mock backend** (no instruments required):

```bash
python run_test.py --serial SN999 --mock
```

---

## Outputs

All outputs land under `reports/<serial>_<timestamp>/`:

| File | Description |
|---|---|
| `results.csv` | One row per (rail, repeat) — all measurements + pass/fail |
| `summary.csv` | One row per rail — mean / std / min / max |
| `report.pdf` | Title page, summary table, annotated plot per rail |
| `waveforms/*.npz` | Raw scope captures — full audit trail |

---

## Safety

- Supply **current limit is set before the output is enabled**.
- E-load is **disarmed between rails**.
- A `KeyboardInterrupt` cleanly disables all outputs via a `finally` block.
- The **mock backend** lets you dry-run the full sequence with zero hardware risk.
