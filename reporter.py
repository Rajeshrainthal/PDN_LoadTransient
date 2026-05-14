"""CSV + PDF report generation."""

from __future__ import annotations
import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages

from measurements import summarize, TransientResult

log = logging.getLogger(__name__)

CSV_FIELDS = [
    "timestamp_utc", "serial", "rail", "repeat", "v_nom",
    "v_baseline_V", "v_min_V", "v_max_V",
    "undershoot_mV", "overshoot_mV",
    "settling_time_us", "settled",
    "deviation_pct", "pass", "fail_reasons", "waveform_file",
]


def write_results_csv(captures, run_dir: Path, serial: str) -> Path:
    out = run_dir / "results.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for c in captures:
            row = c.result.as_row()
            row.update({
                "timestamp_utc": c.timestamp_utc,
                "serial": serial,
                "repeat": c.repeat_idx,
                "waveform_file": c.waveform_path.name,
            })
            w.writerow({k: row.get(k, "") for k in CSV_FIELDS})
    log.info("Wrote %s", out)
    return out


def write_summary_csv(captures, run_dir: Path) -> Path:
    out = run_dir / "summary.csv"
    summary = summarize([c.result for c in captures])
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "rail", "n", "passed", "failed", "yield_pct",
            "undershoot_mean_mV", "undershoot_std_mV", "undershoot_min_mV", "undershoot_max_mV",
            "overshoot_mean_mV", "overshoot_std_mV", "overshoot_min_mV", "overshoot_max_mV",
            "settling_mean_us", "settling_std_us", "settling_min_us", "settling_max_us",
        ])
        for rail, s in summary.items():
            w.writerow([
                rail, s["n"], s["passed"], s["failed"], s["yield_pct"],
                round(s["undershoot_mV"]["mean"], 3), round(s["undershoot_mV"]["std"], 3),
                round(s["undershoot_mV"]["min"], 3), round(s["undershoot_mV"]["max"], 3),
                round(s["overshoot_mV"]["mean"], 3), round(s["overshoot_mV"]["std"], 3),
                round(s["overshoot_mV"]["min"], 3), round(s["overshoot_mV"]["max"], 3),
                round(s["settling_us"]["mean"], 3), round(s["settling_us"]["std"], 3),
                round(s["settling_us"]["min"], 3), round(s["settling_us"]["max"], 3),
            ])
    log.info("Wrote %s", out)
    return out


def write_pdf_report(captures, run_dir: Path, serial: str, config: dict) -> Path:
    out = run_dir / "report.pdf"
    summary = summarize([c.result for c in captures])
    overall_pass = all(c.result.passed for c in captures)

    with PdfPages(out) as pdf:
        # --- Title page ---
        fig, ax = plt.subplots(figsize=(8.27, 11.69))  # A4
        ax.axis("off")
        ax.text(0.5, 0.92, "PDN Load Transient Test Report",
                ha="center", fontsize=18, weight="bold")
        ax.text(0.5, 0.87, f"Board Serial: {serial}", ha="center", fontsize=12)
        ax.text(0.5, 0.84, f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
                ha="center", fontsize=10)
        verdict = "OVERALL: PASS" if overall_pass else "OVERALL: FAIL"
        ax.text(0.5, 0.78, verdict, ha="center", fontsize=14, weight="bold")

        # Summary table
        y = 0.70
        ax.text(0.05, y, "Summary by rail", fontsize=12, weight="bold"); y -= 0.03
        header = f"{'Rail':<8}{'N':>5}{'Pass':>7}{'Fail':>7}{'Yield':>9}{'ΔV mean (mV)':>18}{'t_settle mean (µs)':>22}"
        ax.text(0.05, y, header, fontsize=9, family="monospace"); y -= 0.025
        for rail, s in summary.items():
            dv_mean = max(abs(s["undershoot_mV"]["mean"]), abs(s["overshoot_mV"]["mean"]))
            row = f"{rail:<8}{s['n']:>5}{s['passed']:>7}{s['failed']:>7}{s['yield_pct']:>8.1f}%{dv_mean:>18.2f}{s['settling_us']['mean']:>22.2f}"
            ax.text(0.05, y, row, fontsize=9, family="monospace"); y -= 0.022

        y -= 0.02
        ax.text(0.05, y, "Acceptance criteria", fontsize=12, weight="bold"); y -= 0.03
        acc = config["acceptance"]
        ax.text(0.05, y, f"  |ΔV| < {acc['max_deviation_pct']*100:.0f}% of V_nom    Settling < {acc['max_settling_us']:.0f} µs    Band ±{acc['settling_band_pct']*100:.0f}%",
                fontsize=10); y -= 0.025
        ax.text(0.05, y, f"  Repeats per rail: {config['transient']['repeats_per_rail']}    Slew: {config['transient']['slew_a_per_us']} A/µs",
                fontsize=10)

        pdf.savefig(fig); plt.close(fig)

        # --- One annotated transient plot per rail (best + worst capture) ---
        by_rail: dict[str, list] = {}
        for c in captures:
            by_rail.setdefault(c.result.rail, []).append(c)

        for rail, caps in by_rail.items():
            worst = max(caps, key=lambda c: c.result.deviation_pct)
            best = min(caps, key=lambda c: c.result.deviation_pct)
            fig, ax = plt.subplots(figsize=(8.27, 5.5))
            for cap, label, alpha in [(best, "Best", 0.9), (worst, "Worst", 0.9)]:
                data = np.load(cap.waveform_path)
                ax.plot(data["t"] * 1e6, data["v"], label=f"{label}: ΔV={cap.result.deviation_pct:.2f}%, t_settle={cap.result.settling_time_s*1e6:.1f} µs", alpha=alpha)
            v_nom = caps[0].result.v_nom
            band = config["acceptance"]["settling_band_pct"]
            ax.axhline(v_nom, linestyle="--", linewidth=0.8, color="black", alpha=0.5)
            ax.axhline(v_nom * (1 + band), linestyle=":", linewidth=0.8, color="black", alpha=0.4)
            ax.axhline(v_nom * (1 - band), linestyle=":", linewidth=0.8, color="black", alpha=0.4)
            ax.set_title(f"{rail} — load transient (best vs worst of {len(caps)} captures)")
            ax.set_xlabel("Time (µs)")
            ax.set_ylabel("Voltage (V)")
            ax.legend(loc="lower right", fontsize=8)
            ax.grid(True, linestyle=":", alpha=0.5)
            pdf.savefig(fig); plt.close(fig)

    log.info("Wrote %s", out)
    return out


def write_all(captures, run_dir: Path, serial: str, config: dict):
    results_csv = write_results_csv(captures, run_dir, serial)
    summary_csv = write_summary_csv(captures, run_dir)
    report_pdf = write_pdf_report(captures, run_dir, serial, config)
    return results_csv, summary_csv, report_pdf
