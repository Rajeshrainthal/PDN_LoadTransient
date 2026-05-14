"""Keithley DMM6500 6.5-digit bench DMM. Used for steady-state DC checks."""

from .base import VisaInstrument


class DMM6500(VisaInstrument):

    def reset(self) -> None:
        self.write("*RST")
        self.write("*CLS")

    def measure_voltage_dc(self, nplc: float = 1.0) -> float:
        self.write("SENS:FUNC 'VOLT:DC'")
        self.write(f"SENS:VOLT:DC:NPLC {nplc}")
        return float(self.query("READ?"))

    def measure_current_dc(self, nplc: float = 1.0) -> float:
        self.write("SENS:FUNC 'CURR:DC'")
        self.write(f"SENS:CURR:DC:NPLC {nplc}")
        return float(self.query("READ?"))
