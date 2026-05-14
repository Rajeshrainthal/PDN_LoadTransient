"""
Base VISA wrapper with a mock backend.

Why a mock backend: CI runs on a laptop with no instruments connected.
The mock lets every test in this repo run end-to-end and produce a sample
report, so reviewers can see the format without spinning up the bench.
"""

from __future__ import annotations
import logging
import time
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)


class MockBackend:
    """Stand-in for pyvisa when no hardware is available.

    Returns plausible responses to common SCPI queries and synthesises
    a realistic transient waveform when asked for scope data.
    """

    def __init__(self, idn: str = "MOCK,Model0,SN0,FW0"):
        self._idn = idn
        self._buffer: dict[str, str] = {}
        self._waveform_seed = 0
        self._last_set_voltage = 5.0  # remember what was programmed
        self._last_set_current = 0.5

    # --- VISA-like API ---
    def write(self, cmd: str) -> None:
        log.debug("MOCK write: %s", cmd)
        c = cmd.strip().upper()
        # Track the last programmed values so readbacks make sense.
        if c.startswith("VOLT ") and ":" not in c:
            try:
                self._last_set_voltage = float(c.split()[1])
            except (IndexError, ValueError):
                pass
        elif c.startswith("CURR ") and ":" not in c:
            try:
                self._last_set_current = float(c.split()[1])
            except (IndexError, ValueError):
                pass

    def query(self, cmd: str) -> str:
        log.debug("MOCK query: %s", cmd)
        c = cmd.strip().upper()
        if c.startswith("*IDN"):
            return self._idn
        if c.startswith("*OPC"):
            return "1"
        if c.startswith("MEAS:VOLT") or c.startswith("READ"):
            return f"{self._last_set_voltage + np.random.normal(0, 0.002):.6f}"
        if c.startswith("MEAS:CURR"):
            return f"{self._last_set_current * 0.5 + np.random.normal(0, 0.001):.6f}"
        if c.startswith(":WAV:XINC"):
            return "5e-8"
        if c.startswith(":WAV:XOR"):
            return "-50e-6"
        if c.startswith(":WAV:YINC"):
            return "0.001"
        if c.startswith(":WAV:YOR"):
            return "0"
        if c.startswith(":WAV:YREF"):
            return "0"
        if c.startswith("WAV:DATA") or c.startswith(":WAV:DATA"):
            return ""  # raw bytes path uses query_binary_values
        return "0"

    def query_binary_values(self, cmd: str, datatype="b", container=np.array):
        """Synthesise an AC-coupled transient waveform: zero baseline,
        downward step, undershoot, exponential recovery. Adds noise so
        measurements are non-trivial. The driver will offset this back to
        the rail's nominal DC level."""
        n = 4000
        t = np.linspace(-50e-6, 150e-6, n)  # 200 µs window
        step_t = 0.0
        tau = 8e-6
        undershoot = -0.12  # 120 mV undershoot (matches the assessment scenario)
        baseline = 0.0       # AC-coupled
        pre = np.full_like(t, baseline)
        post = baseline + undershoot * np.exp(-(t - step_t) / tau)
        wf = np.where(t < step_t, pre, post)
        wf += np.random.normal(0, 0.003, n)
        return wf

    def close(self) -> None:
        pass


class VisaInstrument:
    """Common parent for instrument drivers.

    Holds the VISA session, exposes ``write``/``query``, and runs a startup
    ``*IDN?`` so a misconfigured connection fails loudly before any test
    starts. Each subclass adds verbs in its own language (set_voltage,
    arm_trigger, capture, etc.).
    """

    def __init__(self, resource: str, *, timeout_ms: int = 10000, mock: bool = False):
        self.resource = resource
        self.mock = mock
        self._inst = self._open(timeout_ms)
        self.idn = self.query("*IDN?")
        log.info("Connected: %s  ->  %s", resource, self.idn.strip())

    def _open(self, timeout_ms: int):
        if self.mock:
            return MockBackend(idn=f"MOCK,{self.__class__.__name__},SN-MOCK,1.0")
        import pyvisa
        rm = pyvisa.ResourceManager()
        inst = rm.open_resource(self.resource)
        inst.timeout = timeout_ms
        inst.write_termination = "\n"
        inst.read_termination = "\n"
        return inst

    def write(self, cmd: str) -> None:
        self._inst.write(cmd)

    def query(self, cmd: str) -> str:
        return self._inst.query(cmd)

    def query_binary(self, cmd: str) -> np.ndarray:
        return self._inst.query_binary_values(cmd, datatype="b", container=np.array)

    def close(self) -> None:
        try:
            self._inst.close()
        except Exception:
            pass

    # Convenience: wait for operation complete with a timeout (SCPI *OPC?)
    def wait_opc(self, timeout_s: float = 5.0) -> None:
        t_end = time.time() + timeout_s
        while time.time() < t_end:
            try:
                if self.query("*OPC?").strip() == "1":
                    return
            except Exception:
                time.sleep(0.05)
        raise TimeoutError(f"*OPC? timeout on {self.idn}")
