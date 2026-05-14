# PDN Load Transient Test — Automated

Automated load transient test for a satellite payload Power Distribution
Network. Drives a Keithley 2230 supply, a Keithley 2380 electronic load,
a Keysight DSOX6004A oscilloscope, and a Keithley DMM6500 over SCPI/PyVISA;
captures waveforms, logs results to CSV, computes statistics, and generates
a per-board PDF report.

Built for the Digantara Junior Hardware Test Engineer assessment.
Author: R. Rajesh

---

## What it does

1. Reads `config/test_config.yaml` (rails, load step, slew, repeats, pass criteria).
2. Initialises all four instruments and sanity-checks each one with `*IDN?`.
3. For every rail, for every repeat:
   - Sets the supply to +5 V at a safe current limit.
   - Programs the e-load to step between `i_low` and `i_high` at the configured slew.
   - Arms the scope on the e-load trigger output, captures the transient
     window, and saves the raw waveform as `.npz` with a UTC timestamp.
   - Computes undershoot, overshoot, settling time (within ±2 % of nominal),
     and steady-state DC.
   - Applies pass criteria and logs a row to the CSV.
4. After all rails are done, computes mean/std/min/max per rail and writes
   a one-page PDF report with annotated transient plots.

## Repo layout

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
├── waveforms/                   # Per-run captures, .npz
└── reports/                     # Per-run CSV + PDF
```

## Running

```bash
pip install -r requirements.txt
python run_test.py --serial SN017 --config config/test_config.yaml
# or, with no instruments connected, use the mock backend for a dry run:
python run_test.py --serial SN999 --mock
```

Outputs land under `reports/<serial>_<timestamp>/`:

- `results.csv` — one row per (rail, repeat) with all measurements + pass/fail
- `summary.csv` — one row per rail with mean / std / min / max
- `report.pdf` — title page, summary table, annotated plot per rail
- `waveforms/*.npz` — raw scope captures, audit trail

## Assumptions (called out inline in the code too)

- Load slew = 1 A/µs unless overridden in YAML.
- Step size = 10 % → 90 % of rated `i_max` per rail.
- Pass criteria: `|ΔV|` < 5 % of `v_nom`, settling < 50 µs.
- Scope: 1 GS/s, 200 µs window, 20 MHz bandwidth limit, AC coupled.
- These are placeholders aligned with the Annexure; confirm with the lead
  engineer before running on flight hardware.

## Safety

- Supply current limit is set BEFORE output is enabled.
- E-load is disarmed between rails.
- A `KeyboardInterrupt` cleanly disables outputs in a `finally` block.
- The mock backend lets you dry-run the full sequence with zero hardware.
