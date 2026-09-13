import random
import time

import microcontroller
import supervisor
import terminalio
from adafruit_display_shapes.rect import Rect
from displayio import Group

import badge.buttons as hw_buttons
from badge.constants import BLACK, CYAN, WHITE
from badge.neopixels import neopixels_off, set_neopixels
from badge.screens import EPD, LCD, center_text_x_plane, wrap_message

supervisor.runtime.autoreload = False

FONT = terminalio.FONT

FORTUNES = (
    "Yes, but check your logs first.",
    "Access denied. Try again later.",
    "Signs point to sudo.",
    "The exploit will work... eventually.",
    "404: Answer not found.",
    "It's not a bug, it's a feature.",
    "Consult your local red team.",
    "Patch Tuesday says wait.",
    "Definitely, if the WiFi holds.",
    "Reboot and ask again.",
    "The badge says no.",
    "All signs point to root.",
    "Ask again after your coffee.",
    "It compiles. Ship it.",
    "Somewhere, a packet is lost forever.",
    "Trust, but verify the cert.",
)


class QuitGame(Exception):
    pass


def check_quit():
    # holding all four pads at once is the universal "quit to launcher" gesture
    if hw_buttons.a_pressed() and hw_buttons.b_pressed() and hw_buttons.c_pressed() and hw_buttons.d_pressed():
        raise QuitGame()


def draw_epd():
    root = Group()
    root.append(Rect(0, 0, EPD.width, EPD.height, fill=WHITE))
    root.append(center_text_x_plane(EPD, "HACKER 8-BALL", y=28, scale=3, color=BLACK))
    root.append(center_text_x_plane(EPD, "Ask a yes/no question, press S7", y=70, color=BLACK))
    root.append(center_text_x_plane(EPD, "Press all 4 buttons to quit", y=EPD.height - 20, color=BLACK))
    EPD.root_group = root
    EPD.refresh()


def show_idle():
    root = Group()
    root.append(Rect(0, 0, LCD.width, LCD.height, fill=BLACK))
    root.append(center_text_x_plane(LCD, "Press S7\nfor your fortune", y=LCD.height // 2, color=CYAN))
    LCD.root_group = root


def show_thinking():
    root = Group()
    root.append(Rect(0, 0, LCD.width, LCD.height, fill=BLACK))
    root.append(center_text_x_plane(LCD, "...", y=LCD.height // 2, scale=3, color=CYAN))
    LCD.root_group = root


def show_fortune(text):
    root = Group()
    root.append(Rect(0, 0, LCD.width, LCD.height, fill=BLACK))
    label = wrap_message(LCD, text, y=20)
    label.color = CYAN
    root.append(center_text_x_plane(LCD, label, y=20))
    LCD.root_group = root


def wait_for_d():
    while True:
        check_quit()
        if hw_buttons.d_pressed():
            while hw_buttons.d_pressed():
                time.sleep(0.02)
            return
        time.sleep(0.02)


draw_epd()

try:
    while True:
        show_idle()
        wait_for_d()

        show_thinking()
        set_neopixels(CYAN, CYAN, CYAN, CYAN)
        time.sleep(0.8)
        neopixels_off()

        show_fortune(random.choice(FORTUNES))
        time.sleep(3.0)
except QuitGame:
    pass

neopixels_off()
microcontroller.reset()
