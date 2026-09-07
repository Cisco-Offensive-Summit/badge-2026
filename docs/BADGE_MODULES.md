# Badge Hardware Modules (`src/badge/`)

This document describes each module in the `src/badge/` directory. These modules provide the hardware abstraction layer for the badge — they handle physical components such as the LCD and E-Ink screens, tactile buttons, NeoPixel LEDs, WiFi radio, and related subsystems. Apps and the launcher import from these modules to interact with the badge hardware.

---

## Quick Reference

| Module | Purpose |
|---|---|
| [`screens.py`](#screenspy) | LCD and E-Ink display initialization, text helpers, UI primitives, exception display |
| [`buttons.py`](#buttonspy) | GPIO button polling, press/release event generation |
| [`events.py`](#eventspy) | Async event system (Event class, `@on` decorator, button events) |
| [`neopixels.py`](#neopixelspy) | 4× WS2812 NeoPixel control |
| [`wifi.py`](#wifipy) | WiFi connection, HTTPS session management, server communication |
| [`storage_sync.py`](#storage_syncpy) | Server-backed badge storage backup/restore helpers |
| [`launcher.py`](#launcherpy) | App launcher UI, app discovery, boot/NVM configuration, app lifecycle |
| [`launcher_ui.py`](#launcher_uipy) | Alternative launcher UI components (legacy/experimental) |
| [`app.py`](#apppy) | App discovery and metadata loading |
| [`constants.py`](#constantspy) | Screen dimensions, bounding-box indices, color constants, boot config defaults |
| [`colors.py`](#colorspy) | Color constants (hex values) |
| [`utils.py`](#utilspy) | QR code generation, file download, PWM pin listing, directory creation |
| [`fileops.py`](#fileopspy) | Filesystem helpers (is_dir, is_file, freespace) |
| [`log.py`](#logpy) | Logging utilities (log, dbg, async info) |
| [`ziplist.py`](#ziplistpy) | Circular list with current position (used by launcher navigation) |

---

## screens.py

Display initialization and UI helper functions for both the LCD (TFT) and EPD (E-Ink) screens. This module initializes the displays at import time — the `LCD` and `EPD` globals are ready for use immediately after importing the module.

### Globals

| Name | Type | Description |
|---|---|---|
| `LCD` | `ST7735R` | 128×128 color TFT display. Auto-refreshes. |
| `EPD` | `SmartEPD` (wraps `PervasiveWideSmall`) | 264×176 monochrome E-Ink display. Requires explicit `EPD.refresh()`. |

Both displays share the same SPI bus but have separate CS, DC, and RST pins.

### Functions

| Function | Signature | Description |
|---|---|---|
| `clear_screen` | `(screen)` | Reset a screen's root group to an empty `Group`. |
| `center_text_x_plane` | `(screen, text_or_label, y=None, scale=1, color=WHITE)` | Create or adjust a `Label` so the text is horizontally centered on the screen. Accepts a string (creates a new Label) or an existing Label. |
| `center_text_y_plane` | `(screen, text_or_label, x=None, scale=1, color=WHITE)` | Create or adjust a `Label` so the text is vertically centered on the screen. Accepts a string or an existing Label. |
| `center_label_x_plane` | `(screen, lb)` | Center an existing Label horizontally. The label's scale must be set before calling. |
| `center_label_y_plane` | `(screen, lb)` | Center an existing Label vertically. The label's scale must be set before calling. |
| `wrap_message` | `(screen, message, font=FONT, x=0, y=None, scale=1)` | Wrap text to fit the available screen width from `x`, preserving explicit newlines and splitting long unbroken words/paths. Returns a `Label` with wrapped text. |
| `round_button` | `(label, x, y, rad, color=None, fill=None, stroke=1)` | Build a rounded-rectangle button `Group` around a `Label`. The group must be appended to a screen's root group. |
| `set_background` | `(screen, color)` | Fill the entire screen with a solid color. Must be called before adding other elements (it replaces the root group). |
| `epd_print_exception` | `(e)` | Print a truncated exception traceback to the E-Ink display. Useful for crash visibility since the E-Ink image persists without power. |

### Usage Example

```python
from badge.screens import LCD, EPD, clear_screen, center_text_x_plane, center_text_y_plane, round_button, set_background, epd_print_exception
from terminalio import FONT
from adafruit_display_text.label import Label

# Clear and draw on EPD
clear_screen(EPD)
title = center_text_x_plane(EPD, "My App", scale=2)
EPD.root_group.append(title)
EPD.refresh()

# Draw a button on EPD
btn_label = Label(font=FONT, text="S4 Next")
btn = round_button(btn_label, 10, EPD.height - 15, 5)
EPD.root_group.append(btn)
EPD.refresh()

# Set LCD background
set_background(LCD, 0x3453FF)
```

### Key Behavior Notes

- **LCD auto-refreshes** — changes to `LCD.root_group` appear immediately.
- **EPD requires explicit refresh** — call `EPD.refresh()` after modifying `EPD.root_group`.
- `set_background()` replaces the entire root group; call it first before adding other elements.
- Both `center_text_x_plane` and `center_text_y_plane` accept either a string or a pre-existing `Label` object, making them flexible for different coding styles.

---

## buttons.py

GPIO button polling and event generation for the 4 tactile buttons (labeled S4–S7 on the badge casing). Buttons are polled asynchronously at a configurable interval.

### Button Mapping

| Physical Label | GPIO | Code Name | Polling Function | Event Name |
|---|---|---|---|---|
| S4 (left) | GPIO17 | BTN4 | `a_pressed()` | BTN_A |
| S5 | GPIO16 | BTN3 | `b_pressed()` | BTN_B |
| S6 | GPIO15 | BTN2 | `c_pressed()` | BTN_C |
| S7 (right) | GPIO7 | BTN1 | `d_pressed()` | BTN_D |

Buttons are active-low (pressed = `False`) with pull-up resistors.

### Direct Polling Functions

| Function | Returns | Description |
|---|---|---|
| `a_pressed()` | `bool` | `True` if S4 is currently pressed. |
| `b_pressed()` | `bool` | `True` if S5 is currently pressed. |
| `c_pressed()` | `bool` | `True` if S6 is currently pressed. |
| `d_pressed()` | `bool` | `True` if S7 is currently pressed. |

### Async Functions

| Function | Signature | Description |
|---|---|---|
| `start_tasks` | `(interval=0.0)` | Create asyncio tasks that poll each button and fire press/release events. Returns a list of tasks. |
| `start_downup_tasks` | `(interval=0.0)` | Create asyncio tasks that detect press-then-release (downup) sequences for each button, plus an `ANY_BTN_DOWNUP` aggregate event. Returns a list of tasks. |
| `all_tasks` | `(interval=0.0)` | Convenience function that calls both `start_tasks()` and `start_downup_tasks()`. Returns combined task list. |
| `any_button_downup` | `()` (async) | Await any button press-and-release. Returns the triggering event object (e.g., `BTN_A_DOWNUP`). |
| `get_downup_tasks` | `(interval=0.0)` | Return downup coroutine tasks without creating asyncio tasks (for manual task management). |
| `get_tasks` | `(interval=0.0)` | Return polling coroutine tasks without creating asyncio tasks (for manual task management). |

### Usage Example

```python
import asyncio
from badge.buttons import all_tasks, any_button_downup
import badge.events as evt
from badge.events import BTN_A_DOWNUP, BTN_D_DOWNUP

async def main():
    # Start button polling and event generation
    button_tasks = all_tasks(interval=0.05)
    evt_tasks = evt.start_tasks()

    while True:
        btn = await any_button_downup()
        if btn == BTN_A_DOWNUP:
            print("S4 pressed and released")
        elif btn == BTN_D_DOWNUP:
            break

asyncio.run(main())
```

### Key Behavior Notes

- The `Button` class detects state changes between polls and fires `Event` objects from `events.py`.
- Press events fire on transition to pressed; release events fire on transition to unpressed.
- `ANY_BTN_PRESSED` and `ANY_BTN_RELEASED` aggregate events include `data={"name": button_name}`.
- The `interval` parameter controls polling frequency (default 0.0 = as fast as possible; 0.05 = 20 Hz is typical).

---

## events.py

A lightweight async event system built on `asyncio.Event`. Provides the `Event` class, the `@on` decorator for callback registration, and pre-defined event constants for buttons, WiFi, and other system events.

### Event Class

The `Event` class wraps `asyncio.Event` with a name, optional data payload, and fire/wait semantics.

| Method | Description |
|---|---|
| `fire(data=None)` | Trigger the event. All awaiters are released. `data` is stored on the event for callbacks to read. |
| `wait()` (async) | Block until the event is fired. |
| `data` (property) | Dictionary containing the last data payload passed to `fire()`. |

### Module-Level Functions

| Function | Description |
|---|---|
| `on(event)` | Decorator that registers a callback function to run when the given event fires. Callbacks receive the event as an argument. Must call `start_tasks()` (i.e. `evt.start_tasks()` when imported as `import badge.events as evt`) to activate. |
| `start_tasks()` | Create asyncio tasks for all `@on`-registered callbacks. Returns a list of tasks. |
| `event_sequence(input_events, output_event)` (async) | Wait for events in order, then fire the output event. |
| `any_event(input_events, output_event=None)` (async) | Wait for any one of a list of events to fire. Returns the triggering event. Optionally fires an output event with `data={"event": trigger}`. |

### Pre-Defined Event Constants

**Button events:**

| Event | Description |
|---|---|
| `BTN_A_PRESSED` / `BTN_A_RELEASED` | S4 press / release |
| `BTN_B_PRESSED` / `BTN_B_RELEASED` | S5 press / release |
| `BTN_C_PRESSED` / `BTN_C_RELEASED` | S6 press / release |
| `BTN_D_PRESSED` / `BTN_D_RELEASED` | S7 press / release |
| `BTN_A_DOWNUP` / `BTN_B_DOWNUP` / `BTN_C_DOWNUP` / `BTN_D_DOWNUP` | Button press-then-release sequences |
| `ANY_BTN_PRESSED` / `ANY_BTN_RELEASED` | Any button press / release (data includes `name`) |
| `ANY_BTN_DOWNUP` | Any button downup (data includes the triggering event) |

**System events:**

| Event | Description |
|---|---|
| `WIFI_CONNECTED` / `WIFI_DISCONNECTED` | WiFi connection state changes |
| `DISPLAY_ROTATED` | Display rotation event |
| `LOW_BATTERY` / `BATTERY_READ` | Battery events |
| `WILL_BLOCK` | Blocking operation warning |
| `TCP_CONNECTED` / `TCP_DISCONNECTED` / `TCP_GOT_DATA` | TCP communication events |

### Usage Example

```python
import asyncio
import badge.events as evt
from badge.events import Event, on, BTN_A_PRESSED, any_event

# Define a custom event
MY_EVENT = Event("my-event")

# Register a callback
@on(BTN_A_PRESSED)
def handle_a(event):
    print(f"Button A pressed! Data: {event.data}")
    MY_EVENT.fire(data={"triggered": True})

async def main():
    # Start registered callbacks as asyncio tasks
    evt_tasks = evt.start_tasks()
    
    # Wait for custom event
    await MY_EVENT.wait()
    print("Custom event fired!")

asyncio.run(main())
```

### Key Behavior Notes

- `fire()` sets and immediately clears the underlying `asyncio.Event`, so each fire releases all current awaiters.
- `@on` callbacks run in an infinite `while True` loop — they will be called every time the event fires.
- The decorator returns the original function (not a wrapped one), so the function can still be called directly.
- `any_event()` cancels all waiting sub-tasks once one event triggers.

---

## neopixels.py

Controls the 4× WS2812 NeoPixel LEDs on GPIO5. Default brightness is 0.05 (very dim). The NeoPixel power pin (GPIO48) uses inverted logic.

### Globals

| Name | Type | Description |
|---|---|---|
| `NP` | `NeoPixel` | Direct NeoPixel object (4 pixels, RGB order, auto-write enabled). |

### Functions

| Function | Signature | Description |
|---|---|---|
| `set_neopixel` | `(name: str, val)` | Set one pixel by name (`"a"`=pixel 0, `"b"`=pixel 1, `"c"`=pixel 2, `"d"`=pixel 3). `val` is a 24-bit color int. |
| `set_neopixels` | `(a=OFF, b=OFF, c=OFF, d=OFF)` | Set all 4 pixels at once. Each argument is a 24-bit color int. |
| `neopixels_off` | `()` | Turn all 4 pixels off (set to 0). |
| `neopixel_reinit` | `()` | Reinitialize the NeoPixel object. Fixes state issues after certain operations that conflict with the NeoPixel pin. Returns the new `NP` object. |

### Usage Example

```python
from badge.neopixels import set_neopixel, set_neopixels, neopixels_off, NP

# Set individual LEDs
set_neopixel("a", 0xFF0000)  # Red (S4 side)
set_neopixel("b", 0x00FF00)  # Green
set_neopixel("c", 0x0000FF)  # Blue
set_neopixel("d", 0xFFFF00)  # Yellow

# Set all at once
set_neopixels(0xFF0000, 0x00FF00, 0x0000FF, 0xFFFF00)

# Turn all off
neopixels_off()

# Direct access
NP[0] = 0xFF0000
NP.fill(0x000000)
```

### Key Behavior Notes

- The NeoPixel name-to-index mapping corresponds to the button layout: `a`=S4, `b`=S5, `c`=S6, `d`=S7.
- `auto_write=True` means changes appear immediately without calling `NP.show()`.
- After using PWM or other pin-conflicting operations, call `neopixel_reinit()` to restore NeoPixel functionality.

---

## wifi.py

The `WIFI` class manages WiFi connection, HTTPS session creation, and provides a `requests` method for server communication.

### WIFI Class

#### Constructor

```python
WIFI(ssid=WIFI_NETWORK, passw=WIFI_PASS, host=HOST_ADDRESS, update=True)
```

| Parameter | Default | Description |
|---|---|---|
| `ssid` | `WIFI_NETWORK` from `secrets.py` | WiFi network name. |
| `passw` | `WIFI_PASS` from `secrets.py` | WiFi password. |
| `host` | `HOST_ADDRESS` from `secrets.py` | Server base URL. |
| `update` | `True` | Whether to display status messages on the LCD during connection. |

#### Properties

| Property | Type | Description |
|---|---|---|
| `host` | `str` | Server base URL (e.g., `https://badger.becomingahacker.com/`). |
| `mac` | `str` | MAC address as colon-separated hex string (e.g., `AA:BB:CC:DD:EE:FF`). |
| `ipv4` | `str` or `None` | IP address once connected, `None` before connection. |
| `ssid` | `str` | WiFi SSID (with validation on setter). |
| `passw` | `str` | WiFi password (with validation on setter). |

#### Methods

| Method | Returns | Description |
|---|---|---|
| `connect_wifi()` | `bool` | Connect to WiFi (3 retry attempts). Creates socket pool and HTTPS session on success. Shows status on LCD if `update=True`. |
| `disconnect_wifi()` | `bool` | Disconnect and disable the WiFi radio. |
| `is_connected()` | `bool` | Check if WiFi radio is currently connected. |
| `get_new_session()` | `None` | Close existing session and create a new `adafruit_requests.Session`. |
| `close_session()` | `None` | Close and delete the current requests session. |
| `requests` | callable | Bound `adafruit_requests.Session.request` method for making HTTP/HTTPS calls. |

#### Custom Exceptions

| Exception | Description |
|---|---|
| `WifiSSIDException` | Invalid SSID (empty or wrong type). |
| `WifiPasswordException` | Invalid password (empty or wrong type). |
| `WifiSessionException` | Session pool creation or session request failure. |

### Usage Example

```python
from badge.wifi import WIFI
import secrets

wifi = WIFI()
if wifi.connect_wifi():
    response = wifi.requests(
        method='GET',
        url=wifi.host + 'badge/schedule',
        headers={'Content-Type': 'application/json'},
        json={'uniqueID': secrets.UNIQUE_ID}
    )
    if response.status_code == 200:
        data = response.json()
        response.close()
else:
    print("Could not connect to WiFi")
```

### Key Behavior Notes

- Always call `connect_wifi()` before making server requests — WiFi is not always on.
- The LCD shows status messages during connection (e.g., "Connecting to Wifi", "Creating new SocketPool"). The screen is restored after connection.
- `close_session()` is called internally before creating a new session in `get_new_session()`.
- HTTPS is used with `ssl.create_default_context()`.

---

## storage_sync.py

Shared helpers for the Storage app's server-backed backup and restore workflows. The module scans the badge filesystem, computes MD5 hashes for fast change detection on badge hardware, caches file hashes by size/mtime, filters `.mpy` files by default unless the user opts in, filters Python bytecode/cache artifacts, creates restore destination directories, reports optional LCD status updates for long-running phases, and transfers files through the `/badge/storage/*` API.

### Functions

| Function | Description |
|---|---|
| `build_manifest(root="/", status=None, include_mpy=False)` | Return badge-relative file paths and MD5 hashes for local files, reusing `/.storage_manifest_cache.json` entries when size/mtime are unchanged, optionally reporting scan/hash status; skips `.mpy` files by default. |
| `backup_plan(wifi, status=None, include_mpy=False)` | Compare the local manifest with server storage and return local-only, server-only, and changed file lists. |
| `backup(wifi, progress=None, start=None, error=None, delete_server=True, local_manifest=None, local_only=None, changed=None, status=None, include_mpy=False)` | Upload requested badge files and optionally reconcile server-side deletes. |
| `restore_plan(wifi, status=None, include_mpy=False)` | Fetch the server manifest, compare hashes locally, and return local-only, server-only, and changed file lists. |
| `restore(wifi, progress=None, start=None, error=None, delete_local=False, local_only=None, server_only=None, changed=None, status=None, include_mpy=False)` | Download missing/changed server files and optionally delete badge-only files. |
| `upload_file(wifi, path, expected_hash=None)` | Upload one text or base64 file to server badge storage, optionally reusing the manifest hash. |
| `download_file(wifi, path)` | Stream one server file to the badge and create parent directories as needed. |
| `delete_local_file(path)` | Delete one local badge file when destructive restore sync is confirmed. |
| `is_ignored(path, include_mpy=False)` | Ignore `*.mpy` by default, plus `*.pyc`, `*.pyo`, and `__pycache__/` paths consistently. |

See [Storage Transfer Module](apps/storage-transfer.md) for endpoint details and progress callback behavior.

---

## launcher.py

The app launcher — discovers apps, displays the launcher UI, handles navigation, and manages the app lifecycle via NVM configuration and badge reboots.

### Key Functions

| Function | Signature | Description |
|---|---|---|
| `run()` | `()` | Main launcher entry point. Reads NVM for a stored `next_code_file`; if found, launches that app directly. Otherwise, shows the launcher UI. |
| `launch_app(entry)` | `(entry)` | Store the app's boot config and `next_code_file` in NVM, then reset the badge to launch the app. |
| `get_app_list()` | `()` | Scan `/apps/` for app directories (skips directories starting with `_`). Returns a list of `App` objects. |
| `nvm_store_config(new_boot_config)` | `(new_boot_config)` | Serialize and save boot config to NVM under the `BOOT_CONFIG` key. |
| `set_config(config=None)` | `(config)` | Save boot config to NVM. If no config provided, saves `DEFAULT_CONFIG` (clears the stored next_code_file). |
| `run_at_boot()` | `()` | Read boot config from NVM and apply filesystem options (`mount_root_rw`, `disable_usb_drive`). Called during the boot sequence. |

### LauncherUI Class (defined in launcher.py)

| Method | Description |
|---|---|
| `__init__(cache_bmps=False)` | Initialize the launcher UI on both LCD and EPD. Optionally pre-caches all app bitmaps. |
| `init_lcd(app)` | Build the LCD display structure: blue background, app icon, scrolling name/author label. |
| `init_epd()` | Draw the EPD layout: "Offensive Summit", "Select An App", and S4/S7 button labels. |
| `lcd_change_app(app)` | Update LCD when navigating to a different app. |
| `lcd_animate_label()` (async) | Animate the scrolling label on the LCD. |
| `run()` (async) | Start button polling, event callbacks, and label animation tasks. |

### Button Behavior in Launcher

| Button | Action |
|---|---|
| S4 (BTN_A) press | Light NeoPixel as feedback. |
| S4 (BTN_A) release | Advance to next app in the list; update NeoPixel indicators and LCD. |
| S6 (BTN_C) release | Exit/reset. |
| S7 (BTN_D) release | Launch the currently selected app. |

### App Lifecycle

1. User selects an app in the launcher and presses S7.
2. `launch_app()` stores boot config + `next_code_file` in NVM, then calls `microcontroller.reset()`.
3. Badge reboots → `boot.py` runs → `code.py` → `launcher.run()`.
4. `run()` detects `next_code_file` in NVM and launches the app via `supervisor.set_next_code_file()` + `supervisor.reload()`.
5. App's `code.py` runs.
6. App exits via `microcontroller.reset()` → badge reboots → launcher clears NVM config → shows launcher UI.

### NeoPixel Indicator Pattern

The launcher uses a NeoPixel indicator pattern generated by the `indicators()` generator function. Each app gets a unique pattern of `OFF`, `DIM`, and `BRIGHT` values across the 4 LEDs to provide visual feedback of the current position in the app list.

---

## launcher_ui.py

An alternative/legacy set of launcher UI components. This module contains standalone functions for displaying app icons on the LCD and drawing the EPD launch screen. It appears to be an earlier version of the UI code that has been largely superseded by the `LauncherUI` class in `launcher.py`.

### Functions

| Function | Signature | Description |
|---|---|---|
| `display_lcd_app_icon` | `(app: App)` | Display an app's icon and scrolling name/author label on the LCD. Returns the `ScrollingLabel` object. |
| `draw_epd_launch_screen` | `()` | Draw the "Offensive Summit 2024" launch screen on the EPD with "Select An App" header and S4/S7 button labels. |

### Key Behavior Notes

- Uses `SITE_RED` background instead of the `SITE_BLUE` used in `launcher.py`'s `LauncherUI`.
- References the year "2024" — likely from an earlier badge iteration.
- The `clear_lcd_screen` and `clear_epd_screen` functions it imports may not exist in the current `screens.py` module, suggesting this code is non-functional or requires updates.

---

## app.py

App discovery and metadata loading. Provides the `App` class and a module-level `APPLIST` that scans `/apps/` at import time.

### App Class

| Property | Returns | Description |
|---|---|---|
| `code_file` | `str` or `None` | Path to the app's `code.py`, or `None` if missing. |
| `icon_file` | `str` | Path to the app's `icon.bmp`, or the default icon if missing. |
| `metadata_file` | `str` or `None` | Path to `metadata.json`, or `None` if missing. |
| `metadata_json` | `dict` | Parsed `metadata.json`. Raises `Exception` if the file is missing. |
| `boot_config` | `dict` | Merged boot config: `DEFAULT_CONFIG` updated with the app's `boot.json` (if present), with `loaded_app` set to the app's directory. |
| `app_name` | `str` | The directory name of the app (last path component). |

### Module-Level

| Name | Description |
|---|---|
| `APPS_DIR` | `/apps` — the directory scanned for apps. |
| `DEFAULT_ICON` | `/badge/img/app-default.bmp` — fallback icon path. |
| `APPLIST` | List of `App` objects, populated at import time by `get_app_list()`. |
| `get_app_list()` | Scan `APPS_DIR` for subdirectories (skips those starting with `_`). Returns a list of `App` objects. |

### Key Behavior Notes

- Apps are hidden by prefixing their directory name with `_`.
- `metadata_json` will raise if `metadata.json` is missing — apps should always include this file.
- `boot_config` always includes the `loaded_app` key, even if `boot.json` is absent.

---

## constants.py

Hardware constants, color values, bounding-box indices, and boot configuration defaults.

### Screen Dimensions

| Constant | Value | Description |
|---|---|---|
| `LCD_WIDTH` | 128 | LCD width in pixels. |
| `LCD_HEIGHT` | 128 | LCD height in pixels. |
| `EPD_WIDTH` | 264 | E-Ink width in pixels (logical landscape). |
| `EPD_HEIGHT` | 176 | E-Ink height in pixels (logical landscape). |

The physical panel RAM is 176×264 portrait. The display is created with `rotation=270`, which maps these logical landscape dimensions onto it, so app code does not need to pre-rotate.

### Bounding Box Indices

| Constant | Value | Description |
|---|---|---|
| `BB_X` | 0 | Bounding box X index. |
| `BB_Y` | 1 | Bounding box Y index. |
| `BB_WIDTH` | 2 | Bounding box width index. |
| `BB_HEIGHT` | 3 | Bounding box height index. |

### Color Constants

| Constant | Value |
|---|---|
| `BLUE` | `0x0000FF` |
| `GREEN` | `0x00FF00` |
| `RED` | `0xFF0000` |
| `OFF` | `0x000000` |
| `WHITE` | `0xFFFFFF` |
| `BLACK` | `0x000000` |
| `YELLOW` | `0xFFFF00` |
| `CYAN` | `0x00FFFF` |
| `MAGENTA` | `0xFF00FF` |
| `SITE_BLUE` | `0x3453FF` |

### Boot Config

| Constant | Value | Description |
|---|---|---|
| `LOADED_APP` | `'loaded_app'` | NVM key for the currently loaded app path. |
| `BOOT_CONFIG` | `'config'` | NVM key for the boot configuration. |
| `DEFAULT_CONFIG` | `dict` | Default boot config: `mount_root_rw=False`, `disable_usb_drive=False`, `next_code_file=None`, `loaded_app=None`. |

---

## colors.py

Additional color constants. This module supplements `constants.py` with a few extra colors.

| Constant | Value |
|---|---|
| `BLUE` | `0x0000FF` |
| `GREEN` | `0x00FF00` |
| `RED` | `0xFF0000` |
| `OFF` | `0x000000` |
| `WHITE` | `0xFFFFFF` |
| `BLACK` | `0x000000` |
| `YELLOW` | `0xFFFF00` |
| `CYAN` | `0x00FFFF` |
| `MAGENTA` | `0xFF00FF` |
| `SITE_BLUE` | `0x3453FF` |
| `SITE_RED` | `0xEF4A24` |

### Key Behavior Notes

- `SITE_RED` (`0xEF4A24`) is the only color unique to this module — all others are also defined in `constants.py`.
- This module exists to provide a separate import for code that only needs colors (without pulling in the full constants module).

---

## utils.py

Utility functions for badge apps: QR code generation, file download from the server, PWM pin listing, and directory creation.

### Functions

| Function | Signature | Description |
|---|---|---|
| `gen_qr_code` | `(data, screen)` | Generate a QR code from a string and display it centered on the given screen. Uses `adafruit_miniqr` with type 4 and error correction level L. |
| `download_file` | `(file: str, wifi: WIFI) -> bool` | Download a file from the server via the badge's `/badge/download` endpoint. Streams in 8 KB chunks. Creates directories as needed. Returns `True` on success, `False` on failure. |
| `ensure_dirs_exist` | `(path)` | Create all parent directories for a given file path. |
| `list_pwm_pins` | `()` | Enumerate all board pins and test which support PWM output. Logs results. (Diagnostic utility.) |
| `bitmap_QR` | `(matrix)` | Convert a QR code matrix to a `displayio.Bitmap` with a 2-pixel border. Used internally by `gen_qr_code`. |

### Usage Example

```python
from badge.utils import gen_qr_code, download_file
from badge.wifi import WIFI
from badge.screens import LCD

# Display a QR code
gen_qr_code("https://badger.becomingahacker.com/register?code=ABC123", LCD)

# Download a file
wifi = WIFI()
wifi.connect_wifi()
download_file("apps/myapp/code.py", wifi)  # Saves to /apps/myapp/code.py
```

### Key Behavior Notes

- `gen_qr_code` scales the QR bitmap to fill the screen and centers it.
- `download_file` requires a connected `WIFI` instance and sends the badge's `UNIQUE_ID` in the request body.
- `download_file` calls `os.sync()` after each chunk write to ensure data persistence.

---

## fileops.py

Filesystem helper functions for checking paths and disk space.

### Functions

| Function | Signature | Returns | Description |
|---|---|---|---|
| `is_dir` | `(path)` | `bool` | `True` if the path is a directory. Returns `False` on `OSError`. |
| `is_file` | `(path)` | `bool` | `True` if the path is a file. Returns `False` on `OSError`. |
| `freespace` | `()` | `(size, used, free)` tuple of ints (bytes) | Total, used, and free disk space. Calls `os.sync()` first for accurate results. |
| `diskspace_str` | `()` | `str` | Human-readable disk usage string (e.g., `"512/16384K"`). |

### Usage Example

```python
from badge.fileops import is_dir, is_file, freespace, diskspace_str

if is_dir("/apps"):
    print("Apps directory exists")

if is_file("/secrets.py"):
    print("Secrets file exists")

size, used, free = freespace()
print(f"Free: {free // 1024} KB")
print(diskspace_str())
```

---

## log.py

Logging utilities for debugging and status output via the serial console.

### Functions

| Function | Signature | Description |
|---|---|---|
| `log` | `(*msgs)` | Print a formatted log line: `[*] [msg1][msg2]...`. Always prints. |
| `dbg` | `(*msgs)` | Debug log. Only prints when `DEBUG = True` (module-level flag). |
| `info` | `(interval=1.0)` (async) | Periodically log latency and free memory. Useful for monitoring async performance. |

### Module-Level Flag

| Flag | Default | Description |
|---|---|---|
| `DEBUG` | `True` | Controls whether `dbg()` output is printed. |

### Usage Example

```python
from badge.log import log, dbg

log("my_app", "started")        # Output: [*] [my_app][started]
dbg("debug info")               # Output: [*] [debug info] (only if DEBUG=True)
```

### Key Behavior Notes

- `log` formats each argument in square brackets, making it easy to distinguish multiple fields.
- The async `info()` function measures the actual sleep latency vs. the requested interval, providing insight into event loop responsiveness and memory pressure.

---

## ziplist.py

A circular list data structure that maintains a current position. Used by the launcher for cycling through apps.

### ziplist Class

| Method | Description |
|---|---|
| `__init__(a_list)` | Initialize with a non-empty list. Raises `ValueError` if the list is empty. |
| `current()` | Return the element at the current position. |
| `forward()` | Advance to the next element (wraps to the beginning). |
| `backward()` | Move to the previous element (wraps to the end). |

### Usage Example

```python
from badge.ziplist import ziplist

z = ziplist(["a", "b", "c"])
z.current()   # "a"
z.forward()
z.current()   # "b"
z.forward()
z.current()   # "c"
z.forward()
z.current()   # "a" (wrapped)
z.backward()
z.current()   # "c" (wrapped)
```

### Key Behavior Notes

- The list is circular — `forward()` past the last element wraps to the first; `backward()` before the first element wraps to the last.
- The current position is an integer index, not an iterator, so `current()` can be called repeatedly without advancing.
