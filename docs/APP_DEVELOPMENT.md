# App Development — Technical Reference

Dense reference for writing apps for the Offensive Summit 2026 badge. Every API
signature and behavior below was verified against `src/badge/` and `src/apps/`.
For prose-style introductions see the [wiki](https://github.com/Cisco-Offensive-Summit/badge-2026/wiki/Apps); for
module-by-module APIs see [BADGE_MODULES.md](BADGE_MODULES.md) and
[LIB_MODULES.md](LIB_MODULES.md).

**Read [Pitfalls](#pitfalls) before writing code.** Most of that section
documents behavior that is surprising, silently wrong, or unrecoverable at
runtime.

---

## 1. App Contract

An app is a directory under `/apps/`. The launcher enumerates it via
`badge.app.get_app_list()`.

| File | Required | Purpose |
|---|---|---|
| `code.py` | **Yes** | Entry point. `App.code_file` returns `None` without it. |
| `metadata.json` | **Yes** | Launcher display data. `App.metadata_json` raises if absent. |
| `icon.bmp` | No | 128×76 BMP. Falls back to `/badge/img/app-default.bmp`. |
| `boot.json` | No | Boot-config overrides (filesystem mount options). |

Directories whose name begins with `_` are **skipped** by `get_app_list()`.
Rename `apps/totris` → `apps/_totris` to hide an app during development; reset
the badge afterwards so the launcher rescans.

### `metadata.json`

```json
{
  "app_name": "My App",
  "author": "handle",
  "info": "Shown in the App Store detail view.",
  "sort": "-"
}
```

`sort` is optional and only consulted for leaderboard apps (`"+"` ascending,
`"-"` descending).

### `icon.bmp`

Must be **exactly 128×76** (`ICON_W`/`ICON_H` in `badge/launcher.py`). The
launcher swaps the `TileGrid` bitmap in place when scrolling the app list, so a
differently sized icon corrupts the UI rather than merely looking wrong. Use a
palletized BMP (1-bit or indexed).

### `boot.json`

```json
{ "mount_root_rw": true, "disable_usb_drive": true }
```

Required for any app that writes to the filesystem. `mount_root_rw` forces
`disable_usb_drive` — the badge cannot expose CIRCUITPY as mass storage and
write to it from firmware simultaneously. `App.boot_config` injects the app's
own directory as `loaded_app` automatically.

- `mount_root_rw`: Remount the filesystem as writable (needed for apps that write files, such as Storage restore)
- `disable_usb_drive`: Disable USB drive access (required when `mount_root_rw` is true)
- `loaded_app`: Automatically set to the app's directory path by `App.boot_config`

---

## 2. Lifecycle

Apps run **exclusively**. There is no multitasking, no background launcher, and
no supervisor loop reclaiming your app. When your app runs, it owns the device.

```
launcher (BTN_D) → write boot config + next_code_file to NVM → microcontroller.reset()
  → boot.py reads NVM, applies mount options
  → code.py → badge.launcher.run() sees next_code_file → exec app code.py
  → app runs until microcontroller.reset() or sys.exit()
  → boot.py clears config → launcher UI
```

Exit with **`microcontroller.reset()`**. This is the only reliable return to the
launcher, because the boot-config NVM state is cleared on the next boot pass.
`sys.exit(0)` unwinds to the launcher process but leaves mount options and NVM
config from `boot.json` in effect.

Every app should begin with:

```python
import supervisor
supervisor.runtime.autoreload = False
```

Without it, any host write to CIRCUITPY restarts your app mid-execution — and
during an EPD refresh that can leave the panel in a half-driven state.

---

## 3. Input Models

Pick **one** of the two models below. They are mutually incompatible.

### Model A — asyncio event system (interactive apps)

```python
import asyncio
import badge.events as evt                     # module alias, not an object
from badge.buttons import all_tasks, any_button_downup
from badge.events import on, BTN_A_DOWNUP

@on(BTN_A_DOWNUP)              # must be at module level, before start_tasks()
def handle_a(event):
    ...

async def main():
    all_tasks(interval=0.05)   # button polling + downup synthesis
    evt.start_tasks()          # coroutines registered by @on
    while True:
        btn = await any_button_downup()
        ...
```

### Model B — `alarm` light sleep (low-power, poll-free apps)

```python
import alarm, board
s4 = alarm.pin.PinAlarm(pin=board.BTN4, value=False, pull=True)
s7 = alarm.pin.PinAlarm(pin=board.BTN1, value=False, pull=True)
triggered = alarm.light_sleep_until_alarms(s4, s7)
if triggered.pin == s7.pin:
    microcontroller.reset()
```

`light_sleep_until_alarms()` halts the CPU, which stops the asyncio scheduler
dead. Do not mix it with Model A — your button tasks will not run and events
will never fire. `apps/hello` is the reference for Model B; `apps/blink` and
`apps/simon` for Model A.

### Button identity mapping

Three naming schemes exist and **they are not aligned**. This is the single most
common source of inverted controls:

| Logical event | `badge.buttons` getter | Board pin | Silkscreen | NeoPixel |
|---|---|---|---|---|
| `BTN_A_*` | `a_pressed()` | `board.BTN4` | **S4** | `"a"` / `NP[0]` |
| `BTN_B_*` | `b_pressed()` | `board.BTN3` | **S5** | `"b"` / `NP[1]` |
| `BTN_C_*` | `c_pressed()` | `board.BTN2` | **S6** | `"c"` / `NP[2]` |
| `BTN_D_*` | `d_pressed()` | `board.BTN1` | **S7** | `"d"` / `NP[3]` |

The board-pin ordering is **reversed** relative to the logical letters
(`buttons[3]` backs `BTN_A`). Always reach for `BTN_A_DOWNUP` and friends in app
code; only touch `board.BTNn` when constructing a `PinAlarm`, and cross-check
this table when you do. Buttons are active-low with `Pull.UP`, hence
`value=False` in the alarm and `not buttons[n].value` in the getters.

### Event semantics

`Event.fire()` calls `set()` immediately followed by `clear()`:

```python
def fire(self, data=None):
    self.data = data
    self._event.set()
    self._event.clear()
```

Consequences:

- **Events are not latched or queued.** Only coroutines already parked in
  `await evt.wait()` at the instant of the fire observe it. A press that lands
  while your loop is inside a blocking call is lost forever.
- **Events are module-level singletons.** All handlers see the same instance, and
  `event.data` is overwritten by the next fire. Copy anything you need out of
  `event.data` synchronously.
- `fire()` with no argument sets `self.data = None` (not `{}`, despite the
  guard above it) — use `event.data.get(...)` only when you know a producer
  passed data. `any_button_downup()` handles this for you and returns the
  triggering `Event` or `None`.

---

## 4. Displays

Both screens are initialized at import of `badge.screens`, which runs
`_init_screens(fast_mode=True)` at module scope. Importing `badge.screens`
therefore has hardware side effects: it calls `release_displays()`, reads the
EPD OTP, and claims the shared SPI bus.

| | LCD | EPD |
|---|---|---|
| Object | `ST7735R` | `SmartEPD` wrapping `PervasiveWideSmall` |
| Size | 128×128 | 264×176 (logical landscape) |
| Update | immediate on `root_group` assignment | requires explicit `refresh()` |
| Use for | animation, menus, live state | static content, labels, final scores |

The EPD's logical 264×176 already accounts for `rotation=270` against the
physical 176×264 RAM. Do **not** pre-rotate coordinates.

### EPD refresh model

`EPD` is a `SmartEPD`, constructed with `fast_mode=True`. Timings from
`pervasive_epd.py`: `SECONDS_PER_FRAME = 40`, `FAST_SECONDS_PER_FRAME = 0.5`.

| Call | Behavior | Cost |
|---|---|---|
| `EPD.refresh()` | slow on first call (primes the fast buffer), fast thereafter | ~2.5 s then ~0.9 s |
| `EPD.slow_refresh()` | always full refresh; re-primes | ~2.5 s |
| `EPD.fast_refresh()` | always fast; auto-primes with a slow refresh if needed | ~0.9 s |

- **Never gate a fast refresh on `EPD.time_to_refresh`.** That property only
  ever reports the *normal* 40 s interval, so waiting on it stalls 40 seconds
  for a refresh that needed 0.5. `SmartEPD` already waits out the correct
  interval internally — just call `refresh()`.
- All refresh paths are **blocking** (`time.sleep`), so they starve the asyncio
  loop and drop button events for their whole duration. Refresh the EPD at
  natural pauses, not inside a hot loop.
- `SmartEPD.__getattr__` proxies unknown attributes to the driver, so
  `EPD.width`, `EPD.busy`, and `EPD.root_group` all behave normally.

### Group management

`clear_screen(screen)` and `set_background(screen, color)` both **assign a brand
new `Group`** to `screen.root_group`. They do not mutate the existing group.

```python
# WRONG — group is detached from the display; nothing renders
group = LCD.root_group
clear_screen(LCD)
group.append(label)

# RIGHT — build after clearing
clear_screen(LCD)
LCD.root_group.append(label)
```

`set_background()` must be called *before* appending anything, or it discards
the children you just added. `epd_print_exception()` assigns a bare `Label` to
`EPD.root_group`, replacing your entire display.

### Text helpers

```python
center_text_x_plane(screen, text_or_label, y=None, scale=1, color=WHITE) -> Label
center_text_y_plane(screen, text_or_label, x=None, scale=1, color=WHITE) -> Label
center_label_x_plane(screen, lb) -> None    # mutates lb.x
center_label_y_plane(screen, lb) -> None    # mutates lb.y
wrap_message(screen, message, font=FONT, x=0, y=None, scale=1) -> Label
round_button(label, x, y, rad, color=None, fill=None, stroke=1) -> Group
```

The `center_text_*` pair accepts either a `str` or a `Label`. **When you pass a
`Label`, the `scale` argument is ignored** — the function re-reads `label.scale`.
Set scale on the label itself:

```python
lb = Label(font=FONT, text="Score", scale=3)   # not center_text_x_plane(..., scale=3)
center_label_x_plane(LCD, lb)
```

Compose the two axes by nesting, since each returns the label:
`center_text_y_plane(EPD, center_text_x_plane(EPD, "Hi", scale=3))`.

`wrap_message()` preserves explicit newline breaks, wraps text to the available
screen width from `x`, and splits long unbroken words such as file paths so they
stay on-panel.

For `round_button`, `x` is the left edge of the *text* and `y` its vertical
center; the rounded rect is derived outward by `rad`. Labels near the right edge
need manual nudging — see the `NUDGE` comment in `apps/blink/code.py` for a
worked example of keeping labels on-panel.

---

## 5. NeoPixels

```python
from badge.neopixels import NP, set_neopixel, set_neopixels, neopixels_off

set_neopixel("a", 0xFF0000)                    # by letter, see button table
set_neopixels(0xFF0000, 0x00FF00, 0, 0)        # a, b, c, d — omitted default OFF
neopixels_off()
NP[0] = 0xFF0000                               # direct index
```

`NP` is created with `brightness=0.05` and `auto_write=True`. The low default is
deliberate: four LEDs at full brightness is a meaningful current draw on battery
and will brown out the badge under a marginal supply. Raise brightness only
briefly and never leave all four saturated. Because `auto_write=True`, explicit
`NP.show()` is unnecessary (harmless if present, as in `apps/hello`).

Always `neopixels_off()` before exiting — the LEDs latch and would otherwise
stay lit under the launcher.

---

## 6. Networking

```python
from badge.wifi import WIFI

wifi = WIFI()
if wifi.connect_wifi():
    rsp = wifi.requests(method='GET', url=wifi.host + 'badge/schedule',
                        headers={'Accept': 'application/json'},
                        json={'uniqueID': secrets.UNIQUE_ID})
    if rsp.status_code == 200:
        data = rsp.json()
    rsp.close()
```

Hard constraints, learned the hard way in `apps/hello`:

- **lwIP has 8 sockets total, device-wide.** Leaking them bricks networking
  until reset.
- **Create exactly one `SocketPool`.** Each new pool leaks a
  `ConnectionManager`. Cache it at module scope.
- **Always `rsp.close()`**, in a `finally` if there is any branch. Streamed
  responses (`stream=True`) self-close *only* if fully consumed.
- To recover after an error, `session = None` is **not** sufficient — it strands
  sockets in the cached manager. Use
  `connection_manager_close_all(pool, release_references=False)`.
  `release_references=True` raises `KeyError` on a pool you created yourself.
- Resolve `secrets` lazily inside `main()`, not at import. A missing or
  half-provisioned `secrets.py` then raises where your handler can draw the
  traceback to the EPD, instead of dying at import with a blank screen.

Treat any network failure as recoverable: report on the **LCD** and let the user
retry, so the EPD keeps whatever it was showing.

### Helpers

```python
from badge.utils import download_file, gen_qr_code
download_file("apps/myapp/code.py", wifi)   # creates parent dirs, syncs, -> bool
gen_qr_code("https://...", LCD)             # replaces screen.root_group
```

`gen_qr_code` is hardcoded to QR version 4 / ECC level `L` — roughly 78 bytes of
payload. Longer strings raise inside `adafruit_miniqr`; shorten the URL or use a
redirect. It also scales to fit and **replaces `root_group`**, so append nothing
beforehand.

---

## 7. Persistence

| Mechanism | Use for | Notes |
|---|---|---|
| `badge_nvm` (`nvm_save`/`nvm_open`/`nvm_free`) | small config, cross-reboot flags | A few KB total. `nvm_open` raises `ValueError` when the key is absent. |
| JSON file on CIRCUITPY | app state, cached API responses | Requires `mount_root_rw` in `boot.json`; call `os.sync()` after writing. |
| `secrets.py` | badge identity | **Never write or erase.** Holds `UNIQUE_ID`. |

NVM is shared across the whole badge — namespace your keys with the app name.

### Leaderboards

```python
from leaderboard import post_to_leaderboard
try:
    post_to_leaderboard(score)
except Exception as e:
    print("leaderboard post failed:", e)
```

`post_to_leaderboard` draws its own UI and needs WiFi, a valid `UNIQUE_ID`, and
the app registered in the server's `BadgeApp` table. Submissions carry an
anti-cheat hash of the app source, so a locally modified app is flagged as
cheating. A failed post must never end the game — wrap it, as `apps/simon` does.

---

## 8. Available Libraries

Do not add dependencies. Per the repo rules, any new library needs operator
approval.

**Frozen into firmware** (`mpconfigboard.mk`): `adafruit_display_text`,
`adafruit_display_shapes`, `adafruit_requests`, `adafruit_bus_device`,
`adafruit_register`, `adafruit_progressbar`, `adafruit_ble`, `adafruit_motor`,
`adafruit_simpleio`, `neopixel`, `asyncio`, `adafruit_irremote`, `adafruit_wave`,
`adafruit_rfm69`, `adafruit_rfm9x`, `stage`.

**Shipped as `.mpy` in `src/lib/`**: `adafruit_bitmap_font`,
`adafruit_imageload`, `adafruit_led_animation`, `adafruit_hashlib`,
`adafruit_miniqr`, `adafruit_st7735r`, `adafruit_ticks`,
`adafruit_connection_manager`, plus our own `badge_nvm`, `leaderboard`,
`get_token`, `memory_block`, `scrollable_list`, `flavortext`, `QRBitmap`,
`Base64Wrapper`.

`src/lib/` `.mpy` files are built from `badgelibs/*.py`, which remain the source
of truth — map any `.mpy` traceback back to those. `src/badge/` and `src/apps/`
stay plaintext by design; never compile them.

---

## 9. Pitfalls

Ordered roughly by how much time each one costs when hit.

1. **`all_tasks(interval=...)` silently ignores its argument.**
   ```python
   def all_tasks(interval=0.0):
       return start_tasks() + start_downup_tasks()   # interval never forwarded
   ```
   Press/release polling always runs at `interval=0.0`, i.e. a tight yield loop,
   no matter what you pass. If you need real debounce spacing, call
   `badge.buttons.start_tasks(interval=0.05)` and
   `start_downup_tasks()` yourself. `apps/blink` does exactly this.

2. **Blocking calls eat button presses.** EPD refreshes, `time.sleep`, and
   synchronous HTTP all block the single asyncio loop, and events fired during
   that window are dropped (see §3). Use `await asyncio.sleep()`, and expect to
   re-prompt the user after a refresh.

3. **`clear_screen()` / `set_background()` replace `root_group`.** Any `Group`
   reference held across the call is detached and renders nothing. Build display
   groups after clearing.

4. **Logical button letters are reversed relative to `board.BTNn`.** `BTN_A` is
   `board.BTN4`. Getting this wrong inverts your controls in a way that looks
   like a hardware fault. See the table in §3.

5. **`center_text_*(scale=N)` is ignored for `Label` inputs.** Set `scale` on the
   `Label` constructor instead.

6. **`App.boot_config` aliases `DEFAULT_CONFIG` instead of copying it.**
   `new_config = DEFAULT_CONFIG` then mutates it, so reading one app's boot
   config permanently pollutes the module-level default for every app inspected
   afterwards in the same session. Do not rely on `DEFAULT_CONFIG` being
   pristine; treat any config you read as possibly carrying another app's keys.

7. **Writing files without `mount_root_rw` raises `OSError: Read-only
   filesystem`** — and only at the moment of the write, which is often deep in a
   save path. Declare it in `boot.json` up front.

8. **`icon.bmp` must be exactly 128×76.** Other sizes break the launcher's
   in-place bitmap swap.

9. **Socket exhaustion is not self-healing.** Eight sockets, leaked pools, and
   unclosed responses (§6) produce failures that persist until a reset and look
   like server problems.

10. **`sys.exit()` leaves boot config applied.** Use `microcontroller.reset()`.

11. **`import badge.screens` has side effects** — it releases displays and grabs
    SPI at import time. Import it once, at the top, like every existing app.

12. **Don't wait on `EPD.time_to_refresh`** before a fast refresh; it reports the
    40 s normal interval (§4).

13. **`from badge.events import evt` does not work.** There is no `evt` object —
    `evt` is the conventional *module alias* (`import badge.events as evt`).
    Likewise `any_button_downup` is defined in **`badge.buttons`**, not
    `badge.events`, even though it awaits an event. Both mistakes fail at import
    on the app's first line, so they are cheap to find but easy to copy from
    older snippets.

---

## 10. Skeletons

### Minimal, single keypress

```python
import asyncio, microcontroller, supervisor
import badge.events as evt
from badge.buttons import all_tasks, any_button_downup
from badge.screens import (EPD, clear_screen, center_text_x_plane,
                           center_text_y_plane, epd_print_exception)

supervisor.runtime.autoreload = False

clear_screen(EPD)
EPD.root_group.append(
    center_text_y_plane(EPD, center_text_x_plane(EPD, "Hello!", scale=3)))
EPD.refresh()

async def main():
    all_tasks()
    evt.start_tasks()
    await any_button_downup()
    microcontroller.reset()

try:
    asyncio.run(main())
except Exception as e:
    epd_print_exception(e)
```

### Interactive app with explicit task control

```python
import asyncio, microcontroller, supervisor
import badge.buttons
import badge.events as evt
from badge.constants import BLACK
from badge.events import BTN_A_DOWNUP, BTN_D_DOWNUP
from badge.buttons import any_button_downup
from badge.neopixels import neopixels_off, set_neopixel
from badge.screens import (LCD, EPD, clear_screen, set_background,
                           center_text_x_plane, epd_print_exception)

supervisor.runtime.autoreload = False

def draw_static():
    set_background(EPD, BLACK)                     # first — replaces root_group
    EPD.root_group.append(center_text_x_plane(EPD, "My Game", y=10))
    EPD.refresh()                                  # slow once, fast afterwards

async def main():
    draw_static()
    badge.buttons.start_tasks(interval=0.05)       # not all_tasks(interval=...)
    badge.buttons.start_downup_tasks()
    evt.start_tasks()

    score = 0
    while True:
        clear_screen(LCD)
        LCD.root_group.append(center_text_x_plane(LCD, f"Score: {score}", y=60))
        btn = await any_button_downup()
        if btn is BTN_D_DOWNUP:                    # S7 — quit
            break
        if btn is BTN_A_DOWNUP:                    # S4 — action
            score += 1
            set_neopixel("a", 0x00FF00)
    neopixels_off()
    microcontroller.reset()

try:
    asyncio.run(main())
except Exception as e:
    epd_print_exception(e)                         # traceback persists on EPD
```

Wrapping `asyncio.run` is mandatory in practice: without it a crash leaves the
badge blank with no indication of what failed, and the user has no serial
console.

---

## 11. Debugging

```bash
screen /dev/tty.usbmodem* 115200      # macOS
screen /dev/ttyACM0 115200            # Linux
```

```python
from badge.log import log, dbg
log("my_app", "started")   # -> [*] [my_app][started]
dbg("detail")              # suppressed unless DEBUG=True in badge/log.py
```

`badge.log.info(interval)` is a coroutine that periodically logs loop latency
and `gc.mem_free()` — useful for spotting a starved event loop. Expect
`mem_free()` in the millions; ~105 KB means the firmware was built without
PSRAM and that, not your app, is the bug.

`epd_print_exception(e)` renders a 2-frame truncated traceback to the EPD, which
survives a crash and a power loss.

Prefer `mpremote run` for throwaway test scripts so CIRCUITPY is never mounted.
If it *is* mounted on the badge-jumper Pi, `sync` and `umount` before any reset —
see the repo `AGENTS.md` RULE 2. Two writers on one FAT volume corrupts it.

---

## 12. Reference Apps

| App | Demonstrates |
|---|---|
| `apps/blink` | Event decorators, explicit task control, correct `interval` handling, EPD button labels |
| `apps/hello` | Light-sleep input model, socket/session hygiene, recoverable network errors, custom font loading |
| `apps/simon` | Async game loop, NeoPixel feedback, non-fatal leaderboard submission |
| `apps/register` | WiFi + server API, QR display, pin-alarm wake |
| `apps/appStore` | Multi-page UI, file download and install, app deletion |

---
