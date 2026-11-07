# Device brightness control

Date: 2026-11-06

Status: Implemented in the host API, shared protocol, and ESP32-S3 backlight
driver. Desktop checks and a firmware build passed. The latest firmware was
[flashed on 2026-11-06](hardware-validation.md#7-companion-weather-and-alert-firmware-deployment)
and returned Applied feedback at 100%. Actual panel brightness and PWM behavior
still require physical validation.

## Local API

Set an absolute level through `PUT /v1/device/settings`:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8765/v1/device/settings `
    -Method Put -ContentType application/json `
    -Body '{"brightness_percent":30}'
```

Query it through `GET /v1/device/settings`. `GET /v1/device` also includes the
same object under `settings`.

The request requires one integer `brightness_percent` in 0..100. Zero switches
the backlight off; 100 is the maximum setting. Missing values, booleans, strings,
fractions, null, extra fields, and out-of-range values return 422 without changing
the target. HTTP 202 means the host retained the request, including when offline;
it does not mean the device applied it.

Example while offline:

```json
{
  "brightness_percent": 30,
  "applied_brightness_percent": null,
  "delivery": {"state": "pending"}
}
```

Example after correlated device feedback:

```json
{
  "brightness_percent": 30,
  "applied_brightness_percent": 30,
  "delivery": {
    "message_id": "example-operation-id",
    "applied": true,
    "error": null
  }
}
```

`brightness_percent` is the latest target. `applied_brightness_percent` is the
last device-reported applied setting, which can differ while a newer request is
pending. Disconnection clears the reported value to unknown. A failed command
has `applied: false` and an error; the previous reported setting remains separate.
The latest settings outcome survives eviction from the bounded general delivery
history. Rapid unsent requests coalesce to the latest target.

On first use the host starts with target 100. The Rust host persists accepted
targets, including zero, in SQLite and restores them on restart and reconnect.
Device Applied feedback is obtained again after each connection. The firmware
initializes at 100 before host synchronization; device NVS persistence is not
added. Update both host and firmware: discovery requires the new
`Hello.brightness_control` capability.

## Device behavior

The [shared protocol](device-protocol.md#7-device-brightness-settings) adds an
independent `DeviceSettings` command. It uses the existing session, operation
identity, retry, and framing rules. Discovery, snapshot acceptance, and brightness
application complete before the host reports the device online.

The UI task applies an 8-bit, 4 kHz LEDC output on GPIO2, matching the board's
active-low backlight circuit. Duty is `round((100 - percent) * 256 / 100)`;
the installed ESP-IDF driver supports the 0..256 duty range. Endpoint 0% therefore
outputs continuous high (off), and 100% continuous low (on). Intermediate levels
are control settings, not calibrated percentages of perceived brightness.

After a successful PWM update, the device sends `ACK_STAGE_APPLIED` with the
requested setting. A driver failure sends `ERROR_CODE_HARDWARE`. An Accepted
reply alone cannot complete a settings operation, and settings never generate
Presented. The host checks operation identity, field presence, and the echoed
value before recording application. A lost reply retries the same absolute
setting with the same identity.

Brightness settings do not consume task or notification slots or reset page
rotation. At zero, USB, heartbeat, task updates, and local rendering continue.
The device withholds new Presented acknowledgments while the backlight is off;
when enabled, only content still selected for display can receive presentation
feedback. A notification that never becomes visible can expire without Presented.

## Verification

The historical Python checks below precede the Rust replacement. Current
restart and correlated-feedback tests are recorded in [Rust host validation](rust-host-validation.md).

- 52 Python tests passed, including strict API validation, offline zero, request
  coalescing, mismatched/absent feedback, application failure, retry identity,
  settings history retention, capability checks, and reconnect restoration.
- Two of those tests connect the real HTTP service to the native C++ protocol
  bridge. Brightness-off task admission and presentation after enabling are
  covered. The bridge simulates PWM success; it does not operate real hardware.
- Four native CTest cases passed, including setting bounds, required presence,
  session admission, zero-value codec round trips, and unchanged page generation.
- Static type analysis and generated Python/Nanopb binding checks passed.
- The ESP-IDF v6.1 firmware build passed. The app is 706,128 bytes, with 33% of
  the existing 1 MiB application partition remaining. Maximum generated envelope
  size remains 4045 bytes within the 4096-byte payload bound.

Physical follow-up: verify backlight off/on endpoints, an intermediate level,
return from zero without unplugging, and device recovery on the actual panel.
No optical brightness measurement or flicker validation is claimed by these tests.
