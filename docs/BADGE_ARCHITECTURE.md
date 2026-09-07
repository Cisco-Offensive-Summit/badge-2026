# Badge Architecture

This document describes the hardware and software architecture of the Offensive Summit 2026 badge.

## Hardware Architecture

### ESP32-S3 Microcontroller

The badge is built around the ESP32-S3 (module: **ESP32-S3-WROOM-1-N16R8**), which provides:
- Dual-core Xtensa LX7 @ 240 MHz
- 16 MB QSPI flash (dio mode, 80 MHz)
- **8 MB octal PSRAM** — enabled in the build, giving an ~8.2 MB CircuitPython heap
- WiFi 2.4 GHz (802.11 b/g/n)
- ESP-NOW (connectionless peer-to-peer protocol)
- USB (for programming and serial console)
- Hardware SPI (shared by both displays)

### GPIO Pin Map

Defined in `firmware/offsummit_2026/pins.c`:

| Function | GPIO | Notes |
|---|---|---|
| NeoPixels | 5 | 4× WS2812, active-high |
| Status LED | 6 | |
| I2C SCL | 3 | STEMMA QT |
| I2C SDA | 4 | STEMMA QT |
| UART TX | 43 | |
| UART RX | 44 | |
| Boot | 0 | BOOT button |
| BTN1 (S7) | 7 | Right button |
| BTN2 (S6) | 15 | |
| BTN3 (S5) | 16 | |
| BTN4 (S4) | 17 | Left button |
| TFT RST | 8 | LCD reset |
| TFT CS | 10 | LCD chip select |
| TFT MOSI | 11 | Shared SPI MOSI |
| TFT CLK | 12 | Shared SPI CLK |
| TFT DC | 13 | LCD data/command |
| TFT BL | 47 | LCD backlight |
| E-Ink CS | 18 | EPD chip select |
| E-Ink BUSY | 38 | EPD busy signal |
| E-Ink RST | 45 | EPD reset |
| E-Ink DC | 21 | EPD data/command |
| NeoPixel power | 48 | Inverted logic |

Every other pin present in `pins.c` is exposed as a plain `board.GPIO<n>` with no
assigned function.

### Unavailable / Reserved Pins

These are **not** exposed on `board` and cannot be used from application code.
Attempting `board.GPIO35` etc. raises `AttributeError`.

| GPIO | Why |
|---|---|
| **35, 36, 37** | **Consumed by the module's 8 MB octal PSRAM.** Enabling PSRAM (`CIRCUITPY_ESP_PSRAM_MODE = opi`) claims these three lines, so they were removed from `pins.c`. Do not re-add them — doing so conflicts with the PSRAM bus. |
| 0 | `BOOT` button / strapping pin. Deliberately left commented out in `pins.c` so it is not driven as a GPIO. |
| 26 - 32 | Reserved by the ESP32-S3 for the SPI flash interface; never broken out. |
| 22 - 25, 33, 34 | Not available on this package / not routed on the badge. |

> **Historical note:** GPIO35/36/37 *were* exposed as generic pins before PSRAM
> was enabled. Any older code or notes referring to them is out of date.

Verified on hardware (`hasattr(board, "GPIO<n>")` for n in 0..48):

```
exposed : 1-21, 38-48
absent  : 0, 22-37
```

Check at runtime with:

```python
import board
print([n for n in range(49) if hasattr(board, "GPIO%d" % n)])
```

### Displays

Both displays share the same SPI bus (MOSI=GPIO11, CLK=GPIO12) but have separate CS, DC, and RST pins.

**LCD (TFT)**:
- Controller: ST7735R
- Resolution: 128×128
- Color: RGB (16-bit)
- Auto-refresh enabled
- Initialized as `LCD` global in `badge/screens.py`
- Used for: app launcher, dynamic app content, animations

**E-Ink (EPD)**:
- Panel: Pervasive Displays E2271KS0C1, 2.71" "Wide Small" (`eScreen_EPD_271_KS_0C`)
- Driver: `PervasiveWideSmall` in `badge/pervasive_epd.py`, a subclass of CircuitPython's `epaperdisplay.EPaperDisplay`
- Resolution: 264×176 logical landscape (`EPD_WIDTH` × `EPD_HEIGHT` in `badge/constants.py`)
- Physical panel RAM is 176×264 portrait; the display is created with `rotation=270`, which maps the logical landscape dimensions onto it. **App code does not need to pre-rotate anything.**
- Monochrome (black/white)
- Panel start-up sequence is built from PSR (panel setting register) bytes read from the panel's OTP memory
- Manual refresh required (`EPD.refresh()`)
- Initialized as `EPD` global in `badge/screens.py`, wrapped in `SmartEPD`
- Supports an optional **fast refresh mode** (`fast_mode=True`), which uses a modified start sequence; `SmartEPD.refresh()` selects the appropriate update path automatically
- Used for: name tags, button labels, static information, error display
- Ultra-low power — retains image without power

### NeoPixels

