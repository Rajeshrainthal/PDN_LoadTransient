"""Orchestrates the full load transient test sequence.

Reads YAML config, opens instruments, walks every rail and every repeat,
collects results, and hands them to the reporter.
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from instrument_drivers import (
    PowerSupply2230,
    EloadKeithley2380,
    ScopeDSOX6004A,
    DMM6500,
)
from measurements import analyze_transient, recover_dc, TransientResult

log = logging.getLogger(__name__)


@dataclass
class CapturedRun:
    """One capture: the analysis result plus the raw waveform path."""
    result: TransientResult
    repeat_idx: int
    timestamp_utc: str
    waveform_path: Path
    rail_cfg: dict[str, Any]


class TestSequencer:
    def __init__(self, config_path: str | Path, serial: str, *, mock: bool = False, out_root: Path | None = None):
        self.config = yaml.safe_load(Path(config_path).read_text())
        self.serial = serial
        self.mock = mock

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_root = out_root or Path("reports")
        self.run_dir = out_root / f"{serial}_{ts}"
        self.wf_dir = self.run_dir / "waveforms"
        self.wf_dir.mkdir(parents=True, exist_ok=True)
        log.info("Run directory: %s", self.run_dir)

        self.psu: PowerSupply2230 | None = None
        self.eload: EloadKeithley2380 | None = None
        self.scope: ScopeDSOX6004A | None = None
        self.dmm: DMM6500 | None = None

    # ---------- bench bring-up ----------
    def open_instruments(self) -> None:
        inst_cfg = self.config["instruments"]
        timeout = inst_cfg.get("timeout_ms", 10000)
        log.info("Opening instruments (mock=%s)...", self.mock)
        self.psu = PowerSupply2230(inst_cfg["power_supply"], timeout_ms=timeout, mock=self.mock)
        self.eload = EloadKeithley2380(inst_cfg["electronic_load"], timeout_ms=timeout, mock=self.mock)
        self.scope = ScopeDSOX6004A(inst_cfg["oscilloscope"], timeout_ms=timeout, mock=self.mock)
        self.dmm = DMM6500(inst_cfg["dmm"], timeout_ms=timeout, mock=self.mock)

    def close_instruments(self) -> None:
        for inst in (self.eload, self.psu, self.scope, self.dmm):
            try:
                if inst is not None:
                    inst.close()
            except Exception:
                pass

    def safe_shutdown(self) -> None:
        """Always-callable shutdown. Disables load first, then supply."""
        try:
            if self.eload:
                self.eload.safe_shutdown()
        except Exception:
            pass
        try:
            if self.psu:
                self.psu.safe_shutdown()
        except Exception:
            pass

    # ---------- bring-up of the DUT ----------
    def power_up_dut(self) -> None:
        sup = self.config["supply"]
        log.info("Powering DUT at %.2fV (limit %.2fA)", sup["v_input"], sup["i_limit"])
        self.psu.configure_for_pdn(ch=1, volts=sup["v_input"], i_limit=sup["i_limit"])
        # Allow PGood daisy-chain to walk to completion.
        time.sleep(0.5)
        # Quick DC sanity-check via the supply's own meter.
        v_meas = self.psu.measure_voltage(1)
        if abs(v_meas - sup["v_input"]) > 0.1:
            raise RuntimeError(f"Supply readback {v_meas:.3f} V is off target; abort.")

    # ---------- the actual transient test ----------
    def run(self) -> list[CapturedRun]:
        rails = self.config["rails"]
        tr = self.config["transient"]
        acc = self.config["acceptance"]

        captures: list[CapturedRun] = []

        try:
            self.open_instruments()
            self.power_up_dut()
            self.scope.reset_for_run()
            self.scope.set_sample_rate(tr["scope_sample_rate"])
            self.scope.configure_trigger_external(level_v=1.0)

            for rail in rails:
                log.info("=== Rail %s (v_nom=%.2fV, i_max=%.2fA) ===", rail["name"], rail["v_nom"], rail["i_max"])

                i_low = tr["step_low_pct"] * rail["i_max"]
                i_high = tr["step_high_pct"] * rail["i_max"]

                self.eload.configure_dynamic(
                    ch=rail["eload_channel"],
                    i_low=i_low,
                    i_high=i_high,
                    slew_a_per_us=tr["slew_a_per_us"],
                    low_time_us=tr["capture_window_us"],
                    high_time_us=tr["capture_window_us"],
                )
                self.scope.configure_channel(
                    ch=rail["scope_channel"],
                    v_nom=rail["v_nom"],
                    capture_window_us=tr["capture_window_us"],
                    bw_limit_mhz=tr["scope_bw_limit_mhz"],
                )

                self.eload.input_on(rail["eload_channel"], on=True)

                for k in range(tr["repeats_per_rail"]):
                    self.scope.arm_single()
                    time.sleep(0.05)
                    self.eload.fire_single_step()
                    self.scope.wait_for_trigger(timeout_s=2.0)

                    t, v_ac = self.scope.fetch_waveform(rail["scope_channel"])
                    v_dc = recover_dc(v_ac, rail["v_nom"])

                    # Align t = 0 at the step. Trigger is at scope t=0 already.
                    result = analyze_transient(
                        t=t,
                        v=v_dc,
                        rail_name=rail["name"],
                        v_nom=rail["v_nom"],
                        step_time_s=0.0,
                        settling_band_pct=acc["settling_band_pct"],
                        max_deviation_pct=acc["max_deviation_pct"],
                        max_settling_us=acc["max_settling_us"],
                    )

                    ts_utc = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
                    wf_path = self.wf_dir / f"{rail['name'].replace('+','').lower()}_rep{k:02d}.npz"
                    np.savez_compressed(
                        wf_path, t=t, v=v_dc, v_nom=rail["v_nom"],
                        rail=rail["name"], timestamp_utc=ts_utc, repeat=k,
                    )
                    log.info("  rep %02d: ΔV=%.1f mV, t_settle=%.1f µs -> %s",
                             k, max(result.undershoot_v, result.overshoot_v) * 1000,
                             result.settling_time_s * 1e6,
                             "PASS" if result.passed else f"FAIL ({'; '.join(result.fail_reasons)})")

                    captures.append(CapturedRun(
                        result=result,
                        repeat_idx=k,
                        timestamp_utc=ts_utc,
                        waveform_path=wf_path,
                        rail_cfg=rail,
                    ))

                self.eload.input_on(rail["eload_channel"], on=False)
        finally:
            self.safe_shutdown()
            self.close_instruments()

        return captures
