import asyncio
import microcontroller
import os
import time

import supervisor

from adafruit_display_text.label import Label
from adafruit_display_shapes.rect import Rect
from displayio import Group
from terminalio import FONT

import badge.events as evt
import badge.buttons as hw_buttons
from badge.constants import BB_WIDTH, BB_X, LCD_WIDTH, WHITE
from badge.screens import EPD, LCD, center_text_x_plane, clear_screen, epd_print_exception, round_button, wrap_message
from badge.storage_sync import backup, backup_plan, delete_local_file, is_dir, restore, restore_plan
from badge.wifi import WIFI
from scrollable_list import ScrollableList


OPTIONS = ["Backup", "Restore", "Delete"]
NAV_BUTTONS = ("S4 Back", "S5 Down", "S6 Up", "S7 Sel")
MENU_BUTTONS = ("S4 Exit", "S5 Down", "S6 Up", "S7 Sel")
EPD_TEXT_WIDTH = 31
EPD_MAX_LINES = 4
_BUTTON_LOCKS = {}


async def wait_button(timeout=None):
    """Return the next button press using direct pressed-state polling.

    The shared down/up event queue can miss quick presses when the app spends
    time animating list rows. Direct polling matches the more responsive pattern
    used by CorpoBreach: return as soon as a button is pressed, then lock that
    button until it is released so holding it does not auto-repeat.
    """
    mapping = (
        ("a", hw_buttons.BTN_A, evt.BTN_A_DOWNUP),
        ("b", hw_buttons.BTN_B, evt.BTN_B_DOWNUP),
        ("c", hw_buttons.BTN_C, evt.BTN_C_DOWNUP),
        ("d", hw_buttons.BTN_D, evt.BTN_D_DOWNUP),
    )
    start = supervisor.ticks_ms()
    while True:
        for name, button, event in mapping:
            pressed = button.getstate_func()
            if not pressed:
                _BUTTON_LOCKS[name] = False
            elif not _BUTTON_LOCKS.get(name):
                _BUTTON_LOCKS[name] = True
                return event
        if timeout is not None and supervisor.ticks_ms() - start >= int(timeout * 1000):
            return None
        await asyncio.sleep(0.01)


