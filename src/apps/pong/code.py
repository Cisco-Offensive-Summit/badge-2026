import time

import microcontroller
import supervisor
import terminalio
from adafruit_display_shapes.rect import Rect
from adafruit_display_text.label import Label
from displayio import Group

import badge.buttons as hw_buttons
from badge.constants import BLACK, WHITE
from badge.neopixels import neopixels_off, set_neopixels
from badge.screens import EPD, LCD, center_text_x_plane
from badge_nvm import nvm_open, nvm_save

supervisor.runtime.autoreload = False

FONT = terminalio.FONT
NVM_KEY = "pong_high"

HEADER_H = 16
PADDLE_W, PADDLE_H = 28, 4
PADDLE_Y = LCD.height - 10
BALL_SIZE = 4
PADDLE_SPEED = 130.0  # px/sec
BALL_SPEED_START = 70.0
BALL_SPEED_STEP = 1.08


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
    root.append(center_text_x_plane(EPD, "PONG", y=24, scale=3, color=BLACK))
    root.append(center_text_x_plane(EPD, "S4 Left    S5 Right", y=64, color=BLACK))
    if last_score is not None:
        root.append(center_text_x_plane(EPD, "Last score: " + str(last_score), y=86, color=BLACK))
    root.append(center_text_x_plane(EPD, "Best: " + str(high_score), y=108, color=BLACK))
    root.append(center_text_x_plane(EPD, "Press all 4 buttons to quit", y=EPD.height - 20, color=BLACK))
    EPD.root_group = root
    EPD.refresh()


def new_board():
    header = Rect(0, 0, LCD.width, HEADER_H, fill=0x202020)
    score_label = Label(font=FONT, text="Score: 0", color=WHITE)
    score_label.x = 2
    score_label.y = HEADER_H // 2

    paddle_x = (LCD.width - PADDLE_W) // 2
    paddle = Rect(paddle_x, PADDLE_Y, PADDLE_W, PADDLE_H, fill=0x30D0FF)
    ball = Rect(LCD.width // 2, HEADER_H + 4, BALL_SIZE, BALL_SIZE, fill=0xFF3030)

    root = Group()
    root.append(header)
    root.append(score_label)
    root.append(paddle)
    root.append(ball)
    LCD.root_group = root

    return score_label, paddle, ball


def play_game(score_label, paddle, ball):
    paddle_x = float(paddle.x)
    ball_x, ball_y = float(ball.x), float(ball.y)
    vx, vy = BALL_SPEED_START * 0.6, BALL_SPEED_START

    score = 0
    last_tick = time.monotonic()

    while True:
        check_quit()

        now = time.monotonic()
        dt = now - last_tick
        last_tick = now

        if hw_buttons.a_pressed():
            paddle_x -= PADDLE_SPEED * dt
        if hw_buttons.b_pressed():
            paddle_x += PADDLE_SPEED * dt
        paddle_x = max(0.0, min(LCD.width - PADDLE_W, paddle_x))
        paddle.x = int(paddle_x)

        ball_x += vx * dt
        ball_y += vy * dt

        if ball_x <= 0:
            ball_x, vx = 0.0, abs(vx)
        elif ball_x >= LCD.width - BALL_SIZE:
            ball_x, vx = float(LCD.width - BALL_SIZE), -abs(vx)

        if ball_y <= HEADER_H:
            ball_y, vy = float(HEADER_H), abs(vy)

        hit_paddle = (
            vy > 0
            and ball_y + BALL_SIZE >= PADDLE_Y
            and ball_y <= PADDLE_Y + PADDLE_H
            and paddle_x - BALL_SIZE <= ball_x <= paddle_x + PADDLE_W
        )
        if hit_paddle:
            ball_y = PADDLE_Y - BALL_SIZE
            vy = -abs(vy)
            score += 1
            score_label.text = "Score: " + str(score)
            if score % 5 == 0:
                vx *= BALL_SPEED_STEP
                vy *= BALL_SPEED_STEP

        ball.x = int(ball_x)
        ball.y = int(ball_y)

        if ball_y > LCD.height:
            return score

        time.sleep(0.02)


high_score = load_high_score()
draw_epd(high_score)

try:
    while True:
        score_label, paddle, ball = new_board()
        time.sleep(0.5)
        score = play_game(score_label, paddle, ball)

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
