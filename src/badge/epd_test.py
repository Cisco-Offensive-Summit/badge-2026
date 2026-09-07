"""
Pervasive Displays E-paper Display Driver Test
Model: 2.71" Wide Small EPD

Based on: https://docs.pervasivedisplays.com/knowledge/Hardware/epd-usage/Screens/Wide_Small/update-procedure.html
"""

import board
import digitalio
import busio
import time


# Pin definitions
PIN_DC = board.EINK_DISCHARGE      # D/C: Data if HIGH, Command if LOW
PIN_RESET = board.EINK_RST         # /RESET: Panel reset, active low
PIN_CS = board.EINK_CS             # Panel /CS: SPI chip select, active low
PIN_BUSY = board.EINK_BUSY         # !BUSY: Busy signal from panel
PIN_SCK = board.EINK_CLKS          # SPI Clock
PIN_MOSI = board.EINK_MOSI         # SPI Data Out
PIN_MISO = board.EINK_MISO         # SPI Data In

# Note: If your board has a power control pin for the EPD, define it here
# PIN_POWER = board.EINK_POWER     # External MOSFET power driver (if available)


class EPD_Driver:
    """Driver for Pervasive Displays 2.71" E-paper display."""
    
    def __init__(self):
        """Initialize GPIO pins and SPI bus."""
        # Initialize D/C pin as output
        self.dc = digitalio.DigitalInOut(PIN_DC)
        self.dc.direction = digitalio.Direction.OUTPUT
        
        # Initialize RESET pin as output
        self.reset = digitalio.DigitalInOut(PIN_RESET)
        self.reset.direction = digitalio.Direction.OUTPUT
        
        # Initialize CS pin as output
        self.cs = digitalio.DigitalInOut(PIN_CS)
        self.cs.direction = digitalio.Direction.OUTPUT
        
        # Initialize BUSY pin as input (floating)
        self.busy = digitalio.DigitalInOut(PIN_BUSY)
        self.busy.direction = digitalio.Direction.INPUT
        # Note: Pull configuration depends on your hardware
        # self.busy.pull = digitalio.Pull.UP  # Uncomment if needed
        
        # Initialize SPI bus
        # Pervasive Displays typically uses SPI Mode 0, ~20MHz max
        self.spi = busio.SPI(clock=PIN_SCK, MOSI=PIN_MOSI, MISO=PIN_MISO)
        
        # Power control pin (if available on your board)
        self.power = None
        # Uncomment if you have a power control pin:
        # self.power = digitalio.DigitalInOut(PIN_POWER)
        # self.power.direction = digitalio.Direction.OUTPUT
        
        self._powered = False
    
    def epd_power_on(self):
        """
        Power on the EPD screen according to the Pervasive Displays documentation.
        
        Power On Sequence:
        1. Set initial GPIO states (D/C, /RESET, /CS all LOW)
        2. Configure !BUSY as input (floating)
        3. Apply power (if power control pin available)
        4. Wait for power stabilization
        5. Perform reset sequence
        
        Reference: https://docs.pervasivedisplays.com/knowledge/Hardware/epd-usage/Screens/Wide_Small/update-procedure.html
        """
        if self._powered:
            print("EPD: Already powered on")
            return
        
        print("EPD: Starting power-on sequence...")
        
        # Step 1: Set initial GPIO states before power on
        # D/C = LOW (command mode)
        self.dc.value = False
        
        # /RESET = LOW (keep in reset)
        self.reset.value = False
        
        # /CS = LOW (selected, but SPI inactive)
        self.cs.value = False
        
        # !BUSY is configured as input (already done in __init__)
        
        # Step 2: Apply power (if power control available)
        if self.power is not None:
            self.power.value = True  # POWER = HIGH
            print("EPD: Power applied via MOSFET")
        
        # Step 3: Wait for power to stabilize
        time.sleep(0.005)  # 5ms delay for power stabilization
        
        # Step 4: Perform reset sequence (Reset the CoG driver)
        # According to documentation:
        # - /RESET goes HIGH
        # - Wait at least 5ms
        # - /RESET goes LOW
        # - Wait at least 10us
        # - /RESET goes HIGH
        # - Wait at least 5ms
        
        # Release reset (HIGH)
        self.reset.value = True
        time.sleep(0.005)  # 5ms
        
        # Assert reset (LOW)
        self.reset.value = False
        time.sleep(0.001)  # 1ms (well above 10us minimum)
        
        # Release reset (HIGH) - panel exits reset
        self.reset.value = True
        time.sleep(0.005)  # 5ms
        
        # Step 5: De-select chip after reset sequence
        self.cs.value = True  # /CS = HIGH (deselected)
        
        # Step 6: Wait for panel to be ready
        # !BUSY should go HIGH when ready (for most sizes)
        # For 2.7", !BUSY HIGH indicates ready
        timeout = 100  # 1 second timeout (100 x 10ms)
        ready = False
        for _ in range(timeout):
            if self.busy.value:  # !BUSY = HIGH means ready
                ready = True
                break
            time.sleep(0.010)  # 10ms
        
        if not ready:
            print("EPD: Warning - BUSY timeout during power on")
        
        self._powered = True
        print("EPD: Power-on sequence complete")
    
    def epd_power_off(self):
        """
        Power off the EPD screen according to the Pervasive Displays documentation.
        
        Power Off Sequence:
        1. Set D/C = LOW
        2. Set /RESET = LOW
        3. Set /CS = LOW
        4. Set !BUSY as input (floating)
        5. Set POWER = LOW (if power control available)
        
        Note: This should be called after Stop DC/DC command has been sent.
        
        Reference: https://docs.pervasivedisplays.com/knowledge/Hardware/epd-usage/Screens/Wide_Small/update-procedure.html
        """
        if not self._powered:
            print("EPD: Already powered off")
            return
        
        print("EPD: Starting power-off sequence...")
        
        # Step 1: Set D/C = LOW (command mode)
        self.dc.value = False
        
        # Step 2: Set /RESET = LOW (hold in reset)
        self.reset.value = False
        
        # Step 3: Set /CS = LOW
        self.cs.value = False
        
        # Step 4: !BUSY should be input (floating) - already configured
        # The pin is already configured as input in __init__
        
        # Step 5: Remove power (if power control available)
        if self.power is not None:
            self.power.value = False  # POWER = LOW
            print("EPD: Power removed via MOSFET")
        
        # Small delay to ensure clean shutdown
        time.sleep(0.005)  # 5ms
        
        self._powered = False
        print("EPD: Power-off sequence complete")
    
    def deinit(self):
        """Release all GPIO and SPI resources."""
        print("EPD: Releasing resources...")
        
        # Ensure powered off first
        if self._powered:
            self.epd_power_off()
        
        # Deinitialize all pins
        self.dc.deinit()
        self.reset.deinit()
        self.cs.deinit()
        self.busy.deinit()
        self.spi.deinit()
        
        if self.power is not None:
            self.power.deinit()
        
        print("EPD: Resources released")


# Test code
if __name__ == "__main__":
    print("=" * 40)
    print("Pervasive Displays 2.71\" EPD Test")
    print("=" * 40)
    
    # Create driver instance
    epd = EPD_Driver()
    
    try:
        # Test power on
        print("\n--- Testing Power On ---")
        epd.epd_power_on()
        
        print("\nEPD is now powered on.")
        print("BUSY pin state:", "HIGH (ready)" if epd.busy.value else "LOW (busy)")
        
        # Wait a bit
        time.sleep(2)
        
        # Test power off
        print("\n--- Testing Power Off ---")
        epd.epd_power_off()
        
        print("\nEPD is now powered off.")
        
    except Exception as e:
        print(f"Error: {e}")
    
    finally:
        # Clean up
        epd.deinit()
    
    print("\n" + "=" * 40)
    print("Test complete!")
    print("=" * 40)
