# Vortex-Desk-Peripherals V2
A system that control stuff on my desk.
<p align="center">
  <img src="https://github.com/user-attachments/assets/8557640d-16f9-4e5e-99c7-67beb4894a8f" width="49%" />
  <img src="https://github.com/user-attachments/assets/9d033d4f-a02f-4edc-8bd6-fde379dc1c16" width="49%" />
</p>

i made this with a help of AI so it is a mess
## Software:
This project runs python 3.9 <br/>
Requiered libraries:
```bash
pip install PySide6 pyserial numpy soundcard psutil Pillow screeninfo requests Unidecode pywin32 winrt-Windows.Media
```
## Hardware:
This project use NodeMCU ESP8266
32×8 Dot Matrix (MAX7219 ×4)
16×2 LCD (I2C, HD44780)
0.91 OLED display (I2C, SSD1306 / SH1106) [Optional]

Dot Matrix Wiring:
| Device  | DIN             | CLK             | CS / LOAD       | VCC          | GND     |
| ------- | --------------- | --------------- | --------------- | ------------ | ------- |
| MAX7219 | **D7 (GPIO13)** | **D5 (GPIO14)** | **D8 (GPIO15)** | **VIN (5V)** | **GND** |

16x2 LCD Wiring:
| Device   | SDA            | SCL            | VCC     | GND     |
| -------- | -------------- | -------------- | ------- | ------- |
| LCD 16×2 | **D2 (GPIO4)** | **D1 (GPIO5)** | **VIN** | **GND** |

0.91 OLED display Wiring
| Device     | SDA            | SCL            | VCC     | GND     |
| ---------- | -------------- | -------------- | ------- | ------- |
| OLED 0.91″ | **D2 (GPIO4)** | **D1 (GPIO5)** | **3V3** | **GND** |

## Wiring Reference:
<img src="https://europe1.discourse-cdn.com/arduino/original/4X/8/9/b/89bdfadc5637f18b1c9839ad4c8996d98e1b62ff.jpeg"/>
Image Source: mischianti.org (https://mischianti.org/)

