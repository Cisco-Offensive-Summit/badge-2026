"""
badge/pervasive_epd.py

CircuitPython driver for the Pervasive Displays eScreen_EPD_271_KS_0C
(2.71", 176x264, B&W Wide Small).

Subclasses epaperdisplay.EPaperDisplay — no new C module required.
The EPaperDisplay base class handles SPI bus arbitration, displayio
integration, BUSY pin monitoring, and the background refresh task.

Supports both normal update (full refresh, 3-10 s) and fast update
(partial refresh, time TBD on hardware) via the fast_mode parameter.

Fast update usage:
    epd = PervasiveWideSmall(bus, psr, busy_pin, fast_mode=True)
    epd.refresh()        # required first call — primes the previous-frame buffer
    # ... update displayio groups ...
    epd.fast_refresh()   # subsequent updates use fast path

    Always call refresh() at least once after power-on or a full scene
    change before using fast_refresh(). The previous-frame buffer starts
    as all-zeros (all-white), which is correct only if the screen is blank
    after reset. A normal refresh() syncs the buffer to whatever is shown.

References:
  https://docs.pervasivedisplays.com/knowledge/Hardware/epd-usage/
  Screens/Wide_Small/update-procedure.html
  Pervasive_Wide_Small/src/Pervasive_Wide_Small.cpp
"""

from epaperdisplay import EPaperDisplay

try:
    from typing import Tuple
    from fourwire import FourWire
    from microcontroller import Pin
except ImportError:
    pass


# EPaperDisplay sequence format:
#   <cmd_byte> <count | 0x80_if_delay> [param_bytes...] [delay_ms if delay set]
#
# start_sequence runs with should_wait_for_busy=True — after each command,
# EPaperDisplay waits for BUSY to go HIGH (screen ready) before continuing.
#
# Normal update init sequence (from COG_initial, default/other-small-sizes path):
#   0x00 0x0E  — soft-reset (1 param, 100ms delay)
#   0xe5 TSSET — input temperature
#   0xe0 0x02  — activate temperature
#   0x00 PSR0 PSR1 — panel setting register (PSR bytes from OTP)
#
# Note: 0x50 0x07 is fast-update ONLY — not included here.

def _build_start_sequence(psr0: int, psr1: int, tsset: int) -> bytes:
    return bytes([
        0x00, 0x81, 0x0E, 0x64,  # soft-reset: cmd=0x00, 1 param + delay, 0x0E, 100ms
        0xe5, 0x01, tsset,        # input temperature: cmd=0xe5, 1 param, TSSET
        0xe0, 0x01, 0x02,         # activate temperature: cmd=0xe0, 1 param, 0x02
        0x00, 0x02, psr0, psr1,   # PSR: cmd=0x00, 2 params, PSR[0], PSR[1]
    ])


def _build_fast_start_sequence(psr0: int, psr1: int, tsset: int) -> bytes:
    """
    Build the init sequence used before a fast (partial) update.

    Derived from Pervasive_Wide_Small.cpp COG_initial(UPDATE_FAST), default path
    (eScreen_EPD_271_KS_0C). Differences from the normal start sequence:

      - Temperature byte has 0x40 OR'd in  (u_temperature | 0x40)
      - PSR0 has 0x10 OR'd in              (COG_data[0]  | 0x10)
      - PSR1 has 0x02 OR'd in              (COG_data[1]  | 0x02)
      - 0x50 0x07 (CDI) appended after PSR

    The soft reset (0x00 0x0E) IS included — COG_initial() runs it for both
    normal and fast update. Hardware reset is also performed by fast_refresh()
    before this sequence is sent, same as normal refresh().
    """
    fast_tsset = tsset | 0x40        # temperature | 0x40
    fast_psr0  = psr0  | 0x10       # PSR0 | 0x10
    fast_psr1  = psr1  | 0x02       # PSR1 | 0x02
    return bytes([
        0x00, 0x81, 0x0E, 0x64,                    # soft-reset (same as normal)
        0xe5, 0x01, fast_tsset,                     # input temperature | 0x40
        0xe0, 0x01, 0x02,                           # activate temperature
        0x00, 0x02, fast_psr0, fast_psr1,           # modified PSR
        0x50, 0x01, 0x07,                           # CDI: fast update mode (after PSR)
    ])


