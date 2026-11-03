# Hardware Reference

Status: Vendor source code and schematic reviewed; chip, Flash, and USB identification checked on the physical device. Display, touch input, and PSRAM runtime operation remain untested.

Reviewed: 2026-11-03

## 1. Source Material

The vendor package is located at `D:/work/ESP32/S3版本`. The original files have not been modified or copied into this repository.

| ID | Source | Purpose |
| --- | --- | --- |
| S1 | [Display setup](<D:/work/ESP32/S3版本/v1.4加气象预警（S3）/libraries/TFT_eSPI/User_Setup.h>) | Active display driver, geometry, GPIO assignments, color order, and SPI frequency |
| S2 | [Setup selection](<D:/work/ESP32/S3版本/v1.4加气象预警（S3）/libraries/TFT_eSPI/User_Setup_Select.h>) | Confirms that the library selects `User_Setup.h` |
| S3 | [Arduino application](<D:/work/ESP32/S3版本/v1.4加气象预警（S3）/SmallDesktopDisplay/SmallDesktopDisplay.ino>) | Display initialization, brightness control, serial configuration commands, weather UI, and animation playback |
| S4 | [Board schematic](<D:/work/ESP32/S3版本/S3天气预报电路图.pdf>) | LCD wiring, backlight circuit, touch electrode, native USB connection, and exposed programming signals |
| S5 | [TFT_eSPI metadata](<D:/work/ESP32/S3版本/v1.4加气象预警（S3）/libraries/TFT_eSPI/library.properties>) | Bundled library version: 2.5.43 |
| S6 | [TJpg_Decoder metadata](<D:/work/ESP32/S3版本/v1.4加气象预警（S3）/libraries/TJpg_Decoder/library.properties>) | Bundled JPEG decoder version: 1.1.0 |
| S7 | Product listing specification reported by the user on 2026-11-03: `8M+8M` | Advertised memory configuration; the listing itself and a complete module marking have not been supplied |
| S8 | On-device `esptool` probe on 2026-11-03, repeated twice with matching results | ESP32-S3 revision v0.2, 16 MB detected Flash, 8 MB embedded PSRAM reported from chip information, and USB-Serial/JTAG on COM6 |

Local source links refer to the supplied package on this computer. Version numbers describe the bundled copies, not a requirement to use those versions in the new firmware.

## 2. Display Configuration

| Item | Evidence from vendor material | Source |
| --- | --- | --- |
| Controller family | ST7789; active macro is `ST7789_2_DRIVER` | S1, line 56 |
| Resolution | 240 × 240 | S1, lines 87 and 90 |
| Transport | Hardware SPI; parallel modes are disabled | S1 |
| Pixel color order | `TFT_RGB_ORDER TFT_RGB` | S1, line 76 |
| SPI write frequency | 27,000,000 Hz | S1, line 357 |
| Initialization | `tft.begin()` followed by `tft.invertDisplay(1)` | S3, lines 997-998 |
| Rotation | Configurable through the application and persisted settings | S3 |

`ST7789_2_DRIVER` selects the bundled library's minimal ST7789 configuration. It is a software driver variant, not evidence of a different controller model named "ST7789_2".

The active configuration and schematic agree on the following connections:

| Signal | ESP32-S3 GPIO | Schematic label | Notes |
| --- | --- | --- | --- |
| SPI MOSI | 1 | `LCD_SDA` | Pixel data and commands; the SDA label does not imply I2C |
| SPI clock | 18 | `LCD_SCL` | SPI clock despite the SCL label |
| Data/command | 17 | `LCD_DC` | Selects data or command transfers |
| Reset | 6 | `LCD_RESET` | Display reset |
| Backlight control | 2 | `LCD_BL` | Drives the AO3401 backlight switching circuit |

No active `TFT_CS` or `TFT_MISO` assignment is present in S1. The schematic shows ground connections at the display connector but does not label a separate LCD CS signal. Start from the vendor configuration without inventing a CS GPIO; confirm operation during display bring-up.

The backlight circuit uses a high-side P-channel MOSFET. The application drives GPIO2 with `analogWrite(LCD_BL_PIN, 255 - LCD_BL_PWM)`, consistent with active-low control. Match the existing electrical polarity, then verify the usable brightness range on the device rather than assuming that the original UI value is a calibrated percentage.

## 3. Touch Input

The schematic connects a touch electrode labeled `TP_KEY` to GPIO5. This supports the product image's indication of a top touch input.

No touch detection or GPIO5 input handling was found in the supplied application's `.ino`, `.cpp`, or `.h` files. The presence of the electrode is documented, but touch thresholds, debounce behavior, and page switching have not been verified. This is a separate touch input, not evidence of a touchscreen.

## 4. USB and Programming Connections

The schematic connects the USB-C data lines through 27-ohm series resistors to the ESP32-S3:

| USB signal | ESP32-S3 GPIO |
| --- | --- |
| D- | 19 |
| D+ | 20 |

This documents a native USB data connection rather than a power-only connector. No USB-to-UART bridge is shown in that connection. Header H1 exposes GND, TX, RX, +5V, IO0, and RESET signals.

Windows enumerated the connected device on COM6 with USB VID:PID `303A:1001`. The on-device probe reported USB-Serial/JTAG and successfully connected to the ROM loader. Communication worked after the user changed the computer's USB port. The earlier failure to enumerate does not establish a cable or driver fault.

This verifies USB enumeration and the diagnostic connection. It does not yet verify application-level message reception or the USB settings for the new firmware.

## 5. Existing Application Capabilities

The supplied application provides reference implementations for:

