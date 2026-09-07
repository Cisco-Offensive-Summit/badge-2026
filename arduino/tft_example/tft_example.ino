#include <Adafruit_ST7735.h>        // Hardware-specific library for ST7735 TFT displays
#include "guitar.h"
// TFT Display Ports for OS2026 Badge
#define TFT_CS     10
#define TFT_RST    8  
#define TFT_DC     13
#define TFT_SCLK   12   
#define TFT_MOSI   11  
#define TFT_BL     47

#define TFT_ROTATION    3                //Correct rotation for ADAfruit_ST7735 screen on OS2024 badge
#define TFT_BRIGHTNESS  127              //out of 255 max, 50% looks nice
//#define TFT_CENTER_X    38               //out of 128 max x position value
//#define TFT_CENTER_Y    40               //out of 128 max y position value

// Defin TFT Display
Adafruit_ST7735 tft = Adafruit_ST7735(TFT_CS, TFT_DC, TFT_MOSI, TFT_SCLK, TFT_RST);

void setup() {
  //Setup TFT 
  tft.initR(INITR_144GREENTAB);         // initialize a ST7735S chip, green tab 1.44 inch
  tft.fillScreen(ST7735_RED);           // Red background
  //tft.setTextColor(ST7735_WHITE);       // White letters
  //tft.setRotation(TFT_ROTATION);        // Fix the Orientation
  //tft.setTextSize(LARGE_TEXT);          // Use Large Text!!
  tft.drawRGBBitmap(0, 0, guitar_data, 128, 128);
  pinMode(TFT_BL, OUTPUT);              // set the backlight pin as output
  analogWrite(TFT_BL, TFT_BRIGHTNESS);  // apply a duty cycle to backlight pin from 0 to 255
  
}

void loop() {
  // put your main code here, to run repeatedly:

}
