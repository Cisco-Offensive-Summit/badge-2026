###############################################################################
# SCREEN DEMINSIONS

LCD_WIDTH = 128
LCD_HEIGHT = 128

# E-paper display dimensions for eScreen_EPD_271_KS_0C (2.71" Wide Small)
# Logical landscape dimensions (rotation=270 in EPaperDisplay maps these
# correctly to the physical 176×264 RAM — no pre-rotation needed in app code).
EPD_WIDTH = 264
EPD_HEIGHT = 176

###############################################################################
# BOUNDING BOX CONSTENTS

BB_X = 0  # BOUNDING BOX X
BB_Y = 1  # BOUNDING BOX Y
BB_WIDTH = 2  # BOUNDING BOX WIDTH
BB_HEIGHT = 3  # BOUNDING BOX HEIGHT

###############################################################################
# HEX COLLORS

BLUE = 0x0000FF
GREEN = 0x00FF00
RED = 0xFF0000
OFF = 0x000000
WHITE = 0xFFFFFF
BLACK = 0x000000
YELLOW = 0xFFFF00
CYAN = 0x00FFFF
MAGENTA = 0xFF00FF
SITE_BLUE = 0x3453FF

###############################################################################
# MISC
LOADED_APP = 'loaded_app'
BOOT_CONFIG = 'config'
DEFAULT_CONFIG = {
    "mount_root_rw": False,
    "disable_usb_drive": False,
    "next_code_file": None,
    "loaded_app" : None
}