# Refresh sequence: start DC/DC then trigger display refresh.
# Format: each entry is <cmd> <count|0x80> [params] [delay_ms]
#
# From COG_update (default path):
#   b_waitBusy() → 0x04 (power on / start DC/DC) → b_waitBusy() → 0x12 (refresh) → b_waitBusy()
#
# EPaperDisplay runs the refresh_sequence without per-command busy waits.
# The 200ms delay after 0x04 approximates the b_waitBusy() between the two
# commands. The background task handles the post-0x12 wait via the BUSY pin.
_REFRESH_SEQUENCE = bytes([
    0x04, 0x80, 0xC8,  # start DC/DC: cmd=0x04, no params + delay, 200ms
    0x12, 0x80, 0xC8,  # display refresh: cmd=0x12, no params + delay, 200ms
])

# Stop sequence: sent by EPaperDisplay background task once BUSY goes HIGH
# (screen has completed its refresh cycle).
# From COG_stopDCDC: 0x02 (turn off DC/DC)
_STOP_SEQUENCE = bytes([
    0x02, 0x00,  # stop DC/DC: cmd=0x02, 0 params
])


def _celsius_to_tsset(temp_c: int) -> int:
    """
    Convert temperature in Celsius to the TSSET register value.
    Range for normal update: -15°C to +60°C.
    Negative values use two's complement (e.g. -15 → 0xF1).
    """
    temp_c = max(-15, min(60, int(temp_c)))
    return temp_c & 0xFF  # two's complement handles negatives naturally


class PervasiveWideSmall(EPaperDisplay):
    """
    Driver for the Pervasive Displays eScreen_EPD_271_KS_0C.

    2.71" B&W wide-temperature EPD, 176 x 264 pixels physical.
    Driven in landscape orientation (264 × 176) using rotation=270.
    Physical RAM dimensions (ram_width=176, ram_height=264) are kept at the
    hardware values so EPaperDisplay always sends 22-byte rows × 264 rows =
    5808 bytes.  The rotation=270 transform maps GROUP (lx, ly) to physical
    row py=263-lx, column px=ly — correct landscape rendering with no
    pre-rotation required in app code.
    Normal update only.

    :param bus: FourWire display bus (shared SPI with LCD is fine)
    :param psr: 2-tuple of PSR bytes from read_otp() e.g. (0xCF, 0x8D)
    :param busy_pin: microcontroller.Pin for the BUSY signal (board.EINK_BUSY)
    :param temperature: ambient temperature in Celsius (default 25)
    """

    # Physical EPD RAM dimensions (hardware, never change)
    RAM_WIDTH  = 176
    RAM_HEIGHT = 264

    # Logical landscape dimensions exposed to app code
    WIDTH  = 264
    HEIGHT = 176

    # Minimum gap between fast_refresh() calls, and between full refresh()
    # calls. EPaperDisplay rate-limits the two independently and only exposes
    # the normal interval via .time_to_refresh, so SmartEPD reads the fast one
    # from here.
    FAST_SECONDS_PER_FRAME = 0.5
    SECONDS_PER_FRAME      = 40

    def __init__(
        self,
        bus: "FourWire",
        psr: "Tuple[int, int]",
        busy_pin: "Pin",
        temperature: int = 25,
        fast_mode: bool = False,
        **kwargs
    ) -> None:

        tsset = _celsius_to_tsset(temperature)
        start_sequence = _build_start_sequence(psr[0], psr[1], tsset)

        fast_kwargs = {}
        if fast_mode:
            fast_seq = _build_fast_start_sequence(psr[0], psr[1], tsset)
            fast_kwargs["fast_mode"] = True
            fast_kwargs["fast_start_sequence"] = fast_seq
            # Update once actual fast refresh time is measured on hardware.
            # The KS-0C normal refresh takes 3-10 s; fast is expected <1 s but unconfirmed.
            fast_kwargs["fast_seconds_per_frame"] = self.FAST_SECONDS_PER_FRAME

        super().__init__(
            bus,
            start_sequence,
            _STOP_SEQUENCE,
            width=self.WIDTH,
            height=self.HEIGHT,
            ram_width=self.RAM_WIDTH,
            ram_height=self.RAM_HEIGHT,
            rotation=270,
            write_black_ram_command=0x10,
            write_color_ram_command=0x13,
            busy_pin=busy_pin,
            busy_state=False,
            refresh_display_command=_REFRESH_SEQUENCE,
            seconds_per_frame=self.SECONDS_PER_FRAME,
            start_up_time=0.025,
            **fast_kwargs,
            **kwargs,
        )
