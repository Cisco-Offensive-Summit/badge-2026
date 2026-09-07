import board, time, keypad
import gc
import terminalio
from displayio import Group
import json

from os import stat
from adafruit_display_text import label
from adafruit_display_text import bitmap_label

import badge.neopixels
from badge.wifi import WIFI
from badge.constants import EPD_WIDTH, EPD_HEIGHT, LCD_WIDTH, WHITE, BLACK
from badge.log import log
from badge.screens import round_button
from scrollable_list import ScrollableList

# EPD_SMALL left over from the old small/large EPD split; the 2026 badge only
# has the wide screen. Kept as a constant so the toolbar text below is unchanged.
EPD_SMALL = False
EPD_ENABLED = True

SCHED_PATH = '/apps/schedule/sched.json'

# terminalio.FONT has no glyphs for these; map to ASCII lookalikes.
# All are 1:1 so line offsets are unaffected.
_SUBS = (("\u2013", "-"), ("\u2014", "-"), ("\u2019", "'"),
         ("\u201c", '"'), ("\u201d", '"'), ("\u2022", "*"))

def to_ascii(s: str) -> str:
    for a, b in _SUBS:
        if a in s:
            s = s.replace(a, b)
    return s

def expand_breaks(s: str) -> str:
    """Turn the schedule feed's literal <br> tags into real newlines.

    Must run before wrapping: it changes length, whereas to_ascii() is 1:1 and
    is applied after wrapping so the line-offset table stays valid.
    A doubled <br><br> becomes a blank line, i.e. a paragraph gap.
    """
    for tag in ("<br />", "<br/>", "<br>"):
        if tag in s:
            s = s.replace(tag, "\n")
    return s


def bar_text(left: str, mid: str, right: str, width_px: int = EPD_WIDTH, char_w: int = 6) -> str:
    """Spread three labels across a full-width inverted toolbar.

    Padded to exactly panel-width/char_w characters so the white background
    spans the whole panel instead of stopping short of it.
    """
    n = width_px // char_w
    gap = (n - len(left) - len(mid) - len(right)) // 2
    s = left + " " * gap + mid + " " * gap + right
    return s + " " * (n - len(s))


def wrap_mono(text: str, width_px: int, char_w: int = 6) -> list:
    """Word-wrap for a fixed-width font.

    wrap_text_to_pixels() measures every glyph, which costs ~5.6 s for a long
    talk description. terminalio.FONT is monospace (6 px advance for every
    glyph, verified on hardware), so a character count gives the same result
    for ~0 s.

    Two harmless deviations from wrap_text_to_pixels, both verified to stay
    within the line width: leading spaces after a newline are dropped, and a
    word longer than a line (e.g. a bare URL) starts its hard-split on a fresh
    line rather than filling the current one.
    """
    max_chars = width_px // char_w
    if max_chars < 1:
        max_chars = 1
    lines = []
    for para in text.split("\n"):
        if not para:
            lines.append("")
            continue
        cur = ""
        for word in para.split(" "):
            cand = word if not cur else cur + " " + word
            if len(cand) <= max_chars:
                cur = cand
                continue
            if cur:
                lines.append(cur)
            # hard-split any word longer than a full line
            while len(word) > max_chars:
                lines.append(word[:max_chars])
                word = word[max_chars:]
            cur = word
        lines.append(cur)
    return lines

# Convert meta integer to date string
def meta_date(meta: int) -> str:
    month = f"{meta>>15:02d}"
    day = f"{(meta & 0x7fff)>>10:02d}"
    hour = f"{8+(((meta & 0x3ff)>>4)//4):02d}"
    minute = f"{(((meta & 0x3ff)>>4)%4)*15:02d}"

    return f"{month}-{day} {hour}:{minute}"

class WifiUnreachable(Exception):
    def __init__(self, message):
        self.message = message          
        super().__init__(message)
    def __str__(self):
        return self.message

class EndpointNotReachable(Exception):
    def __init__(self, message):
        self.message = message       
        super().__init__(message)
    def __str__(self):
        return self.message

