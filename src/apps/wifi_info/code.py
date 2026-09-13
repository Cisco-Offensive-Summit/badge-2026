import alarm
import board
import microcontroller
import supervisor
import terminalio
from adafruit_display_text.label import Label

from badge.constants import BB_HEIGHT, WHITE
from badge.screens import EPD, LCD, center_text_x_plane, clear_screen, round_button, wrap_message

supervisor.runtime.autoreload = False

FONT = terminalio.FONT

try:
    import secrets
    ssid = getattr(secrets, "WIFI_NETWORK", "(not set)")
    password = getattr(secrets, "WIFI_PASS", "(not set)")
except ImportError:
    ssid = password = host = "secrets.py missing"

clear_screen(LCD)

# EPD is the wider/bigger screen (264x176 vs the LCD's 128x128), use it for the info
clear_screen(EPD)
title = center_text_x_plane(EPD, "WiFi Info", y=12, scale=2)
EPD.root_group.append(title)

info = f"SSID:\n{ssid}\n\nPassword:\n{password}"
body = wrap_message(EPD, info, x=6, y=40)
body.color = WHITE
EPD.root_group.append(body)

btn_lbl = Label(font=FONT, text="S4 = Exit")
radius = 5
btn_x = 2 + radius
btn_y = EPD.height - 2 - radius - (btn_lbl.bounding_box[BB_HEIGHT] // 2)
EPD.root_group.append(round_button(btn_lbl, btn_x, btn_y, radius))
EPD.refresh()

# S4 wakes the badge from light sleep so it can return to the launcher
S4_pin_alarm = alarm.pin.PinAlarm(pin=board.BTN4, value=False, pull=True)
triggered_alarm = alarm.light_sleep_until_alarms(S4_pin_alarm)
if triggered_alarm.pin == S4_pin_alarm.pin:
    microcontroller.reset()
