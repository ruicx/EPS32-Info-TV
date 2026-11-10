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

## 6. Multi-conversation Firmware Deployment

Date: 2026-11-05. The user explicitly requested flashing the tested revision.

The same ESP32-S3 was confirmed on COM6, USB VID:PID `303A:1001`, MAC
`58:e6:c5:68:6c:70`. The previous info_tv host was stopped after its task and
device state were captured locally. Before writing, addresses `0x0..0x10ffff`
were read into `.local/device-backups/info-tv-before-multi-20261105.bin`:

- Length: 1,114,112 bytes, including the bootloader, partition table, and complete
  1 MiB app partition. This is a region backup, not a new full-Flash backup.
- SHA-256: `83f5d8119b69674cf09355e06c1bcc932f17b8fddd2813bb6a649339631f6418`.
- The previous 484,608-byte app within the backup matches the earlier deployed
  application SHA-256 recorded above. The original full-Flash backup remains intact.

Esptool 5.6.0 wrote and hash-verified all three images:

| Image | Address | Length |
| --- | --- | --- |
| Bootloader | `0x0` | 21,120 bytes |
| Partition table | `0x8000` | 3,072 bytes |
| Application | `0x10000` | 682,768 bytes |

Application SHA-256:
`e11016545ae2c5c1076e7bfd2fbc8568bc842afb60309d9c02bc29624cacd7b4`.
The device was hard-reset after writing. No eFuses were programmed.

The updated host was restarted as a hidden background process at
`http://127.0.0.1:8765`, and the device reached `online` with no reported error.
The new eight-card capability handshake succeeded. The five-conversation demo
then produced five individual card Presented acknowledgments, including the
second overview page, and two independent important-notification Presented
acknowledgments. Presented records actual UI refresh/DMA completion. On the same
date, the user explicitly confirmed (English translation): "Physical text, layout,
and page rotation are normal." This validates
the observed text, layout, and page rotation; precise interval measurements and
arbitrary Chinese glyph coverage are not established by that confirmation.

The running host currently retains these five **simulated** conversations:
Codex Message API (waiting input), agy Login flow (failed), Codex Unit tests
(running), agy Documentation (running), and Codex UI review (running).
These do not represent real agent-client integrations. The earlier single demo
card is preserved in the pre-flash JSON record rather than restored to this demo.

Local evidence:

- `.local/hardware-validation/before-multi-conversation-flash.json`
- `.local/hardware-validation/multi-conversation-flash.log`
- `.local/hardware-validation/multi-conversation-demo.log`
- `.local/hardware-validation/multi-conversation-device.json`
- `.local/device-backups/info-tv-before-multi-20261105.bin.json`
- `.local/run/host-process.json` and `host-multi.stdout.log` / `host-multi.stderr.log`

The new UI's desktop screenshots and test scope are recorded in
[Multi-conversation Validation](multi-conversation-validation.md).

## 7. Companion, weather, and alert firmware deployment

Date: 2026-11-06. The user connected the device and requested flashing the latest
tested firmware, commit `aabb11d`.

The ESP32-S3 was confirmed on COM6 with USB VID:PID `303A:1001` and MAC
`58:e6:c5:68:6c:70`. The verified prior project host processes were stopped after
saving their device/task state. Addresses `0x0..0x10ffff` were backed up to
`.local/device-backups/info-tv-before-weather-20261106.bin` before writing:

- Length: 1,114,112 bytes, including bootloader, partition table, and the complete
  1 MiB app partition. Earlier region and full-Flash backups remain intact.
- SHA-256: `89C46A4371125B9EBFB3E0497D90BC5F8982C0C2EB90AF62D1EF2072B276A3D1`.

Esptool 5.6.0 wrote and hash-verified the following images with DIO, 80 MHz,
16 MiB Flash settings, then hard-reset the device. No eFuses were programmed.

| Image | Address | Length |
| --- | --- | --- |
| Bootloader | `0x0` | 21,120 bytes |
| Partition table | `0x8000` | 3,072 bytes |
| Application | `0x10000` | 872,624 bytes |

Application SHA-256:
`9B3EBBCA825962B7FB055668C1C3581609B8DE2DF4ECE19AC921A7E04A40618C`.