class EndpointBadCredentials(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(message)
    def __str__(self):
        return self.message

class EndpointUnknownResponse(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(message)
    def __str__(self):
        return self.message

class CantFetchSchedule(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(message)
    def __str__(self):
        return self.message

class LCDLoading:
    def __init__(self):
        self.group = Group()
        self.loading_area = label.Label(terminalio.FONT, text='\n'.join(wrap_mono("Retrieving schedule, please wait...", LCD_WIDTH)))
        self.loading_area.anchor_point = (0,0)
        self.loading_area.anchored_position = (2, 2)
        self.group.append(self.loading_area)

    def get_group(self):
        return self.group

    def set_text(self, text):
        self.loading_area.text = '\n'.join(wrap_mono(text, LCD_WIDTH))

    def set_error(self, text):
        self.loading_area.text = '\n'.join(wrap_mono(text, LCD_WIDTH))
        self.loading_area.color = 0x111111
        self.loading_area.background_color = 0xFF0000

class LCDListHeader:
    """Track badge + time row that sits above the ScrollableList.

    ScrollableList has no on-selection-change hook, so the app calls
    update() with the newly selected talk after every input.
    """
    def __init__(self):
        self.group = Group()

        self.track_area = label.Label(terminalio.FONT)
        self.track_area.anchor_point = (0,0)
        self.track_area.anchored_position = (1,0)

        self.time_area = label.Label(terminalio.FONT)
        self.time_area.anchor_point = (0,0)
        self.time_area.anchored_position = (1, 0)
        self.time_area.background_color = 0xaaaaaa
        self.time_area.color = 0x111111

        self.group.append(self.time_area)
        self.group.append(self.track_area)

    def get_group(self):
        return self.group

    def update(self, talk):
        track = talk["track"]
        if "Main" in track:
            self.track_area.background_color = 0x0000FF
            self.track_area.text = "Main"
        elif "Hardware" in track:
            self.track_area.background_color = 0xFF0000
            self.track_area.text = "Hardware"
        else:
            self.track_area.background_color = 0x00FF00
            self.track_area.color = 0x111111
            self.track_area.text = "?????"

        self.time_area.text = "         {} ".format(meta_date(talk["meta"]))


class LCDTitle:
    def __init__(self):
        self.WRAP_WIDTH = 124
        self.group = Group()
        
        self.title_area = label.Label(terminalio.FONT)
        self.title_area.anchor_point = (0,0)
        self.title_area.anchored_position = (4, 16)

        # Title Scrolling behavior
        self.title_lines = 0
        self.title_wait = 200
        self.title_wait_acc = 0

        self.track_area = label.Label(terminalio.FONT)
        self.track_area.anchor_point = (0,0)
        self.track_area.anchored_position = (1,0)
        
        self.time_area = label.Label(terminalio.FONT)
        self.time_area.anchor_point = (0,0)
        self.time_area.anchored_position = (1, 0)
        self.time_area.background_color = 0xaaaaaa
        self.time_area.color = 0x111111

        self.group.append(self.title_area)
        self.group.append(self.time_area)
        self.group.append(self.track_area)

    def get_group(self):
        return self.group

    def set_data(self, title: str, track: str, meta: int):
        wrapped_title = wrap_mono(title, self.WRAP_WIDTH)
        self.title_lines = len(wrapped_title)
        self.title_area.y = 16
        self.title_wait_acc = 0
        self.title_area.text = "\n".join(wrapped_title)
        date_text = f"         {meta_date(meta)} "

        if "Main" in track:
            self.track_area.background_color = 0x0000FF
            self.track_area.text = "Main"
        elif "Hardware" in track:
            self.track_area.background_color = 0xFF0000
            self.track_area.text = "Hardware"
        else:
            self.track_area.background_color = 0x00FF00
            self.track_area.color = 0x111111
            self.track_area.text = "?????"

        self.time_area.text = date_text

    def update(self):
        if self.title_lines > 7:
            if self.title_wait_acc > self.title_wait:
                ny = self.title_area.anchored_position[1] - 1
                self.title_area.anchored_position = (4, ny)
            elif self.title_wait_acc == 0:
                self.title_area.anchored_position = (4, 16)
            
            self.title_wait_acc += 1

            if self.title_area.anchored_position[1] <= ((self.title_lines - 7) * -12) + 16 and self.title_wait_acc > 0:
                self.title_wait_acc = -1 * self.title_wait

class EPDTalks:
    """Schedule splash screen: title, talk count and the button legend.

    Button map (S4-S7 are BTN4-BTN1, so key_number 0..3 == S7,S6,S5,S4):
      S4 Up   S5 Down   S6 Exit   S7 Select
    """
    root = None
    def __init__(self, talk_count=None):
        self.root = Group()

        title = label.Label(font=terminalio.FONT, text=" Summit Schedule ",
                            color=BLACK, background_color=WHITE,
                            background_tight=True, scale=2, anchor_point=(0.5, 0))
        title.anchored_position = (EPD_WIDTH // 2, 6)

        if talk_count is None:
            sub_text = "People are talking."
        else:
            sub_text = "{} talks scheduled".format(talk_count)
        subtitle = label.Label(font=terminalio.FONT, text=sub_text,
                               color=WHITE, anchor_point=(0.5, 0))
        subtitle.anchored_position = (EPD_WIDTH // 2, 40)

        self.root.append(title)
        self.root.append(subtitle)

        # Button legend, 2x2. round_button() takes the text centre as (x, y).
        col_l = 46
        col_r = EPD_WIDTH - 92
        row_t = 86
        row_b = 124
        for text, x, y in (("S4  Up", col_l, row_t),
                          ("S5  Down", col_l, row_b),
                          ("S7  Select", col_r, row_t),
                          ("S6  Exit", col_r, row_b)):
            lb = label.Label(font=terminalio.FONT, text=text, color=WHITE)
            self.root.append(round_button(lb, x, y, 5))

        hint = label.Label(font=terminalio.FONT,
                          text="Select a talk to read its description",
                          color=WHITE, anchor_point=(0.5, 0))
        hint.anchored_position = (EPD_WIDTH // 2, EPD_HEIGHT - 18)
        self.root.append(hint)

    def get_group(self):
        return self.root

class EPDDescription:
    root = None
    tool_bar_l = None
    desc_l = None
    
    def __init__(self):
        self.root = Group()
        self.x = 2
        # Clear of the 12 px toolbar.
        self.y = 13
        self._wrapped = ""
        self._offsets = [0]
        self.line_count = 0
        self.description_position = 0
        # Measured on hardware at y=13: spacing 0.9 -> 10 px pitch -> 16 lines,
        # 1.0 -> 12 px -> 13 lines, 1.1 -> 13 px -> 12, 1.2 -> 14 px -> 11.
        # Change both together or the last line clips off the panel.
        self.LINE_SPACING = 1.0
        self.MAX_LINES = 13
        if EPD_SMALL:
            tool_bar_text = "Up|Dwn  Info  Bck|Top "
        else:
            tool_bar_text = bar_text("Up | Down", "<Info>", "Back | Top")
        
        self.tool_bar_l = label.Label(font=terminalio.FONT, text=tool_bar_text, color=BLACK, background_color=WHITE, background_tight=True, anchor_point=(0,0))
        self.tool_bar_l.anchored_position = (0,0)

        self.desc_l = bitmap_label.Label(font=terminalio.FONT, text="No Data...", color=WHITE, line_spacing=self.LINE_SPACING, anchor_point=(0, 0))
        self.desc_l.anchored_position = (self.x, self.y)

        self.root.append(self.tool_bar_l)
        self.root.append(self.desc_l)

    def get_group(self):
        return self.root

    def _render(self):
        start = self._offsets[self.description_position]
        end_i = self.description_position + self.MAX_LINES
        if end_i < self.line_count:
            end = self._offsets[end_i] - 1
        else:
            end = len(self._wrapped)
        self.desc_l.text = self._wrapped[start:end]

    def set_data(self, epd, description: str):
        # Keep the wrapped text as ONE string plus a line-offset table.
        lines = wrap_mono(expand_breaks(description), EPD_WIDTH-self.x)
        self.line_count = len(lines)
        self._wrapped = '\n'.join(lines)
        lines = None
        self._wrapped = to_ascii(self._wrapped)

        offs = [0]
        i = self._wrapped.find('\n')
        while i >= 0:
            offs.append(i + 1)
            i = self._wrapped.find('\n', i + 1)
        self._offsets = offs

        self.description_position = 0
        self._render()

    def input(self, scroll_up: bool) -> bool:
        if self.line_count < self.MAX_LINES:
            return False
        
        np = 0

        # Scroll direction up
        if scroll_up:
            # Already at top
            if self.description_position == 0:
                return False
            np = max(0, self.description_position - self.MAX_LINES)
        # Scroll direction Down
        else:
            # Already at bottom
            if self.description_position + self.MAX_LINES >= self.line_count:
                return False
            # Advance a whole page. Do NOT clamp to (line_count - MAX_LINES):
            # that re-aligned the last page to the bottom and re-showed lines
            # the reader had already passed. The final page may be partial.
            np = self.description_position + self.MAX_LINES
        
        self.description_position = np
        self._render()
        return True
    
    def top(self) -> bool:
        if self.line_count < self.MAX_LINES:
            return False
        self.description_position = 0
        self._render()
        return True
        

class ScheduleApp:
    def __init__(self, lcd, epd, ssid: str, wifipass: str, base_endpoint: str, unique_id: str):
        self.lcd = lcd
        self.epd = epd

        self.ssid = ssid
        self.wifipass = wifipass
        self.unique_id = unique_id
        self.sched_endpoint = f"{base_endpoint}badge/schedule"
        self.sched_time_endpoint = f"{base_endpoint}badge/schedule_time"

        self.buttons = keypad.Keys((
            board.BTN1,
            board.BTN2,
            board.BTN3,
            board.BTN4,
        ), value_when_pressed=False)

    # Handle response codes from server
    def _handle_resp(self, resp) -> {}:
        sc = resp.status_code
        if sc == 200:
            return json.loads(resp.text)
        elif sc == 404:
            raise EndpointNotReachable(f"Could not reach endpoint: {self.sched_endpoint}.")
        elif sc >= 400 and sc < 500:
            raise EndpointBadCredentials(f"Token rejected at endpoint: {self.sched_endpoint}. Make sure you have registered your badge!")
        else:
            raise EndpointUnknownResponse(f"Unknown response. Code {sc} reason {resp.reason}")
        

    # Get schedule from server
    def _get_schedule(self, loading) -> {}:
        disk_sched = None
        disk_sched_time = 0
        try:
            # Check file size
            if stat(SCHED_PATH)[6] != 0:
                with open(SCHED_PATH, 'r') as f:
                    log("Schedule file exists")
                    disk_sched = json.load(f)
                    disk_sched_time = disk_sched["time"]
            else:
                log("Schedule file exists but is empty")
        except OSError:
            log("Schedule file does not exist")

        w = WIFI()
        if w.connect_wifi():
            headers = {"Content-Type": "application/json"}
            data = {"uniqueID": self.unique_id}
            
            server_time_resp = w.requests(method="GET", url=self.sched_time_endpoint, json=data, headers=headers, timeout=5.0)
            server_sched_time = self._handle_resp(server_time_resp)["time"]

            if server_sched_time != disk_sched_time:
                log("New schedule found, replacing old file...")
                loading.set_text("New schedule found, replacing old file...")
                resp = w.requests(method='GET', url=self.sched_endpoint, json=data, headers=headers, stream=True)
                # Stream straight to disk. Holding resp.text + the parsed dict +
                # a json.dumps() copy at once blows the ~105 KB heap.
                if resp.status_code != 200:
                    self._handle_resp(resp)
                try:
                    with open(SCHED_PATH, 'wb') as f:
                        for chunk in resp.iter_content(chunk_size=512):
                            if chunk:
                                f.write(chunk)
                finally:
                    try:
                        resp.close()
                    except Exception:
                        pass
                gc.collect()
                with open(SCHED_PATH, 'r') as f:
                    disk_sched = json.load(f)
                return disk_sched["schedule"]

        if disk_sched != None:
            log("Using on-disk file")
            return disk_sched["schedule"]
        else:
            log("No schedule on disk, and cannot connect to badge network")
            raise CantFetchSchedule(f"No local schedule available and cannot fetch from badge network.")

    # Sort schedule
    def _get_schedule_list(self, json: str):
        acc = []
        for track in json["tracks"]:
            for talk in track['talks']:
                talk["track"] = track["name"]
                acc.append(talk)
        
        acc.sort(key=lambda d: d['meta'])
        return acc

    # Main entry
    def run(self):
        lcd_main_group = Group()
        epd_main_group = Group()

        self.lcd.root_group = lcd_main_group
        self.epd.root_group = epd_main_group

        loading = LCDLoading()
        lcd_main_group.append(loading.get_group())
        
        try: 
            schedule_json = self._get_schedule(loading)
        except Exception as e:
            loading.set_error(f"{e}")
            raise e

        try: 
            sorted_schedule = self._get_schedule_list(schedule_json)
        except Exception as e:
            loading.set_error(f"{e}")
            raise e

        # The raw parse tree is no longer needed; the talk dicts are shared.
        schedule_json = None
        gc.collect()
        log("Free after load: {}".format(gc.mem_free()))

        lcd_main_group.pop()

        # Classes
        select = ScrollableList(sorted_schedule, text_fn=lambda t: t['title'])
        header = LCDListHeader()
        epdsplash = EPDTalks(len(sorted_schedule))

        title = LCDTitle()
        desc = EPDDescription()
        
        list_group = Group()
        list_group.append(select.get_group())
        list_group.append(header.get_group())
        header.update(select.get_selected())

        lcd_main_group.append(list_group)
        if EPD_ENABLED:
            epd_main_group.append(epdsplash.get_group())
            self.epd.refresh()

        self.buttons.events.clear()
        while True:
            time.sleep(0.025)
            select.update()
            event = self.buttons.events.get()
            if event and event.pressed:

                # BTN1 Select
                if event.key_number == 0:
                    talk = select.get_selected()
                    log("Displaying talk: {}".format(talk["title"]))
                    title.set_data(talk["title"], talk["track"], talk["meta"])
                    lcd_main_group.pop()
                    lcd_main_group.append(title.get_group())
                    
                    if EPD_ENABLED:
                        epd_main_group.pop()
                        epd_main_group.append(desc.get_group())
                        desc.set_data(self.epd, talk["desc"])
                        self.epd.refresh()

                    self.buttons.events.clear()
                    while True:
                        title.update()
                        time.sleep(0.025)

                        subevent = self.buttons.events.get()
                        if subevent and subevent.pressed:

                            badge.neopixels.NP.fill(0x00FF00)
                            time.sleep(0.1)
                            badge.neopixels.NP.fill(0x000000)

                            # BTN1 Top
                            if subevent.key_number == 0:
                                if EPD_ENABLED and desc.top():
                                    self.epd.refresh()
                            # BTN2 Back
                            elif subevent.key_number == 1:
                                lcd_main_group.pop()
                                lcd_main_group.append(list_group)
                                
                                if EPD_ENABLED:
                                    epd_main_group.pop()
                                    epd_main_group.append(epdsplash.get_group())
                                    self.epd.refresh()

                                break
                            # BTN3 Down
                            elif subevent.key_number == 2:
                                if EPD_ENABLED and desc.input(False):
                                    self.epd.refresh()
                            # BTN4 Up
                            elif subevent.key_number == 3:
                                if EPD_ENABLED and desc.input(True):
                                    self.epd.refresh()
                            
                            self.buttons.events.clear()

                # BTN2 Exit
                elif event.key_number == 1:
                    log("Exiting")
                    for i in range(len(lcd_main_group)):
                        lcd_main_group.pop()
                    return

                # BTN3 Down
                elif event.key_number == 2:
                    select.input(False)
                    header.update(select.get_selected())

                # BTN4 Up
                elif event.key_number == 3:
                    select.input(True)
                    header.update(select.get_selected())

                self.buttons.events.clear()
