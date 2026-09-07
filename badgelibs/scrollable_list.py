import time

from displayio import Group
import terminalio
from adafruit_display_shapes.rect import Rect
# scrolling_label.ScrollingLabel is a deprecated alias for this class and emits a
# warning on import; use it directly.
from adafruit_display_text.bitmap_label import Label as ScrollingLabel


class ScrollableList:

    def __init__(self, items: list, text_fn=None, max_visible: int = 7,
                 max_chars: int = 20, animate_time: float = 0.5,
                 selected_bg: int = 0xaaaaaa, selected_fg: int = 0x111111,
                 unselected_bg: int = 0x000000, unselected_fg: int = 0xFFFFFF,
                 row_height: int = 16, row_width: int = 128,
                 x_offset: int = 2, y_offset: int = 16,
                 style_fn=None, selected_style_fn=None,
                 selected_bg_adjust=None,
                 wrap: bool = False, loop_scroll: bool = False,
                 scroll_end_pause: float = 1.0):

        if not items:
            raise ValueError("Items list cannot be empty")

        self._items = items
        self._text_fn = text_fn if text_fn is not None else str
        self._style_fn = style_fn
        self._selected_style_fn = selected_style_fn
        self._selected_bg_adjust = selected_bg_adjust
        self._max_visible = max_visible
        self._max_chars = max_chars
        self._wrap = wrap
        self._loop_scroll = loop_scroll
        self._scroll_end_pause = scroll_end_pause
        self._scroll_end_at = None

        self._selected_bg = selected_bg
        self._selected_fg = selected_fg
        self._unselected_bg = unselected_bg
        self._unselected_fg = unselected_fg

        self._item_index = 0
        self._selection_index = 0

        self.group = Group()

        self._rows = []
        self._row_bgs = []
        self._rows_group = Group()
        for i in range(max_visible):
            row_y = y_offset + row_height * i
            row_bg = Rect(0, row_y, row_width, row_height, fill=unselected_bg)
            row = ScrollingLabel(terminalio.FONT, text="",
                                 max_characters=max_chars, animate_time=animate_time)
            # ScrollingLabel is now an alias for bitmap_label.Label, whose
            # update(force=True) short-circuits when text == full_text, leaving
            # _bounding_box None. anchored_position needs it, so set text first.
            text = self._text_fn(items[i]) if i < len(items) else " "
            row.text = text
            row.full_text = text
            row.anchor_point = (0, 0)
            row.anchored_position = (x_offset, row_y)
            row.color = unselected_fg
            row.background_color = unselected_bg
            self._row_bgs.append(row_bg)
            self._rows.append(row)
            self._rows_group.append(row_bg)
            self._rows_group.append(row)

        self._refresh_visible_text()
        self._set_selection(0)

        self.group.append(self._rows_group)

    def get_group(self):
        return self.group

    def get_selected(self):
        return self._items[self._item_index]

    def get_selected_index(self):
        return self._item_index

    def _row_item(self, row_index):
        item_index = self._item_index - self._selection_index + row_index
        if 0 <= item_index < len(self._items):
            return self._items[item_index]
        return None

    def _adjust_color(self, color, amount):
        r = min(255, max(0, ((color >> 16) & 0xFF) + amount))
        g = min(255, max(0, ((color >> 8) & 0xFF) + amount))
        b = min(255, max(0, (color & 0xFF) + amount))
        return (r << 16) | (g << 8) | b

    def _apply_style(self, row, item, selected, row_bg=None):
        fg = self._unselected_fg
        bg = self._unselected_bg
        if self._style_fn is not None and item is not None:
            style = self._style_fn(item)
            if style:
                fg = style[0]
                bg = style[1]
        if selected:
            if self._selected_style_fn is not None:
                fg, bg = self._selected_style_fn(item, fg, bg)
            elif self._selected_bg_adjust is not None:
                fg = self._selected_fg if self._selected_fg is not None else fg
                bg = self._adjust_color(bg, self._selected_bg_adjust)
            else:
                fg = self._selected_fg if self._selected_fg is not None else fg
                bg = self._selected_bg if self._selected_bg is not None else bg
        row.color = fg
        row.background_color = bg
        if row_bg is not None:
            row_bg.fill = bg

    def _reset_scroll(self, row):
        row.current_index = 0
        row.update(force=True)
        self._scroll_end_at = None

    def _set_row_text(self, row_index, item):
        row = self._rows[row_index]
        text = self._text_fn(item) if item is not None else ""
        row.text = text
        row.full_text = text
        self._reset_scroll(row)

    def _refresh_visible_text(self):
        for i in range(self._max_visible):
            self._set_row_text(i, self._row_item(i))
        self._refresh_visible_styles()

    def _set_selection(self, new_selection: int):
        old_selection = self._selection_index
        self._selection_index = new_selection

        old = self._rows[old_selection]
        self._apply_style(old, self._row_item(old_selection), False,
                          self._row_bgs[old_selection])
        self._reset_scroll(old)

        new = self._rows[new_selection]
        self._apply_style(new, self._row_item(new_selection), True,
                          self._row_bgs[new_selection])
        self._reset_scroll(new)

    def _refresh_visible_styles(self):
        for i, row in enumerate(self._rows):
            self._apply_style(row, self._row_item(i), i == self._selection_index,
                              self._row_bgs[i])

    def _scroll_text(self, scroll_up: bool):
        if scroll_up:
            for i in range(self._max_visible - 1, 0, -1):
                self._rows[i].text = self._rows[i - 1].text
                self._rows[i].full_text = self._rows[i - 1].full_text
                self._reset_scroll(self._rows[i])
            self._set_row_text(0, self._items[self._item_index])
        else:
            for i in range(1, self._max_visible):
                self._rows[i - 1].text = self._rows[i].text
                self._rows[i - 1].full_text = self._rows[i].full_text
                self._reset_scroll(self._rows[i - 1])
            self._set_row_text(self._max_visible - 1, self._items[self._item_index])
        self._refresh_visible_styles()

    def _select_wrapped_index(self, new_item_index):
        self._item_index = new_item_index
        if new_item_index == 0:
            self._selection_index = 0
        else:
            self._selection_index = min(self._max_visible - 1, len(self._items) - 1)
        self._refresh_visible_text()
        self._set_selection(self._selection_index)

    def _selected_row_at_scroll_end(self):
        row = self._rows[self._selection_index]
        text = row.full_text if hasattr(row, "full_text") else row.text
        if len(text) <= self._max_chars:
            return False
        return row.current_index >= len(text) - self._max_chars

    def update(self):
        row = self._rows[self._selection_index]
        if not self._loop_scroll:
            row.update()
            return

        now = time.monotonic()
        if self._scroll_end_at is not None:
            if now - self._scroll_end_at >= self._scroll_end_pause:
                self._reset_scroll(row)
            return

        row.update()
        if self._selected_row_at_scroll_end():
            self._scroll_end_at = now

    def input(self, scroll_up: bool):
        if scroll_up:
            if self._item_index == 0:
                if not self._wrap:
                    return
                self._select_wrapped_index(len(self._items) - 1)
                return
            self._item_index -= 1
            if self._selection_index == 0:
                self._scroll_text(scroll_up)
            self._set_selection(0 if self._selection_index - 1 < 0 else self._selection_index - 1)
        else:
            if self._item_index == len(self._items) - 1:
                if not self._wrap:
                    return
                self._select_wrapped_index(0)
                return
            self._item_index += 1
            if self._selection_index == self._max_visible - 1:
                self._scroll_text(scroll_up)
            self._set_selection(self._max_visible - 1 if self._selection_index + 1 > self._max_visible - 1 else self._selection_index + 1)
