import board
import busio
import sys
import time
from badge.epd_otp import read_otp
from badge.pervasive_epd import PervasiveWideSmall
from adafruit_st7735r import ST7735R
from adafruit_display_shapes.roundrect import RoundRect
from adafruit_display_text.label import Label
from adafruit_display_text import wrap_text_to_pixels
from displayio import Bitmap
from displayio import Group
from displayio import Palette
from displayio import release_displays
from displayio import TileGrid
from fourwire import FourWire
from terminalio import FONT
from traceback import format_exception, print_exception

from badge.constants import BLACK
from badge.constants import WHITE
from badge.constants import BB_WIDTH
from badge.constants import BB_HEIGHT
from badge.constants import EPD_WIDTH
from badge.constants import EPD_HEIGHT
from badge.constants import LCD_WIDTH
from badge.constants import LCD_HEIGHT

LCD = None
EPD = None


###############################################################################
# SmartEPD — transparent wrapper around PervasiveWideSmall.
#
# Provides a unified refresh() interface that automatically handles the
# slow-refresh prime on first call when fast_mode is enabled.
#
#   refresh()       — smart: slow on first call, fast on all subsequent ones
#                      (or always slow when fast_mode=False)
#   slow_refresh()  — always a full normal refresh; resets the prime flag
#   fast_refresh()  — always fast; auto-primes with slow_refresh if needed
#
# All other EPD attributes (root_group, width, height, busy, …) are
# transparently proxied to the underlying display object so existing badge
# code requires no changes.
###############################################################################
class SmartEPD:
    """
    Transparent wrapper around PervasiveWideSmall that provides a unified
    refresh() interface.

    refresh() behaviour:
      fast_mode=False            →  always slow_refresh
      fast_mode=True, first call →  slow_refresh (primes the fast buffer)
      fast_mode=True, subsequent →  fast_refresh

    Manual control is always available:
      slow_refresh()  — full normal refresh, resets the prime flag
      fast_refresh()  — fast refresh; auto-primes on first call if needed

    All EPD attributes (width, height, busy, time_to_refresh, …) are
    forwarded to the underlying display via __getattr__. root_group is
    exposed as a property so existing assignment syntax works unchanged.

    Both refresh paths wait out their own minimum interval, so callers never
    see EPaperDisplay's "Refresh too soon" RuntimeError. Note the two limits are
    tracked independently by the base class: fast_refresh() is gated by
    fast_seconds_per_frame (0.5 s) against the last *fast* refresh, while
    .time_to_refresh only ever reports the normal seconds_per_frame (40 s).
    Waiting on .time_to_refresh before a fast refresh would stall 40 s.
    """

    def __init__(self, epd: PervasiveWideSmall, fast_mode: bool = False):
        self._epd       = epd
        self._fast_mode = fast_mode
        self._primed    = False
        self._last_fast = 0
        self._fast_interval = getattr(epd, "FAST_SECONDS_PER_FRAME", 0.5)

    # --- Transparent read proxy (called only when attr not found locally) ---

    def __getattr__(self, name: str):
        return getattr(self._epd, name)

    # --- root_group property (the only EPD attribute that gets assigned) ---

    @property
    def root_group(self):
        return self._epd.root_group

    @root_group.setter
    def root_group(self, value):
        self._epd.root_group = value

    # --- Refresh interface ---

    def _wait_idle(self, timeout: float = 20.0) -> None:
        """Block until any in-flight refresh has finished.

        Both refresh() and fast_refresh() return false (-> "Refresh too soon")
        while the panel is still physically refreshing. Reading .busy also pumps
        the driver's background state machine, which is what clears the flag and
        sends the stop sequence, so this poll is required, not just polite.
        """
        deadline = time.monotonic() + timeout
        while self._epd.busy:
            if time.monotonic() > deadline:
                break
            time.sleep(0.05)

    def _wait_until_ready(self) -> None:
        """Block until a full refresh is allowed (normal interval, ~40 s)."""
        remaining = self._epd.time_to_refresh
        if remaining > 0:
            time.sleep(remaining + 0.05)

    def _fast(self) -> None:
        """Fast refresh, waiting out only the fast interval (~0.5 s)."""
        self._wait_idle()
        if self._last_fast:
            remaining = self._fast_interval - (time.monotonic() - self._last_fast)
            if remaining > 0:
                time.sleep(remaining + 0.05)
        self._epd.fast_refresh()
        self._last_fast = time.monotonic()

    def _baj_rendered_by_root_group(self) -> bool:
        """Return True when baj already rendered the EPD assignment.

        The simulator patches EPaperDisplay.root_group so assigning a new group
        updates the pygame EPD immediately. Calling the desktop epaperdisplay
        refresh path afterwards can block or fail in ways real CircuitPython
        does not. Hardware never has the baj module loaded, so it still uses the
        normal slow/fast refresh sequence below.
        """
        if "baj" not in sys.modules:
            return False
        self._primed = True
        self._last_fast = time.monotonic()
        return True

    def slow_refresh(self) -> None:
        """Normal full refresh (~2.5 s). Always primes the fast-update buffer."""
        if self._baj_rendered_by_root_group():
            return
        self._wait_idle()
        self._wait_until_ready()
        self._epd.refresh()
        self._primed = True
        self._last_fast = time.monotonic()

    def fast_refresh(self) -> None:
        """
        Fast partial refresh (~0.9 s).
        Automatically primes with a slow_refresh on the very first call;
        all subsequent calls go straight to the hardware fast path.
        """
        if self._baj_rendered_by_root_group():
            return
        if not self._primed:
            self.slow_refresh()
            return
        self._fast()

    def refresh(self) -> None:
        """
        Smart refresh — routes based on fast_mode and prime state:

          fast_mode=False            →  slow_refresh
          fast_mode=True, first call →  slow_refresh  (primes the buffer)
          fast_mode=True, subsequent →  fast_refresh
        """
        if self._baj_rendered_by_root_group():
            return
        if self._fast_mode and self._primed:
            self._fast()
        else:
            self.slow_refresh()


