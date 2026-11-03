# Initial Hardware Validation

Date: 2026-11-03

Status: Minimal USB demo flashed and verified on the physical ESP32-S3.

## 1. Device and Deployed Image

The device enumerated on COM6 as USB VID:PID `303A:1001`. Esptool reported
ESP32-S3 revision v0.2, 16 MB Flash, and 8 MB embedded PSRAM. Secure Boot and
Flash Encryption were disabled. No eFuses were programmed.

The deployed build uses ESP-IDF 6.1, LVGL 9.3.0, Nanopb 0.4.9.1, 16 MB Flash
configuration, and ST7789 at 27 MHz SPI mode 3. The demo does not enable PSRAM.

| Image | Flash address | Write result |
| --- | --- | --- |
| Bootloader | `0x00000000` | Written and hash-verified |
| Partition table | `0x00008000` | Written and hash-verified |
| Application | `0x00010000` | Written and hash-verified |

Application file: `firmware/build/info_tv.bin`, 484608 bytes.

Application SHA-256:

```text
C81C0179CB1AF96BEA12C65B5DD35B31B4ADCD2425EE8DD179503F1AF3E269AD
```

## 2. Original Firmware Backup

Before writing, all 16777216 bytes of Flash were read successfully into:

```text
.local/device-backups/esp32s3-before-demo-20261103-170933.bin
```

A neighboring `.bin.json` records file length, SHA-256, port, security state,
and capture time. The backup SHA-256 is:

```text
F5FB645E74464F6E583345AD7B49F7DF183F7308B3C2B9CEAC8CA735CDFE9A4E
```

Backups and local validation evidence are excluded from version control.
The backup remains on this computer; it is not bundled with source checkouts.
It contains the device's original application and stored configuration.

Recovery reference, **not executed**: stop the host, confirm the same board and
current port, then restore the full image with the IDF environment's esptool:

```powershell
python -m esptool --chip esp32s3 --port COM6 --baud 460800 write-flash --flash-mode keep --flash-freq keep --flash-size keep 0x0 .local/device-backups/esp32s3-before-demo-20261103-170933.bin
```

## 3. Observed Results

| Check | Evidence | Result |
| --- | --- | --- |
| Panel and backlight initialization | User saw INFO TV and text | Passed |
| Default screen direction | User confirmed correct orientation | Passed |
| Native USB protocol | Actual Hello, snapshot Accepted, ongoing heartbeats | Passed |
| HTTP-to-device task flow | Production FastAPI service and the script now located at `demos/demo_task.py`, 0..100% | Passed |
| Visible card feedback | Actual card/revision Presented after panel DMA completion | Passed |
| Completion notice | Device returned independent Accepted/Presented | Passed |
| Notice end and overview restoration | User confirmed the second replay switched normally after approximately five seconds | Passed |
| Host process restart | New service session and fresh overview synchronized | Passed |
| Powered serial reconnection | Four-second injected I/O outage with device still powered | Passed |
| Offline state recovery | Latest overview restored, both recovered cards reported Presented | Passed |
| No historical popup replay | One completion notice before outage; still one afterward; offline completion marked `skipped_offline` | Passed |

## 4. Recovery Test Method and Evidence

A local validation harness used the production `ServiceRuntime`, `TaskService`,
`DeviceSession`, and `SerialTransport`. Its wrapper injected an I/O error and
blocked reopen for four seconds. The session remained the sole owner of port
closure and reopening. The physical USB cable stayed connected and powered.

The test completed one task and waited for notification restoration, injected
the outage, accepted a newer revision and a second completion while offline,
then waited for automatic reconnection and both snapshot cards to become visible.
The service session and device boot identity stayed unchanged.

Recorded outcome: two successful serial opens, two snapshots, two recovered cards,
and exactly one notification. This verifies powered software-connection recovery;
it does not claim a physical cable removal/reinsertion test.

Local evidence files:

- `.local/hardware-validation/first-demo.json`
- `.local/hardware-validation/replayed-demo.json`
- `.local/hardware-validation/usb-recovery.json`
- `.local/hardware-validation/final-service.json`

The temporary recovery harness is retained beside these files. It must run with
the normal service stopped, because the service exclusively owns the serial port.

## 5. Current Demo and Remaining Evaluation

After validation, the production host was started as a hidden background process,
listening only at `http://127.0.0.1:8765`. The final task is `Demo validated` with
100% progress and confirmed Accepted/Presented feedback. This is a manually
started process, not an installed OS service or an autostart configuration.
Process metadata and logs are under `.local/run/`.

Detailed RGB/brightness calibration, stack/heap headroom, refresh/animation
performance, physical hot-plug/power-cycle scenarios, PSRAM, and touch input remain
outside this initial validation. Linux/macOS and Wi-Fi/BLE have not been exercised.
