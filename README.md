# Offensive Summit Badge 2026

Custom ESP32-S3 conference badge firmware, built with CircuitPython. The badge connects to Offensive Summit online services over WiFi for account registration, app downloads, schedule access, leaderboards, and RPG combat.

## Hardware

| Component | Specification |
|---|---|
| MCU | ESP32-S3 |
| Flash | 16 MB |
| LCD | 128×128 ST7735R TFT (color) |
| E-Ink | 264×176 Pervasive Displays E2271KS0C1 2.71" EPD (monochrome) |
| Buttons | 4 tactile (labeled S4–S7) |
| LEDs | 4× WS2812 NeoPixels |
| I2C | STEMMA QT connector |
| USB | Programmable (CircuitPython) |
| Wireless | WiFi + ESP-NOW |

## Quick Start

### First Boot (Provisioning)

1. Flash the badge with the CircuitPython firmware (see `firmware/offsummit_2026/`)
2. Copy all files from `src/` to the `CIRCUITPY` USB drive
3. On first boot, the badge will:
   - Connect to the WiFi network specified in `secrets.py`
   - Send its MAC address to the online service to request a `UNIQUE_ID`
   - Display "nobody" on the E-Ink screen (indicating it needs registration)
4. The badge is now ready for account registration

### Registration

1. Open the **Register** app on the badge (it displays a QR code)
2. Scan the QR code with a phone to open the registration page
3. Create an account and enter the 6-character code shown on the badge
4. The badge is now linked to the user's account

### Using the Badge

- **S4** (left button): Next app in the launcher
- **S7** (right button): Launch the selected app
- **S6**: Exit/reset back to launcher

The LCD shows the app launcher with icons and scrolling names. The E-Ink display shows button labels and static information.

## Apps

The badge includes a built-in app launcher. Apps are stored in `/apps/` and auto-discovered. The following apps are included:

| App | Description |
|---|---|
| **Hello** | Display your name tag on the E-Ink screen |
| **Register** | Get a QR code for account registration |
| **App Store** | Download new apps from the online service |
| **Schedule** | View the conference talk schedule |
| **CorpoBreach** | PvP RPG client for matchmaking, ability loadout management, and turn-based combat |
| **Not Simon!** | Memory pattern game |
| **Masher** | Reaction time game |
| **Totris** | Tetris-like game |
| **Sequencer** | 16-step LED sequencer |
| **Blink** | Simple LED demo |
| **Leet Badge** | Flashy display effects |
| **Messenger** | Badge-to-badge messaging |
| **Print BMP** | Display bitmap images |
| **Storage** | Back up and restore badge files with online badge storage |
| **Baidge** | Experimental microphone-enabled badge app |

## Project Structure

```
├── firmware/offsummit_2026/   # CircuitPython board definition
├── src/                   # Main firmware code
│   ├── boot.py                # Boot: safe mode, OTA, provisioning
│   ├── code.py                # Entry point → launcher
│   ├── secrets.py             # WiFi creds, service URL, UNIQUE_ID
│   ├── badge/                 # Core hardware abstraction
│   ├── apps/                  # Badge applications
│   ├── lib/                   # Libraries (frozen into firmware)
│   ├── font/                  # Font files
│   └── img/                   # System images
├── docs/PROJECT_CORPOBREACH.md # RPG client design/status
```

## Development

### Deploying Code

1. Connect the badge via USB
2. It mounts as a `CIRCUITPY` drive
3. Copy files from `src/` to the drive
4. The badge auto-reloads (unless `autoreload` is disabled in code)

### Writing a New App

Create a directory in `src/apps/<app_name>/` with:

- `code.py` — Main app code
- `metadata.json` — `{"app_name": "...", "author": "...", "info": "..."}`
- `icon.bmp` — 128×76 BMP icon
- Optional `boot.json` — Boot configuration overrides

The launcher will automatically discover and display the app. See [App Development Guide](docs/APP_DEVELOPMENT.md) for details.

## Documentation

- [Badge Architecture](docs/BADGE_ARCHITECTURE.md) — Hardware and software architecture deep-dive
- [App Development Guide](docs/APP_DEVELOPMENT.md) — How to write badge apps
- [Badge Hardware Modules](docs/BADGE_MODULES.md) — Usage and functionality of each `src/badge/` module (screens, buttons, LEDs, WiFi, etc.)
- [Shared Library Modules](docs/LIB_MODULES.md) — Usage and functionality of each non-Adafruit `src/lib/` module (NVM, provisioning, scrollable list, etc.)
- [Storage Transfer Module](docs/apps/storage-transfer.md) — Shared badge storage sync helper behavior

## Boot Button Combos

| Combination | Action |
|---|---|
| Hold S4 + S7 | Enter safe mode |
| Hold S4 + S6 | OTA firmware update |

### Building Firmware

Firmware is built using a Podman container. The board definition in `firmware/offsummit_2026/` is copied into the CircuitPython submodule at build time.

1. **Ensure Podman is running**
   ```bash
   export PATH="/opt/podman/bin:$PATH"
   podman machine start
   ```
2. **Ensure the CircuitPython submodule is populated**
   ```bash
   git submodule update --init --recursive
   ```
3. **Build the container image** (only needed once, or after `docker/` changes)
   ```bash
   podman build -t badge-2026-builder -f docker/Dockerfile docker/
   ```
4. **Run the build**
   ```bash
   podman run --rm -v "$(pwd)":/work badge-2026-builder
   ```
5. **Firmware output**
   ```
   build/build-offsummit_2026/
   ├── firmware.bin    ← flash via esptool  (the supported path)
   └── firmware.uf2    ← byproduct, NOT usable on this badge
   ```
   `firmware.uf2` cannot be used: `UF2_BOOTLOADER = 0` and the factory partition
   is never written, so nothing on the badge consumes a UF2. After flashing the
   `.bin`, press **S2** — esptool's RTS reset leaves the badge in download mode.

For a full toolchain re-setup, add `-e REUSE_SETUP=0` to the `podman run` command.
