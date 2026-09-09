---
name: badge-app-development
description: Build, test, and ship an app for the Offensive Summit 2026 badge (CircuitPython, dual LCD + e-ink displays, 4 buttons, 4 NeoPixels). Use when asked to write a badge app, add a game or tool to the badge, debug a badge app that crashes or has inverted controls, or deploy an app folder to CIRCUITPY.
---

# Badge 2026 App Development

## Overview

A badge app is a folder under `src/apps/` (deployed to `/apps/` on the badge).
The launcher auto-discovers it — there is no registry, no build step, no
compilation. Apps run **exclusively**: when an app runs it owns the device, and
it returns to the launcher by rebooting.

```
src/apps/<appname>/
├── code.py           entry point                (required)
├── metadata.json     name / author / info       (required)
├── icon.bmp          exactly 128x76 BMP         (optional, strongly recommended)
└── boot.json         only if the app writes files
```

Reference docs in this repo (read when you need exact signatures):

| Doc | Contents |
|---|---|
| `docs/APP_DEVELOPMENT.md` | Full technical reference + numbered pitfalls list |
| `docs/BADGE_MODULES.md` | Every function in `badge.screens`, `buttons`, `events`, `neopixels`, `wifi` |
| `docs/LIB_MODULES.md` | `badge_nvm`, `leaderboard`, `QRBitmap`, `scrollable_list` |
| `docs/BADGE_ARCHITECTURE.md` | Boot flow, launcher, NVM boot config |

