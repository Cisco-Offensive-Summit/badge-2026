import random
import time

import microcontroller
import supervisor
import terminalio
from adafruit_display_shapes.rect import Rect
from adafruit_display_text.label import Label
from displayio import Bitmap, Group, Palette, TileGrid

import badge.buttons as hw_buttons
from badge.constants import BLACK, WHITE
from badge.neopixels import neopixels_off, set_neopixels
from badge.screens import EPD, LCD, center_text_x_plane
from badge_nvm import nvm_open, nvm_save

supervisor.runtime.autoreload = False

FONT = terminalio.FONT
NVM_KEY = "snake_high"

CELL = 8
COLS = 16
ROWS = 14
HEADER_H = 16
MOVE_SECONDS = 0.22

BG, BODY, HEAD, FOOD = 0, 1, 2, 3


class QuitGame(Exception):
    pass


def check_quit():
    # holding all four pads at once is the universal "quit to launcher" gesture
    if hw_buttons.a_pressed() and hw_buttons.b_pressed() and hw_buttons.c_pressed() and hw_buttons.d_pressed():
        raise QuitGame()


def load_high_score():
    try:
        return int(nvm_open(NVM_KEY))
    except (ValueError, TypeError):
        return 0


def save_high_score(value):
    nvm_save(NVM_KEY, str(value))


def draw_epd(high_score, last_score=None):
    root = Group()
    root.append(Rect(0, 0, EPD.width, EPD.height, fill=WHITE))
    root.append(center_text_x_plane(EPD, "SNAKE", y=24, scale=3, color=BLACK))
    root.append(center_text_x_plane(EPD, "S4 Left  S5 Right  S6 Up  S7 Down", y=60, color=BLACK))
    root.append(center_text_x_plane(EPD, "Edges wrap around", y=76, color=BLACK))
    if last_score is not None:
        root.append(center_text_x_plane(EPD, "Last score: " + str(last_score), y=98, color=BLACK))
    root.append(center_text_x_plane(EPD, "Best: " + str(high_score), y=118, color=BLACK))
    root.append(center_text_x_plane(EPD, "Press all 4 buttons to quit", y=EPD.height - 16, color=BLACK))
    EPD.root_group = root
    EPD.refresh()


def new_board():
    bitmap = Bitmap(COLS, ROWS, 4)
    palette = Palette(4)
    palette[BG] = 0x102010
    palette[BODY] = 0x30D030
    palette[HEAD] = 0xB0FFB0
    palette[FOOD] = 0xFF3030

    grid_group = Group(scale=CELL)
    grid_group.y = HEADER_H
    grid_group.append(TileGrid(bitmap, pixel_shader=palette))

    header = Rect(0, 0, LCD.width, HEADER_H, fill=0x202020)
    score_label = Label(font=FONT, text="Score: 0", color=WHITE)
    score_label.x = 2
    score_label.y = HEADER_H // 2

    root = Group()
    root.append(header)
    root.append(grid_group)
    root.append(score_label)
    LCD.root_group = root

    return bitmap, score_label


def random_empty_cell(occupied):
    while True:
        cell = (random.randrange(COLS), random.randrange(ROWS))
        if cell not in occupied:
            return cell


def play_game(bitmap, score_label):
    snake = [(COLS // 2, ROWS // 2)]
    bitmap[snake[0][0], snake[0][1]] = HEAD
    direction = (1, 0)
    food = random_empty_cell(set(snake))
    bitmap[food[0], food[1]] = FOOD

    score = 0
    last_move = time.monotonic()

    while True:
        check_quit()

        if hw_buttons.a_pressed() and direction != (1, 0):
            direction = (-1, 0)
        elif hw_buttons.b_pressed() and direction != (-1, 0):
            direction = (1, 0)
        elif hw_buttons.c_pressed() and direction != (0, 1):
            direction = (0, -1)
        elif hw_buttons.d_pressed() and direction != (0, -1):
            direction = (0, 1)

        now = time.monotonic()
        if now - last_move >= MOVE_SECONDS:
            last_move = now
            head_x, head_y = snake[0]
            new_head = ((head_x + direction[0]) % COLS, (head_y + direction[1]) % ROWS)

            if new_head in snake:
                return score

            bitmap[snake[0][0], snake[0][1]] = BODY
            snake.insert(0, new_head)

            if new_head == food:
                score += 1
                score_label.text = "Score: " + str(score)
                food = random_empty_cell(set(snake))
                bitmap[food[0], food[1]] = FOOD
            else:
                tail = snake.pop()
                bitmap[tail[0], tail[1]] = BG

            bitmap[new_head[0], new_head[1]] = HEAD

        time.sleep(0.02)


high_score = load_high_score()
draw_epd(high_score)

try:
    while True:
        bitmap, score_label = new_board()
        time.sleep(0.6)
        score = play_game(bitmap, score_label)

        set_neopixels(0xFF0000, 0xFF0000, 0xFF0000, 0xFF0000)
        time.sleep(0.3)
        neopixels_off()

        if score > high_score:
            high_score = score
            save_high_score(high_score)
        draw_epd(high_score, score)
        time.sleep(1.2)
except QuitGame:
    pass

neopixels_off()
microcontroller.reset()