The updated production host was started hidden at `http://127.0.0.1:8765`,
using COM6. Launcher PID was 30928; server PID was 49024 at deployment. These
are observations, not stable process identifiers. The device reached `online`
with no reported error, requiring the eight-card, task-icon, brightness,
weather, and weather-details capability handshake. Brightness 100% returned
Applied feedback. This confirms driver application, not optical calibration.

Five simulated Codex/agy cards each returned Accepted and actual device
Presented feedback, exercising both three-row overview pages. Two task-state
notifications also returned Presented. Synthetic weather `Shanghai`, 23 degrees
Celsius, daily range 18..26, was accepted independently of the cards.

A separate orange `TEST Rain` warning from `Demo` was submitted with a 60-second
lifetime and detail `Demo only; no real warning.` Its important notification
returned Accepted and Presented. After the notification interval, the host still
reported an active alert. The test alert was explicitly withdrawn; the clear
was accepted, and synthetic clear weather was restored and accepted. Final
device state was `online`, alert `unavailable`, brightness Applied at 100%, and
all five simulated task cards retained. Weather and warning values are fixtures,
not actual observations or real alerts.

Presented confirms firmware UI refresh/DMA completion. Visual appearance,
animation smoothness, physical warning-marker behavior, and panel brightness
still await user observation; no new visual confirmation is recorded here.

Local evidence:

- `.local/hardware-validation/before-weather-flash.json`
- `.local/hardware-validation/weather-backup.log` and `weather-flash.log`
- `.local/hardware-validation/weather-conversations-demo.log` and `weather-demo-tasks.json`
- `.local/hardware-validation/weather-alert-request.json`, `weather-alert-presented.json`,
  and `weather-alert-after-notification.json`
- `.local/hardware-validation/weather-deployment-device.json`
- `.local/device-backups/info-tv-before-weather-20261106.bin.json`
- `.local/run/host-process.json` and `host-weather.stdout.log` / `host-weather.stderr.log`

See [Weather UI validation](weather-ui-validation.md) for the API and desktop
scope. The background host is manually started, not an installed/autostart service.

## 8. Header connection icon deployment

Date: 2026-11-06. During the connected-device UI trial, connection status moved
from the weather footer to the header, freeing a separate weather line. Source:
`aabb11d` plus the uncommitted header/weather-line UI changes. The implementation
and actual desktop captures are in [Header connection UI](header-connection-ui.md).

The same ESP32-S3 MAC `58:e6:c5:68:6c:70` was verified on COM6. Before writing,
the current device/task state was saved and the project host stopped. The
`0x0..0x10ffff` region backup is
`.local/device-backups/info-tv-before-header-20261106.bin` (1,114,112 bytes),
SHA-256 `C83274D765C9806DBC816C5B24F2CDAB0C66233D41C047E34647EEB23F7DED88`.
Previous backups remain intact.

Esptool wrote and hash-verified bootloader (21,120 bytes at `0x0`), partition
table (3,072 bytes at `0x8000`), and application (872,608 bytes at `0x10000`),
using the same DIO/80 MHz/16 MiB settings, then hard-reset the device. No eFuses
were programmed. Application SHA-256:
`B14058BBC45FA29301D0185C0D8A052DB1E62497FD7EE83161A105EE7E03B760`.

The production host was restarted hidden on the same loopback URL/COM6. COM6
was temporarily held during HTTP state restoration, so the five saved demo
conversations were admitted while offline and old transition notices were not
replayed. The temporary port holder was disposed before normal synchronization.
The existing synthetic Shanghai weather, current temperature, and daily range
were restored with reduced remaining freshness rather than a renewed lifetime.

After release, the device reached `online` without a remaining error. All five
cards returned actual device Presented feedback through the recovery snapshot;
the weather snapshot was accepted. The test alert remained withdrawn. Launcher
PID was 1136 and server PID 34764 at deployment; these are observations only.
Physical icon readability and layout still await user confirmation. No physical
Bluetooth or Wi-Fi path was tested or added.

Additional local evidence:

- `.local/hardware-validation/before-header-flash.json`
- `.local/hardware-validation/header-backup.log` and `header-flash.log`
- `.local/hardware-validation/header-restored-admissions.json`
- `.local/hardware-validation/header-deployment-device.json` and `header-deployment-tasks.json`
- `.local/device-backups/info-tv-before-header-20261106.bin.json`
- `.local/run/host-process.json` and `host-header.stdout.log` / `host-header.stderr.log`

