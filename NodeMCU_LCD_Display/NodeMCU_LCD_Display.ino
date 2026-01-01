#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <RTClib.h>
#include <LedControl.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>


bool channelMode = false;
bool logoMode = false;
bool audioMode = false;


// 0–100 per channel
uint8_t channelLevel[6] = {0,0,0,0,0,0};

const char* channelLabels[6] = {
  "FL", "FR", "CT", "RL", "RR", "SW"
};


#define OLED_ADDR 0x3C   // most 0.91" OLEDs
Adafruit_SSD1306 oled(128, 32, &Wire, -1);

// ---------- MAX7219 1×4 dot-matrix ----------
const int PIN_DIN = D7, PIN_CLK = D5, PIN_CS = D8;
LedControl lc(PIN_DIN, PIN_CLK, PIN_CS, 4);   // 4 cascaded matrices

// ---- Mapping controls (set as needed) ----
#define REVERSE_DEVICE_ORDER 1   // 1 = logical device 0 is physically the RIGHT-most panel
#define H_MIRROR_PER_PANEL  1    // 1 = mirror columns inside each 8×8
#define ROTATE_90_CCW       0    // 1 = panels mounted rotated 90° CCW

static inline uint8_t bitrev8(uint8_t v){
  v = (v>>1 & 0x55) | ((v & 0x55)<<1);
  v = (v>>2 & 0x33) | ((v & 0x33)<<2);
  v = (v>>4 & 0x0F) | ((v & 0x0F)<<4);
  return v;
}

// hex helper for framebuffer parsing
uint8_t hexVal(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'A' && c <= 'F') return 10 + (c - 'A');
  if (c >= 'a' && c <= 'f') return 10 + (c - 'a');
  return 0;
}

void matrixInit(){
  for(int d=0; d<4; d++){
    lc.shutdown(d,false);
    lc.setIntensity(d, 2);  // lower current
    lc.clearDisplay(d);
  }
}

// Draw a bar of height 0..8, filling from bottom (row 7) upward.
void drawBar(int device, int height){
  if(device<0 || device>3) return;
  if(height<0) height=0; if(height>8) height=8;
  for(int row=0; row<8; row++){
    bool on = (7 - row) < height;
    lc.setRow(device, row, on ? 0xFF : 0x00);
  }
}
void renderLevels(int l0,int l1,int l2,int l3){
  drawBar(0,l0); drawBar(1,l1); drawBar(2,l2); drawBar(3,l3);
}

// ===== 8×8 digit font for MAX7219 clock (fixed) =====
const byte DIGIT[10][8] = {
//0
{B00111100,B01100110,B01101110,B01110100,B01100110,B01100110,B00111100,B00000000},
//1
{B00011000,B00111000,B00011000,B00011000,B00011000,B00011000,B00111100,B00000000},
//2
{B00111100,B01100110,B00000110,B00001100,B00110000,B01100000,B01111110,B00000000},
//3
{B00111100,B01100110,B00000110,B00011100,B00000110,B01100110,B00111100,B00000000},
//4
{B00001100,B00011100,B00101100,B01001100,B01111110,B00001100,B00001100,B00000000},
//5
{B01111110,B01100000,B01111100,B00000110,B00000110,B01100110,B00111100,B00000000},
//6
{B00111100,B01100000,B01111100,B01100110,B01100110,B01100110,B00111100,B00000000},
//7
{B01111110,B00000110,B00001100,B00011000,B00110000,B00110000,B00110000,B00000000},
//8
{B00111100,B01100110,B01100110,B00111100,B01100110,B01100110,B00111100,B00000000},
//9
{B00111100,B01100110,B01100110,B00111110,B00000110,B00001100,B00111000,B00000000},
};

