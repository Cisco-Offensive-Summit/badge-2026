import json
import time

import microcontroller
import supervisor
import terminalio
from adafruit_display_shapes.rect import Rect
from adafruit_display_shapes.roundrect import RoundRect
from adafruit_display_text.label import Label
from displayio import Group

import badge.buttons as hw_buttons
from badge.constants import BLACK, WHITE
from badge.log import log
from badge.screens import EPD, LCD, center_text_x_plane, clear_screen, epd_print_exception, wrap_message
from badge.wifi import WIFI

supervisor.runtime.autoreload = False

FONT = terminalio.FONT
REFRESH_SECONDS = 30 * 60
CACHE_PATH = "/apps/webex_meetings/cache.json"
MAX_CARDS = 3
CARD_H = 30
CARD_GAP = 4
CARD_TOP = 44
TITLE_X = 84  # wide enough for the longest time "12:30 PM" + a raised "+N" marker
TITLE_MAX_CHARS = 23

MONTH_NUMBERS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

LIGHT_THEME = (WHITE, BLACK)  # (background, foreground)
DARK_THEME = (BLACK, WHITE)
THEMES = (LIGHT_THEME, DARK_THEME)

try:
    import secrets
    WEBEX_TOKEN = getattr(secrets, "WEBEX_TOKEN", None)
    # optional IANA zone name (e.g. "America/New_York"); default is UTC
    WEBEX_TIMEZONE = getattr(secrets, "WEBEX_TIMEZONE", None)
except ImportError:
    WEBEX_TOKEN = None
    WEBEX_TIMEZONE = None