###############################################################################
# Initialise both screens and return (LCD, EPD).
#
# fast_mode  — when True the EPD is created with fast_mode=True and wrapped
#              in SmartEPD so that epd.refresh() automatically uses the fast
#              path after the first (priming) slow refresh.
###############################################################################
def _init_screens(fast_mode: bool = False):
    global LCD
    global EPD

    # release_displays() is called inside read_otp() as its first action,
    # so any displays alive from a prior session (never_reset pins) are freed
    # before we touch the GPIO lines or create a new SPI bus.
    psr = read_otp()

    # Shared SPI bus for both LCD and EPD.
    d_spi = busio.SPI(board.EINK_CLKS, board.EINK_MOSI)

    # LCD — ST7735R on its own FourWire (TFT_CS / TFT_DC / TFT_RST)
    lcd_fw = FourWire(d_spi, command=board.TFT_DC, chip_select=board.TFT_CS,
                      reset=board.TFT_RST, baudrate=20000000)
    LCD = ST7735R(lcd_fw, width=LCD_WIDTH, height=LCD_HEIGHT, colstart=1,
                  rowstart=3, rotation=0)

    # EPD — PervasiveWideSmall on its own FourWire (EINK_CS / EINK_DC / EINK_RST)
    epd_fw = FourWire(d_spi, command=board.EINK_DC, chip_select=board.EINK_CS,
                      reset=board.EINK_RST, baudrate=20000000)
    _epd = PervasiveWideSmall(epd_fw, psr=psr, busy_pin=board.EINK_BUSY,
                              fast_mode=fast_mode)
    EPD = SmartEPD(_epd, fast_mode=fast_mode)

    return LCD, EPD

###############################################################################
# While it is just a easy and clean to do this manually, this function allows
#   for other users to understand what is happening when reading code in the 
#   apps.
#
def clear_screen(screen):
        screen.root_group = Group()

