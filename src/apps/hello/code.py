import adafruit_requests as requests
import alarm
import board
import displayio
import json
import microcontroller
import socketpool
import ssl
import supervisor
import terminalio
import time
import wifi
from adafruit_bitmap_font import bitmap_font
from adafruit_connection_manager import connection_manager_close_all
from adafruit_display_text.label import Label
from os import sync
from sys import exit
from traceback import print_exception
from time import sleep
from badge.constants import *
from badge.neopixels import NP
from badge.screens import EPD
from badge.screens import LCD
from badge.screens import clear_screen
from badge.screens import epd_print_exception
from badge.screens import wrap_message
from badge.screens import set_background
from badge.screens import center_text_x_plane
from badge.screens import center_label_y_plane

supervisor.runtime.autoreload = False
###############################################################################
FONT = terminalio.FONT
EPD_H = EPD.height
EPD_W = EPD.width
LCD_H = LCD.height
LCD_W = LCD.width
splash = None
DEFAULT_FONT = terminalio.FONT
CUSTOM_FONT = 'font/custom_font.pcf'
###############################################################################
# Anything that touches secrets.py is resolved lazily by load_secrets() so a
# missing / half-configured secrets file raises inside main() -- where the
# handler at the bottom of this file can render the traceback to the EPD --
# instead of blowing up at import time with nothing on screen.
SSID = None
WIFI_PASSWORD = None
UNIQUE_ID = None
session = None
# one pool only; new pools leak ConnectionManagers
pool = None
###############################################################################
HOST = None
HELLO_API = 'badge/hello'
URL = None
METHOD = 'GET'
HEADERS = {
    'Accept': 'application/json',
    'Content-Type': 'application/json'
}
JSON = {}
hello_json = None


def load_secrets():
  """Pull the badge's config out of secrets.py.

  Raises ImportError if secrets.py is absent and AttributeError if the badge
  has not finished setup (e.g. no UNIQUE_ID yet).
  """
  global SSID, WIFI_PASSWORD, UNIQUE_ID, HOST, URL

  import secrets

  SSID = secrets.WIFI_NETWORK
  WIFI_PASSWORD = secrets.WIFI_PASS
  HOST = secrets.HOST_ADDRESS
  UNIQUE_ID = secrets.UNIQUE_ID
  URL = HOST + HELLO_API
  JSON['uniqueID'] = UNIQUE_ID

###############################################################################
# This sets pin S4 as the button that will wake the badge from deep sleep
S4_pin_alarm = alarm.pin.PinAlarm(pin=board.BTN4, value=False, pull=True)
S7_pin_alarm = alarm.pin.PinAlarm(pin=board.BTN1, value=False, pull=True)

###############################################################################

def connect_screen_splash():

  splash = displayio.Group()
  LCD.root_group = splash

  return splash

###############################################################################