- Initializing the ST7789 display through `TFT_eSPI`.
- Adjusting backlight brightness and display rotation.
- Drawing text and graphics using sprites, including 8-bit sprite buffers.
- Decoding embedded JPEG assets using `TJpg_Decoder`.
- Playing a sequence of embedded JPEG frames for an illustration.
- Connecting to Wi-Fi and providing web-based configuration.
- Receiving serial configuration commands through `Serial_set()`; `Serial.begin(115200)` appears in `setup()`.

These are existing application features, not the project's generic structured display protocol. The serial configuration parser and weather-specific UI do not establish support for arbitrary pushed messages, agent task cards, or BLE delivery.

The schematic also contains audio circuitry. Audio is not part of the current project requirements and is not added to scope by its presence in the schematic.

## 6. Memory and On-Device Identification

The user reports that the product listing specifies `8M+8M`, initially interpreted as 8 MB Flash plus 8 MB PSRAM. Two matching on-device probes instead detected **16 MB Flash** and reported **8 MB embedded PSRAM**. Use the detected 16 MB Flash plus 8 MB PSRAM specification as the current development baseline, while retaining the advertisement as conflicting source information.

### 6.1 Probe Method and Results

Tool: esptool 5.6.0 from the installed ESP-IDF v6.1 Python environment. The following command was executed twice:

```powershell
& 'C:/Espressif/tools/python/v6.1/venv/Scripts/python.exe' -m esptool --port COM6 --baud 115200 --connect-attempts 3 --no-stub flash-id
```

The operation read chip information and Flash identification through the ROM loader, then reset the device. No firmware was flashed, no Flash sectors were erased, and no eFuses were programmed.

| Field | Reported value | Interpretation |
| --- | --- | --- |
| Chip type | ESP32-S3 (QFN56), revision v0.2 | Detected SoC family, package, and revision |
| Features | Wi-Fi, BT 5 (LE), Dual Core + LP Core, 240 MHz | Capabilities reported by the tool |
| Embedded PSRAM | 8 MB (`AP_3v3`) | Chip-information report; runtime initialization and memory testing have not been performed |
| Crystal | 40 MHz | Reported crystal frequency |
| USB mode | USB-Serial/JTAG | Verified diagnostic transport |
| Detected Flash size | 16 MB | Flash identification result, consistent across both probes |
| Flash manufacturer / device | `46` / `4018` | Values printed by esptool; the memory vendor's full part number is not established |
| Flash type in eFuse | Quad, four data lines | eFuse-reported Flash configuration |
| Flash voltage in eFuse | 3.3 V | eFuse-reported voltage configuration |

Flash capacity, PSRAM capacity, and runtime usable memory are different quantities. This result does not imply 24 MB of interchangeable runtime RAM or establish that all PSRAM has been initialized successfully.

### 6.2 Part Number Interpretation

Chip and module names are different. The [ESP32-S3 chip datasheet, Table 1-1](https://documentation.espressif.com/esp32_s3_datasheet_en.pdf) lists `ESP32-S3R8` with 8 MB of in-package Octal SPI PSRAM and a 3.3 V memory interface. The probe's embedded PSRAM information is consistent with this specification; esptool itself printed the generic chip description shown above rather than a complete commercial module ordering code.

Espressif's [ESP32-S3-WROOM-1 / WROOM-1U datasheet, Tables 1-1 and 1-2](https://www.espressif.com/sites/default/files/documentation/esp32-s3-wroom-1_wroom-1u_datasheet_en.pdf) includes module variants matching the detected capacities:

| Official module part number | Flash | PSRAM | Identification status |
| --- | --- | --- | --- |
| ESP32-S3-WROOM-1-N16R8 | 16 MB, Quad SPI | 8 MB, Octal SPI | Matches detected capacities; not confirmed as this device's module |
| ESP32-S3-WROOM-1U-N16R8 | 16 MB, Quad SPI | 8 MB, Octal SPI | Also matches; not confirmed as this device's module |

These are examples of matching specifications, not a unique identification of the enclosed module. The earlier N8R8 examples matched the advertisement only and are superseded as the capacity baseline by the probe results. The exact module ordering code is not required to continue development with the documented wiring and detected memory specification.

The official [`esptool flash-id` documentation](https://docs.espressif.com/projects/esptool/en/latest/esp32s3/esptool/basic-commands.html#read-spi-flash-id-flash-id) describes Flash identification. PSRAM initialization, usable capacity, and stability still need firmware-level validation.

## 7. Remaining Hardware Checks

1. Verify successful initialization, usable capacity, and stability of the reported 8 MB PSRAM. Flash identification has already detected 16 MB twice; retain the advertisement discrepancy in the hardware record.
2. Establish a reproducible build profile, including the Arduino core version and runtime USB settings. Bundled library metadata alone does not identify the complete original build environment.
3. Validate application-level USB message reception and reconnection using the chosen firmware build settings. USB enumeration and ROM-loader diagnostics already work on the physical device.
4. Validate display initialization, inversion, rotation, offsets, and backlight behavior with a small on-device display check.
5. Validate GPIO5 touch sensing before assigning user interaction behavior.
6. Measure memory use, refresh performance, and animation playback on the actual device before setting performance acceptance targets.

## 8. Implications for Requirements and Design

The package provides enough display driver and wiring information to plan hardware integration without requesting another complete schematic or requiring the original compiled firmware.

The new application can reuse the documented board configuration while keeping source adapters and message scheduling independent of the hardware. The user subsequently selected ESP-IDF with its integrated FreeRTOS for the new firmware; the supplied Arduino code remains a board configuration reference.

Requirements analysis, the display message model, and independent Windows-side work can continue while the remaining hardware checks are completed.
