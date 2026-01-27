# Vortex-Desk-Assembly 🖥️⚡
## Build For Guestdaprotogen, Lord of microcontrollers 🥶🥶🥶🥶🥶



> **The ultimate low-level desk controller.**
> A high-performance, zero-dependency rewrite of the [Vortex-Desk-Peripherals V2](Rm-ld.md) controller in pure **NASM x64 Assembly**.

---

## 📖 Table of Contents
- [Overview](#-overview)
- [Why Assembly?](#-why-assembly)
- [Software Architecture](#-software-architecture)
- [Hardware Setup](#-hardware-setup)
- [Installation & Build](#-installation--build)
- [Usage Manual](#-usage-manual)
- [Serial Protocol](#-serial-protocol)
- [Troubleshooting](#-troubleshooting)

---

## 🔍 Overview

**Vortex-Desk-Assembly** is a lightweight Command Line Interface (CLI) tool designed to communicate with an ESP8266 (NodeMCU) via Serial (UART). It allows manual control of various desk peripherals, including:
- **16x2 LCD Display**: For status updates and messages.
- **MAX7219 Dot Matrix Array**: For scrolling text, clock, and visualizers.
- **OLED Display**: Secondary status information.

This project replaces the original Python-based controller with a native Windows executable that uses **direct Win32 API calls** for maximum efficiency and minimal resource footprint.

---

## 💡 Why Assembly?

Rewriting a high-level Python script into x64 Assembly was a deliberate choice for:
1.  **Performance**: The final executable is **< 70KB** and starts instantly.
2.  **Resource Efficiency**: Uses < 1MB of RAM compared to Python's heavy runtime interpretation.
3.  **Educational Value**: Demonstrates how to perform complex tasks (File I/O, Serial Comm, User Input) using **System Calls** and **Registers** (`RBX`, `RCX`, `RDX`, etc.) instead of libraries.
4.  **Zero Dependencies**: No `pip install`, no `node_modules`, no runtime environment needed. Just one `.exe`.

---

## 🏗️ Software Architecture

The application is built as a single-file assembly program (`main.asm`) with the following structure:

### Win32 API Integration
Instead of the C standard library for everything, we leverage the Windows Kernel directly:
- **`CreateFileA`**: Opens the COM port handle.
- **`GetCommState` / `SetCommState`**: Configures Baud Rate (115200), Parity, and Byte size.
- **`WriteFile` / `ReadFile`**: Sends and receives raw bytes over UART.
- **`GetStdHandle`**: Handles Console Input/Output.

### Memory Layout
- **`.data` Section**: Stores static strings (Menus, UI messages) and pre-allocated buffers.
- **`.bss` (implicitly handled)**: Input buffers (`inputBuf`, `serialBuf`) allow up to 256 bytes of data.

---

## 🛠️ Hardware Setup

The software controls a **NodeMCU (ESP8266)** acting as the master for the peripherals.

### Components
1.  **NodeMCU V3 (ESP8266)**
2.  **MAX7219 Dot Matrix Module (4-in-1)**
3.  **LCD 1602 (with I2C Backpack)**
4.  *(Optional)* **OLED 0.96" (I2C)**

### Wiring Diagram
<img src="https://europe1.discourse-cdn.com/arduino/original/4X/8/9/b/89bdfadc5637f18b1c9839ad4c8996d98e1b62ff.jpeg" width="600" />

*Image Credit: mischianti.org*

#### Pinout Configuration

**1. Dot Matrix (SPI)**
| NodeMCU Pin | Matrix Pin | Description |
| :--- | :--- | :--- |
| **D7** (GPIO13) | DIN | Data In |
| **D5** (GPIO14) | CLK | Clock |
| **D8** (GPIO15) | CS/LOAD | Chip Select |
| **VU / VIN** | VCC | 5V Power |
| **GND** | GND | Ground |

**2. LCD & OLED (I2C)**
| NodeMCU Pin | Display Pin | Description |
| :--- | :--- | :--- |
| **D2** (GPIO4) | SDA | Serial Data |
| **D1** (GPIO5) | SCL | Serial Clock |
| **VU / 3V3** | VCC | Power |
| **GND** | GND | Ground |

---

## 📥 Installation & Build

### Prerequisites
- **Windows x64**
- **[NASM](https://www.nasm.us/)** (The assembler)
- **[MinGW-w64](https://www.mingw-w64.org/)** (For GCC linker)

### formatting
Ensure `nasm` and `gcc` are in your System PATH.

### Building from Source
A helper script `build.bat` is provided.

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/athivaratz/Vortex-Desk-Assembly.git
    cd Vortex-Desk-Assembly
    ```
2.  **Run Build Script**:
    Double-click `build.bat` or run in terminal:
    ```cmd
    .\build.bat
    ```
3.  **Manual Build Command**:
    ```cmd
    nasm -f win64 main.asm -o main.obj
    gcc -o main.exe main.obj -lkernel32 -mconsole -no-pie
    ```

---

## 🎮 Usage Manual

Run the application:
```cmd
.\main.exe
```

### 1. Connection
Upon launch, you will be prompted:
```text
Enter COM Port (e.g. COM3):
```
Type your port (e.g., `COM3`, `COM5`) and press Enter. The tool will attempt to open a serial connection at **115200 baud**.

### 2. Main Menu
Once connected, you can use Single-Key commands (no need to press Enter for menu items):

| Key | Mode | Description |
|:---:|:---|:---|
| **`1`** | **Visit Mode** | Default idle animation / visitor welcome. |
| **`2`** | **Music Mode** | Audio visualizer style (requires device support). |
| **`3`** | **Clock Mode** | Displays current time large on the matrix. |
| **`4`** | **Text Mode** | Scads custom messages across the screen. |
| **`5`** | **System Mode** | Displays PC stats (received from manual input). |
| **`6`** | **Screen Mode** | Specific screen configuration. |
| **`r`** | **Reset** | Sends `RESET` command to reboot NodeMCU. |
| **`m`** | **Menu** | Reprints the help menu. |
| **`q`** | **Quit** | Closes the connection and exits. |

### 3. Data Entry Commands
These commands allow you to send dynamic content:

- **Type `t` (Send Text)**:
    - Prompts: `Enter text:`
    - Effect: Scrolls your text on the Matrix/LCD.
- **Type `c` (Send Clock)**:
    - Prompts: `Time:` then `Date:`
    - Effect: Updates the clock display manually.
- **Type `l` (Send 2-Line)**:
    - Prompts: `Line 1:` then `Line 2:`
    - Effect: Updates the 16x2 LCD rows directly.

---

## 📡 Serial Protocol

For developers modifying the NodeMCU firmware, here is the protocol this CLI uses:

**Baud Rate**: 115200

| Type | Command Format | Example | Description |
| :--- | :--- | :--- | :--- |
| **Change Mode** | `MODE:<ID>` | `MODE:1` | Switch device state. |
| **Send Text** | `TEXT:<string>` | `TEXT:Hello` | General text display. |
| **Update Clock** | `CLOCK:<time>|<date>` | `CLOCK:12:00|Jan 01` | Updates time/date variables. |
| **LCD Lines** | `TEXT:<line1><line2>` | `TEXT:CPU 50% RAM 20% ` | Sends exactly 16+16 chars for LCD. |
| **System Reset** | `RESET` | `RESET` | Soft reset the ESP8266. |

---

## 🔧 Troubleshooting

- **`[ERROR] Cannot open port`**:
    - Check if the NodeMCU is plugged in.
    - Verify the COM port in Device Manager.
    - Ensure no other software (Arduino IDE, Cura) is using the port.
- **Garbage Text on LCD**:
    - Ensure your connection is **115200 baud**.
    - Check loose wiring on SDA/SCL lines.
- **"GCC linking failed"**:
    - Ensure MinGW is installed and `gcc` is in your PATH.
    - Check if `main.exe` is already running (it locks the file).

---

## 📜 Credits

- **Original Project**: [Vortex-Desk-Peripherals V2](Rm-ld.md)
- **Assembly Implementation**: Athivaratz
- **Reference**: [Mischianti.org](https://mischianti.org/) (Wiring Diagrams)

_Crafted with precision in x64 Assembly._
 
 
# Ruined with 🦅🦅🦅🦅🦅 by Athivaratz
# Vibed with 🦅🦅🦅🦅🦅 by Athivaratz
# I LOVE GUEST'S WORK 🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥

