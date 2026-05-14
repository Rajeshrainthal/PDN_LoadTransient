"""Waveform math for the load transient test.

Why this lives in pure NumPy and not on the scope:
- The criteria are auditable. A failure can be re-computed from the saved
  .npz without the scope present.
- Defaults are explicit (settling band, baseline window). No hidden firmware
  knobs.
- We can iterate on the algorithm without re-touching the bench.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import numpy as np


@dataclass
class TransientResult:
    rail: str
    v_nom: float
    v_baseline: float       # Pre-step DC level (V)
    v_min: float            # Lowest point during transient (V)
    v_max: float            # Highest point during transient (V)
    undershoot_v: float     # v_baseline - v_min (positive = droop)
    overshoot_v: float      # v_max - v_baseline (positive = ringback)
    settling_time_s: float  # Time from step to staying within band
    settled: bool           # True if settled before window end
    deviation_pct: float    # max(|under|,|over|) / v_nom * 100
    passed: bool
    fail_reasons: list[str]

    def as_row(self) -> dict:
        return {
            "rail": self.rail,
            "v_nom": self.v_nom,
            "v_baseline_V": round(self.v_baseline, 6),
            "v_min_V": round(self.v_min, 6),
            "v_max_V": round(self.v_max, 6),
            "undershoot_mV": round(self.undershoot_v * 1000, 3),
            "overshoot_mV": round(self.overshoot_v * 1000, 3),
            "settling_time_us": round(self.settling_time_s * 1e6, 3),
            "settled": self.settled,
            "deviation_pct": round(self.deviation_pct, 3),
            "pass": self.passed,
            "fail_reasons": "; ".join(self.fail_reasons) if self.fail_reasons else "",
        }


def analyze_transient(
    t: np.ndarray,
    v: np.ndarray,
    rail_name: str,
    v_nom: float,
    *,
    step_time_s: float = 0.0,
    settling_band_pct: float = 0.02,
    max_deviation_pct: float = 0.05,
    max_settling_us: float = 50.0,
) -> TransientResult:
    """Compute undershoot / overshoot / settling and apply pass criteria.

    Args:
        t: time vector (s), with t=0 at the load step edge.
        v: voltage vector (V), AC-coupled measurements should be offset back
           to DC before calling this — see ``recover_dc()`` below.
        v_nom: nominal rail voltage from config.
        step_time_s: index of the load step in seconds (defaults to 0).
        settling_band_pct: half-width of the settled band, fraction of v_nom.
        max_deviation_pct: pass criterion on |ΔV| / v_nom.
        max_settling_us: pass criterion on settling time.
    """
    # Baseline = mean of the pre-step window (everything before the step).
    pre_mask = t < step_time_s
    if pre_mask.sum() < 10:
        # Not enough pre-step samples; fall back to first 5 %.
        n5 = max(10, len(t) // 20)
        baseline = float(np.mean(v[:n5]))
    else:
        baseline = float(np.mean(v[pre_mask]))

    post_mask = t >= step_time_s
    v_post = v[post_mask]
    t_post = t[post_mask]

    v_min = float(np.min(v_post))
    v_max = float(np.max(v_post))
    undershoot = baseline - v_min   # positive number for a droop
    overshoot = v_max - baseline    # positive number for ringback

    # Settling time: last instant the trace was OUTSIDE the band.
    band = settling_band_pct * v_nom
    outside = np.abs(v_post - baseline) > band
    if not outside.any():
        settling_time = 0.0
        settled = True
    else:
        last_outside_idx = int(np.where(outside)[0][-1])
        settling_time = float(t_post[last_outside_idx] - step_time_s)
        settled = settling_time < (max_settling_us * 1e-6)

    deviation = max(abs(undershoot), abs(overshoot))
    deviation_pct = deviation / v_nom * 100.0

    fail_reasons: list[str] = []
    if deviation_pct > max_deviation_pct * 100.0:
        fail_reasons.append(
            f"|ΔV|={deviation_pct:.2f}% > {max_deviation_pct*100:.1f}%"
        )
    if settling_time > max_settling_us * 1e-6:
        fail_reasons.append(
            f"t_settle={settling_time*1e6:.1f}µs > {max_settling_us:.0f}µs"
        )

    return TransientResult(
        rail=rail_name,
        v_nom=v_nom,
        v_baseline=baseline,
        v_min=v_min,
        v_max=v_max,
        undershoot_v=undershoot,
        overshoot_v=overshoot,
        settling_time_s=settling_time,
        settled=settled,
        deviation_pct=deviation_pct,
        passed=(len(fail_reasons) == 0),
        fail_reasons=fail_reasons,
    )


def recover_dc(v_ac: np.ndarray, v_nom: float) -> np.ndarray:
    """AC-coupled scope captures sit around 0 V; add v_nom back so analysis
    and plots show the real rail voltage."""
    return v_ac + v_nom


def summarize(results: list[TransientResult]) -> dict:
    """Per-rail mean / std / min / max for the headline metrics."""
    by_rail: dict[str, list[TransientResult]] = {}
    for r in results:
        by_rail.setdefault(r.rail, []).append(r)

    out = {}
    for rail, runs in by_rail.items():
        under = np.array([r.undershoot_v * 1000 for r in runs])  # mV
        over = np.array([r.overshoot_v * 1000 for r in runs])
        settle = np.array([r.settling_time_s * 1e6 for r in runs])  # µs
        passed = sum(1 for r in runs if r.passed)
        out[rail] = {
            "n": len(runs),
            "passed": passed,
            "failed": len(runs) - passed,
            "yield_pct": round(passed / len(runs) * 100.0, 2),
            "undershoot_mV": {
                "mean": float(np.mean(under)), "std": float(np.std(under, ddof=1)) if len(under) > 1 else 0.0,
                "min": float(np.min(under)), "max": float(np.max(under)),
            },
            "overshoot_mV": {
                "mean": float(np.mean(over)), "std": float(np.std(over, ddof=1)) if len(over) > 1 else 0.0,
                "min": float(np.min(over)), "max": float(np.max(over)),
            },
            "settling_us": {
                "mean": float(np.mean(settle)), "std": float(np.std(settle, ddof=1)) if len(settle) > 1 else 0.0,
                "min": float(np.min(settle)), "max": float(np.max(settle)),
            },
        }
    return out
