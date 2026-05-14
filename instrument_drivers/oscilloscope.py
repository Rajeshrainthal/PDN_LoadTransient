"""Keysight DSOX6004A 4-channel oscilloscope.

We use external trigger from the e-load, AC coupling on the rail channel
(transient view), and 20 MHz bandwidth limit to keep switching noise out
of the ripple/transient numbers.
"""

from __future__ import annotations
import numpy as np

from .base import VisaInstrument


class ScopeDSOX6004A(VisaInstrument):

    def reset_for_run(self) -> None:
        self.write("*RST")
        self.write("*CLS")
        self.write(":WAV:FORM BYTE")
        self.write(":WAV:POIN:MODE RAW")
        self.write(":WAV:BYT LSBF")

    def configure_channel(
        self,
        ch: int,
        v_nom: float,
        capture_window_us: float,
        bw_limit_mhz: int = 20,
    ) -> None:
        """AC coupled around the steady-state, fine vertical scale for the
        droop / overshoot. Bandwidth limited to take switching noise off the
        plot."""
        self.write(f":CHAN{ch}:DISP ON")
        self.write(f":CHAN{ch}:COUP AC")          # AC: focus on the transient
        self.write(f":CHAN{ch}:SCAL {0.05:.3f}")  # 50 mV/div, adjust per rail
        self.write(f":CHAN{ch}:OFFS 0.0")
        if bw_limit_mhz == 20:
            self.write(f":CHAN{ch}:BWL ON")
        # Timebase: capture_window_us across the screen (10 divs)
        timebase_per_div = capture_window_us * 1e-6 / 10.0
        self.write(f":TIM:SCAL {timebase_per_div:.6e}")
        self.write(":TIM:POS 0")

    def configure_trigger_external(self, level_v: float = 1.0) -> None:
        self.write(":TRIG:MODE EDGE")
        self.write(":TRIG:EDGE:SOUR EXT")
        self.write(":TRIG:EDGE:SLOP POS")
        self.write(f":TRIG:EDGE:LEV EXT,{level_v:.3f}")

    def set_sample_rate(self, sample_rate_sps: float) -> None:
        # DSOX honours :ACQ:SRAT in some firmware; otherwise it's derived from
        # timebase + memory depth. Setting memory depth explicitly is safer.
        try:
            self.write(f":ACQ:SRAT {sample_rate_sps:.3e}")
        except Exception:
            pass
        # Force enough memory to hit the requested rate for the window.
        self.write(":ACQ:TYPE NORM")
        self.write(":ACQ:MODE RTIM")

    def arm_single(self) -> None:
        self.write(":SING")

    def wait_for_trigger(self, timeout_s: float = 5.0) -> None:
        # Block until TER bit indicates the trigger happened.
        self.wait_opc(timeout_s=timeout_s)

    def fetch_waveform(self, ch: int) -> tuple[np.ndarray, np.ndarray]:
        """Return (time_s, volts) numpy arrays for one channel."""
        self.write(f":WAV:SOUR CHAN{ch}")
        self.write(":WAV:FORM BYTE")
        x_inc = float(self.query(":WAV:XINC?"))
        x_orig = float(self.query(":WAV:XOR?"))
        y_inc = float(self.query(":WAV:YINC?"))
        y_orig = float(self.query(":WAV:YOR?"))
        y_ref = float(self.query(":WAV:YREF?"))
        raw = self.query_binary(":WAV:DATA?")
        # In mock mode, the backend returns the cooked waveform directly.
        if self.mock:
            volts = np.asarray(raw, dtype=float)
            t = np.linspace(x_orig, x_orig + (len(volts) - 1) * 1e-6 * 0.05, len(volts))
            return t, volts
        raw = np.asarray(raw, dtype=np.int16)
        volts = (raw - y_ref) * y_inc + y_orig
        t = x_orig + np.arange(len(volts)) * x_inc
        return t, volts
