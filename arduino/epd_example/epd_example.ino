/*
 * E2271KS0C1 "Hello World"
 *
 * ESP32-S3-WROVER
 *
 * Pervasive Displays libraries:
 *   PDLS_Common          10.0.9
 *   PDLS_Basic           10.0.9
 *   Pervasive_Wide_Small 10.0.1
 *
 * Display:
 *   E2271KS0C1
 *   2.71", 264 x 176
 *   Film K / Controller 0C
 *
 * CUSTOM WIRING
 * -------------------------
 * EPD SCK    -> GPIO 12
 * EPD MOSI   -> GPIO 11
 * EPD MISO   -> NOT CONNECTED
 * EPD BUSY   -> GPIO 38
 * EPD DC     -> GPIO 21
 * EPD RESET  -> GPIO 45
 * EPD CS     -> GPIO 18
 *
 * IMPORTANT:
 * The E2271KS0C1 uses 3-wire SPI for its OTP read.
 * The library bit-bangs this on the SCK/MOSI pair, so
 * MISO is intentionally not connected.
 */

#include <Arduino.h>
#include <SPI.h>

// Pervasive Displays common library
#include "PDLS_Common.h"

// ------------------------------------------------------------
// Custom ESP32-S3 board definition
// ------------------------------------------------------------

Board_EXT myBoard =
{
    .scope       = BOARD_EXT3,

    .panelBusy  = 38,
    .panelDC    = 21,
    .panelReset = 45,

    // No external flash
    .flashCS    = NOT_CONNECTED,

    .panelCS    = 18,

    // No secondary chip select
    .panelCSS   = NOT_CONNECTED,
    .flashCSS   = NOT_CONNECTED,

    // No touch controller
    .touchInt   = NOT_CONNECTED,
    .touchReset = NOT_CONNECTED,

    // No switched panel power
    .panelPower = NOT_CONNECTED,

    // No SD card
    .cardCS     = NOT_CONNECTED,
    .cardDetect = NOT_CONNECTED,

    // EXT4-only functions
    .button     = NOT_CONNECTED,
    .ledData    = NOT_CONNECTED,
    .nfcFD      = NOT_CONNECTED,
    .imuInt1    = NOT_CONNECTED,
    .imuInt2    = NOT_CONNECTED,
    .weatherInt = NOT_CONNECTED
};


// ------------------------------------------------------------
// Display driver
// ------------------------------------------------------------

#include "Pervasive_Wide_Small.h"

Pervasive_Wide_Small myDriver(
    eScreen_EPD_271_KS_0C,
    myBoard
);


// ------------------------------------------------------------
// Basic screen interface
// ------------------------------------------------------------

#include "PDLS_Basic.h"

Screen_EPD myScreen(&myDriver);


// ------------------------------------------------------------
// The PDLS_Common ESP32 implementation has its own global
// SPI-initialisation flag.  We initialize SPI ourselves so
// that we can use the custom GPIO pins.
//
// This is intentionally an extern declaration rather than
// changing the installed PDLS_Common source.
// ------------------------------------------------------------

extern bool flagSPI;


// ------------------------------------------------------------
// Setup
// ------------------------------------------------------------

void setup()
{
    // --------------------------------------------------------
    // Serial
    // --------------------------------------------------------

    Serial.begin(115200);
    delay(1000);

    Serial.println();
    Serial.println("========================================");
    Serial.println("E2271KS0C1 Hello World");
    Serial.println("ESP32-S3 custom wiring");
    Serial.println("========================================");

    Serial.println("SCK  = GPIO 12");
    Serial.println("MOSI = GPIO 11");
    Serial.println("MISO = NC");
    Serial.println("BUSY = GPIO 38");
    Serial.println("DC   = GPIO 21");
    Serial.println("RST  = GPIO 45");
    Serial.println("CS   = GPIO 18");


    // --------------------------------------------------------
    // Start the Pervasive Displays HAL.
    //
    // This initializes the library's serial/HAL state.
    // --------------------------------------------------------

    hV_HAL_begin();


    // --------------------------------------------------------
    // IMPORTANT:
    //
    // The K-film panel performs an OTP read using the
    // library's software 3-wire SPI.
    //
    // hV_HAL_begin() normally defines that bus using the
    // Arduino SCK/MOSI defaults.
    //
    // Override it with our actual physical pins.
    // --------------------------------------------------------

    hV_HAL_SPI3_define(12, 11);


    // --------------------------------------------------------
    // Initialize the ESP32 hardware SPI bus using:
    //
    //   SCK  = 12
    //   MISO = -1
    //   MOSI = 11
    //
    // The display does not have MISO connected.
    // --------------------------------------------------------

    SPI.begin(
        12,     // SCK
        -1,     // MISO - not connected
        11      // MOSI
    );


    // --------------------------------------------------------
    // Tell PDLS_Common that SPI is already initialized.
    //
    // Otherwise its ESP32 HAL would execute:
    //
    //   SPI.begin(SCK, MISO, MOSI)
    //
    // using the ESP32 board's default SPI pin definitions.
    // --------------------------------------------------------

    flagSPI = true;


    // --------------------------------------------------------
    // Start the display.
    //
    // This initializes:
    //   BUSY
    //   DC
    //   RESET
    //   CS
    //
    // and reads the display's embedded OTP/PSR data.
    // --------------------------------------------------------

    Serial.println("Starting display...");

    myScreen.begin();

    Serial.println("Display initialized.");

    myScreen.regenerate();
    // --------------------------------------------------------
    // Select landscape orientation.
    //
    // E2271KS0C1 is 264 x 176.
    // --------------------------------------------------------

    myScreen.setOrientation(ORIENTATION_LANDSCAPE);

    Serial.print("Screen X = ");
    Serial.println(myScreen.screenSizeX());

    Serial.print("Screen Y = ");
    Serial.println(myScreen.screenSizeY());


    // --------------------------------------------------------
    // Clear the frame buffer to white.
    // --------------------------------------------------------

    myScreen.clear();
    


    // --------------------------------------------------------
    // Use the built-in 8x12 terminal font.
    //
    // This avoids loading an external font and is sufficient
    // for the Hello World test.
    // --------------------------------------------------------

    myScreen.selectFont(Font_Terminal16x24);


    // --------------------------------------------------------
    // Draw "Hello World!"
    //
    // The text is 12 characters wide at 8 pixels/character:
    //
    //   12 * 8 = 96 pixels
    //
    // and 12 pixels high.
    //
    // Center approximately on the 264 x 176 display.
    // --------------------------------------------------------

    const char *message = "JED WAS HERE!";

    uint16_t textWidth  = 12 * 16;
    uint16_t textHeight = 24;

    uint16_t x = (myScreen.screenSizeX() - textWidth) / 2;
    uint16_t y = (myScreen.screenSizeY() - textHeight) / 2;
    

    myScreen.gText(
        x,
        y,
        message,
        myColours.black,
        myColours.white
    );


    // --------------------------------------------------------
    // Send the frame buffer to the display and perform the
    // e-paper refresh.
    // --------------------------------------------------------

    Serial.println("Flushing display...");

    myScreen.flush();

    Serial.println("Display refresh complete.");
    Serial.println("Hello World should now be visible.");
}


void loop()
{
    // Nothing else to do.
    //
    // E-paper retains the image without continuous updating.
    delay(1000);
}