# Cisco's VID
USB_VID = 0x05A6
USB_PID = 0x07E8
USB_PRODUCT = "Offensive-Summit-Badge-2026-ESP32S3"
USB_MANUFACTURER = "Best-Most-Awesomest-Hacker-Badge-Group"

IDF_TARGET = esp32s3

CIRCUITPY_ESP_FLASH_MODE = dio
CIRCUITPY_ESP_FLASH_FREQ = 80m
CIRCUITPY_ESP_FLASH_SIZE = 16MB

# ESP32-S3-WROOM-1-N16R8 -> 8 MB octal PSRAM. Without these the Python heap is
# limited to ~107 KB of internal SRAM. Octal PSRAM consumes GPIO35/36/37, which
# is why they are not exposed in pins.c.
CIRCUITPY_ESP_PSRAM_SIZE = 8MB
CIRCUITPY_ESP_PSRAM_MODE = opi
CIRCUITPY_ESP_PSRAM_FREQ = 80m

# espcamera defaults to 1 and is only auto-disabled when PSRAM is off, so
# enabling PSRAM turns it on. The badge has no camera, and QR codes come from
# the adafruit_miniqr library rather than native qrio (which follows espcamera).
CIRCUITPY_ESPCAMERA = 0

# Specify core modules
CIRCUITPY_STAGE = 1

# Include these Python libraries in firmware.
FROZEN_MPY_DIRS += $(TOP)/frozen/Adafruit_CircuitPython_BLE
FROZEN_MPY_DIRS += $(TOP)/frozen/Adafruit_CircuitPython_BusDevice
FROZEN_MPY_DIRS += $(TOP)/frozen/Adafruit_CircuitPython_Display_Shapes
FROZEN_MPY_DIRS += $(TOP)/frozen/Adafruit_CircuitPython_FakeRequests
FROZEN_MPY_DIRS += $(TOP)/frozen/Adafruit_CircuitPython_IRRemote
FROZEN_MPY_DIRS += $(TOP)/frozen/Adafruit_CircuitPython_Display_Text
FROZEN_MPY_DIRS += $(TOP)/frozen/Adafruit_CircuitPython_Motor
FROZEN_MPY_DIRS += $(TOP)/frozen/Adafruit_CircuitPython_RFM69
FROZEN_MPY_DIRS += $(TOP)/frozen/Adafruit_CircuitPython_RFM9x
FROZEN_MPY_DIRS += $(TOP)/frozen/Adafruit_CircuitPython_ProgressBar
FROZEN_MPY_DIRS += $(TOP)/frozen/Adafruit_CircuitPython_Register
FROZEN_MPY_DIRS += $(TOP)/frozen/Adafruit_CircuitPython_SimpleIO
FROZEN_MPY_DIRS += $(TOP)/frozen/Adafruit_CircuitPython_NeoPixel
FROZEN_MPY_DIRS += $(TOP)/frozen/Adafruit_CircuitPython_Requests
FROZEN_MPY_DIRS += $(TOP)/frozen/Adafruit_CircuitPython_asyncio
FROZEN_MPY_DIRS += $(TOP)/frozen/Adafruit_CircuitPython_Wave
FROZEN_MPY_DIRS += $(TOP)/frozen/circuitpython-stage