## 9. Weather label simplification

Date: 2026-11-06. The user agreed to remove redundant condition names such as
`Clear`. The daily range now sits directly below the current temperature, and
the bottom line is reserved for warnings. `Stale` and `Not set` remain visible
when applicable. This supersedes the condition/range placement in section 8.

Four native CTest targets and the ESP-IDF v6.1 build passed. Source remains
`aabb11d` plus the uncommitted header/weather UI changes. The same COM6 device
and MAC were verified; its `0x0..0x10ffff` region was backed up to
`.local/device-backups/info-tv-before-weather-clean-20261106.bin` (1,114,112 bytes),
SHA-256 `ED9C8C16A86380194349966A33D32F9D089EC86536F1E017400300AEA8587EDD`.

Esptool wrote and hash-verified the bootloader, partition table, and the new
872,368-byte application, using the same addresses and DIO/80 MHz/16 MiB
settings. No eFuses were programmed. App SHA-256:
`326DC136CC431DB024EF66433ED7A1651A435B1BB4D99F9D26B1ED42F472B539`.

The host was restarted hidden with the same silent offline restoration used in
section 8. All five demo cards returned device Presented feedback; the synthetic
Shanghai weather/range was restored with reduced freshness and accepted in the
snapshot. Final state was `online` with no remaining error. Launcher PID was
36480 and server PID 11856 at deployment. The alert remained withdrawn. Visual
confirmation of the revised layout remains pending.

Evidence uses `.local/hardware-validation/before-weather-clean-flash.json`,
`weather-clean-backup.log`, `weather-clean-flash.log`,
`weather-clean-restored-admissions.json`, `weather-clean-deployment-device.json`,
and `weather-clean-deployment-tasks.json`. Backup metadata is adjacent to the
image. Process metadata remains `.local/run/host-process.json`; current logs are
`host-weather-clean.stdout.log` and `host-weather-clean.stderr.log` there.

## 10. ULP touch wake firmware deployment

Date: 2026-11-10. With explicit user authorization, the new firmware was flashed
to the ESP32-S3 on COM6, MAC `58:e6:c5:68:6c:70`, USB VID:PID `303A:1001`.
The chip reported revision v0.2 and USB-Serial/JTAG mode. Before writing, the
installed host was stopped and the complete 16 MiB Flash was read successfully.
The old and new partition tables were compared byte for byte and matched.

- Flash backup: `.local/ulp-deploy-20261110-083218/device-before.bin`,
  16,777,216 bytes, SHA-256
  `B305D822A403ED59371D53131D20959FDA0DFA2CC48EFD43EC3295446C726317`.
- New application: 4,710,752 bytes, SHA-256
  `1094C6C6C142090F05EC477151D04EEA22C800B29A75FBA8103FFF8455107F44`.
- Installed host: Windows x86-64 Release with the static MSVC runtime, SHA-256
  `20B96A63234EE5F78C0138337AB3A72CA54DC2AFABBA289E72EB9683FD73B4E2`.

Esptool v5.6.0 wrote and hash-verified the bootloader at `0x0`, partition table
at `0x8000`, and application at `0x10000`, then reset the device. The generated
flash arguments retained DIO, 80 MHz, and 16 MiB settings. NVS was not erased.
Flash logs are `device-backup.log` and `device-flash.log` in the deployment
directory; `deployment.json` records artifact identities.

The installed `C:\h\info-tv\info-tv.exe` and YAML were backed up before replacing
the executable and adding `lock_action: deep_sleep`. Existing Changsha weather
settings, brightness 20%, and the SQLite state directory were preserved. The
database, WAL, and SHM were copied after stopping the host. The replacement host
was started hidden with the same configuration and state paths; PID 54648 is
an observation, not a reusable identity. No startup registration was changed.

The actual device returned `online`, brightness Applied at 20%, and correlated
power-policy Applied for `deep_sleep` with `session_locked: false`. Both saved
cards recovered and received device Accepted and Presented feedback. The
completed card subsequently expired under the existing retention policy; the
remaining active card continued receiving Presented feedback. `last_error`
remained null. The serial library logged a stop-bit query warning, but the
protocol handshake and the device feedback above succeeded.