4 individually addressable WS2812 RGB LEDs on GPIO5. Default brightness is 0.05 (very dim). The NeoPixel power pin (GPIO48) uses inverted logic. Controlled via the `neopixels` module — see [Badge Hardware Modules](BADGE_MODULES.md#neopixelspy) for the full API.

### Buttons

4 tactile buttons with pull-up resistors. Active-low (pressed = `False`). Buttons are polled asynchronously and state changes fire `Event` objects. For the complete button API (polling functions, async tasks, event constants) see [Badge Hardware Modules](BADGE_MODULES.md#buttonspy). For the event system details see [Badge Hardware Modules](BADGE_MODULES.md#eventspy).

## Software Architecture

### Boot Sequence

```
Power On
  │
  ▼
boot.py
  ├── Disable autoreload
  ├── Read button states
  ├── Check boot combos:
  │   ├── S4+S7 → Safe mode
  │   ├── S4+S6 → OTA update
  │   └── S5+S6 → Re-provision token
  ├── Check for UNIQUE_ID in secrets.py
  │   └── If missing → run get_token.py → request from server
  ├── Read NVM boot config
  └── Apply filesystem options (mount_root_rw, disable_usb_drive)
  │
  ▼
code.py
  └── launcher.run()
      ├── Read NVM for next_code_file
      ├── If next_code_file exists:
      │   └── Launch app directly (supervisor.set_next_code_file + reload)
      └── Else: Show app launcher UI
          ├── Discover apps in /apps/
          ├── Display launcher on LCD (icons + scrolling names)
          ├── Display "Select An App" on EPD with button labels
          └── Wait for button events:
              ├── S4 released → next app
              ├── S7 released → launch app
              └── S6 released → reset
```

### App Lifecycle

```
Launcher running
  │
  │ S7 pressed (launch app)
  ▼
launcher.launch_app(app)
  ├── Read app's boot.json for config overrides
  ├── Store config + next_code_file in NVM
  └── microcontroller.reset()
  │
  ▼
Reboot → boot.py → code.py → launcher.run()
  ├── Detects next_code_file in NVM
  └── supervisor.set_next_code_file(code_file) + supervisor.reload()
  │
  ▼
App code.py runs
  ├── App executes (game, utility, etc.)
  └── App exits (microcontroller.reset() or sys.exit())
  │
  ▼
Reboot → boot.py → code.py → launcher.run()
  ├── NVM config cleared (set_config() with defaults)
  └── Show launcher UI
```

### Async Event System

The badge uses a cooperative async model built on `asyncio`. The event system provides `Event` objects (with `fire()`/`wait()`), the `@on()` decorator for callback registration, and pre-defined button/system event constants. Button polling and event generation are handled by the `buttons` and `events` modules — see [Badge Hardware Modules](BADGE_MODULES.md#eventspy) for the full event API and [Badge Hardware Modules](BADGE_MODULES.md#buttonspy) for button polling.

A typical app's `main()` function (`evt` here is the module alias from
`import badge.events as evt` — there is no `evt` object to import):
```python
async def main():
    # Start button polling
    button_tasks = badge.buttons.all_tasks(interval=0.05)
    # Start event callbacks
    evt_tasks = evt.start_tasks()
    # Run app logic
    app_task = asyncio.create_task(app_main_loop())
    # Gather all tasks
    await asyncio.gather(*button_tasks, *evt_tasks, app_task)
```

### NVM Persistent Storage

The badge uses ESP32 non-volatile memory (NVM) for persistent configuration across reboots. The NVM module implements a key-value store with a memory block allocator and automatic compaction. Used by the launcher to store `BOOT_CONFIG` (which app to launch, filesystem options). For the complete NVM API (save, open, free, compact, format) and internal layout details, see [Shared Library Modules](LIB_MODULES.md#badge_nvmpy). The underlying memory block allocator is documented in [Shared Library Modules](LIB_MODULES.md#memory_blockpy).

### Display Rendering

Both displays use CircuitPython's `displayio` system:

```python
from displayio import Group, Bitmap, TileGrid, Palette

# Create a group (layer)
group = Group()

# Add a background
bg = Bitmap(128, 128, 1)
palette = Palette(1)
palette[0] = 0x3453FF  # Site blue
group.append(TileGrid(bg, pixel_shader=palette))

# Add text
from adafruit_display_text.label import Label
from terminalio import FONT
label = Label(font=FONT, text="Hello", color=0xFFFFFF)
label.x = 10
label.y = 20
group.append(label)

# Set as root group
LCD.root_group = group  # LCD auto-refreshes
EPD.root_group = group  # EPD needs EPD.refresh()
```

The `screens` module provides helper functions for common display tasks (centering text, wrapping text, creating rounded buttons, setting backgrounds, printing exceptions). See [Badge Hardware Modules](BADGE_MODULES.md#screenspy) for the complete function reference and usage examples.

A reusable scrollable selection list UI component is available via the `scrollable_list` module. See [Shared Library Modules](LIB_MODULES.md#scrollable_listpy) for the complete API and usage examples.

### WiFi Communication

The `WIFI` class manages WiFi connection, HTTPS session creation, and server communication. It handles WiFi connection with retry attempts, socket pool management, SSL context, and provides status feedback on the LCD during connection. For the complete `WIFI` class API (constructor parameters, properties, methods, custom exceptions) see [Badge Hardware Modules](BADGE_MODULES.md#wifipy).

```python
wifi = WIFI()
if wifi.connect_wifi():
    response = wifi.requests(
        method='GET',
        url=wifi.host + 'badge/hello',
        headers={'Content-Type': 'application/json'},
        json={'uniqueID': secrets.UNIQUE_ID}
    )
```

### File Download and Storage Sync

The `utils` module provides a legacy `download_file()` function that streams App Store files from `/badge/download` in 8 KB chunks and creates directories as needed. The `storage_sync` module provides the Storage app's `/badge/storage/*` backup and restore workflows, including SHA-256 manifests, default `.mpy` skipping with user opt-in, bytecode/cache ignore rules, text/base64 upload, streamed restore downloads, transfer progress callbacks, and phase status callbacks for long-running scan/hash/server-check steps. See [Badge Hardware Modules](BADGE_MODULES.md#utilspy), [Badge Hardware Modules](BADGE_MODULES.md#storage_syncpy), and [Storage Transfer Module](apps/storage-transfer.md) for details.

### Shared Badge Modules

Reusable badge behavior should live in shared modules instead of being duplicated inside a single app. Use `src/badge/` for core badge/framework behavior such as hardware abstraction, launcher integration, display helpers, button/event handling, WiFi, and filesystem utilities. Use `badgelibs/` for reusable library-style code that apps can import directly, such as NVM helpers, QR bitmap generation, or generic UI components — those are compiled into `src/lib/*.mpy`, so **edit `badgelibs/`, never `src/lib/`**.

When a helper under `src/apps/<app_name>/` grows beyond app-specific behavior, evaluate extracting it into `src/badge/` or `src/lib/`. After extraction, inspect existing apps and badge modules for duplicate call sites and update [Badge Hardware Modules](BADGE_MODULES.md), [Shared Library Modules](LIB_MODULES.md), or app development guidance as appropriate. Keeping shared behavior out of app payloads reduces duplicated source, keeps deployed app files smaller, and makes firmware behavior easier to maintain.

## Configuration

### `secrets.py`

Per-badge file with WiFi credentials, server URL, and the badge's unique ID:

```python
WIFI_NETWORK = "os2025-badge"
WIFI_PASS    = "supersecretpassword"
HOST_ADDRESS = 'https://badger.becomingahacker.com/'
UNIQUE_ID = '<token_from_server>'  # Added by get_token.py
```

### `badge/constants.py`

Hardware constants (screen dimensions, bounding-box indices), color constants, and boot configuration defaults. See [Badge Hardware Modules](BADGE_MODULES.md#constantspy) for the complete constant listing.

### `badge/colors.py`

Additional color constants, including `SITE_RED = 0xEF4A24`. See [Badge Hardware Modules](BADGE_MODULES.md#colorspy) for details.

## Memory Considerations

- **CircuitPython heap**: ~**8.2 MB**, because the module's 8 MB octal PSRAM is
  enabled and `port_malloc()` allocates from PSRAM first. Check with
  `gc.mem_free()`.
  - **Sanity check:** if `gc.mem_free()` reports only ~105 KB, the firmware was
    built *without* PSRAM (the internal SRAM heap). That is a build
    misconfiguration — verify `CIRCUITPY_ESP_PSRAM_SIZE = 8MB` /
    `_MODE = opi` / `_FREQ = 80m` in `firmware/offsummit_2026/mpconfigboard.mk`.
    Do not work around it in application code.
  - TLS buffers also come from PSRAM (`MBEDTLS_EXTERNAL_MEM_ALLOC=y`).
- **NVM**: Very small (~a few KB). Only store config, not data.
- **Flash filesystem**: 16 MB total, shared with CircuitPython. Use `badge/fileops.py:freespace()` to check.
- **Compiled libraries**: `src/lib/*.mpy` is **build output**, not source. Our own
  libraries live as plaintext in `badgelibs/` and are compiled by
  `docker/tools/build-badgelibs.sh` (~43 KB of `.py` -> ~15 KB of `.mpy`), which
  also avoids compiling them on the device at import time. Editing `src/lib/*.mpy`
  directly is pointless — it is overwritten by the next libs build.
  `src/badge/` and `src/apps/` stay plaintext on purpose so users can read and
  hack them on the badge.
- **`.mpy` tracebacks** report the compile-time source path, e.g.
  `File "/work/badgelibs/badge_nvm.py"`. That is the container path from the build,
  and it points at the real source file.

## Power Management

The badge uses light sleep for power conservation in some apps:

```python
import alarm
pin_alarm = alarm.pin.PinAlarm(pin=board.BTN4, value=False, pull=True)
triggered = alarm.light_sleep_until_alarms(pin_alarm)
```

This allows the badge to wake on button press while conserving power.
