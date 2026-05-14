"""Keithley 2380 series programmable electronic load.

We use dynamic CC mode to generate the transient step: low level, high
level, slew rate, low time, high time. The 2380 has a TRIG OUT BNC that
we wire to the scope external trigger so each capture is aligned to the
load edge.
"""

from .base import VisaInstrument


class EloadKeithley2380(VisaInstrument):

    def select_channel(self, ch: int) -> None:
        # 2380 multi-channel variant. Single-channel SKU ignores this.
        try:
            self.write(f"INST:NSEL {ch}")
        except Exception:
            pass

    def set_mode_cc_dynamic(self) -> None:
        self.write("FUNC CURR")
        self.write("CURR:MODE DYN")

    def set_static_current(self, ch: int, amps: float) -> None:
        self.select_channel(ch)
        self.write("FUNC CURR")
        self.write("CURR:MODE FIX")
        self.write(f"CURR {amps:.4f}")

    def configure_dynamic(
        self,
        ch: int,
        i_low: float,
        i_high: float,
        slew_a_per_us: float,
        low_time_us: float = 200.0,
        high_time_us: float = 200.0,
    ) -> None:
        self.select_channel(ch)
        self.set_mode_cc_dynamic()
        self.write(f"CURR:LOW {i_low:.4f}")
        self.write(f"CURR:HIGH {i_high:.4f}")
        self.write(f"CURR:SLEW {slew_a_per_us:.4f}")
        self.write(f"CURR:LOW:TIME {low_time_us * 1e-6:.6f}")
        self.write(f"CURR:HIGH:TIME {high_time_us * 1e-6:.6f}")
        # Route the transient edge to TRIG OUT so the scope can sync on it.
        self.write("OUTP:TRIG:SOUR DYN")

    def input_on(self, ch: int, on: bool) -> None:
        self.select_channel(ch)
        self.write(f"INP {'ON' if on else 'OFF'}")

    def fire_single_step(self) -> None:
        """Trigger one low->high->low cycle and emit a trigger pulse."""
        self.write("TRIG:IMM")

    def safe_shutdown(self) -> None:
        for ch in (1, 2, 3, 4):
            try:
                self.input_on(ch, on=False)
            except Exception:
                pass
