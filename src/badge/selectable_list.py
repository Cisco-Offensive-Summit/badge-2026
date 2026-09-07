"""
Selectable List Library for Badge Display

A reusable component for creating scrollable, selectable lists on the badge's
LCD display, with associated content for both LCD and EPD displays.

Usage:
    from badge.selectable_list import SelectableList

    items = [
        {
            "text": "Item 1 Title",
            "lcd_group": some_lcd_displayio_group,
            "epd_group": some_epd_displayio_group,
        },
        {
            "text": "Item 2 Title", 
            "lcd_group": another_lcd_group,
            "epd_group": another_epd_group,
        },
    ]

    selectable = SelectableList(items)
    
    # Add to display
    lcd.root_group.append(selectable.get_group())
    
    # Navigation
    selectable.move_up()
    selectable.move_down()
    
    # Get selected item's groups
    lcd_content, epd_content = selectable.get_selected_groups()
    
    # Call in main loop for scroll animation
    selectable.update()
"""

import terminalio
from displayio import Group
from adafruit_display_text.scrolling_label import ScrollingLabel

from badge.constants import LCD_WIDTH, LCD_HEIGHT


class SelectableList:
    """
    A scrollable, selectable list UI component for the badge LCD.
    
    Displays a vertical list of items that can be navigated with up/down inputs.
    Each item has associated LCD and EPD display groups that can be retrieved
    when the item is selected.
    
    Attributes:
        items: List of item dictionaries containing 'text', 'lcd_group', 'epd_group'
        selected_index: Currently selected item index in the full list
        visible_index: Position of selection within the visible window (0 to max_visible-1)
    """

    # Display configuration
    MAX_VISIBLE_ITEMS = 7           # Number of items visible at once
    MAX_CHARACTERS = 20             # Max characters before scrolling
    ANIMATE_TIME = 0.5              # Scroll animation speed
    ITEM_HEIGHT = 16                # Pixel height per item row
    START_Y = 16                    # Y offset for first item
    START_X = 2                     # X offset for items
    
    # Colors
    COLOR_NORMAL = 0xFFFFFF         # Unselected text color
    COLOR_NORMAL_BG = 0x000000      # Unselected background
    COLOR_SELECTED = 0x111111       # Selected text color  
    COLOR_SELECTED_BG = 0xaaaaaa    # Selected background

    def __init__(self, items: list, font=None):
        """
        Initialize the selectable list.
        
        Args:
            items: List of dicts, each containing:
                   - 'text': str - Display text for the list item
                   - 'lcd_group': displayio.Group - Content to show on LCD when selected
                   - 'epd_group': displayio.Group - Content to show on EPD when selected
            font: Font to use for labels (defaults to terminalio.FONT)
        """
        if not items:
            raise ValueError("Items list cannot be empty")
        
        self._items = items
        self._font = font or terminalio.FONT
        
        # Selection state
        self._selected_index = 0    # Index in the full items list
        self._visible_index = 0     # Index within visible window (0 to MAX_VISIBLE-1)
        
        # Build UI
        self._group = Group()
        self._labels = []
        self._init_labels()
        
    def _init_labels(self):
        """Initialize the ScrollingLabel elements for visible items."""
        # TODO: Create ScrollingLabel for each visible slot
        # TODO: Populate initial visible items from self._items
        # TODO: Set initial selection highlighting
        pass

    def _update_label(self, label_index: int, item_index: int):
        """
        Update a label slot with content from an item.
        
        Args:
            label_index: Which label slot to update (0 to MAX_VISIBLE-1)
            item_index: Which item from self._items to display
        """
        # TODO: Update label text and full_text from item
        pass

    def _set_selection(self, new_visible_index: int):
        """
        Update the visual selection highlighting.
        
        Args:
            new_visible_index: New position within visible window
        """
        # TODO: Remove highlight from old selection
        # TODO: Add highlight to new selection
        # TODO: Reset scroll position on old selection
        pass

    def _scroll_labels(self, direction_up: bool):
        """
        Shift all label contents when scrolling past visible bounds.
        
        Args:
            direction_up: True if scrolling up (showing earlier items)
        """
        # TODO: Shift label contents up or down
        # TODO: Fill in new item at top or bottom
        pass

    def move_up(self) -> bool:
        """
        Move selection up one item.
        
        Returns:
            True if selection changed, False if already at top
        """
        # TODO: Check if at top of list
        # TODO: Update selected_index
        # TODO: Handle scrolling if at top of visible window
        # TODO: Update selection highlighting
        pass

    def move_down(self) -> bool:
        """
        Move selection down one item.
        
        Returns:
            True if selection changed, False if already at bottom
        """
        # TODO: Check if at bottom of list
        # TODO: Update selected_index
        # TODO: Handle scrolling if at bottom of visible window
        # TODO: Update selection highlighting
        pass

    def update(self):
        """
        Update scroll animation for the selected item's label.
        Call this in the main loop.
        """
        # TODO: Call update() on the currently selected label
        pass

    def get_group(self) -> Group:
        """
        Get the displayio Group for this list.
        
        Returns:
            The Group to append to LCD root_group
        """
        return self._group

    def get_selected_item(self) -> dict:
        """
        Get the currently selected item dict.
        
        Returns:
            The full item dict for the current selection
        """
        return self._items[self._selected_index]

    def get_selected_groups(self) -> tuple:
        """
        Get the LCD and EPD groups for the current selection.
        
        Returns:
            Tuple of (lcd_group, epd_group) for the selected item
        """
        item = self.get_selected_item()
        return (item.get("lcd_group"), item.get("epd_group"))

    def get_selected_index(self) -> int:
        """
        Get the index of the currently selected item.
        
        Returns:
            Index into the items list
        """
        return self._selected_index

    def set_selected_index(self, index: int):
        """
        Programmatically set the selection to a specific index.
        
        Args:
            index: Index to select (will be clamped to valid range)
        """
        # TODO: Clamp index to valid range
        # TODO: Update visible window if needed
        # TODO: Update selection highlighting
        pass

    @property
    def item_count(self) -> int:
        """Number of items in the list."""
        return len(self._items)

    def __len__(self) -> int:
        """Number of items in the list."""
        return len(self._items)