class StorageApp:
    def __init__(self):
        self.wifi = WIFI()
        self.menu = None

    def center_label(self, text, y, scale=1):
        label = Label(font=FONT, text=text, scale=scale)
        box = label.bounding_box
        label.x = (EPD.width - box[BB_WIDTH] * scale) // 2 - box[BB_X] * scale
        label.y = y
        return label

    def shorten_epd_line(self, text):
        if len(text) <= EPD_TEXT_WIDTH:
            return text
        if "/" in text:
            parts = text.strip("/").split("/")
            text = ".../" + "/".join(parts[-2:])
            if len(text) <= EPD_TEXT_WIDTH:
                return text
        return text[: EPD_TEXT_WIDTH - 3] + "..."

    def format_epd_message(self, message):
        lines = []
        for raw_line in message.split("\n"):
            line = raw_line.strip()
            if len(line) <= EPD_TEXT_WIDTH:
                lines.append(line)
                continue
            words = line.split(" ")
            if len(words) == 1:
                lines.append(self.shorten_epd_line(line))
                continue
            current = words[0]
            for word in words[1:]:
                if len(current) + len(word) + 1 <= EPD_TEXT_WIDTH:
                    current += " " + word
                else:
                    lines.append(current)
                    current = word
            lines.append(current)
        lines = [self.shorten_epd_line(line) for line in lines]
        if len(lines) > EPD_MAX_LINES:
            lines = lines[:EPD_MAX_LINES]
            lines[-1] = self.shorten_epd_line(lines[-1])
        return "\n".join(lines)

    def draw_buttons(self, root, labels):
        radius = 5
        button_y = EPD.height - 13
        column_width = EPD.width // len(labels)
        for index, text in enumerate(labels):
            label = Label(font=FONT, text=text)
            width = label.bounding_box[BB_WIDTH] + radius * 2
            left = index * column_width + (column_width - width) // 2
            root.append(round_button(label, left + radius, button_y, radius))

    def draw_epd(self, message, labels=NAV_BUTTONS):
        clear_screen(EPD)
        root = Group()
        root.append(self.center_label("Storage", 18, 2))
        root.append(Rect(0, 38, EPD.width, 1, fill=WHITE))
        root.append(Rect(0, EPD.height - 27, EPD.width, 1, fill=WHITE))
        wrapped = wrap_message(EPD, self.format_epd_message(message), x=2, y=68)
        root.append(center_text_x_plane(EPD, wrapped, y=68))
        self.draw_buttons(root, labels)
        EPD.root_group = root
        EPD.refresh()

    def draw_lcd_message(self, message):
        clear_screen(LCD)
        LCD.root_group.append(center_text_x_plane(LCD, wrap_message(LCD, message, y=18)))

    def draw_list(self, title, items):
        clear_screen(LCD)
        root = Group()
        root.append(center_text_x_plane(LCD, Label(font=FONT, text=title), y=8))
        self.menu = ScrollableList(
            items,
            max_visible=min(6, len(items)),
            max_chars=18,
            y_offset=24,
            row_height=17,
            row_width=LCD_WIDTH,
            wrap=False,
            loop_scroll=False,
        )
        root.append(self.menu.get_group())
        LCD.root_group = root

    def draw_mpy_prompt(self):
        clear_screen(LCD)
        root = Group()
        prompt = wrap_message(LCD, "Check .mpy files too?\nThis will take more time", y=8)
        root.append(center_text_x_plane(LCD, prompt, y=8))
        self.menu = ScrollableList(
            ["No", "Yes"],
            max_visible=2,
            max_chars=18,
            y_offset=54,
            row_height=17,
            row_width=LCD_WIDTH,
            wrap=False,
            loop_scroll=False,
        )
        root.append(self.menu.get_group())
        LCD.root_group = root

    def draw_menu(self):
        self.draw_list("Storage", OPTIONS)
        self.draw_epd("Choose an action", MENU_BUTTONS)

    def draw_progress(self, path, index, total):
        self.draw_lcd_message(path + "\nOn " + str(index) + " of " + str(total))

    def draw_backup_count(self, total):
        self.draw_epd("Backing up " + str(total) + " Files")

    def draw_restore_count(self, total):
        self.draw_epd("Downloading " + str(total) + " Files")

    def draw_transfer_error(self, path, error):
        self.draw_lcd_message("Failed\n" + path)
        self.draw_epd("Transfer failed\n" + self.shorten_epd_line(path))
        time.sleep(1)

    def complete_message(self, action, total, failed):
        if failed:
            return action + " complete\n" + str(total - failed) + " ok " + str(failed) + " failed"
        return action + " complete\n" + str(total) + " files"

    def connect(self):
        self.draw_lcd_message("Connecting to WiFi")
        if not self.wifi.connect_wifi():
            self.draw_lcd_message("WiFi failed")
            return False
        self.draw_lcd_message("Connected\nIP " + str(self.wifi.ipv4))
        return True

    async def confirm_files(self, title, files):
        if not files:
            return True
        items = files + ["Delete These Files", "Keep These Files"]
        self.draw_list(title, items)
        self.draw_epd(title + "\n" + str(len(files)) + " files")
        while True:
            self.menu.update()
            btn = await wait_button()
            if btn == evt.BTN_A_DOWNUP:
                return False
            if btn == evt.BTN_B_DOWNUP:
                self.menu.input(False)
            elif btn == evt.BTN_C_DOWNUP:
                self.menu.input(True)
            elif btn == evt.BTN_D_DOWNUP:
                selected = self.menu.get_selected()
                if selected == "Delete These Files":
                    return True
                if selected == "Keep These Files":
                    return False

    async def confirm_include_mpy(self):
        self.draw_mpy_prompt()
        self.draw_epd("Check .mpy files too?\nThis will take more time")
        while True:
            self.menu.update()
            btn = await wait_button()
            if btn == evt.BTN_A_DOWNUP:
                return None
            if btn == evt.BTN_B_DOWNUP:
                self.menu.input(False)
            elif btn == evt.BTN_C_DOWNUP:
                self.menu.input(True)
            elif btn == evt.BTN_D_DOWNUP:
                return self.menu.get_selected() == "Yes"

    async def run_backup(self):
        include_mpy = await self.confirm_include_mpy()
        if include_mpy is None:
            return
        if not self.connect():
            return
        self.draw_epd("Checking server files")
        local_manifest, local_only, server_only, changed = backup_plan(
            self.wifi, status=self.draw_lcd_message, include_mpy=include_mpy
        )
        delete_server = await self.confirm_files("Server deletes?", server_only)
        total, failed = backup(
            self.wifi,
            self.draw_progress,
            self.draw_backup_count,
            self.draw_transfer_error,
            delete_server,
            local_manifest,
            local_only,
            changed,
            status=self.draw_lcd_message,
            include_mpy=include_mpy,
        )
        message = self.complete_message("Backup", total, failed)
        self.draw_lcd_message(message)
        self.draw_epd(message)

    async def run_restore(self):
        include_mpy = await self.confirm_include_mpy()
        if include_mpy is None:
            return
        if not self.connect():
            return
        self.draw_epd("Checking badge files")
        local_only, server_only, changed = restore_plan(
            self.wifi, status=self.draw_lcd_message, include_mpy=include_mpy
        )
        delete_local = await self.confirm_files("Badge deletes?", local_only)
        total, failed = restore(
            self.wifi,
            self.draw_progress,
            self.draw_restore_count,
            self.draw_transfer_error,
            delete_local,
            local_only,
            server_only,
            changed,
            status=self.draw_lcd_message,
            include_mpy=include_mpy,
        )
        message = self.complete_message("Restore", total, failed)
        self.draw_lcd_message(message)
        self.draw_epd(message)

    def list_entries(self, path):
        entries = []
        for name in os.listdir(path):
            full_path = path.rstrip("/") + "/" + name if path != "/" else "/" + name
            label = name + "/" if is_dir(full_path) else name
            entries.append(label)
        entries.sort()
        return entries if entries else ["<empty>"]

    async def confirm_delete_file(self, path):
        self.draw_list("Delete file?", ["Delete", "Cancel"])
        self.draw_epd("Delete?\n" + path)
        while True:
            self.menu.update()
            btn = await wait_button()
            if btn == evt.BTN_A_DOWNUP:
                return False
            if btn == evt.BTN_B_DOWNUP:
                self.menu.input(False)
            elif btn == evt.BTN_C_DOWNUP:
                self.menu.input(True)
            elif btn == evt.BTN_D_DOWNUP:
                return self.menu.get_selected() == "Delete"

    async def run_delete_browser(self):
        path = "/"
        while True:
            entries = self.list_entries(path)
            self.draw_list(path, entries)
            self.draw_epd("Delete local files")
            while True:
                self.menu.update()
                btn = await wait_button()
                if btn == evt.BTN_A_DOWNUP:
                    if path == "/":
                        return
                    path = "/" + "/".join(path.strip("/").split("/")[:-1])
                    if path == "":
                        path = "/"
                    break
                if btn == evt.BTN_B_DOWNUP:
                    self.menu.input(False)
                elif btn == evt.BTN_C_DOWNUP:
                    self.menu.input(True)
                elif btn == evt.BTN_D_DOWNUP:
                    selected = self.menu.get_selected()
                    if selected == "<empty>":
                        continue
                    full_path = path.rstrip("/") + "/" + selected.rstrip("/") if path != "/" else "/" + selected.rstrip("/")
                    if selected.endswith("/"):
                        path = full_path
                        break
                    if await self.confirm_delete_file(full_path.strip("/")):
                        delete_local_file(full_path)
                        self.draw_lcd_message("Deleted\n" + selected)
                        time.sleep(1)
                        break

    async def run(self):
        self.draw_menu()
        while True:
            self.menu.update()
            btn = await wait_button()
            if btn == evt.BTN_A_DOWNUP:
                self.draw_lcd_message("Exiting")
                time.sleep(1)
                microcontroller.reset()
            elif btn == evt.BTN_B_DOWNUP:
                self.menu.input(False)
            elif btn == evt.BTN_C_DOWNUP:
                self.menu.input(True)
            elif btn == evt.BTN_D_DOWNUP:
                selected = self.menu.get_selected()
                if selected == "Backup":
                    await self.run_backup()
                elif selected == "Restore":
                    await self.run_restore()
                else:
                    await self.run_delete_browser()
                await wait_button()
                self.draw_menu()


try:
    asyncio.run(StorageApp().run())
except Exception as e:
    epd_print_exception(e)
    time.sleep(60)

microcontroller.reset()