Wiki (prose walkthroughs):
[Writing Your First App](https://github.com/Cisco-Offensive-Summit/badge-2026/wiki/Writing-Your-First-App),
[Apps](https://github.com/Cisco-Offensive-Summit/badge-2026/wiki/Apps),
[Getting Started](https://github.com/Cisco-Offensive-Summit/badge-2026/wiki/Getting-Started),
[Server API](https://github.com/Cisco-Offensive-Summit/badge-2026/wiki/Server-API).

---

## Workflow

### 1. Scaffold

```bash
mkdir -p src/apps/greeter
cp skills/badge-app-development/template/code.py \
   skills/badge-app-development/template/metadata.json \
   src/apps/greeter/
```

`template/boot.json.example` -> rename to `boot.json` only if the app writes files.

Folder name: short, lowercase, no spaces. The display name comes from
`metadata.json`, not the folder.

`metadata.json`:

```json
{
  "app_name": "Greeter",
  "author": "your_handle",
  "info": "Shown in the App Store detail view."
}
```

Optional `"sort": "-"` biases launcher position (used by leaderboard games only).

### 2. Pick an input model — exactly one

**Model A — asyncio events.** Interactive apps, games, menus. See
`template/code.py`, and `src/apps/blink` / `src/apps/simon` for real examples.

```python
import badge.buttons
import badge.events as evt
badge.buttons.start_tasks(interval=0.05)   # poll pins
badge.buttons.start_downup_tasks()         # synthesize press+release events
evt.start_tasks()                          # run @on(...) handlers
btn = await any_button_downup()
```

**Model B — `alarm.light_sleep_until_alarms()`.** Low-power, poll-free apps that
just wait for a keypress (`src/apps/hello`). Light sleep halts the CPU and kills
the asyncio scheduler — **never mix Model B with Model A.**

### 3. Write `code.py`

Non-negotiables in every app:

```python
import supervisor
supervisor.runtime.autoreload = False      # else host writes restart you mid-refresh

try:
    asyncio.run(main())
except Exception as e:
    epd_print_exception(e)                 # traceback on e-ink, survives power loss
```

Exit with `microcontroller.reset()` after `neopixels_off()`. Never `sys.exit()` —
it leaves the app's boot config applied.

### 4. Icon

Exactly **128x76**. The launcher swaps icon bitmaps in place while scrolling, so
a wrong size corrupts the UI rather than just looking off.

```bash
magick art.png -resize 128x76! -colors 16 BMP3:src/apps/greeter/icon.bmp
```

### 5. Deploy and test

```bash
cp -r src/apps/greeter /Volumes/CIRCUITPY/apps/    # macOS
```

On Linux, or anywhere you mounted CIRCUITPY yourself: `sync` **and unmount it
before resetting the badge.** Two writers on one FAT volume corrupts the filesystem.
Prefer `mpremote run` for throwaway test scripts so the drive is never mounted.

Serial console for `print()` output:

```bash
screen /dev/tty.usbmodem* 115200      # macOS
screen /dev/ttyACM0 115200            # Linux
```

Hide a work-in-progress app from the launcher by renaming it `_greeter`, then
reset.

---

## Hardware model an app must respect

### Two displays, two jobs

| | LCD (`ST7735R`, 128x128) | EPD (e-ink, 264x176) |
|---|---|---|
| Update | immediate on `root_group` assignment | only on explicit `refresh()` |
| Speed | fast | ~2.5 s first refresh, ~0.9 s after |
| Persists without power | no | yes |
| Use for | scores, menus, animation, live state, errors | titles, instructions, button labels, final results |

Rule: **anything that changes goes on the LCD; anything that stays goes on the
e-ink.** EPD refreshes are blocking — they starve the asyncio loop and drop
button presses for their whole duration, so refresh only at natural pauses.
EPD coordinates are already logical landscape; do not pre-rotate.

### Buttons: silkscreen and code disagree

| Silkscreen | Event name | Board pin | NeoPixel |
|---|---|---|---|
| **S4** | `BTN_A_DOWNUP` | `board.BTN4` | `set_neopixel("a", …)` |
| **S5** | `BTN_B_DOWNUP` | `board.BTN3` | `"b"` |
| **S6** | `BTN_C_DOWNUP` | `board.BTN2` | `"c"` |
| **S7** | `BTN_D_DOWNUP` | `board.BTN1` | `"d"` |

Board-pin numbering is **reversed** relative to the logical letters. Use
`BTN_A..BTN_D` in app code; only touch `board.BTNn` when building a `PinAlarm`
(active-low, so `value=False, pull=True`). Inverted controls are almost always
this table.

### NeoPixels

```python
from badge.neopixels import set_neopixel, set_neopixels, neopixels_off
set_neopixel("a", 0xFF0000)
set_neopixels(0xFF0000, 0x00FF00, 0, 0)
neopixels_off()
```

Brightness is 0.05 on purpose — four LEDs at full brightness browns out a
battery-powered badge. Flash bright; never stay bright. Always
`neopixels_off()` before exiting or the LEDs stay lit under the launcher.

---

## Pitfalls — check these before debugging anything

1. **`all_tasks(interval=...)` silently ignores `interval`** and always polls at
   `0.0`. Call `badge.buttons.start_tasks(interval=0.05)` +
   `start_downup_tasks()` yourself.
2. **Button presses are never queued.** Events fire and clear instantly; only
   coroutines already awaiting see them. Anything lost during an EPD refresh,
   `time.sleep`, or a synchronous HTTP call is gone — re-prompt the user. Use
   `await asyncio.sleep()`, never `time.sleep()`.
3. **`clear_screen()` / `set_background()` assign a brand-new `Group`.** A
   `Group` reference held across the call is orphaned and renders nothing.
   Always build the display *after* clearing; call `set_background()` first.
4. **Logical letters are reversed vs `board.BTNn`** (`BTN_A` == `board.BTN4`).
5. **`center_text_*(scale=N)` is ignored when passed a `Label`** — set `scale` in
   the `Label(...)` constructor and use `center_label_x_plane()`.
6. **Writing files without `boot.json`** raises `OSError: Read-only filesystem`
   at the moment of the write, deep in a save path.
7. **`icon.bmp` must be exactly 128x76.**
8. **Networking has 8 sockets device-wide and does not self-heal.** One
   module-scope `SocketPool`, `rsp.close()` in a `finally`, and
   `connection_manager_close_all(pool, release_references=False)` to recover.
9. **`sys.exit()` leaves boot config applied** — use `microcontroller.reset()`.
10. **`import badge.screens` has hardware side effects** (releases displays,
    claims SPI). Import once, at the top.
11. **`from badge.events import evt` does not exist** — `evt` is a module alias:
    `import badge.events as evt`. And `any_button_downup` lives in
    **`badge.buttons`**, not `badge.events`.
12. **Never wait on `EPD.time_to_refresh`** — it reports the 40 s normal
    interval and stalls a refresh that needed 0.5 s. Just call `refresh()`.

Full annotated list: `docs/APP_DEVELOPMENT.md` §9.

---

## Common extras

### Persistence

Small values (high scores, settings) — NVM, no `boot.json` needed:

```python
from badge_nvm import nvm_save, nvm_open
nvm_save("greeter_count", "12")
try:
    v = nvm_open("greeter_count")
except ValueError:
    v = None                       # key absent
```

NVM is a few KB shared badge-wide — namespace keys with the app name.

Files on CIRCUITPY need `boot.json` (`{"mount_root_rw": true,
"disable_usb_drive": true}` — both keys, together) plus `os.sync()` after
writing. With this set the CIRCUITPY drive stops appearing on the host, so copy
files over first. Never write or erase `secrets.py`.

### Networking

```python
from badge.wifi import WIFI
wifi = WIFI()
if wifi.connect_wifi():
    rsp = wifi.requests(method='GET', url=wifi.host + 'badge/schedule',
                        headers={'Accept': 'application/json'})
    try:
        if rsp.status_code == 200:
            data = rsp.json()
    finally:
        rsp.close()
```

Resolve `secrets` lazily inside `main()` so a half-provisioned badge raises where
the handler can draw the traceback. Treat conference WiFi failure as normal:
report on the LCD, leave the e-ink alone, let the user retry.

### Leaderboard

`post_to_leaderboard(score)` draws its own UI, needs WiFi + a valid `UNIQUE_ID` +
server-side app registration, and hashes the app source for anti-cheat (a locally
modified app is flagged). Always wrap it — a failed post must never end the game.

### Libraries and dependencies

Two different rules, depending on where the app is going.

**On your own badge — add whatever you like.** Drop any pure-Python or `.mpy`
CircuitPython library into `/lib/` on CIRCUITPY and import it. Caveats:

- `.mpy` files must be built for the **same CircuitPython major version** as the
  firmware (10.x), or the import fails with a bytecode-version error. When in
  doubt use the `.py` source, or pull the matching bundle release.
- Libraries needing a C extension can't be added this way at all — they have to
  be built into the firmware image (`firmware/offsummit_2026/mpconfigboard.mk`).
- Flash and RAM are finite. Check `gc.mem_free()` if an app starts failing in odd
  places after adding a big dependency.

**For an app submitted to this repo or the App Store — default to what's already
on the badge.** Those apps run on stock firmware on every attendee's badge, so an
import that isn't in `/lib/` crashes the app for everyone else. The available set
is in `docs/APP_DEVELOPMENT.md` §8: libraries frozen into firmware
(`adafruit_display_text`, `adafruit_requests`, `asyncio`, `neopixel`, …) plus the
`.mpy` files shipped in `src/lib/`.

If the app genuinely needs a library that isn't there, **include it in the pull
request** rather than asking first — add it under `src/lib/` and say so in the PR
description, with what it is, where it came from, its license, and why the app
needs it. Adding to `src/lib/` grows the image on every badge, so expect that part
to get the most review attention; a smaller diff or a pure-Python drop-in is an
easier yes. Anything requiring a C extension has to be frozen into firmware
instead, which is a bigger change — raise it as an issue before writing code.

`src/badge/` and `src/apps/` stay plaintext by design; never compile them. The
`.mpy` files in `src/lib/` are built from `badgelibs/*.py`, which remain the
source of truth when mapping a traceback.

---

## Learn from working code

| App | Demonstrates |
|---|---|
| `src/apps/blink` | Event decorators, explicit task control, correct `interval`, EPD button labels |
| `src/apps/hello` | Light-sleep model, socket hygiene, recoverable network errors, custom fonts |
| `src/apps/simon` | Async game loop, NeoPixel feedback, non-fatal leaderboard post |
| `src/apps/register` | Server API, QR display, pin-alarm wake |
| `src/apps/appStore` | Multi-page UI, downloading and installing files |

---

## Contributing an app to the badge

Apps are contributed by **pull request** against
[`Cisco-Offensive-Summit/badge-2026`](https://github.com/Cisco-Offensive-Summit/badge-2026).
There is no submission form and no registry to edit — the launcher discovers
whatever lands in `src/apps/`.

1. Fork the repo and branch off `main`.
2. Add the app as a single new directory, `src/apps/<appname>/`, containing
   `code.py`, `metadata.json`, `icon.bmp`, and `boot.json` if it writes files.
   Keep the change self-contained — don't reformat or refactor existing apps in
   the same PR.
3. If it needs a library that isn't on the badge, add it under `src/lib/` in the
   same PR and call it out in the description (see
   [Libraries and dependencies](#libraries-and-dependencies)).
4. Test on real hardware first, and say so in the PR: which firmware version, and
   that the app launches, exits cleanly to the launcher via
   `microcontroller.reset()`, and leaves no LEDs lit.
5. Open the PR with a short description of what the app does, plus a screenshot or
   photo of both screens if there's anything visual to show. Maintainers review
   from there and may ask for changes.

What review looks at, roughly in order: it doesn't break the launcher or other
apps, it can't wedge the badge (blocking loops, leaked sockets, unhandled
exceptions with no `epd_print_exception`), it behaves on flaky conference WiFi, it
respects the NeoPixel current budget, `icon.bmp` is 128x76, and any new `src/lib/`
addition is justified and licensed compatibly. Run the [ship
checklist](#ship-checklist) before opening the PR and most of this takes care of
itself.

Apps distributed through the **App Store** at the conference are served from the
backend rather than this repo, but they start life as the same PR — get it merged
first.

---

## Ship checklist

- [ ] `metadata.json` has a real name, your handle, a useful `info`
- [ ] `icon.bmp` is exactly 128x76
- [ ] `supervisor.runtime.autoreload = False` at the top
- [ ] One input model only (asyncio events *or* light sleep)
- [ ] Static content on e-ink, changing content on LCD
- [ ] `neopixels_off()` then `microcontroller.reset()` on exit
- [ ] `asyncio.run(main())` wrapped in `try/except epd_print_exception(e)`
- [ ] Every HTTP response closed in a `finally`
- [ ] `boot.json` present *only* if the app actually writes files
- [ ] Comments explain tricky hardware bits only — every byte lives on the badge
