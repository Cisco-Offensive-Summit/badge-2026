# Shared Library Modules (`src/lib/`)

This document describes the non-Adafruit modules in the `src/lib/` directory. These modules contain reusable logic shared across multiple apps and the launcher — they speed up development by providing functionality that would otherwise need to be reimplemented in each app.

Adafruit CircuitPython libraries (e.g., `adafruit_bitmap_font`, `adafruit_imageload`, `adafruit_requests`, etc.) are excluded from this document. They are frozen into the firmware as `.mpy` files and are documented by [Adafruit](https://docs.circuitpython.org/projects/).

---

## Quick Reference

| Module | Purpose |
|---|---|
| [`badge_nvm.py`](#badge_nvmpy) | Persistent key-value store using ESP32 non-volatile memory (NVM) |
| [`memory_block.py`](#memory_blockpy) | Memory block allocator for NVM storage (doubly-linked list of free/used blocks) |
| [`Base64Wrapper.py`](#base64wrapperpy) | Base64 encoding/decoding wrapper for serializing typed data into NVM |
| [`get_token.py`](#get_tokenpy) | Badge provisioning — requests a `UNIQUE_ID` from the online service on first boot |
| [`scrollable_list.py`](#scrollable_listpy) | Generic scrollable, highlight-based selection list UI for the LCD |
| [`flavortext.py`](#flavortextpy) | Random humorous text generator (adapted from Zack Freedman's Singularitron) |
| [`QRBitmap.py`](#qrbitmappy) | QR code bitmap generation (converts a QR matrix to a `displayio.Bitmap`) |
| [`leaderboard.mpy`](#leaderboardmpy) | Score submission to the online service's leaderboard (frozen `.mpy`) |

---

## badge_nvm.py

A persistent key-value store built on top of ESP32 non-volatile memory (NVM). Data survives across reboots and power cycles. The module implements a memory block allocator with automatic compaction for managing the limited NVM space.

### NVM Layout

```
┌──────────────────────────────────────────────┐
│ Bytes 0–4:   "size:" magic string             │
│ Bytes 5–8:   Map size (uint32)                │
│ Bytes 9–~10%:  JSON key-value map             │
│ Bytes ~10%–end: Data blocks (free + used)     │
└──────────────────────────────────────────────┘
```

- The first 9 bytes are a header: the string `"size:"` followed by a 4-byte unsigned int recording the map's serialized size.
- The JSON map occupies approximately the first 10% of NVM. Each key maps to `[start, end, data_type]`.
- The remaining ~90% is the data region, managed as a linked list of free and used memory blocks.
- When no free block can accommodate a save, the module automatically compacts memory (moves used blocks down, merges free space) and retries.

### Public Functions

| Function | Signature | Description |
|---|---|---|
| `nvm_save` | `(name: str, data)` | Serialize `data` (str, int, bool, or bytes) via `Base64Wrapper` and store it under `name`. If the key already exists, attempts in-place overwrite; otherwise allocates a new block. |
| `nvm_open` | `(name: str)` | Read and deserialize the value stored under `name`. Raises `ValueError` (which surfaces as `KeyError`-like behavior) if the key is not found. |
| `nvm_free` | `(name: str)` | Delete the key and mark its memory block as free. Adjacent free blocks are merged automatically. |
| `nvm_compact` | `()` | Manually trigger memory compaction. Moves all used blocks to the start of the data region and consolidates free space. |
| `nvm_info` | `()` | Print a summary of all stored entries showing their name, byte range, and data type. |
| `nvm_format` | `()` | Erase the entire NVM map by resetting the map size to 0. Data blocks remain in NVM but are no longer referenced. |
| `nvm_wipe` | `()` | Delete each entry in the map individually (calls `nvm_free` for each key). |
| `print_list` | `()` | Print the memory block list (start, stop, FREE/USED status) as a linked-list chain. |
| `print_memory_block_details` | `()` | Print detailed memory block information (node-by-node with start, stop, block type, and next pointer). |

### Usage Example

```python
from badge_nvm import nvm_save, nvm_open, nvm_free, nvm_info

# Save data (persists across reboots)
nvm_save("my_app_state", "some_value")
nvm_save("high_score", 42)
nvm_save("enabled", True)

# Read data (raises ValueError if not found)
try:
    value = nvm_open("my_app_state")
    score = nvm_open("high_score")
    enabled = nvm_open("enabled")
except ValueError:
    print("Key not found")

# Delete data
nvm_free("my_app_state")

# Inspect NVM usage
nvm_info()
```

### Key Behavior Notes

- **NVM is very limited** (~a few KB). Only store small config values, not large data.
- Supported data types: `str`, `int`, `bool`, and `bytes`/`bytearray`. All are serialized via `Base64Wrapper`.
- When saving a value under an existing key: if the new data fits in the old block, it overwrites in place (splitting any leftover space into a free block). If it doesn't fit, the old block is freed and a new block is allocated.
- The module is used by the launcher to store `BOOT_CONFIG` (which app to launch, filesystem options).
- The internal `_NVM` class is instantiated as a module-level singleton `_nvm` at import time.

---

## memory_block.py

A doubly-linked list memory block allocator used by `badge_nvm.py` to manage the NVM data region. This module is not typically used directly by apps — it is an internal dependency of the NVM system.

### _MemoryBlock Class

Represents a single block of memory (free or used) with a start and stop position.

| Property/Method | Description |
|---|---|
| `start` (property) | Start byte offset (must be positive). |
| `stop` (property) | End byte offset (must be greater than `start`). |
| `block_type` (property) | `0` = FREE, `1` = USED. |
| `size()` | Return block size (`stop - start`). |
| `prev` / `next` | Pointers to adjacent blocks in the linked list. |
| `print()` | Log the block's details. |

Comparison operators (`<`, `>`, `==`) are implemented for sorting blocks by address.

### _MemoryBlockList Class

A sorted doubly-linked list of `_MemoryBlock` objects.

| Method | Description |
|---|---|
| `insert(new_block)` | Insert a block in sorted order by start address. Raises `MemoryBlockListException` on duplicate start addresses. |
| `remove(block)` | Remove a specific block from the list. |
| `pop()` | Remove and return the tail block. |
| `free(block)` | Mark a USED block as FREE, then merge adjacent free blocks via `_clean()`. |
| `_clean()` | Merge consecutive FREE blocks into a single block. |
| `__iter__()` | Iterate over all blocks from head to tail. |

### Module-Level Singleton

| Name | Description |
|---|---|
| `_mbl` | Global `_MemoryBlockList` instance shared with `badge_nvm.py`. Initialized as an empty list; populated by `_NVM._build_list()` when the NVM map is read. |

### Key Behavior Notes

- Blocks are kept sorted by start address at all times.
- The `_clean()` method is called automatically after `free()` to merge adjacent free blocks, preventing fragmentation.
- Custom exceptions: `MemoryBlockException` (invalid block parameters) and `MemoryBlockListException` (list operations on missing/duplicate blocks).

---

## Base64Wrapper.py

A serialization wrapper that encodes Python values (str, int, bool, bytes) into base64 `bytearray` data for storage in NVM. Used internally by `badge_nvm.py`.

### Base64Wrapper Class

#### Constructor

```python
Base64Wrapper(value=None, data=None, data_type=None)
```

- If `value` is provided, the value is serialized via `set()`.
- If `data` and `data_type` are provided (used when reconstructing from NVM), they are stored directly.

#### Data Types

| Type Code | Constant | Python Type | Serialization |
|---|---|---|---|
| 0 | `_TYPE_BIT` | `bytes`/`bytearray` | Direct base64 encoding of raw bytes. |
| 1 | `_TYPE_STR` | `str` | UTF-8 encode, then base64. |
| 2 | `_TYPE_BOL` | `bool` | String encode ("True"/"False"), then base64. |
| 3 | `_TYPE_INT` | `int` | `struct.pack("i", value)`, then base64. |

#### Methods

| Method | Description |
|---|---|
| `set(value)` | Serialize a Python value into base64 `bytearray`. Sets `self.data`, `self.data_type`, and `self.size`. |
| `get()` | Deserialize the stored base64 data back to the original Python type. |
| `data` (property) | The base64-encoded `bytearray`. Must be a `bytearray` (validated on setter). |
| `__bytes__()` | Convert to `bytes`. |
| `__repr__()` | String representation showing the data. |

### Usage Example

```python
from Base64Wrapper import Base64Wrapper

# Serialize
wrapper = Base64Wrapper("hello world")
print(wrapper.data)        # bytearray of base64
print(wrapper.data_type)   # 1 (TYPE_STR)
print(wrapper.size)        # length of base64 data

# Deserialize
wrapper2 = Base64Wrapper(data=wrapper.data, data_type=wrapper.data_type)
print(wrapper2.get())      # "hello world"

# Works with int, bool, bytes too
w_int = Base64Wrapper(42)
print(w_int.get())         # 42

w_bool = Base64Wrapper(True)
print(w_bool.get())        # True

w_bytes = Base64Wrapper(b'\x01\x02\x03')
print(w_bytes.get())       # b'\x01\x02\x03'
```

### Custom Exception

| Exception | Description |
|---|---|
| `Base64WrapperException` | Raised when `data` and `data_type` are not both provided during reconstruction. |

### Key Behavior Notes

- Integers are packed as 4-byte signed (`struct.pack("i", ...)`) — range is -2,147,483,648 to 2,147,483,647.
- Booleans are serialized as the strings "True" or "False" for simplicity.
- The `data` property setter enforces `bytearray` type to ensure compatibility with NVM's `board_NVM[slice]` writes.

---

## get_token.py

Badge provisioning script. Runs on first boot (or when manually triggered by holding S5+S6) to request a `UNIQUE_ID` from the online service. The `UNIQUE_ID` is the badge's secret key for online service authentication.

### Functions

| Function | Signature | Description |
|---|---|---|
| `get_token` | `() -> bool` | Connect to WiFi, POST the badge's MAC address to `/badge/gen_token`, and append the returned `UNIQUE_ID` to `secrets.py`. Returns `True` on success. |
| `connect_wifi` | `() -> bool` | Connect to WiFi using credentials from `secrets.py`. Tries 5 times. Returns `True` on success. |
| `flash_red` | `(count)` | Flash all NeoPixels red `count` times, then leave them red. Used as visual error feedback. |

### Provisioning Flow

1. Disable autoreload (`supervisor.runtime.autoreload = False`).
2. Read MAC address from `wifi.radio.mac_address`.
3. Light NeoPixel 0 green (indicating start).
4. Connect to WiFi (light NeoPixel 1 green on success).
5. Create socket pool and HTTPS session (light NeoPixel 2 green).
6. POST `{"mac_address": "..."}` to `/badge/gen_token` (light NeoPixel 3 green on HTTP 200).
7. Parse the `uniqueID` from the response JSON.
8. Append `UNIQUE_ID = '<token>'` to `/secrets.py`.
9. On any failure, flash NeoPixels red.

### Usage Example

This module is typically invoked by `boot.py` and not called directly by apps. However, it can be triggered manually:

```python
from get_token import get_token

if get_token():
    print("Provisioning successful. Rebooting...")
else:
    print("Provisioning failed.")
```

### Key Behavior Notes

- The module reads WiFi credentials and service URL from `secrets.py` at import time. If `secrets.py` is missing or incomplete, the module calls `exit()`.
- The MAC address is sent as a hex string (no colons).
- The `UNIQUE_ID` is appended to `secrets.py` (not overwritten), so existing content is preserved.
- NeoPixels provide visual feedback of each step: green = success, red = failure.
- This provisioning endpoint is locked before the conference starts, so provisioning must happen beforehand.

---

## scrollable_list.py

A generic, data-agnostic scrollable selection list for the LCD. Provides a highlight-based UI where one item is selected at a time, and the list scrolls when the selection moves beyond the visible window. Extracted from the schedule app's `LCDTalksList` into a reusable component.

### ScrollableList Class

#### Constructor

```python
ScrollableList(items, text_fn=None, max_visible=7, max_chars=20, animate_time=0.5,
               selected_bg=0xaaaaaa, selected_fg=0x111111,
               unselected_bg=0x000000, unselected_fg=0xFFFFFF,
               row_height=16, row_width=128, x_offset=2, y_offset=16,
               style_fn=None, selected_style_fn=None,
               selected_bg_adjust=None, wrap=False, loop_scroll=False,
               scroll_end_pause=1.0)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `items` | list | (required) | List of arbitrary data objects to display. |
| `text_fn` | callable | `str` | Callable(item) → str for display text. |
| `max_visible` | int | 7 | Number of rows visible on screen at once. |
| `max_chars` | int | 20 | Max characters per scrolling label row. |
| `animate_time` | float | 0.5 | Scrolling label animation interval in seconds. |
| `selected_bg` | int | `0xaaaaaa` | Background color of the highlighted row. |
| `selected_fg` | int | `0x111111` | Text color of the highlighted row. |
| `unselected_bg` | int | `0x000000` | Background color of non-highlighted rows. |
| `unselected_fg` | int | `0xFFFFFF` | Text color of non-highlighted rows. |
| `row_height` | int | 16 | Pixel height of each row. Also controls the full-row background height. |
| `row_width` | int | 128 | Pixel width of each row's background fill. Defaults to the LCD width so row backgrounds extend to the right edge. |
| `x_offset` | int | 2 | X pixel offset for the list text. Row backgrounds start at x=0. |
| `y_offset` | int | 16 | Y pixel offset for the first row (leaves room for a header). |
| `style_fn` | callable | `None` | Optional Callable(item) → `(foreground, background)` for per-row colors. Set `selected_fg` and/or `selected_bg` to `None` to preserve row-specific colors on the highlighted row. |
| `selected_style_fn` | callable | `None` | Optional Callable(item, foreground, background) → `(selected_foreground, selected_background)` for calculating highlighted colors from the row's normal style. When set, this overrides `selected_fg`, `selected_bg`, and `selected_bg_adjust` for selected rows. |
| `selected_bg_adjust` | int | `None` | Optional RGB-channel adjustment applied to the row's normal background color when selected. Positive values brighten, negative values darken. Uses `selected_fg` for selected text unless `selected_fg=None`. |
| `wrap` | bool | `False` | When `True`, navigating up from the first item selects the last item, and navigating down from the last item selects the first item. |
| `loop_scroll` | bool | `False` | When `True`, a long selected row scrolls to the end, pauses, resets to the beginning, and repeats. |
| `scroll_end_pause` | float | `1.0` | Pause duration, in seconds, before a looped long row restarts from the beginning. |

#### Methods

| Method | Returns | Description |
|---|---|---|
| `get_group()` | `displayio.Group` | Return the display group for compositing (assign to `LCD.root_group`). |
| `get_selected()` | object | Return the currently-highlighted data item. |
| `get_selected_index()` | int | Return the index of the highlighted item in the full list. |
| `input(scroll_up)` | `None` | Navigate up (`True`) or down (`False`). Handles scrolling when the selection reaches the edge of the visible window. |
| `update()` | `None` | Animate the scrolling label for the highlighted row. Call once per frame in the main loop. |

### Usage Example

```python
from scrollable_list import ScrollableList
from badge.screens import LCD
from badge.buttons import all_tasks, any_button_downup
import badge.events as evt
from badge.events import BTN_A_DOWNUP, BTN_D_DOWNUP
import asyncio

async def main():
    all_tasks(interval=0.05)
    evt.start_tasks()

    items = [
        {"title": "Talk A", "time": "10:00"},
        {"title": "Talk B", "time": "11:00"},
        {"title": "Talk C", "time": "12:00"},
    ]

    lst = ScrollableList(items, text_fn=lambda item: item["title"])
    LCD.root_group = lst.get_group()

    while True:
        lst.update()
        btn = await any_button_downup()
        if btn == BTN_A_DOWNUP:
            lst.input(scroll_up=True)    # navigate up
        elif btn == BTN_D_DOWNUP:
            lst.input(scroll_up=False)   # navigate down

asyncio.run(main())
```

### Key Behavior Notes

- The list works with any data type — just provide a `text_fn` that extracts a display string from each item.
- Each row has a full-row background rectangle behind the text; this lets item and selected backgrounds extend across the LCD instead of only behind the rendered characters.
- When the selection reaches the top or bottom of the visible window, the list scrolls the text content of all visible rows rather than changing the group structure.
- `update()` only animates the currently selected row's scrolling label. Call it every frame for smooth animation.
- By default, navigation stops at the top and bottom to preserve existing app behavior; pass `wrap=True` for cyclic menus.
- By default, long selected labels use the underlying `ScrollingLabel` behavior; pass `loop_scroll=True` to pause at the end and restart from the beginning.
- The `y_offset` default of 16 leaves room for a header label above the list.
- Colors can be customized globally or per item with `style_fn`; selected colors override row colors unless set to `None`.
- Use `selected_bg_adjust` for simple highlighted backgrounds calculated from each item's normal background color.
- Use `selected_style_fn` when highlighted foreground/background colors need fully custom calculation.

---

## flavortext.py

A random humorous text generator that produces phrases like "Hackinging the Matrix" or "Snorting data". Adapted from Zack Freedman's Singularitron firmware (MIT licensed).

### Classes

#### Verbs

| Constructor | Description |
|---|---|
| `Verbs(constructive=True)` | Initialize with constructive verbs (build, hack, deploy...) or destructive verbs (trash, smash, yeet...). |
| `get_verb()` | Return a random verb stem from the list. |

#### Nouns

| Constructor | Description |
|---|---|
| `Nouns()` | Initialize with the noun list. |
| `get_noun()` | Return a random noun from the list. |

### Functions

| Function | Signature | Description |
|---|---|---|
| `line` | `(constructive=True) -> str` | Generate a random phrase: `verb + "ing " + noun`. E.g., `"Hackinging the Matrix"`. |

### Usage Example

```python
from flavortext import line

# Generate a random constructive phrase
print(line())              # e.g., "Buildinging kittens"

# Generate a random destructive phrase
print(line(constructive=False))  # e.g., "Yeeting the core"
```

### Key Behavior Notes

- Verb stems lack the trailing "ing" — the `line()` function appends it, so verbs like "Hack" become "Hackinging". This is intentional from the original source.
- The noun list includes humorous entries like "your mom", "the Gibson", "[REDACTED]", and "cyber-doobie".
- This module is used to display entertaining status messages on the badge during operations.

---

## QRBitmap.py

A minimal QR code bitmap generator that converts a QR matrix into a `displayio.Bitmap`. This is a standalone version of the `bitmap_QR` function also found in `badge/utils.py`.

### Functions

| Function | Signature | Description |
|---|---|---|
| `bitmap_QR` | `(matrix) -> displayio.Bitmap` | Convert a QR code matrix (from `adafruit_miniqr`) into a monochrome `displayio.Bitmap` with a 2-pixel border. |

### Usage Example

```python
import adafruit_miniqr
from QRBitmap import bitmap_QR
import displayio

qr = adafruit_miniqr.QRCode(qr_type=4, error_correct=adafruit_miniqr.L)
qr.add_data("https://example.com".encode('utf-8'))
qr.make()

qr_bitmap = bitmap_QR(qr.matrix)
palette = displayio.Palette(2)
palette[0] = 0xFFFFFF
palette[1] = 0x000000
tile_grid = displayio.TileGrid(qr_bitmap, pixel_shader=palette)

splash = displayio.Group(scale=2)
splash.append(tile_grid)
LCD.root_group = splash
```

### Key Behavior Notes

- The bitmap includes a 2-pixel white border around the QR code (required for scannability).
- Pixel value 0 = white (background), 1 = black (QR module).
- This module provides only the bitmap conversion. For full QR display (with scaling and centering), use `badge.utils.gen_qr_code()` which wraps this functionality.

---

## leaderboard.mpy

Score submission module for the online service's leaderboard system. This module is frozen into the firmware as a `.mpy` file, so the source code is not available in the repository.

### Functions

| Function | Signature | Description |
|---|---|---|
| `post_to_leaderboard` | `(score)` | Submit a game score to the online service's `/badge/submit_score` endpoint. Includes the badge's `UNIQUE_ID` and a hash for anti-cheat verification. |

### Usage Example

```python
from leaderboard import post_to_leaderboard

# After game ends
post_to_leaderboard(score)
```

### Key Behavior Notes

- The score submission includes a hash that combines the score with other elements for anti-cheat verification. Modified apps will be flagged as cheaters.
- The app must be registered in the online service's `BadgeApp` database table for the score to be accepted.
- The badge must be connected to WiFi and have a valid `UNIQUE_ID` linked to a user account.
- Since this is a frozen `.mpy` file, modifications require obtaining the source and recompiling with the CircuitPython build system.
