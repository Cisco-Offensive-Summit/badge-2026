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
NVM_KEY = "rps_best_streak"

CHOICES = ("ROCK", "PAPER", "SCISSORS")
BEATS = {"ROCK": "SCISSORS", "PAPER": "ROCK", "SCISSORS": "PAPER"}


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
        return 0


def save_best(value):
    nvm_save(NVM_KEY, str(value))


def draw_epd(best_streak, last_result=None):
    root = Group()
    root.append(Rect(0, 0, EPD.width, EPD.height, fill=WHITE))
    root.append(center_text_x_plane(EPD, "ROCK PAPER SCISSORS", y=22, scale=2, color=BLACK))
    root.append(center_text_x_plane(EPD, "S4 Rock  S5 Paper  S6 Scissors  S7 Random", y=54, color=BLACK))
    if last_result is not None:
        root.append(center_text_x_plane(EPD, last_result, y=76, color=BLACK))
    root.append(center_text_x_plane(EPD, "Best win streak: " + str(best_streak), y=98, color=BLACK))
    root.append(center_text_x_plane(EPD, "Press all 4 buttons to quit", y=EPD.height - 20, color=BLACK))
    EPD.root_group = root
    EPD.refresh()


def show_lcd(you, cpu, banner, banner_color):
    root = Group()
    root.append(Rect(0, 0, LCD.width, LCD.height, fill=BLACK))
    root.append(center_text_x_plane(LCD, "You: " + you, y=30, color=WHITE))
    root.append(center_text_x_plane(LCD, "CPU: " + cpu, y=54, color=WHITE))
    root.append(center_text_x_plane(LCD, banner, y=90, scale=2, color=banner_color))
    LCD.root_group = root


def wait_for_choice():
    # d_pressed has no fixed choice -> "random" (a lucky-dip 4th option)
    getters = (
        (hw_buttons.a_pressed, "ROCK"),
        (hw_buttons.b_pressed, "PAPER"),
        (hw_buttons.c_pressed, "SCISSORS"),
        (hw_buttons.d_pressed, None),
    )
    while True:
        check_quit()
        for getter, choice in getters:
            if getter():
                while getter():
                    time.sleep(0.02)
                return choice if choice is not None else random.choice(CHOICES)
        time.sleep(0.02)


def judge(you, cpu):
    if you == cpu:
        return "tie"
    return "win" if BEATS[you] == cpu else "lose"


best_streak = load_best()
streak = 0
draw_epd(best_streak)

try:
    while True:
        show_lcd("?", "?", "Pick: S4/S5/S6\nor S7 = random", WHITE)
        you = wait_for_choice()

        cpu = random.choice(CHOICES)
        outcome = judge(you, cpu)

        if outcome == "win":
            banner, flash = "YOU WIN", GREEN
            streak += 1
        elif outcome == "lose":
            banner, flash = "YOU LOSE", RED
            streak = 0
        else:
            banner, flash = "TIE", YELLOW
        show_lcd(you, cpu, banner, flash)

        set_neopixels(flash, flash, flash, flash)
        time.sleep(0.3)
        neopixels_off()

        if streak > best_streak:
            best_streak = streak
            save_best(best_streak)
        draw_epd(best_streak, "Last: " + banner)
        time.sleep(1.5)
except QuitGame:
    pass

neopixels_off()
microcontroller.reset()