def request_data(hello_json):
  global session, pool

  L1 = Label(font=FONT,text="Connecting to WIFI",color=WHITE)
  L1.y = L1.height // 2
  L2 = Label(font=FONT,text="Creating session pool", color=WHITE)
  L2.y = L2.height + (L2.height // 2)
  L3 = Label(font=FONT,text="Requesting new code", color=WHITE)
  L3.y = (L3.height * 2) + (L3.height // 2)

  clear_screen(LCD)
  splash = connect_screen_splash()
  NP[0] = GREEN
  NP.show()
  splash.append(L1)

  # reconnect strands held sockets
  if not wifi.radio.connected:
    wifi.radio.connect(SSID, WIFI_PASSWORD)
  NP[1] = GREEN
  NP.show()
  splash.append(L2)
  sleep(0.5)

  # lwIP has 8 sockets total
  if pool is None:
    pool = socketpool.SocketPool(wifi.radio)

  if not session:
    session = requests.Session(pool, ssl.create_default_context())
  NP[2] = GREEN
  NP.show()
  splash.append(L3)
  sleep(0.5)

  # Attempting to get the name tag
  # Adding other elements to the request
  if 'size' in hello_json.keys():
    JSON['size'] = hello_json['size']
  if 'font' in hello_json.keys():
    JSON['font'] = hello_json['font']

  rsp = session.request(method=METHOD,url=URL,json=JSON,headers=HEADERS)
  # If the request was a sucsess, extract info
  if rsp.status_code == 200:
    NP[3] = GREEN
    sleep(0.5)
    NP.fill(OFF)
    rsp_body_json = rsp.json()
    rsp.close()

  # else the request failed: raise so the main loop can report it and recover
  else:
    status_code = rsp.status_code
    try:
      message = rsp.json().get('message', 'no message')
    except Exception:
      message = 'unreadable response body'
    rsp.close()
    raise HelloError('Error {}:\n{}'.format(status_code, message))

  new_file = False
  if rsp_body_json['font_file']:
    font_file = rsp_body_json['font_file']
    body = {
      'uniqueID' : UNIQUE_ID,
      "file": font_file
    }
    rsp = session.request(method="GET",url=HOST + "badge/download", json=body, stream=True)
    # self-closes only if fully consumed
    try:
      if rsp.status_code < 400:
        with open(CUSTOM_FONT, 'wb') as f:
          for chunk in rsp.iter_content(chunk_size=1024 * 8):
            if chunk:
              f.write(chunk)
              f.flush()
              sync()
        new_file = True
      else:
        code = rsp.status_code
        raise HelloError('Font download failed:\n{}'.format(code))
    finally:
      try:
        rsp.close()
      except Exception:
        pass

  return rsp_body_json, new_file

###############################################################################

def set_font(font):
  if font == 'default':
    return DEFAULT_FONT
  return bitmap_font.load_font(font)

###############################################################################
def build_name_tag(hello_json, font):

  color = hello_json['color']
  bg_color = hello_json['background_color']
  name = hello_json['name']
  scale = hello_json['scale']

  set_background(EPD, bg_color)
  lb = Label(font=font, text=name, scale=scale, color=color)
  tag = center_text_x_plane(EPD,lb)
  center_label_y_plane(EPD, tag)
  EPD.root_group.append(tag)
  EPD.refresh()

###############################################################################

def epd_print_error(message):

  set_background(EPD, BLACK)
  lb = wrap_message(EPD, message)
  EPD.root_group.append(lb)
  EPD.refresh()

###############################################################################

class HelloError(Exception):
  """A recoverable problem talking to the badge API."""
  pass

###############################################################################

def reset_connections():
  # session=None alone keeps the cached manager + stranded sockets.
  # release_references=True would KeyError on our own pool.
  global session

  session = None

  if pool is None:
    return

  try:
    connection_manager_close_all(pool, release_references=False)
  except RuntimeError:
    pass
  except Exception as e:
    print_exception(e)

###############################################################################

def lcd_print_error(message, hold=4):
  """Report a recoverable error on the LCD, then restore the button labels.

  The LCD is used on purpose: the EPD keeps showing the current name tag, so a
  failed refresh does not cost the user their badge display.
  """
  # drop stranded sockets or retries degrade
  reset_connections()

  clear_screen(LCD)
  splash = connect_screen_splash()
  lb = wrap_message(LCD, message)
  lb.color = RED
  splash.append(lb)

  for i in range(3):
    NP.fill(RED)
    NP.show()
    sleep(0.25)
    NP.fill(OFF)
    NP.show()
    sleep(0.25)

  sleep(hold)
  clear_screen(LCD)
  connect_screen_splash()
  set_lcd_button_labels()
  
###############################################################################

def read_json_file():
  # try to load any saved hello screen info.
  try:
    with open('hello.json', 'r') as j:
      hello_json = json.load(j)
  # if that file doesn't exist then just set the value to none.
  except OSError as e:
    hello_json = None

  return hello_json

###############################################################################

def set_default_background():
  hello = dict()
  hello['name']='nobody'
  hello['color']=0xffffff
  hello['background_color']=0x0
  hello['scale']=3
  build_name_tag(hello, font=DEFAULT_FONT)

###############################################################################

def set_lcd_button_labels():
  splash = LCD.root_group

  L4 = Label(font=FONT,text="S4 GET TAG", padding_top=2,padding_bottom=2,
  padding_right=2,padding_left=2, color=BLACK, background_color=YELLOW,
  label_direction = "TTB")
  L4.y = 0
  L4.x = 2
  L5 = Label(font=FONT,text="S7   EXIT", padding_top=2,padding_bottom=2,
    padding_left=2, padding_right=2, color=BLACK, background_color=YELLOW,
    label_direction = "TTB")
  L5.y = 2
  L5.x = LCD.width - (L5.width +2) * 2

  splash.append(L4)
  splash.append(L5)

###############################################################################

def main():
  global splash

  # resolve secrets first so setup problems surface on the EPD
  load_secrets()

  # try to load any saved hello screen info.
  hello_json = read_json_file()

  # Create a root group for the LCD screen
  splash = connect_screen_splash()

  set_lcd_button_labels()

  # always have a usable font, even if nothing is saved yet
  font = DEFAULT_FONT

  # if there is saved hello screen info, load that.
  if hello_json:
    clear_screen(EPD)
    # set the font value to what is saved in the file.
    saved_font = hello_json['font']
    # check to see if we need to use the default or the custom font
    if saved_font != 'default':
      font = set_font(CUSTOM_FONT)
    else:
      font = DEFAULT_FONT
    build_name_tag(hello_json, font)

  else:
    set_default_background()

  while True:
    triggered_alarm = alarm.light_sleep_until_alarms(S4_pin_alarm, S7_pin_alarm)
    if triggered_alarm.pin == S7_pin_alarm.pin:
      microcontroller.reset()

    # A WiFi/API failure is recoverable: report it on the LCD, keep the name
    # tag already on the EPD, and drop back into the loop so the user can just
    # press S4 to retry instead of the app dying.
    try:
      new_json, new_file = request_data(hello_json)
    except HelloError as e:
      lcd_print_error('{}\n\nS4 retry / S7 exit'.format(e))
      continue
    except (ConnectionError, OSError, RuntimeError, ValueError) as e:
      print_exception(e)
      lcd_print_error('Network error:\n{}\n\nS4 retry / S7 exit'.format(e))
      continue
    except Exception as e:
      print_exception(e)
      lcd_print_error('{}:\n{}\n\nS4 retry / S7 exit'.format(type(e).__name__, e))
      continue

    hello_json = new_json
    NP.fill(OFF)
    NP.show()

    with open('hello.json', 'w') as j:
      json.dump(hello_json, j)

    clear_screen(EPD)
    clear_screen(LCD)
    if hello_json['font'] == 'default':
      font = DEFAULT_FONT
    if  new_file:
      font = set_font(CUSTOM_FONT)
    set_lcd_button_labels()
    build_name_tag(hello_json, font)
    triggered_alarm = alarm.light_sleep_until_alarms(S4_pin_alarm, S7_pin_alarm)


if __name__ == "__main__":
  try:
    main()
  except ImportError:
    epd_print_exception(AttributeError(
      "Secrets file is missing. Please visit:\nbadger.becomingahacker.com /recovery"))
    time.sleep(60)
    microcontroller.reset()
  except Exception as e:
    # Everything else -- including the AttributeError raised when the badge
    # has not been set up yet (no secrets.UNIQUE_ID) -- gets its traceback
    # drawn on the EPD so the failure is visible without a serial console.
    epd_print_exception(e)
    time.sleep(60)
    microcontroller.reset()
