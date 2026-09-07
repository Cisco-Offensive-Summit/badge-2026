import asyncio
import os
import sys
import board
import supervisor
from adafruit_display_text.label import Label
from displayio import Bitmap
from displayio import Group
from displayio import OnDiskBitmap
from displayio import Palette
from displayio import TileGrid
from terminalio import FONT

import badge.buttons
import badge.events as evt
from badge.constants import BLACK
from badge.constants import BB_HEIGHT
from badge.constants import BB_WIDTH
from badge.events import on
from badge.neopixels import set_neopixels
from badge.neopixels import set_neopixel
from badge.screens import EPD
from badge.screens import epd_print_exception
from badge.screens import round_button
from badge.screens import center_text_x_plane

Curcolor = 0
Pattern = [0]
Heldcount = 0
@on(evt.BTN_A_PRESSED)
def a_pressed(event):
    global Curcolor
    global Heldcount
    Curcolor |= 255 << 16
    Heldcount += 1

@on(evt.BTN_B_PRESSED)
def b_pressed(event):
    global Curcolor
    global Heldcount
    Curcolor |= 255 << 8
    Heldcount += 1

@on(evt.BTN_C_PRESSED)
def c_pressed(event):
    global Curcolor
    global Heldcount
    Curcolor |= 255
    Heldcount += 1

@on(evt.BTN_D_PRESSED)
def d_pressed(event):
    global Curcolor
    global Heldcount
    Curcolor = 0
    Heldcount += 1

@on(evt.BTN_A_RELEASED)
def a_released(event):
    global Curcolor
    update_color(Curcolor)

@on(evt.BTN_B_RELEASED)
def b_released(event):
    global Curcolor
    update_color(Curcolor)

@on(evt.BTN_C_RELEASED)
def c_released(event):
    global Curcolor
    update_color(Curcolor)

@on(evt.BTN_D_RELEASED)
def d_released(event):
    global Curcolor
    update_color(Curcolor)

def update_color(color):
    global Curcolor
    global Pattern
    global Heldcount
    Heldcount -= 1
    if (Heldcount == 0):
        Pattern.append(color)
        Curcolor = 0


def run():
    asyncio.run(main())

def text(text, scale=1, y=0):
    lb = center_text_x_plane(EPD, text, scale=scale, y=y)
    EPD.root_group.append(lb)

def background():
    group = Group()
    background = Bitmap(EPD.width, EPD.height, 1)
    palette1 = Palette(1)
    palette1[0] = BLACK
    tile_grid1 = TileGrid(background, pixel_shader=palette1)
    group.append(tile_grid1)
    EPD.root_group = group


LED_IMAGE = "/apps/blink/led.bmp"

def led_image(y=100):
    """Drop the little LED graphic into the whitespace in the middle of the EPD."""
    try:
        bitmap = OnDiskBitmap(LED_IMAGE)
    except OSError:
        return
    grid = TileGrid(bitmap, pixel_shader=bitmap.pixel_shader,
                    x=(EPD.width - bitmap.width) // 2, y=y)
    group = Group()
    group.append(grid)
    EPD.root_group.append(group)


# Horizontal stagger (px) used to make the on-screen labels echo the badge's
# physically offset buttons.  S6 already sits flush against the right edge of
# the panel (text x=227 + 30px text + 5px radius = 262 of 264), so the 15px
# gap between S7 and S6 is created by pulling S7 left instead of pushing S6
# right -- pushing S6 right would run it 13px off the display.
NUDGE = 15


def button_row(x, y, lt_txt=None, rt_txt=None, lb_txt=None, rb_txt=None,
               lt_dx=0, rt_dx=0, lb_dx=0, rb_dx=0):
    """Draw the four button labels.

    lt/rt/lb/rb = left-top, right-top, left-bottom, right-bottom.
    *_dx nudges an individual label horizontally.
    """
    radius = 5
    splash = Group()

    lb_lt = Label(font=FONT, text=lt_txt)
    lb_rt = Label(font=FONT, text=rt_txt)
    lb_lb = Label(font=FONT, text=lb_txt)
    lb_rb = Label(font=FONT, text=rb_txt)

    def left_x(label, dx):
        return 2 + radius + dx

    def right_x(label, dx):
        return EPD.width - 2 - label.bounding_box[BB_WIDTH] - radius + dx

    y_bottom = EPD.height - 2 - radius - (lb_rb.bounding_box[BB_HEIGHT] // 2)
    y_top = EPD.height - 4 - (radius * 3) - (lb_lt.bounding_box[BB_HEIGHT] // 2 * 3)

    splash.append(round_button(lb_lt, left_x(lb_lt, lt_dx), y_top, radius))
    splash.append(round_button(lb_rt, right_x(lb_rt, rt_dx), y_top, radius))
    splash.append(round_button(lb_lb, left_x(lb_lb, lb_dx), y_bottom, radius))
    splash.append(round_button(lb_rb, right_x(lb_rb, rb_dx), y_bottom, radius))

    EPD.root_group.append(splash)

def usage():
    background()
    text(" Push buttons to\n  make blinking\n     pattern", scale=1, y=4)
    led_image(y=92)
    # S4 top-left, S5 bottom-left (+15), S7 top-right, S6 bottom-right (-15)
    button_row(0, 107,
               lt_txt="S4: R", rt_txt="S7: N",
               lb_txt="S5: G", rb_txt="S6: B",
               lb_dx=NUDGE, rb_dx=-NUDGE)
    EPD.refresh()

async def main():
    usage()
    button_tasks = badge.buttons.start_tasks(interval=0.05)
    event_tasks = evt.start_tasks()
    # all_tasks = [info_task, battery_task] + button_tasks + event_tasks
    all_tasks = [ ] + button_tasks + event_tasks
    i = 0 
    while(True):
        # set_neopixel("b", 0)
        patlen = len(Pattern)
        a = Pattern[i%patlen]
        b = Pattern[(i+1)%patlen]
        c = Pattern[(i+2)%patlen]
        d = Pattern[(i+3)%patlen]
        set_neopixels(a,b,c,d)
        await asyncio.sleep(0.5)
        # set_neopixel("b", 255<<8)
        # await asyncio.sleep(1.5)
        i = (i + 1) % patlen
    await asyncio.gather(*all_tasks)

if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        epd_print_exception(e)