###############################################################################
# Returns a adafruit_display_text.label.Label with the text wrapped
#
# screen: The badge screen object either LCD or EPD. Used to gather dimensions
# message: This is the text that will be wrapped
# font: This is a font object from the fontio class. Default is terminalio.FONT
# x: This is the starting x location
# y: This is the starting y location.
# scale: This is the scaling of the font.
#
def wrap_message(screen, message, font=FONT, x=0, y=None, scale=1):
  lb = Label(font=font, text="", scale=scale)
  if not y:
    lb.y = (lb.bounding_box[BB_HEIGHT]*scale)//2
  else:
    lb.y = y
  lb.x = x
  max_width = screen.width - x

  def fits(text):
    lb.text = text
    return (lb.bounding_box[BB_WIDTH] * scale) <= max_width

  def append_wrapped_word(lines, current, word):
    if current:
      candidate = current + " " + word
      if fits(candidate):
        return lines, candidate
      lines.append(current)

    # Long paths and filenames often have no spaces. Split any word that still
    # cannot fit so LCD status text never runs off the right edge.
    current = ""
    for char in word:
      candidate = current + char
      if fits(candidate):
        current = candidate
      else:
        if current:
          lines.append(current)
        current = char
    return lines, current

  wrapped_lines = []
  for raw_line in str(message).split("\n"):
    current = ""
    for word in raw_line.split(" "):
      if word == "":
        continue
      wrapped_lines, current = append_wrapped_word(wrapped_lines, current, word)
    wrapped_lines.append(current)

  lb.text = "\n".join(wrapped_lines).rstrip("\n")
  return lb
  
