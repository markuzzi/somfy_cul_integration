import logging
import time
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Callable, Optional

import serial

_LOGGER = logging.getLogger(__name__)

class Cul:
    """Serial CUL connector with auto-reconnect and thread-safe writes."""

    def __init__(self, serial_port: str, baud_rate: int = 38400, test: bool = False) -> None:
        self._port = serial_port
        self._baud = baud_rate
        self._test = test
        self._ser: Optional[serial.Serial] = None
        self._stop = Event()
        self._wlock = Lock()
        self._rx_thread: Optional[Thread] = None

        if not test and not Path(serial_port).exists():
            raise ValueError(f"Cannot find CUL device at {serial_port}")

        if not self._test:
            self._open_serial()

    @property
    def serial(self) -> Optional[serial.Serial]:
        return self._ser

    def _open_serial(self) -> None:
        try:
            self._ser = serial.Serial(
                port=self._port,
                baudrate=self._baud,
                timeout=1,
                write_timeout=2,
                exclusive=True
            )
            _LOGGER.info("Opened CUL at %s (baud %d)", self._port, self._baud)
        except serial.SerialException as e:
            self._ser = None
            _LOGGER.error("Opening CUL failed at %s: %s", self._port, e)

    def start_listen(self, callback: Callable[[str], None]) -> None:
        if self._test:
            return
        if self._rx_thread and self._rx_thread.is_alive():
            return
        self._stop.clear()
        self._rx_thread = Thread(target=self._listen_loop, args=(callback,), daemon=True)
        self._rx_thread.start()

    def _listen_loop(self, callback: Callable[[str], None]) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                if not self._ser:
                    self._open_serial()
                    if not self._ser:
                        time.sleep(min(backoff, 30))
                        backoff *= 2
                        continue
                    backoff = 1.0

                line = self._ser.readline()
                if not line:
                    continue
                backoff = 1.0
                msg = line.decode("utf-8", "ignore").strip()
                if msg:
                    # _LOGGER.debug("RF: %s", msg)
                    callback(msg)
            except serial.SerialException as e:
                _LOGGER.warning("Serial exception; will try to reconnect: %s", e)
                if self._ser:
                    try:
                        self._ser.close()
                    except Exception:
                        pass
                self._ser = None
                wait_s = min(backoff, 30.0)
                if self._stop.wait(wait_s):   # breaks, if close() was called
                    break
                backoff *= 2
            except Exception as e:
                _LOGGER.exception("Unexpected error in listen loop: %s", e)
                # avoid a busy loop on persistent errors
                if self._stop.wait(1.0):
                    break

    def get_cul_version(self, attempts: int = 5) -> Optional[str]:
        """Query the firmware version.

        A nanoCUL resets when the port is opened and ignores input while its
        bootloader runs. After a power loss the input buffer of the CUL may
        also contain garbage. Thus, the query is repeated several times and
        starts with a newline to terminate any partial line.
        """
        if self._test:
            return "VTEST"
        msg = ""
        for attempt in range(1, attempts + 1):
            if self._stop.is_set():
                return None
            if not self._ser:
                self._open_serial()
                if not self._ser:
                    self._stop.wait(2.0)
                    continue
            try:
                with self._wlock:
                    self._ser.reset_input_buffer()
                    self._ser.write(b"\nV\n")
                    self._ser.flush()
                deadline = time.time() + 2.0
                while time.time() < deadline and not self._stop.is_set():
                    line = self._ser.readline()
                    if not line:
                        continue
                    msg = line.decode("ascii", "ignore").strip()
                    if msg.startswith("V"):
                        return msg
            except serial.SerialException as e:
                _LOGGER.warning("Reading CUL version failed: %s", e)
                self._close_serial()
            _LOGGER.debug(
                "No version from CUL (attempt %d/%d). Response: %r",
                attempt, attempts, msg,
            )
        _LOGGER.warning("Timeout while reading CUL version. Response: %r", msg)
        return None

    def _close_serial(self) -> None:
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass
        self._ser = None

    def send_command(self, payload: bytes) -> bool:
        if self._test:
            _LOGGER.info(payload.decode(errors="ignore"))
            return True
        if not self._ser:
            _LOGGER.error("Cannot send (no serial handle): %r", payload)
            return False
        try:
            with self._wlock:
                _LOGGER.debug("TX: %r", payload)
                self._ser.write(payload)
                self._ser.flush()
            return True
        except serial.SerialException as e:
            _LOGGER.error("Send failed, will drop: %r (%s)", payload, e)
            return False

    def close(self) -> None:
        self._stop.set()
        if self._rx_thread:
            self._rx_thread.join(timeout=2)
            self._rx_thread = None
        if self._ser and self._ser.is_open:
            try:
                self._ser.close()
            except Exception:
                pass

    def is_open(self) -> bool:
        return bool(self._ser and self._ser.is_open)

    def send_line(self, line: str) -> bool:
        return self.send_command((line + "\n").encode("ascii"))

    def reload_connection(self) -> bool:
        """Close and reopen the serial connection."""
        if self._test:
            return True

        self.close()
        self._stop.clear()
        self._open_serial()

        return self.is_open()