// 'logo', 128x32px
const unsigned char epd_bitmap_logo [] PROGMEM = {
	0xfe, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0xf0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0xf8, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0xf8, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x07, 0xbc, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x07, 0xbc, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x07, 0xbc, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x07, 0xbc, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x00, 0x3d, 0xfe, 0x78, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x00, 0x3d, 0xfc, 0x88, 0x00, 0x00, 0x00, 0x1c, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x00, 0x3d, 0xfd, 0x90, 0x00, 0x00, 0x00, 0x7f, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x00, 0x3d, 0xf9, 0x20, 0x38, 0x01, 0xc1, 0xff, 0xe0, 0x7f, 0x8f, 0xff, 0x9f, 0xf8, 0x00, 0x00, 
	0x00, 0x3c, 0x02, 0x60, 0x1c, 0x02, 0x03, 0xc0, 0xe0, 0x7f, 0xcf, 0xff, 0x9f, 0xf8, 0x68, 0x3c, 
	0x00, 0x3c, 0x04, 0x40, 0x1c, 0x02, 0x87, 0x80, 0x70, 0x01, 0xe0, 0x70, 0x00, 0x00, 0x24, 0x78, 
	0x00, 0x3c, 0x0c, 0x80, 0x0e, 0x04, 0x87, 0x00, 0x38, 0x00, 0xe0, 0x70, 0x00, 0x00, 0x14, 0xf0, 
	0x00, 0x3c, 0x09, 0x80, 0x0e, 0x05, 0x06, 0x00, 0x38, 0x00, 0xe0, 0x70, 0x00, 0x00, 0x03, 0xe0, 
	0x00, 0x3c, 0x19, 0x00, 0x0e, 0x01, 0x0e, 0x00, 0x18, 0x00, 0xe0, 0x70, 0x00, 0x00, 0x09, 0xe0, 
	0x00, 0x3c, 0x3e, 0x00, 0x07, 0x08, 0x0e, 0x00, 0x1c, 0x00, 0xe0, 0x70, 0x00, 0x00, 0x07, 0xc0, 
	0x00, 0x3c, 0x3e, 0x00, 0x07, 0x0a, 0x0e, 0x00, 0x18, 0x01, 0xe0, 0x70, 0x1f, 0xf8, 0x07, 0x80, 
	0x00, 0x3c, 0x7c, 0x00, 0x03, 0x92, 0x0e, 0x00, 0x00, 0x7f, 0xc0, 0x70, 0x1f, 0xf8, 0x07, 0xc0, 
	0x00, 0x3c, 0xf8, 0x00, 0x03, 0x94, 0x0e, 0x00, 0x00, 0x7f, 0x80, 0x70, 0x00, 0x00, 0x0f, 0xe0, 
	0x00, 0x3c, 0xf0, 0x00, 0x03, 0x9c, 0x07, 0x00, 0x00, 0x0f, 0x00, 0x70, 0x00, 0x00, 0x1f, 0xe0, 
	0x00, 0x3d, 0xf0, 0x00, 0x01, 0xf8, 0x07, 0x00, 0x00, 0x07, 0x80, 0x70, 0x00, 0x00, 0x1c, 0xf0, 
	0x00, 0x3f, 0xe0, 0x00, 0x01, 0xf8, 0x03, 0xc0, 0x00, 0x03, 0x80, 0x70, 0x00, 0x00, 0x3c, 0x78, 
	0x00, 0x3f, 0xc0, 0x00, 0x00, 0xf8, 0x01, 0xfc, 0x00, 0x01, 0xc0, 0x70, 0x00, 0x00, 0x78, 0x38, 
	0x00, 0x3f, 0xc0, 0x00, 0x00, 0xf0, 0x00, 0xfc, 0x00, 0x01, 0xe0, 0x70, 0x1f, 0xf8, 0x70, 0x3c, 
	0x00, 0x3f, 0x80, 0x00, 0x00, 0xf0, 0x00, 0x3c, 0x00, 0x00, 0xe0, 0x70, 0x1f, 0xf8, 0xf0, 0x1c, 
	0x00, 0x3f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x00, 0x3f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x00, 0x3e, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x00, 0x3c, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
};

// 'channels', 128x32px
const unsigned char epd_bitmap_channel [] PROGMEM = {
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xe8, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x88, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xc8, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x8e, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xee, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x8a, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xcc, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x8a, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xee, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x84, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x84, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xe4, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xe8, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xa8, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xc8, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xae, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xee, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xaa, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xcc, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xaa, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xea, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x8a, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xea, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x2e, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xea, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
};

// 'Audio', 128x32px
const unsigned char epd_bitmap_Audio [] PROGMEM = {
	0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x08, 
	0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x08, 
	0x07, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x08, 
	0x0f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x08, 
	0x7f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x08, 
	0x9f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x0f, 
	0x9f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x9f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x9f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x0f, 
	0x7f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 
	0x0f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 
	0x07, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x0e, 
	0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 
	0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x1c, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x3e, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x3e, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x3e, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x3e, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x3e, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0xbe, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0xbe, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x9c, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x41, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x3e, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x08, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x08, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x08, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
	0x3e, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
};


bool colonOn = false;
unsigned long lastColonToggle = 0, lastClockDraw = 0;

void matrixClearAll(){
  for(int d=0; d<4; d++) lc.clearDisplay(d);
}

// ===== Splash bitmaps (1×4) =====
const uint64_t IMAGES[] = {
  0x0000e4aaaaaaea00,
  0x0000120a0e12ce00,
  0x0000f111f111f700,
  0x0000221408142200
};
const int IMAGES_LEN = sizeof(IMAGES)/8;

// Draw one 8×8 bitmap onto module 'device'.
void drawImageOnDevice(int device, uint64_t img){
  int dev = REVERSE_DEVICE_ORDER ? (3 - device) : device;

  for(int row=0; row<8; row++){
    uint8_t b = (uint8_t)((img >> (8*row)) & 0xFF);
    if(H_MIRROR_PER_PANEL) b = bitrev8(b);

    if(!ROTATE_90_CCW){
      lc.setRow(dev, row, b);
    } else {
      uint8_t colByte = 0;
      for(int r=0; r<8; r++) if(b & (1u<<r)) colByte |= (uint8_t)(1u << (7 - r));
      lc.setColumn(dev, row, colByte);
    }
  }
}

