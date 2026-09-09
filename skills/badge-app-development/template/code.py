import asyncio
import microcontroller
import supervisor

import badge.buttons
import badge.events as evt                  # module alias - there is no `evt` object
from badge.buttons import any_button_downup
from badge.constants import BLACK
from badge.events import BTN_A_DOWNUP, BTN_D_DOWNUP
from badge.neopixels import neopixels_off, set_neopixel
from badge.screens import (EPD, LCD, center_text_x_plane, clear_screen,
                           epd_print_exception, set_background)

# Stop host writes to CIRCUITPY from restarting the app mid-execution.
supervisor.runtime.autoreload = False


def draw_static():
    """E-ink: things that do not change. One slow refresh, then leave it alone."""
    set_background(EPD, BLACK)              # first - it replaces root_group
    EPD.root_group.append(center_text_x_plane(EPD, "My App", y=20))
    EPD.root_group.append(center_text_x_plane(EPD, "S4 = count   S7 = quit", y=150))
    EPD.refresh()                           # blocking: ~2.5 s first, ~0.9 s after


def draw_count(n):
    """LCD: things that change. Build the group AFTER clearing."""
    clear_screen(LCD)
    LCD.root_group.append(center_text_x_plane(LCD, "Presses:", y=50))
    LCD.root_group.append(center_text_x_plane(LCD, str(n), y=75, scale=2))


async def main():
    draw_static()

    # Start the button machinery, in this order. Do not use
    # all_tasks(interval=...) - it silently drops the interval.
    badge.buttons.start_tasks(interval=0.05)
    badge.buttons.start_downup_tasks()
    evt.start_tasks()

    count = 0
    draw_count(count)

    while True:
        btn = await any_button_downup()

        if btn is BTN_D_DOWNUP:             # S7 - quit
            break

        if btn is BTN_A_DOWNUP:             # S4 - action
            count += 1
            set_neopixel("a", 0x00FF00)
            draw_count(count)

    neopixels_off()                         # LEDs latch - always clear them
    microcontroller.reset()                 # the correct way back to the launcher


# Without this wrapper a crash leaves the badge blank with no clue why.
try:
    asyncio.run(main())
except Exception as e:
    epd_print_exception(e)