###############################################################################
# This function returns Group that contains the text that it is passed inside 
#   of a rounded rectangle.  This group, once returned, would then need to be 
#   appended to either the LCD screen root group or the EPD screen root group
#
# label: The button will be built around this label. Must be of type 
#        adafruit_display_text.label.Label
# x: The left edge of the text (not of the button)
# y: The center of the text on the y plane
# fill: Hex encoded color that can fill the button. None means translucent
# stroke: The thickness of the button line.
# EXAMPLE:
#   lb = Label(font=FONT,text="s4 next")
#   splash = round_button(lb, 10, 15, 5)
#   LCD.root_group = splash
#
def round_button(label:Label, x, y, rad, color=None, fill=None ,stroke=1):
  scale = label.scale
  if not color:
    color = label.color
  label.x = x
  label.y = y
  t_height = label.bounding_box[BB_HEIGHT] * scale
  t_width = label.bounding_box[BB_WIDTH] * scale
  total_width = t_width + (rad * 2)
  total_height = t_height + (rad * 2)
  rect_x = x - rad
  rect_y = y - rad - ((label.font.get_bounding_box()[1]*scale)//2)
  
  rect = RoundRect(x=rect_x, y=rect_y, width=total_width, height=total_height, 
         r=rad, fill=fill, outline=color, stroke=stroke)

  splash = Group()
  splash.append(rect)
  splash.append(label)
  return splash

###############################################################################
# This function simply will print exceptions to the EPD screen.
#
def epd_print_exception(e:Exception):
  print_exception(e)
  text = '\n'.join(wrap_text_to_pixels('\n'.join(format_exception(e, limit=2)), EPD_WIDTH, FONT))
  lb = Label(font=FONT, text=text, anchor_point=(0,0), line_spacing=0.9)
  lb.anchored_position = (1,1)
  EPD.root_group = lb
  EPD.refresh()

###############################################################################
# This function will return a basic Label object with the X set such that the
#   text will be centered in the screen that is passed to the function. Optionally 
#   the Y can also be passed to this function and it will be set also.  If left 
#   empty the Y will need to be set after the Label is returned.
#
# screen: The screen object. Must be either LCD or EPD
# text: The text to be centered on the screen
# y: The starting Y position for the text
# scale: This is the scaling of the font.
# color: 24 bit color. Either hex or int
#
def center_text_x_plane(screen, text_or_label, y=None, scale=1, color=WHITE):
    # If the input is a string, create a new Label
  if isinstance(text_or_label, str):
    lb = Label(font=FONT, text=text_or_label, scale=scale, color=color)
  elif isinstance(text_or_label, Label):
    lb = text_or_label
    # Ensure we respect the passed-in scale only if this is a new label
    scale = lb.scale
  else:
      raise TypeError("text_or_label must be a string or a Label object")

  # Set x position to center
  lb.x = (screen.width // 2) - ((lb.bounding_box[BB_WIDTH] * scale) // 2)
  if y:
    lb.y = y
  else:
    lb.y = (lb.bounding_box[BB_HEIGHT] * scale) //2

  return lb

###############################################################################
# This function will return a basic Label object with the Y set such that the
#   text will be centered in the screen that is passed to the function. Optionally 
#   the X can also be passed to this function and it will be set also.  If left 
#   empty the X will need to be set after the Label is returned.
#   of the screen
#
# screen: The screen object. Must be either LCD or EPD
# text: The text to be centered on the screen
# x: The starting X position for the text
# scale: This is the scaling of the font.
# color: 24 bit color. Either hex or int
#
def center_text_y_plane(screen, text_or_label, x=None, scale=1, color=WHITE):
  # If the input is a string, create a new Label
  if isinstance(text_or_label, str):
    lb = Label(font=FONT, text=text_or_label, scale=scale, color=color)
  elif isinstance(text_or_label, Label):
    lb = text_or_label
    # Use the scale of the existing label
    scale = lb.scale
  else:
    raise TypeError("text_or_label must be a string or a Label object")

  # Calculate glyph height using the font's bounding box
  glyph_height = lb._font.get_bounding_box()[1] * scale

  # Center vertically on the screen
  lb.y = (glyph_height // 2) + (screen.height // 2) - ((lb.bounding_box[BB_HEIGHT] * scale) // 2)

  # Set x position if provided
  if x is not None:
    lb.x = x

  return lb

###############################################################################
# This function will take a label that it is passed and set the Y starting point
#   for the text relative to the size of the screen. The scale for the text must
#   be set prior to calling this function.                                                                                                                
#
# screen: The screen object. Must be either LCD or EPD
# lb: label containing the text and scale.
#
def center_label_x_plane(screen, lb):
  lb.x = (screen.width // 2) - ((lb.bounding_box[BB_WIDTH] * lb.scale) // 2)

###############################################################################
# This function will take a label that it is passed and set the Y starting point
#   for the text relative to the size of the screen. The scale for the text must
#   be set prior to calling this function.
#
# screen: The screen object. Must be either LCD or EPD
# lb: label containing the text and scale.
#
def center_label_y_plane(screen, lb):
  glyph_height = lb._font.get_bounding_box()[1]*lb.scale
  lb.y = (glyph_height //2) + (screen.height // 2) - (lb.bounding_box[BB_HEIGHT]*lb.scale // 2)

###############################################################################
# This function will set the background color of the screen that is passed to 
#   it. This must be call first before anything else is added to the screen. If
#   not then the background color will overwrite anyother groups set for that 
#   screen.  You should note that the LCD screen will draw the color automaticly,
#   while the EPD screen will need EPD.refresh() to draw the screen.
#
# screen: Screen to set a backround color on. Either LCD or EPD
# color: 24 bit color. Either hex or int
def set_background(screen, color):
  group = Group()
  background = Bitmap(screen.width, screen.height, 1)
  palette1 = Palette(1)
  palette1[0] = color                                                                                                                                     
  tile_grid1 = TileGrid(background, pixel_shader=palette1)
  group.append(tile_grid1)
  screen.root_group = group

###############################################################################

if not (LCD and EPD):
    LCD, EPD = _init_screens(fast_mode=True)