void showSplashArt(){
  for(int i=0; i<4 && i<IMAGES_LEN; i++) drawImageOnDevice(i, IMAGES[i]);
}

// Draw one decimal digit onto module 'device' [0..3]
void drawDigit(int device, int num){
  if(device<0 || device>3 || num<0 || num>9) return;
  for(int row=0; row<8; row++){
    lc.setRow(device, row, DIGIT[num][row]);
  }
}

// Blink colon using two center LEDs on module #1
void drawColon(bool on){
  lc.setLed(1, 2, 3, on);
  lc.setLed(1, 5, 3, on);
}

// Render HH:MM on modules 0..3
void drawTimeOnMatrix(int hh, int mm){
  int d0 = (hh/10)%10;
  int d1 = hh%10;
  int d2 = (mm/10)%10;
  int d3 = mm%10;
  drawDigit(0, d0);
  drawDigit(1, d1);
  drawDigit(2, d2);
  drawDigit(3, d3);
}

// -- OLED --
void renderLogoOLED() {
  oled.clearDisplay();
  oled.drawBitmap(0, 0, epd_bitmap_logo, 128, 32, SSD1306_WHITE);
  oled.display();
}

void renderAudioOLED() {
  oled.clearDisplay();

  // Draw background bitmap
  oled.drawBitmap(0, 0, epd_bitmap_Audio, 128, 32, SSD1306_WHITE);

  const int BAR_X = 12;          // Bars start at 12th pixel
  const int TOP_BAR_HEIGHT = 6;  // Top bars
  const int TOP_GAP = 2;         // Gap between top bars
  const int BOTTOM_GAP = 5;      // Gap from bottom bar to top bars
  const int BOTTOM_BAR_HEIGHT = 10; 
  const int SCREEN_BOTTOM_GAP = 3;

  // Width scaling limits
  const int TOP_BAR_MAX_WIDTH = 111;
  const int BOTTOM_BAR_MAX_WIDTH = 117;

  // Top bars (2 bars)
  for(int i = 0; i < 2; i++){
    int y = i * (TOP_BAR_HEIGHT + TOP_GAP);  // vertical position
    int w = map(channelLevel[i], 0, 100, 0, TOP_BAR_MAX_WIDTH);  // width
    if(w > 0){
      oled.fillRect(BAR_X, y, w, TOP_BAR_HEIGHT, SSD1306_WHITE);
    }
  }

  // Bottom bar (3rd value)
  int bottomY = 2*(TOP_BAR_HEIGHT + TOP_GAP) + BOTTOM_GAP;  // vertical start
  bottomY = min(bottomY, 32 - SCREEN_BOTTOM_GAP - BOTTOM_BAR_HEIGHT); // clamp
  int w = map(channelLevel[2], 0, 100, 0, BOTTOM_BAR_MAX_WIDTH);
  if(w > 0){
    oled.fillRect(BAR_X, bottomY, w, BOTTOM_BAR_HEIGHT, SSD1306_WHITE);
  }

  oled.display();
}


void renderChannelOLED() {
  oled.clearDisplay();

  // Optional background bitmap
  oled.clearDisplay();
  oled.fillRect(0, 0, 128, 32, SSD1306_BLACK);
  oled.drawBitmap(0, 0, epd_bitmap_channel, 128, 32, SSD1306_WHITE);

  const int BAR_X = 2;
  const int BAR_WIDTH_MAX = 119;
  const int BAR_HEIGHT = 4;
  const int ROW_GAP = 1;
  const int TOP_MARGIN = 1;

  for(int i = 0; i < 6; i++){
    int y = TOP_MARGIN + i * (BAR_HEIGHT + ROW_GAP);

    // scale 0–100 → pixels
    int w = map(channelLevel[i], 0, 100, 0, BAR_WIDTH_MAX);

    // draw bar
    if(w > 0){
      oled.fillRect(BAR_X, y, w, BAR_HEIGHT, SSD1306_WHITE);
    }
  }

  oled.display();
}


// ---------- LCD + logic ----------
LiquidCrystal_I2C lcd(0x27, 16, 2);
RTC_DS3231 rtc;

// add SCREEN = 7
enum Mode { VISIT=0, NOTIFY=1, MUSIC=2, CLOCK=3, TEXT=4, BACKLIGHT=5, SYSTEM=6, SCREEN=7 };
int sysCpuPct=0, sysGpuPct=0, sysRamPct=0;
float sysCpuGHz=0.0;

Mode mode = VISIT;

String serialBuffer = "";
const int MAX_BUFFER_SIZE = 200;

char lastLine[2][17];
void initLastLineCache() {
  for (int r=0;r<2;r++){
    for(int c=0;c<16;c++) lastLine[r][c]=' ';
    lastLine[r][16]='\0';
  }
}

// VISIT mode
long astroCount=0, coreCount=0;
uint8_t boxStep=0; bool visitAnimActive=false;
unsigned long lastAnim=0; const unsigned long animInterval=900;

