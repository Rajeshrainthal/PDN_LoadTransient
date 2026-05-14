"""Keithley 2230-30-1 programmable DC supply.

Three independent channels. We use Channel 1 as the +5V input to the PDN.
SCPI is mostly standard; channel selection is via ``INST:NSEL n``.
"""

from .base import VisaInstrument


class PowerSupply2230(VisaInstrument):

    def select_channel(self, ch: int) -> None:
        self.write(f"INST:NSEL {ch}")

    def set_voltage(self, ch: int, volts: float) -> None:
        self.select_channel(ch)
        self.write(f"VOLT {volts:.4f}")

    def set_current_limit(self, ch: int, amps: float) -> None:
        self.select_channel(ch)
        self.write(f"CURR {amps:.4f}")

    def output(self, ch: int, on: bool) -> None:
        self.select_channel(ch)
        self.write(f"OUTP {'ON' if on else 'OFF'}")

    def measure_voltage(self, ch: int) -> float:
        self.select_channel(ch)
        return float(self.query("MEAS:VOLT?"))

    def measure_current(self, ch: int) -> float:
        self.select_channel(ch)
        return float(self.query("MEAS:CURR?"))

    def configure_for_pdn(self, ch: int, volts: float, i_limit: float) -> None:
        """Set limits BEFORE turning output on. This is the safe sequence."""
        self.output(ch, on=False)
        self.set_current_limit(ch, i_limit)
        self.set_voltage(ch, volts)
        self.output(ch, on=True)

    def safe_shutdown(self) -> None:
        for ch in (1, 2, 3):
            try:
                self.output(ch, on=False)
            except Exception:
                pass