def lcd_status(text):
    clear_screen(LCD)
    LCD.root_group.append(center_text_x_plane(LCD, text, y=LCD.height // 2))


def load_cache():
    try:
        with open(CACHE_PATH, "r") as f:
            return json.load(f).get("meetings")
    except (OSError, ValueError, AttributeError):
        return None


def save_cache(meetings):
    try:
        with open(CACHE_PATH, "w") as f:
            json.dump({"meetings": meetings}, f)
    except OSError:
        pass  # missing boot.json / read-only fs -- caching is best-effort


def truncate(text, max_chars):
    return text if len(text) <= max_chars else text[: max_chars - 3] + "..."


def wrap_two_lines(text, max_chars):
    """Word-wrap onto at most 2 lines; anything left over is dropped with '...'."""
    words = text.split(" ")
    line1 = ""
    used = 0
    for word in words:
        candidate = (line1 + " " + word).strip()
        if len(candidate) <= max_chars:
            line1 = candidate
            used += 1
        else:
            break
    if used == 0:
        return truncate(text, max_chars), ""
    line2 = truncate(" ".join(words[used:]), max_chars)
    return line1, line2


def format_time_12h(hhmm):
    if not hhmm or ":" not in hhmm:
        return hhmm
    try:
        hour_str, minute_str = hhmm.split(":")
        hour = int(hour_str)
    except ValueError:
        return hhmm
    period = "AM" if hour < 12 else "PM"
    hour12 = hour % 12 or 12
    return "{}:{} {}".format(hour12, minute_str, period)


def days_from_civil(year, month, day):
    """Days since 1970-01-01 for a proleptic Gregorian date (Howard Hinnant's
    days_from_civil), so we can compare timestamps without time.mktime()'s
    local-timezone assumptions -- CircuitPython has no real TZ database."""
    year -= 1 if month <= 2 else 0
    era = (year if year >= 0 else year - 399) // 400
    yoe = year - era * 400
    doy = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def to_epoch(year, month, day, hour, minute, second, offset_minutes=0):
    """UTC epoch seconds; offset_minutes shifts a local time back to UTC."""
    return days_from_civil(year, month, day) * 86400 + hour * 3600 + minute * 60 + second - offset_minutes * 60


def parse_http_date(date_str):
    """'Wed, 13 Sep 2026 14:23:01 GMT' (HTTP Date header, always GMT/UTC) -> epoch."""
    parts = date_str.split()
    day = int(parts[1])
    month = MONTH_NUMBERS[parts[2]]
    year = int(parts[3])
    hour, minute, second = (int(p) for p in parts[4].split(":"))
    return to_epoch(year, month, day, hour, minute, second)


def parse_iso_offset_minutes(offset_str):
    if not offset_str or offset_str == "Z":
        return 0
    sign = 1 if offset_str[0] == "+" else -1
    digits = offset_str[1:].replace(":", "")
    hour = int(digits[0:2])
    minute = int(digits[2:4]) if len(digits) >= 4 else 0
    return sign * (hour * 60 + minute)


def split_iso8601(timestamp):
    """'2026-09-13T19:53:00+05:30' -> (year, month, day, hour, minute, second, offset_minutes)."""
    date_part, time_part = timestamp.split("T")
    year, month, day = (int(p) for p in date_part.split("-"))

    offset_at = len(time_part)
    for i in range(1, len(time_part)):
        if time_part[i] in "Z+-":
            offset_at = i
            break
    time_main, offset_str = time_part[:offset_at], time_part[offset_at:]

    hour, minute = (int(p) for p in time_main.split(":")[:2])
    second = int(time_main.split(":")[2].split(".")[0])
    return year, month, day, hour, minute, second, parse_iso_offset_minutes(offset_str)


def parse_iso8601(timestamp):
    """'2026-09-13T19:53:00+05:30' / '...Z' -> epoch seconds (UTC)."""
    year, month, day, hour, minute, second, offset_minutes = split_iso8601(timestamp)
    return to_epoch(year, month, day, hour, minute, second, offset_minutes)


def civil_from_days(days):
    """Inverse of days_from_civil: epoch days -> (year, month, day)."""
    z = days + 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    year = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    day = doy - (153 * mp + 2) // 5 + 1
    month = mp + 3 if mp < 10 else mp - 9
    year += 1 if month <= 2 else 0
    return year, month, day


def date_str_from_epoch(epoch_seconds):
    year, month, day = civil_from_days(epoch_seconds // 86400)
    return "{:04d}-{:02d}-{:02d}".format(year, month, day)


def draw_epd(meetings, theme, stale=False, error=None, page=0):
    bg, fg = theme
    root = Group()
    root.append(Rect(0, 0, EPD.width, EPD.height, fill=bg))

    title = "Upcoming Meetings" + (" (offline)" if stale else "")
    root.append(center_text_x_plane(EPD, title, y=14, scale=2, color=fg))
    root.append(Rect(6, 30, EPD.width - 12, 1, fill=fg))

    if error and not meetings:
        wrapped = wrap_message(EPD, error, x=10, y=80)
        wrapped.color = fg
        root.append(center_text_x_plane(EPD, wrapped, y=80))
    elif not meetings:
        msg = "No cached meetings available." if stale else "No upcoming meetings."
        root.append(center_text_x_plane(EPD, msg, y=90, color=fg))
    else:
        total_pages = max(1, (len(meetings) + MAX_CARDS - 1) // MAX_CARDS)
        page %= total_pages
        page_meetings = meetings[page * MAX_CARDS: page * MAX_CARDS + MAX_CARDS]

        y = CARD_TOP
        for meeting in page_meetings:
            root.append(RoundRect(10, y, EPD.width - 20, CARD_H, r=5, outline=fg, stroke=1))

            time_lb = Label(font=FONT, text=meeting.get("time", "??:??"), color=fg)
            time_lb.x = 16
            time_lb.y = y + CARD_H // 2
            root.append(time_lb)

            if meeting.get("day_diff", 0) > 0:
                marker = Label(font=FONT, text="+{}".format(meeting["day_diff"]), color=fg)
                marker.x = 16 + len(meeting.get("time", "")) * 6 + 2
                marker.y = time_lb.y - 5  # raised, superscript-style
                root.append(marker)

            line1, line2 = meeting.get("title_lines", ("(untitled)", ""))
            line1_lb = Label(font=FONT, text=line1, color=fg)
            line1_lb.x = TITLE_X
            line1_lb.y = y + 9
            root.append(line1_lb)

            line2_lb = Label(font=FONT, text=line2, color=fg)
            line2_lb.x = TITLE_X
            line2_lb.y = y + 21
            root.append(line2_lb)

            y += CARD_H + CARD_GAP
        if total_pages > 1:
            root.append(center_text_x_plane(EPD, "Page {}/{}".format(page + 1, total_pages), y=y + 6, color=fg))

    hint = Label(font=FONT, text="S4 Exit  S5 Theme  S6 Scroll  S7 Refresh", color=fg)
    hint.x = 8
    hint.y = EPD.height - 10
    root.append(hint)

    EPD.root_group = root
    EPD.refresh()


def fetch_meetings(wifi):
    headers = {"Authorization": "Bearer " + WEBEX_TOKEN, "Accept": "application/json"}
    if WEBEX_TIMEZONE:
        headers["timezone"] = WEBEX_TIMEZONE

    # meetingType intentionally omitted: it defaults to "meetingSeries", which
    # covers both recurring series AND plain one-off meetings (a non-recurring
    # meeting is just a series with one occurrence). "scheduledMeeting" only
    # covers individual occurrences that belong to a recurring series, so
    # querying it exclusively silently skipped every one-off invite you'd
    # accepted -- that was the actual bug.
    url = "https://webexapis.com/v1/meetings?max=10"
    rsp = wifi.requests(method="GET", url=url, headers=headers)
    try:
        if rsp.status_code == 401:
            raise RuntimeError(
                "401 Unauthorized. Token must be a personal/integration "
                "token with meeting:schedules_read (not a bot token), and "
                "not expired (personal tokens last 12h)."
            )
        if rsp.status_code != 200:
            raise RuntimeError("Webex API error {}".format(rsp.status_code))
        items = rsp.json().get("items", [])
        date_header = rsp.headers.get("Date") or rsp.headers.get("date")
    finally:
        rsp.close()

    if not items:
        return []

    # HTTP Date is always GMT/UTC, and every returned `start` carries its own
    # explicit UTC offset -- so both convert to comparable epoch seconds
    # without needing a synced local clock or a timezone database.
    now_epoch = parse_http_date(date_header) if date_header else parse_iso8601(items[0]["start"])

    # "today" in whatever zone Webex localized `start` to (same offset for
    # every item in one response), so it's comparable to each start[:10].
    _, _, _, _, _, _, tz_offset_minutes = split_iso8601(items[0]["start"])
    today_str = date_str_from_epoch(now_epoch + tz_offset_minutes * 60)
    today_days = days_from_civil(*(int(p) for p in today_str.split("-")))

    # No 24h cutoff: show every upcoming meeting the API returned (already
    # capped at max=10 in the request) -- the old "next 24h only" window was
    # why only 3 of the 10 fetched meetings ever showed, with nothing to scroll to.
    upcoming = []
    for m in items:
        start = m.get("start", "")
        if not start:
            continue
        try:
            start_epoch = parse_iso8601(start)
        except (ValueError, IndexError, KeyError):
            continue
        if start_epoch >= now_epoch:
            upcoming.append(m)
    upcoming.sort(key=lambda m: m.get("start", ""))
    log("webex_meetings", "api_items=" + str(len(items)), "upcoming=" + str(len(upcoming)))

    rows = []
    for m in upcoming:
        start = m.get("start", "")
        hhmm = start[11:16] if len(start) >= 16 else "??:??"
        year, month, day = (int(p) for p in start[:10].split("-"))
        rows.append({
            "time": format_time_12h(hhmm),
            "day_diff": days_from_civil(year, month, day) - today_days,
            "title_lines": wrap_two_lines(m.get("title") or "(untitled)", TITLE_MAX_CHARS),
        })
    return rows


def show_offline(theme_idx, reason):
    cached = load_cache() or []
    stale = bool(cached)
    error = None if cached else reason
    draw_epd(cached, THEMES[theme_idx], stale=stale, error=error)
    return cached, stale, error


def wait_for_action(seconds):
    """Poll during the refresh interval, showing a MM:SS countdown to the next
    refresh on the LCD; returns 'exit'/'theme'/'scroll'/'refresh', or None on timeout."""
    deadline = time.monotonic() + seconds
    shown_secs = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        secs_left = int(remaining)
        if secs_left != shown_secs:
            lcd_status("Next refresh in\n{:02d}:{:02d}".format(secs_left // 60, secs_left % 60))
            shown_secs = secs_left
        if hw_buttons.a_pressed():
            _debounce(hw_buttons.a_pressed)
            return "exit"
        if hw_buttons.b_pressed():
            _debounce(hw_buttons.b_pressed)
            return "theme"
        if hw_buttons.c_pressed():
            _debounce(hw_buttons.c_pressed)
            return "scroll"
        if hw_buttons.d_pressed():
            _debounce(hw_buttons.d_pressed)
            return "refresh"
        time.sleep(0.1)
    return None


def _debounce(getter):
    while getter():
        time.sleep(0.02)


def main():
    theme_idx = 0
    page_index = 0
    wifi = None
    meetings, stale, error = [], False, None

    if not WEBEX_TOKEN:
        meetings, stale, error = show_offline(theme_idx, "Missing WEBEX_TOKEN in secrets.py")
    else:
        wifi = WIFI()
        if not wifi.connect_wifi():
            meetings, stale, error = show_offline(theme_idx, "WiFi connection failed.")
            wifi = None

    need_fetch = wifi is not None

    while True:
        if need_fetch:
            lcd_status("Fetching meetings...")
            try:
                meetings = fetch_meetings(wifi)
                save_cache(meetings)
                stale, error = False, None
                lcd_status("{} meeting(s) loaded".format(len(meetings)))
            except Exception as e:
                cached = load_cache()
                if cached is not None:
                    meetings, stale, error = cached, True, None
                    lcd_status("Fetch failed, showing cached data")
                else:
                    meetings, stale, error = [], False, str(e)
                    lcd_status("Fetch failed")
            page_index = 0
            draw_epd(meetings, THEMES[theme_idx], stale=stale, error=error, page=page_index)
            need_fetch = False

        action = wait_for_action(REFRESH_SECONDS)
        if action == "exit":
            return
        if action == "theme":
            theme_idx = 1 - theme_idx
            draw_epd(meetings, THEMES[theme_idx], stale=stale, error=error, page=page_index)
        elif action == "scroll":
            page_index += 1
            draw_epd(meetings, THEMES[theme_idx], stale=stale, error=error, page=page_index)
        elif action in ("refresh", None):
            need_fetch = wifi is not None



try:
    main()
except Exception as e:
    epd_print_exception(e)
    time.sleep(10)

microcontroller.reset()