// SCROLLING
String scrollTop="", scrollBottom="";
int scrollIndexTop=0, scrollIndexBottom=0;
unsigned long lastScroll=0; const unsigned long scrollInterval=750;

// Visit animation CGRAM cells
byte char0[8]={0,0,0,0,0,0,0,0};
byte char1[8]={0,0,0,0,0,0,0,31};
byte char2[8]={0,0,0,0,0,0,31,31};
byte char3[8]={0,0,0,0,0,31,31,31};
byte char4[8]={0,0,0,0,31,31,31,31};
byte char5[8]={0,0,0,31,31,31,31,31};
byte char6[8]={0,0,31,31,31,31,31,31};
byte char7[8]={0,31,31,31,31,31,31,31};

// MUSIC/ARTIST icons
byte MusicIcon[8]   ={B00000,B00111,B01101,B01001,B01011,B11011,B11000,B00000};
byte ArtistIcon[8]  ={B00000,B01000,B01100,B01110,B01110,B01100,B01000,B00000};
byte VolumeIcon[8]  ={B00000,B00001,B00101,B10101,B10101,B10101,B00000,B00000};
byte SpeakerIcon[8] ={B00000,B00010,B00110,B11110,B11110,B00110,B00010,B00000};

byte CPUIcon[8]     ={B00000,B01010,B11111,B01110,B11111,B01010,B00000,B00000};
byte RamIcon[8]     ={B00000,B00000,B11111,B11111,B11111,B10101,B00000,B00000};
byte DisplayIcon[8] ={B00000,B11111,B11111,B11111,B00100,B01110,B00000,B00000};

// VOLUME OVERLAY
bool volumeOverlay=false;
unsigned long volumeOverlayUntil=0;
int lastVolumeShown=-1;

String pad16(const String &s){
  String r=s; if(r.length()>16) r=r.substring(0,16);
  while(r.length()<16) r+=' '; return r;
}

void printOptimizedLineBuffer(const char *buf,int row){
  for(int i=0;i<16;i++){
    if(lastLine[row][i]!=buf[i]){
      lcd.setCursor(i,row);
      lcd.print(buf[i]);
      lastLine[row][i]=buf[i];
    }
  }
}

void printOptimizedLine(int row,const String &text){
  String p=pad16(text); char buf[17];
  for(int i=0;i<16;i++) buf[i]=p[i];
  buf[16]='\0';
  printOptimizedLineBuffer(buf,row);
}

void printIconPrefixLine(int row, uint8_t iconIndex, const String &text){
  if(lastLine[row][0] != (char)iconIndex){
    lcd.setCursor(0,row);
    lcd.write(iconIndex);
    lastLine[row][0] = (char)iconIndex;
  }
  if(lastLine[row][1] != ' '){
    lcd.setCursor(1,row);
    lcd.print(' ');
    lastLine[row][1] = ' ';
  }
  String t = text;
  if(t.length() > 14) t = t.substring(0,14);
  while(t.length() < 14) t += ' ';

  for(int i=0;i<14;i++){
    char c = t[i];
    if(lastLine[row][i+2] != c){
      lcd.setCursor(i+2, row);
      lcd.print(c);
      lastLine[row][i+2] = c;
    }
  }
}

void printOptimizedLinePartial(int row,const String &text,int len){
  if(len<=0) return; if(len>16) len=16;
  for(int i=0;i<len;i++){
    char c=(i<text.length())?text[i]:' ';
    if(lastLine[row][i]!=c){
      lcd.setCursor(i,row);
      lcd.print(c);
      lastLine[row][i]=c;
    }
  }
}

void resetScrollState(){
  scrollTop=""; scrollBottom="";
  scrollIndexTop=0; scrollIndexBottom=0;
  lastScroll=millis();
}

String cleanString(String input){
  String out="";
  for(unsigned int i=0;i<input.length();i++){
    char c=input[i];
    if(c>=32 && c<=126) out+=c;
  }
  return out;
}

// VISIT helpers
void drawVisitHeaderAndCounts(){
  printOptimizedLine(0,"Live Visit Count");
  String bottom="ARI:"+String(astroCount)+" CC:"+String(coreCount);
  if(bottom.length()>15) bottom=bottom.substring(0,15);
  while(bottom.length()<15) bottom+=' ';
  printOptimizedLinePartial(1,bottom,15);
}
void enterVisitMode(){
  for(int i=0;i<8;i++){
    lcd.createChar(i,(i==0?char0:i==1?char1:i==2?char2:i==3?char3:i==4?char4:i==5?char5:i==6?char6:char7));
  }
  mode=VISIT; lcd.clear(); initLastLineCache(); resetScrollState();
  boxStep=0; visitAnimActive=false; drawVisitHeaderAndCounts();
}
void updateVisitAnimationFrame(){
  lcd.setCursor(15,1); lcd.write((uint8_t)boxStep);
  if(boxStep<7){ boxStep++; lastAnim=millis(); } else { visitAnimActive=false; }
}

