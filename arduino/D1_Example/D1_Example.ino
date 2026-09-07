// SDK and configuration headers
#include "PDLS_Common.h"
#include <SPI.h> 

// Define custom pins
#define CUSTOM_SPI_SCK    12
#define CUSTOM_SPI_MOSI   11
#define DUMMY_SPI_MISO    39  // Unused Port 39
#define DUMMY_SPI_SS      38  // Unused Port 38
#define CUSTOM_EPD_BUSY   38
#define CUSTOM_EPD_DC     21
#define CUSTOM_EPD_RESET  45
#define CUSTOM_EPD_CS     18

// FIX: Map CUSTOM_EPD_RESET to BOTH panelReset and panelPower
const Board_EXT myBoard = {
    .panelBusy  = CUSTOM_EPD_BUSY,
    .panelDC    = CUSTOM_EPD_DC,
    .panelReset = CUSTOM_EPD_RESET,
    .flashCS    = NOT_CONNECTED,
    .panelCS    = CUSTOM_EPD_CS,
    .panelCSS   = NOT_CONNECTED,
    .flashCSS   = NOT_CONNECTED,
    .touchInt   = NOT_CONNECTED,
    .touchReset = NOT_CONNECTED,
    .panelPower = CUSTOM_EPD_RESET, // REQUIRED: Ties the software charge-pump to Pin 45
    .cardCS     = NOT_CONNECTED,
    .cardDetect = NOT_CONNECTED
};

// Driver
#include "Pervasive_Wide_Small.h"
Pervasive_Wide_Small myDriver(eScreen_EPD_271_KS_0C, myBoard);

// Screen
#include "PDLS_Basic.h"
Screen_EPD myScreen(&myDriver);

void setup() {
    Serial.begin(115200);
    delay(500);

    // Initialize SPI bus architecture with the dummy channels
    SPI.begin(CUSTOM_SPI_SCK, DUMMY_SPI_MISO, CUSTOM_SPI_MOSI, DUMMY_SPI_SS);

    // Initialise hardware and screen drivers
    hV_HAL_begin();
    myScreen.begin();

    // Setup text layout
    uint8_t myFont = Font_Terminal12x16;
    myScreen.clear();
    myScreen.selectFont(myFont);
    myScreen.gText(4, 4, "Hello, World!");
    
    // Perform standard global screen refresh
    yield();
    myScreen.flush(); 

    // Safety clear cycle 
    hV_HAL_delayMilliseconds(4000);
    myScreen.regenerate();
    
    // NOTE: Comment out hV_HAL_exit() if you want to perform actions in loop() 
    // hV_HAL_exit(); 
}

void loop() {
    hV_HAL_delayMilliseconds(1000);
}
