import random
import time

import microcontroller
import supervisor
import terminalio
from adafruit_display_shapes.rect import Rect
from displayio import Group

import badge.buttons as hw_buttons
from badge.constants import BLACK, GREEN, RED, WHITE, YELLOW
from badge.neopixels import neopixels_off, set_neopixels
from badge.screens import EPD, LCD, center_text_x_plane
from badge_nvm import nvm_open, nvm_save

supervisor.runtime.autoreload = False

FONT = terminalio.FONT
NVM_KEY = "reflex_best_ms"


class QuitGame(Exception):
    pass


def check_quit():
    # holding all four pads at once is the universal "quit to launcher" gesture
    if hw_buttons.a_pressed() and hw_buttons.b_pressed() and hw_buttons.c_pressed() and hw_buttons.d_pressed():
        raise QuitGame()


def load_best():
    try:
        return int(nvm_open(NVM_KEY))
    except (ValueError, TypeError):
        return None


def save_best(value):
    nvm_save(NVM_KEY, str(value))


def draw_epd(best_ms):
    root = Group()
    root.append(Rect(0, 0, EPD.width, EPD.height, fill=WHITE))
    root.append(center_text_x_plane(EPD, "REFLEX", y=24, scale=3, color=BLACK))
    root.append(center_text_x_plane(EPD, "Press S7 to start, then again on GREEN", y=64, color=BLACK))
    best_text = "Best: " + str(best_ms) + " ms" if best_ms is not None else "Best: --"
    root.append(center_text_x_plane(EPD, best_text, y=108, color=BLACK))
    root.append(center_text_x_plane(EPD, "Press all 4 buttons to quit", y=EPD.height - 20, color=BLACK))
    EPD.root_group = root
    EPD.refresh()


def show_lcd(message, bg):
    root = Group()
    root.append(Rect(0, 0, LCD.width, LCD.height, fill=bg))
    label_color = BLACK if bg in (GREEN, YELLOW) else WHITE
    root.append(center_text_x_plane(LCD, message, y=LCD.height // 2, color=label_color))
    LCD.root_group = root


def wait_for_d():
    while True:
        check_quit()
        if hw_buttons.d_pressed():
            while hw_buttons.d_pressed():
                time.sleep(0.01)
            return
        time.sleep(0.01)


def play_round():
    show_lcd("Press S7\nto begin", BLACK)
    wait_for_d()

    show_lcd("Wait for\nGREEN...", BLACK)
    end_time = time.monotonic() + random.uniform(1.5, 4.0)
    while time.monotonic() < end_time:
        check_quit()
        if hw_buttons.d_pressed():
            while hw_buttons.d_pressed():
                time.sleep(0.01)
            show_lcd("Too soon!\nTry again", RED)
            time.sleep(1.2)
            return None
        time.sleep(0.01)

    show_lcd("GO!", GREEN)
    set_neopixels(GREEN, GREEN, GREEN, GREEN)
    start = time.monotonic()
    wait_for_d()
    elapsed_ms = int((time.monotonic() - start) * 1000)
    neopixels_off()
    show_lcd(str(elapsed_ms) + " ms", BLACK)
    time.sleep(1.5)
    return elapsed_ms


best = load_best()
draw_epd(best)

try:
    while True:
        result = play_round()
        if result is not None and (best is None or result < best):
            best = result
            save_best(best)
            draw_epd(best)
except QuitGame:
    pass

neopixels_off()
microcontroller.reset()