// MUSIC helpers
void loadMusicIcons(){
  lcd.createChar(0, MusicIcon);
  lcd.createChar(1, ArtistIcon);
  lcd.createChar(2, VolumeIcon);
  lcd.createChar(3, SpeakerIcon);
}
void loadSystemIcons(){
  lcd.createChar(0, CPUIcon);
  lcd.createChar(1, DisplayIcon);
  lcd.createChar(2, RamIcon);
}
void printSystemBottom(){
  char buf[17]; for(int i=0;i<16;i++) buf[i]=' '; buf[16]='\0';
  int i=0;
  if(i<16) buf[i++] = (char)1; if(i<16) buf[i++] = ' ';
  String g = String(sysGpuPct) + "%";
  for(int k=0;k<g.length() && i<16; k++) buf[i++] = g[k];
  if(i<16) buf[i++] = ' ';
  if(i<16) buf[i++] = (char)2;
  if(i<16) buf[i++] = ' ';
  String r = String(sysRamPct) + "%";
  for(int k=0;k<r.length() && i<16; k++) buf[i++] = r[k];
  printOptimizedLineBuffer(buf,1);
}
void renderSystemNowOnce(){
  String top = String(sysCpuPct) + "% " + String(sysCpuGHz,2) + "GHz";
  printIconPrefixLine(0, 0, top);
  printSystemBottom();
}
void enterSystemMode(){
  loadSystemIcons();
  mode=SYSTEM; lcd.clear(); initLastLineCache(); resetScrollState();
  String top = String(sysCpuPct)+"% "+String(sysCpuGHz,2)+"GHz";
  printIconPrefixLine(0, 0, top);
  printSystemBottom();
}
void renderMusicNowOnce(){
  String t = scrollTop.substring(0, min((size_t)15, scrollTop.length()));
  String b = scrollBottom.substring(0, min((size_t)15, scrollBottom.length()));
  printIconPrefixLine(0, 0, t);
  printIconPrefixLine(1, 1, b);
}
void scrollTextLineIcon(int row,const String &text,int *idx,uint8_t iconIndex){
  const int avail = 14;
  if(avail <= 0) return;
  if((int)text.length() <= avail){
    printIconPrefixLine(row, iconIndex, text);
    *idx = 0;
    return;
  }
  String buf = text + "    ";
  int pos = (*idx) % buf.length();
  String seg;
  for(int i=0;i<avail;i++) seg += buf[(pos+i)%buf.length()];
  printIconPrefixLine(row, iconIndex, seg);
  (*idx)++;
}
void handleMusicCommand(const String &cmdIn){
  String cmd=cmdIn; int sep=cmd.indexOf('|',6);
  String topPart,bottomPart;
  if(sep>6){ topPart=cleanString(cmd.substring(6,sep)); bottomPart=cleanString(cmd.substring(sep+1)); }
  else{ topPart=cleanString(cmd.substring(6)); bottomPart=""; }
  if(topPart.length()==0) topPart="Unknown Title";
  if(bottomPart.length()==0) bottomPart="Unknown Artist";
  scrollTop=topPart; scrollBottom=bottomPart;
  scrollIndexTop=0; scrollIndexBottom=0; lastScroll=millis();
  if(mode==MUSIC && !volumeOverlay) renderMusicNowOnce();
}

// CLOCK helpers
void enterClockMode(){
  mode = CLOCK;
  lcd.clear(); initLastLineCache(); resetScrollState();
  printOptimizedLine(0,"Clock Mode");
  printOptimizedLine(1,"Running");
}

// ===== SCREEN MIRROR mode (matrix-only) =====
void enterScreenMode(){
  mode = SCREEN;
  lcd.clear(); initLastLineCache(); resetScrollState();
  printOptimizedLine(0,"Screen Mirror");
  printOptimizedLine(1,"Running");
}

// ======== 32-band VU overlay (buffered, matrix-only) ========
bool vuEnabled = false;
uint8_t vuH[32];
int8_t  vuPeak[32];
unsigned long vuLastRx = 0, vuLastDecay = 0, vuLastDraw = 0;
const unsigned long vuFrameMs = 33;   // ~30 FPS
const unsigned long vuIdleMs  = 120;
const unsigned long vuDecayMs = 60;
bool vuShowPeaks = true;

void buildDeviceRows(uint8_t devIdx, uint8_t rows[8]){
  for(int r=0;r<8;r++) rows[r]=0;

  int physDev = REVERSE_DEVICE_ORDER ? (3 - devIdx) : devIdx;
  int base = physDev << 3;  // 8 bands per panel

  for(int x=0;x<8;x++){
    uint8_t h = vuH[base + x];
    if(h>8) h=8;
    uint8_t m = (h==0) ? 0x00 : ((h==8) ? 0xFF : (uint8_t)((1u<<h)-1u));

    for(int y=0;y<8;y++){
      if(m & (1u<<y)){
        int col = H_MIRROR_PER_PANEL ? (7 - x) : x;
        rows[7 - y] |= (uint8_t)(1u << col);
      }
    }
    if(vuShowPeaks){
      int8_t pk = vuPeak[base + x];
      if(pk>=0 && pk<8){
        int col = H_MIRROR_PER_PANEL ? (7 - x) : x;
        rows[7 - pk] |= (uint8_t)(1u << col);
      }
    }
  }
}

