"""
badge/epd_otp.py

Reads the 2-byte PSR (Panel Setting Register) from the OTP memory of the
Pervasive Displays eScreen_EPD_271_KS_0C via a bit-bang SPI3 sequence.

The OTP read uses SDIN (GPIO11) as a bidirectional line — output for the
command byte, input for the data bytes. This is incompatible with busio.SPI
(MOSI is output-only), so it is done here in software before the SPI bus is
initialised.

Soft-reload safety: FourWire marks the SPI bus and all display pins as
never_reset. release_displays() is called first so this function is safe
to call regardless of prior display state.

Must be called before busio.SPI is initialised (i.e. before _init_screens
creates the SPI object).

Reference:
  https://docs.pervasivedisplays.com/knowledge/Hardware/epd-usage/
  Screens/Wide_Small/update-procedure.html
  Pervasive_Wide_Small/src/Pervasive_Wide_Small.cpp — COG_getDataOTP()
"""

import board
import digitalio
import time
from displayio import release_displays

# OTP PSR addresses for the 2.71" (eScreen_EPD_271_KS_0C) screen.
# bank0 is active when OTP[0] == 0xa5, otherwise bank1.
_PSR_ADDR_BANK0 = 0x0FB4
_PSR_ADDR_BANK1 = 0x1FB4


def _write_byte(sck, sdin, byte):
    """Write one byte MSB-first. SDIN must be configured as OUTPUT."""
    for i in range(7, -1, -1):
        sdin.value = bool(byte & (1 << i))
        sck.value = True
        sck.value = False


def _read_byte(sck, sdin):
    """Read one byte MSB-first. SDIN must be configured as INPUT."""
    value = 0
    for _ in range(8):
        sck.value = True
        value = (value << 1) | (1 if sdin.value else 0)
        sck.value = False
    return value


def _skip_bytes(sck, count):
    """
    Clock out `count` dummy bytes without reading them.
    Used to advance the OTP address pointer to the PSR location.
    SDIN must already be configured as INPUT.
    """
    bits = count * 8
    for _ in range(bits):
        sck.value = True
        sck.value = False


def read_otp():
    """
    Read the 2-byte PSR from the EPD OTP memory using bit-bang SPI3.

    Returns a tuple (psr0, psr1) to be passed to the EPD driver constructor.

    CS is toggled per byte/operation, matching the Arduino COG_getDataOTP()
    implementation exactly.

    Sequence (from Arduino source and PD application note):
      1. DC LOW (command), CS LOW, write 0xa2, CS HIGH, delay 10ms
      2. DC HIGH (data), CS LOW, read dummy byte, CS HIGH
      3. CS LOW, read bank indicator byte (0xa5 = bank0, else bank1), CS HIGH
      4. For bank0: skip (PSR_ADDR - 1) bytes to advance OTP pointer
         For bank1: skip (PSR_ADDR - 1) bytes
      5. CS LOW, read PSR[0], CS HIGH
      6. CS LOW, read PSR[1], CS HIGH
    """
    # Free any pins claimed by a previous display session
    release_displays()

    # SCK — GPIO12, output, idle LOW
    sck = digitalio.DigitalInOut(board.EINK_CLKS)
    sck.direction = digitalio.Direction.OUTPUT
    sck.value = False

    # SDIN — GPIO11, starts as output for the command byte
    sdin = digitalio.DigitalInOut(board.EINK_MOSI)
    sdin.direction = digitalio.Direction.OUTPUT
    sdin.value = False

    # CS — GPIO18, output, idle HIGH (active LOW)
    cs = digitalio.DigitalInOut(board.EINK_CS)
    cs.direction = digitalio.Direction.OUTPUT
    cs.value = True

    # DC — GPIO21, output (LOW = command, HIGH = data)
    dc = digitalio.DigitalInOut(board.EINK_DC)
    dc.direction = digitalio.Direction.OUTPUT
    dc.value = True

    # RST — GPIO45, output, active LOW
    rst = digitalio.DigitalInOut(board.EINK_RST)
    rst.direction = digitalio.Direction.OUTPUT
    rst.value = True

    # BUSY — GPIO38, input
    busy = digitalio.DigitalInOut(board.EINK_BUSY)
    busy.direction = digitalio.Direction.INPUT

    try:
        # --- Reset sequence ---
        dc.value  = True
        rst.value = True
        cs.value  = True
        time.sleep(0.005)
        rst.value = True
        time.sleep(0.005)
        rst.value = False
        time.sleep(0.010)
        rst.value = True
        time.sleep(0.020)

        deadline = time.monotonic() + 2.0
        while not busy.value:
            if time.monotonic() > deadline:
                break

        # --- Step 1: Send command 0xa2 ---
        dc.value = False
        cs.value = False
        _write_byte(sck, sdin, 0xa2)
        cs.value = True

        sdin.switch_to_input()
        time.sleep(0.01)

        # --- Step 2: Read dummy byte ---
        dc.value = True
        cs.value = False
        _read_byte(sck, sdin)
        cs.value = True

        # --- Step 3: Read bank indicator byte ---
        cs.value = False
        bank_indicator = _read_byte(sck, sdin)
        cs.value = True

        bank = 0 if bank_indicator == 0xa5 else 1
        psr_addr = _PSR_ADDR_BANK0 if bank == 0 else _PSR_ADDR_BANK1

        # --- Step 4: Skip bytes to advance OTP pointer to PSR address ---
        for _ in range(psr_addr - 1):
            cs.value = False
            _read_byte(sck, sdin)
            cs.value = True

        # --- Step 5 & 6: Read PSR[0] and PSR[1] ---
        cs.value = False
        psr0 = _read_byte(sck, sdin)
        cs.value = True

        cs.value = False
        psr1 = _read_byte(sck, sdin)
        cs.value = True

        return (psr0, psr1)

    finally:
        # Always release all pins regardless of success or exception
        sck.deinit()
        sdin.deinit()
        cs.deinit()
        dc.deinit()
        rst.deinit()
        busy.deinit()