API evidence is saved as `before-device.json`, `before-tasks.json`,
`after-device.json`, `after-tasks.json`, `verified-device.json`, and
`verified-tasks.json` in the deployment directory. Host launch metadata and logs
are `host-process.json`, `host.stdout.log`, and `host.stderr.log` there.

The initial deployment established USB recovery, ULP preparation, and policy
configuration. Physical lock/touch/unlock behavior was subsequently checked
after the baseline fix below. Standby power consumption remains unmeasured.

### Wake failure investigation and baseline fix (2026-11-10)

The user subsequently confirmed that locking Windows puts the device to sleep,
but touching the top pad does not restore the display. The host log records USB
loss at `2026-11-10T01:12:01Z` and no later device reconnection. Port discovery
returns no matching port. This narrows the investigation to wake/startup rather
than confirming a backlight-only failure; the root cause is not yet established.

Automatic sleep was temporarily disabled in the installed YAML (`lock_action:
none`) and the same host restarted hidden, retaining its database and weather
configuration. The previous YAML and failed firmware were backed up under
`.local/ulp-wake-fix-20261110-091710`. USB power cycling has been requested from
the user because the sleeping device's USB controller is unavailable.

A temporary diagnostic build added ULP sample/error counters and a 30-second RTC
timer wake for recovery. It was subsequently flashed after USB power cycling.
The diagnostic image and ULP symbols are saved in that directory as
`diagnostic-firmware.bin` and `diagnostic-ulp-symbols.ld`; image SHA-256 is
`60852CF4DA219BB319C3360C25875B92AD5DCF6A733C45AA367F93F18F8DCD49`.
The first no-touch RTC dump showed `sampleCount: 1437`, `readErrors: 0`,
`baseline: 16611`, `lastSample: 16576`, and `armed: 0`. The old detector required
a reading less than 18 counts below the pre-sleep baseline before arming. The
35-count idle shift across the power transition therefore prevented arming even
though the ULP was sampling normally. The recorded values were added to the
native power test first; it failed at `shifted.armed` before the fix.

The detector now calibrates three stable samples in the sleep power state
before arming. It still requires three below-baseline samples to trigger wake.
The regression and all six native tests passed. A second physical no-touch
cycle yielded `sampleCount: 1436`, `readErrors: 0`, `releaseSamples: 3`,
`baseline: 16609`, `lastSample: 16604`, `armed: 1`, and `wakeTriggered: 0`:
the detector armed without a false wake. Two later diagnostic recovery checks
returned a timer wake rather than retained touch-trigger evidence; those checks
alone do not establish physical touch wake, despite the user's report of fast
display recovery. The diagnostic window was extended to 120 seconds during
the investigation to distinguish it from the requested 15-second preview.

The timer, diagnostic ULP counters, and repository sleep-probe example were
then removed. Probe source, raw RTC dumps, decoded counters, build output, and
flash logs remain under the investigation directory as local evidence.
The final touch-only application is SHA-256
`5BFFB9ADE75360DBBC23CFD2D4A1950ADB888377404F55B69F5E50A0641690EE`.
It was flashed and hash-verified, and the installed host was restored to
`lock_action: deep_sleep`. Device status was `online`, brightness Applied at
20%, power-policy Applied, and no device error. A final user-driven lock/touch/
unlock check then passed; unlike the diagnostic builds, this image has no timer
wakeup fallback.

The user confirmed all three final checks: touch restores the locked display,
the display sleeps again after roughly 15 seconds while Windows remains locked,
and unlocking during a second preview keeps the display awake. The host's
physical USB trace agrees: it disconnected on lock at `10:10:50.974 +08:00`,
reconnected after touch at `10:10:55.029`, and disconnected again at
`10:11:10.764`, approximately 15 seconds later. On another cycle, it returned
online with Windows still locked at `10:12:20.664`, then received unlock at
`10:12:24.137`. At `10:13:15`, it remained online, unlocked, at 20% brightness,
with current power-policy Applied and no device error.

The final application is 4,710,768 bytes and the ULP image is 374 bytes. The
new hardware-derived regression, all six native tests, firmware build,
rustfmt check, and whitespace check passed. Final API/task snapshots and
artifact identities are saved as `final-verified-device.json`, `final-tasks.json`,
and `final-validation.json`; session transitions are in `final-lock-trace.jsonl`
and `final-host.stderr.log`. Long-running touch drift/noise behavior and actual
standby current remain unqualified by this short physical test.