void renderVU32(){
  uint8_t rows[8];
  for(int d=0; d<4; d++){
    buildDeviceRows(d, rows);

    if(!ROTATE_90_CCW){
      for(int r=0;r<8;r++){
        lc.setRow(d, r, rows[r]);
      }
    } else {
      for(int c=0;c<8;c++){
        uint8_t colByte=0;
        for(int r=0;r<8;r++){
          if(rows[r] & (1u<<c)) colByte |= (uint8_t)(1u<<(7-r));
        }
        lc.setColumn(d, c, colByte);
      }
    }
    yield();
  }
}

void clearMatrixFast(){
  for(int d=0; d<4; d++) lc.clearDisplay(d);
}

// Optional wiring test
void sweepTest(){
  for(int p=0;p<4;p++){
    for(int c=0;c<8;c++){
      for(int r=0;r<8;r++) lc.setRow(p,r,0);
      for(int r=0;r<8;r++) lc.setRow(p,r,(uint8_t)(1u<<c));
      delay(120);
    }
  }
  for(int p=0;p<4;p++) lc.clearDisplay(p);
}

// ---------- MODE switch ----------
void switchMode(uint8_t newModeRaw){
  mode=(Mode)newModeRaw;
  lcd.clear(); initLastLineCache(); resetScrollState();
  volumeOverlay=false; lastVolumeShown=-1;

  switch(mode){
    case VISIT:  enterVisitMode();   break;
    case NOTIFY:
      loadMusicIcons();
      printOptimizedLine(0,"Notify Mode");
      printOptimizedLine(1,"Loading...");
      break;
    case MUSIC:
      loadMusicIcons();
      printOptimizedLine(0,"Music Mode");
      printOptimizedLine(1,"Loading...");
      break;
    case CLOCK:  enterClockMode();   break;
    case TEXT:
      printOptimizedLine(0,"Text Mode");
      printOptimizedLine(1,"Loading...");
      break;
    case BACKLIGHT:
      break;
    case SYSTEM: enterSystemMode();  break;
    case SCREEN: enterScreenMode();  break;
  }
}

// ---------- COMMANDS ----------
void showVolumeOverlay(int vol, const String& dev){
  volumeOverlay = true;
  volumeOverlayUntil = millis() + 1500;
  lastVolumeShown = vol;
  loadMusicIcons();
  if(mode == VISIT){
    visitAnimActive = false;
    lcd.setCursor(15,1);
    lcd.print(' ');
  }
  String line0 = "Volume: " + String(vol);
  String line1 = dev.length() ? dev : "";
  printIconPrefixLine(0, 2, line0);
  printIconPrefixLine(1, 3, line1);
}

void handleCommand(String cmdRaw){
  String cmd=cmdRaw; cmd.trim(); if(cmd.length()==0) return;

    // ---------- CHANNEL MODE (OLED) ----------
  if(cmd == "CHANNEL:ON"){
    channelMode = true;
    logoMode = false;
    audioMode = false; 
    renderChannelOLED();
    return;
  }

  if(cmd == "CHANNEL:OFF"){
    channelMode = false;
    logoMode = false;
    oled.clearDisplay();
    oled.display();
    return;
  }

  if(cmd == "AUDIO:ON"){
    audioMode = true;
    channelMode = false;
    logoMode = false;
    renderAudioOLED();
    return;
  }

  if(cmd == "AUDIO:OFF"){
      audioMode = false;
      oled.clearDisplay();
      oled.display();
      return;
  }

  if(cmd == "LOGO:ON" || cmd == "LOGO=true"){
    logoMode = true;
    channelMode = false;   // 👈 force exit channel mode
    audioMode = false; 
    renderLogoOLED();
    return;
  }

  if(cmd == "LOGO:OFF" || cmd == "LOGO=false"){
    logoMode = false;
    oled.clearDisplay();
    oled.display();
    return;
  }


  // Channel level update: CH:FL,FR,CT,RL,RR,SW (0–100)
  if(cmd.startsWith("CH:")){
    int idx = 0;
    int last = 3;

    for(int i = 3; i <= cmd.length() && idx < 6; i++){
      if(i == cmd.length() || cmd[i] == ','){
        channelLevel[idx] = constrain(
          cmd.substring(last, i).toInt(),
          0, 100
        );
        idx++;
        last = i + 1;
      }
    }

    if(audioMode){
      renderAudioOLED();
    }


    if(channelMode && !logoMode){
      renderChannelOLED();
    }
    return;
  }


  // VU overlay toggle
  if(cmd=="VUMODE:ON"){ vuEnabled = true; clearMatrixFast(); vuLastDraw = millis(); return; }
  if(cmd=="VUMODE:OFF"){ vuEnabled = false; clearMatrixFast(); return; }

  // VU frame
  if(cmd.startsWith("V:")){
    if(cmd.length()>=34){
      for(int i=0;i<32;i++){
        char c = cmd[2+i];
        uint8_t v = (c>='0' && c<='8') ? (uint8_t)(c-'0') : 0;
        vuH[i]   = v;
        vuPeak[i]= (v>0) ? (int8_t)(v-1) : -1;
      }
      vuLastRx = millis();
      if(vuEnabled){
        renderVU32();
        vuLastDraw = vuLastRx;
      }
    }
    return;
  }

  // ---------- 32×8 framebuffer: "FB:" + 8 rows × 8 hex chars ----------
  if (cmd.startsWith("FB:")){
    if (cmd.length() < 3 + 8*8) return; // need 64 hex chars
    uint32_t rowBits[8];
    int idx = 3;
    for (int r = 0; r < 8; r++){
      uint32_t v = 0;
      for (int h = 0; h < 8; h++){
        v = (v << 4) | hexVal(cmd[idx++]);
      }
      rowBits[r] = v;
    }

    // rowBits[r]: bit31..bit0 = x=0..31 (left→right)
    for (int dev = 0; dev < 4; dev++){
      uint8_t rows8[8];
      for (int r = 0; r < 8; r++){
        uint8_t b = 0;
        for (int x = 0; x < 8; x++){
          int col = dev*8 + x;
          if (rowBits[r] & (1UL << (31 - col))){ // MSB = leftmost
            int colInPanel = H_MIRROR_PER_PANEL ? (7 - x) : x;
            b |= (uint8_t)(1U << colInPanel);
          }
        }
        rows8[r] = b;
      }

      int physDev = REVERSE_DEVICE_ORDER ? (3 - dev) : dev;
      if (!ROTATE_90_CCW){
        for (int r = 0; r < 8; r++){
          lc.setRow(physDev, r, rows8[r]);
        }
      } else {
        for (int c = 0; c < 8; c++){
          uint8_t colByte = 0;
          for (int r = 0; r < 8; r++){
            if (rows8[r] & (1U << c)) colByte |= (uint8_t)(1U << (7 - r));
          }
          lc.setColumn(physDev, c, colByte);
        }
      }
    }
    return;
  }

  if(cmd.startsWith("MODE:")){
    int m = cmd.substring(5).toInt();
    // accept VISIT..SCREEN = 1..8
    if(m >= 1 && m <= 8) switchMode((uint8_t)(m - 1));
    return;
  }

  if(cmd.startsWith("LIVE:")){
    int comma=cmd.indexOf(',');
    if(comma>5){
      astroCount=cmd.substring(5,comma).toInt();
      coreCount =cmd.substring(comma+1).toInt();
      if(mode==VISIT){
        drawVisitHeaderAndCounts();
        boxStep=0; visitAnimActive=true; lastAnim=millis();
        lcd.setCursor(15,1); lcd.write((uint8_t)boxStep);
      }
    } return;
  }

  if(cmd.startsWith("CLOCK:")){
    int sep=cmd.indexOf('|',6);
    String top=(sep>6)?cmd.substring(6,sep):cmd.substring(6);
    String bottom=(sep>6)?cmd.substring(sep+1):"";
    top=pad16(cleanString(top)); bottom=pad16(cleanString(bottom));
    if(mode==CLOCK){
      printOptimizedLine(0,top);
      printOptimizedLine(1,bottom);
    }
    return;
  }

  if(cmd.startsWith("MUSIC:")){ handleMusicCommand(cmd); return; }

  if(cmd.startsWith("NOTIFY:")){
    int sep=cmd.indexOf('|',7);
    if(sep>7){
      scrollTop   = cleanString(cmd.substring(7,sep));
      scrollBottom= cleanString(cmd.substring(sep+1));
    } else {
      scrollTop   = cleanString(cmd.substring(7));
      scrollBottom= "";
    }
    scrollIndexTop=scrollIndexBottom=0; lastScroll=millis();
    if(mode==NOTIFY) renderMusicNowOnce();
    return;
  }

  if(cmd.startsWith("TEXT:")){
    String txt=cleanString(cmd.substring(5));
    if(mode==TEXT){
      String top=pad16(txt.substring(0,min((size_t)16,txt.length())));
      printOptimizedLine(0,top);
      if(txt.length()>16){
        String bottom=pad16(txt.substring(16,min((size_t)32,txt.length())));
        printOptimizedLine(1,bottom);
      } else {
        printOptimizedLine(1,pad16(""));
      }
    }
    return;
  }

  if(cmd.startsWith("BACKLIGHT:")){
    if(cmd.endsWith("ON")) lcd.backlight();
    else if(cmd.endsWith("OFF")) lcd.noBacklight();
    else if(cmd.endsWith("TOGGLE")){
      static bool bl=true; bl=!bl;
      if(bl) lcd.backlight(); else lcd.noBacklight();
    }
    return;
  }

  if(cmd.startsWith("VOL:")){
    int sep = cmd.indexOf('|', 4);
    int v = (sep>0 ? cmd.substring(4, sep) : cmd.substring(4)).toInt();
    if(v<0) v=0; if(v>100) v=100;
    String dev = "";
    if(sep>0) dev = cleanString(cmd.substring(sep+1));
    showVolumeOverlay(v, dev);
    return;
  }

  // legacy 4-band demo: "L:a,b,c,d"
  if(cmd.startsWith("L:")){
    int v[4]={0,0,0,0}; int idx=0; int last=2;
    for(int i=2;i<=cmd.length() && idx<4;i++){
      if(i==cmd.length() || cmd[i]==','){
        v[idx++] = cmd.substring(last, i).toInt();
        last = i+1;
      }
    }
    renderLevels(v[0],v[1],v[2],v[3]);
    return;
  }

  if(cmd=="GOODBYE"){
    lcd.clear(); initLastLineCache();
    printOptimizedLine(0,"Disconnected");
    printOptimizedLine(1,String(' ',16));
    for(int d=0; d<4; d++) lc.clearDisplay(d);
    return;
  }

  if(cmd.startsWith("SYS:")){
    int bar = cmd.indexOf('|',4);
    if(bar>4){
      String a = cmd.substring(4,bar);
      String b = cmd.substring(bar+1);
      int c = a.indexOf(',');
      if(c>0){
        sysCpuPct = a.substring(0,c).toInt();
        sysCpuGHz = a.substring(c+1).toFloat();
      }
      c = b.indexOf(',');
      if(c>0){
        sysGpuPct = b.substring(0,c).toInt();
        sysRamPct = b.substring(c+1).toInt();
      }
      if(mode==SYSTEM) renderSystemNowOnce();
    }
    return;
  }
}

// ---------- SETUP ----------
void setup(){
  Serial.begin(115200);
  lcd.begin(); lcd.backlight();
  initLastLineCache();

  // init matrices BEFORE drawing splash
  matrixInit();

    // ---- OLED init ----
  if(!oled.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    // OLED failed to init (optional: Serial print)
  }
  oled.setRotation(2);
  oled.clearDisplay();

  // draw bitmap at (0,0)
  oled.drawBitmap(
    0,              // x
    0,              // y
    epd_bitmap_logo,
    128,            // width
    32,             // height
    SSD1306_WHITE
  );

  oled.display();   // <-- THIS actually pushes pixels to screen

  // LCD splash
  lcd.clear();
  lcd.setCursor(3,0); lcd.print("Vortex LCD");
  lcd.setCursor(1,1); lcd.print("Display System");

  // dot-matrix splash during LCD splash
  showSplashArt();
  delay(2000);

  // init VU buffers
  for(int i=0;i<32;i++){ vuH[i]=0; vuPeak[i]=-1; }
  vuEnabled=false; vuLastRx=vuLastDecay=vuLastDraw=millis();

  rtc.begin();

  clearMatrixFast();

  oled.clearDisplay();
  oled.display();

  lcd.clear();
  lcd.setCursor(2,0); lcd.print("Waitting For");
  lcd.setCursor(3,1); lcd.print("Serial....");
  delay(2000);
}

// ---------- LOOP ----------
void loop(){
  while(Serial.available()){
    char c=Serial.read();
    if(c=='\n'||c=='\r'){
      if(serialBuffer.length()>0){
        handleCommand(serialBuffer);
        serialBuffer="";
      }
    } else if(c>=32 && c<=126){
      if(serialBuffer.length()<MAX_BUFFER_SIZE) serialBuffer+=c;
    }
  }

  unsigned long now=millis();

  if(mode==VISIT && visitAnimActive && now-lastAnim>=animInterval)
    updateVisitAnimationFrame();

  if(volumeOverlay){
    if(now >= volumeOverlayUntil){
      volumeOverlay = false;
      if     (mode == MUSIC) { renderMusicNowOnce(); lastScroll = now; }
      else if(mode == NOTIFY){ renderMusicNowOnce(); lastScroll = now; }
      else if(mode == SYSTEM){ loadSystemIcons(); renderSystemNowOnce(); }
      else if(mode == VISIT) { enterVisitMode(); }
    }
  } else {
    if((mode==MUSIC || mode==NOTIFY) && now-lastScroll>=scrollInterval){
      if(scrollTop.length()>0 || scrollBottom.length()>0){
        scrollTextLineIcon(0, scrollTop,   &scrollIndexTop,    0);
        scrollTextLineIcon(1, scrollBottom,&scrollIndexBottom, 1);
      }
      lastScroll=now;
    }
  }

  if((mode==MUSIC || mode==NOTIFY) && lastLine[0][0] == ' ')
    loadMusicIcons();

  // VU engine
  if(vuEnabled){
    if(now - vuLastRx >= vuIdleMs && now - vuLastDecay >= vuDecayMs){
      for(int i=0;i<32;i++){
        if(vuH[i]>0) vuH[i]--;
        if(vuPeak[i]>=0) vuPeak[i]--;
      }
      vuLastDecay = now;
      renderVU32();
      vuLastDraw = now;
    }
    if(now - vuLastDraw >= vuFrameMs){
      renderVU32();
      vuLastDraw = now;
    }
  }
}
