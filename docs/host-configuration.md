# Host YAML configuration reference

The host reads one UTF-8 YAML file, selected explicitly or discovered in the
current working directory. From the repository root:

```powershell
cargo run --manifest-path host/Cargo.toml --locked -- serve --config host/info-tv.example.yaml
```

Copy [the example configuration](../host/info-tv.example.yaml) for local use.
Its weather mapping is commented out; uncomment and edit it to enable retrieval.
Settings are read once at startup; restart the service after editing the file.
Without `--config`, `serve` and `ports` look for `info-tv.yaml` in the current
working directory. A missing default file uses built-in defaults. An explicit
missing file or an invalid selected file is an error.

## Complete example

This example enables automatic serial discovery, Windows lock following, and Shanghai weather. Shanghai
is an example location, not a built-in default.

```yaml
serial_port: auto
usb_vid: 0x303A
usb_pid: 0x1001
http_port: 8765
completed_retention_seconds: 300
lock_action: deep_sleep
unlock_poll_seconds: 5

weather:
  location: Shanghai
  latitude: 31.2304
  longitude: 121.4737
  refresh_seconds: 900
  retry_seconds: 60
  valid_for_seconds: 1800
```

## Top-level fields

All top-level fields are optional. Omitting a field uses the default below.

| Field | Type | Default | Meaning and allowed values |
| --- | --- | --- | --- |
| `serial_port` | String | `auto` | Nonempty serial device path or the literal `auto`. Examples: `COM6`, `/dev/ttyACM0`, `/dev/cu.usbmodem...`. Automatic mode selects exactly one port matching both USB IDs. |
| `usb_vid` | Integer | `0x303A` | USB vendor ID for automatic discovery, from 0 to 65535 inclusive. Accepts an unquoted hexadecimal or decimal integer. Ignored when `serial_port` is an explicit path. |
| `usb_pid` | Integer | `0x1001` | USB product ID for automatic discovery, with the same range and notation as `usb_vid`. Ignored when `serial_port` is an explicit path. |
| `http_port` | Integer | `8765` | HTTP listening port, from 1 to 65535 inclusive. The bind address remains `127.0.0.1`. |
| `completed_retention_seconds` | Integer | `300` | Seconds to retain a completed or interrupted task before removing its card. Must be at least 1; no configured upper limit. Zero does not disable cleanup. |
| `lock_action` | String | `none` | Windows only when enabled. `none` leaves the device running; `screen_off` turns off the backlight; `deep_sleep` sleeps the main CPU and USB controller, with ULP touch wake and a 15-second preview while locked. |
| `unlock_poll_seconds` | Integer | `0` | Seconds asleep between silent unlock probes, from 0 to 3600 inclusive. Zero disables timer wake. Effective only with `lock_action: deep_sleep`; ignored for other actions. Startup and USB reconnection add to this interval. |
| `weather` | Mapping or `null` | `null` | Enables automatic Open-Meteo retrieval when a valid mapping is supplied. Omit it or use `null` to disable automatic retrieval; manual weather API/CLI commands remain available. |

### Serial selection

The default USB pair `303A:1001` matches this board's native USB Serial/JTAG
interface. Other ESP32 devices can share it; the existing protocol handshake
checks compatibility after selection. These fields select a device and do not
change its USB identity or firmware.

With no matching port or multiple matches, the host remains offline and retries
while continuing to serve its HTTP API. Discovery runs again on reconnect, so
an automatically selected device can return under a different COM number. Use
an explicit `serial_port` if several devices match.

Inspect candidates using the same file, without opening a serial connection:

```powershell
cargo run --manifest-path host/Cargo.toml --locked -- ports --config host/info-tv.example.yaml
```

### Follow Windows session locking

Set `lock_action: screen_off` or `lock_action: deep_sleep` and restart the host.
A hidden Windows PowerShell helper queries the calling session once per second
through `WTSQuerySessionInformationW` (`WTSSessionInfoEx`). It checks the initial
state before the USB handshake, so starting or reconnecting while locked also
applies the configured policy. A touch-wake boot retains its firmware preview.
Only the host's own Windows session is monitored.
This requires an interactive Windows session with Windows PowerShell and
`Add-Type` available. Enabling it on other platforms fails at service startup.

The saved `brightness_percent` remains the user's setting. With `screen_off`,
the effective target is zero while locked. Manual brightness changes are saved
for unlock without illuminating the display. Unlock restores the latest saved
target, including manual zero. USB communication continues in this mode.

With `deep_sleep`, update host and firmware together. The main CPU and USB
controller sleep, while the ULP RISC-V coprocessor samples TOUCH5 every 20 ms
with the touch peripheral's RTC domain powered. Three samples below the saved
baseline by at least 35 counts qualify a press, matching the existing board's
decreasing-value detection. The detector first establishes a baseline from
three stable samples in the sleep power state, so a power-induced idle shift
does not leave it waiting for a release indefinitely. A continuing stable
contact during sleep entry does not immediately wake it. This is deep sleep
with a running low-power touch detector, not removal of USB power.

Touching the top pad wakes the device. The waking press is consumed until
release; existing single/double-click actions resume afterward. The display
stays dark during startup and synchronization. If the host does not restore
brightness within five seconds after UI initialization, the device reveals its
normal offline screen using RTC-retained brightness. Task content is recovered
from the host, not retained in deep-sleep RAM.

The preview timer starts after a rendered frame is complete and the backlight
is enabled. While the host session remains locked, or unlock cannot be
confirmed, the device sleeps again after 15 seconds. Repeated touches, refreshes,
lock samples, and serial reconnections do not extend the preview. An unlock
confirmation received before expiry cancels it; the next lock sleeps immediately.
With the default `unlock_poll_seconds: 0`, unlocking Windows while the device is
already asleep does not wake it. A saved brightness of zero remains dark and skips the visible preview. Keep the host
running to confirm unlock; state sampling has up to roughly one second of delay.

For automatic unlock recovery, set `unlock_poll_seconds: 5`. An RTC timer wakes
the main CPU after each five-second sleep; ULP touch detection remains enabled.
The backlight stays off while USB reconnects and the host sends a fresh policy.
A confirmed unlock restores the current user brightness and keeps the device
awake. A confirmed locked state immediately returns it to sleep without a visible
preview. Without a host response, a silent probe waits at most five seconds from
application startup before sleeping again. A touch during a probe instead starts
the same 15-second visible preview. Thus five seconds is the sleep interval,
not an upper bound on unlock latency: startup, USB reconnection, and the host's
session sampling also take time. Repeated main-CPU/USB wakeups consume more power
than touch-only sleep; standby current has not been measured.

Update host and firmware together before enabling polling. The host requires
the `unlock_polling` firmware capability and verifies the echoed interval. It
configures power policy before brightness on capable firmware, so a timer probe
cannot illuminate the backlight before unlock confirmation.

`info-tv brightness` and device status report `effective_brightness_percent`
and `screen_off_for_lock` alongside the saved target and device Applied feedback.
The reported brightness target stays nonzero in deep-sleep mode when that is
the user's setting; power policy separately controls sleep. `lock_action`,
`session_locked`, `unlock_poll_seconds`, and `power_delivery` describe the requested policy and its
configuration acknowledgment. Applied policy is not proof of sleep entry or
physical power consumption. The host continues accepting tasks while the USB
device sleeps and resynchronizes current state after touch wake.

Neither mode follows monitor timeout or computer sleep independently of session
locking. Failed or unsupported WTS queries surface
as service errors rather than being treated as unlocks. The helper is stopped
with the host.

The Windows API layouts and lock flags are documented in
[WTSINFOEXW](https://learn.microsoft.com/en-us/windows/win32/api/wtsapi32/ns-wtsapi32-wtsinfoexw)
and [WTSINFOEX_LEVEL1_W](https://learn.microsoft.com/en-us/windows/win32/api/wtsapi32/ns-wtsapi32-wtsinfoex_level1_w).
The ULP integration follows the installed ESP-IDF v6.1
[`ulp_riscv/touch` example](https://github.com/espressif/esp-idf/tree/v6.1/examples/system/ulp/ulp_riscv/touch).
The basic lock/touch/15-second-preview/unlock sequence passed on the physical
board after the [sleep-baseline fix](hardware-validation.md#wake-failure-investigation-and-baseline-fix-2026-11-10).
Long-running touch drift/noise behavior and standby current remain unqualified.

The earlier uncommitted `screen_off_on_lock` boolean has been replaced by
`lock_action`; remove that key from local YAML because unknown keys are rejected.

### Completed and interrupted task retention

Retention starts when the current execution enters completed or interrupted state.
Updates that remain in either state do not extend the timer. Cleanup runs once per
second, so removal can occur shortly after the configured interval.
`running`, `waiting_input`, and `failed` tasks remain until manually closed or
replaced by a later execution. Accepted task state and original expiry times
are persisted in SQLite and restored after host restarts; downtime counts toward
retention. See [task lifecycle](host-lifecycle-weather.md#task-lifecycle)
for closure and later-execution behavior.

## Weather fields

When `weather` is a mapping, `location`, `latitude`, and `longitude` are required.
The other weather fields have defaults. Every time value below is in seconds.

| Field | Type | Default | Meaning and allowed values |
| --- | --- | --- | --- |
| `weather.location` | String | Required | Display label, such as `Shanghai`. Must be nonblank, printable, and at most 24 UTF-8 bytes. It does not determine coordinates or trigger geocoding. See [font coverage](font-conversion.md) for supported Chinese characters and display limits. |
| `weather.latitude` | Number | Required | Latitude from -90 to 90 inclusive. Must be finite; integer and decimal numeric values are accepted. |
| `weather.longitude` | Number | Required | Longitude from -180 to 180 inclusive, with the same numeric rules as latitude. |
| `weather.refresh_seconds` | Integer | `900` | Delay after a successful retrieval before the next attempt. Must be at least 60; no configured upper limit. |
| `weather.retry_seconds` | Integer | `60` | Delay after a failed retrieval before retrying. Must be at least 1; no configured upper limit. |
| `weather.valid_for_seconds` | Integer | `1800` | Maximum age allowed for the provider's current observation, from 1 to 3600 inclusive. Remaining validity is calculated from the provider's timestamp, rather than renewed on each fetch. |

Retrieval starts immediately when the configured service starts. Failed attempts
retain the last weather values without extending their expiry. Choose a refresh
interval shorter than the validity window if you want to reduce stale periods;
provider timestamps and availability still determine freshness.

While the updater is enabled, its next successful retrieval can replace
manually set or cleared weather.
Automatic retrieval does not generate official weather alerts. See
[automatic weather](host-lifecycle-weather.md#automatic-weather) for provider
behavior and attribution.

## Defaults, overrides, and validation

An empty mapping is a valid minimal configuration: it enables default serial
discovery and disables automatic weather retrieval.

```yaml
{}
```

A completely empty file is invalid because it is not a mapping. Unknown keys
are rejected at both the top level and inside `weather`. Missing required
weather fields, invalid ranges, and incorrect types fail before resources open.
Numeric fields must contain YAML numbers: for example, use `usb_vid: 0x303A`
and `http_port: 8765`, without quotes. Quoted numeric strings and booleans are
not accepted as numeric settings. Only `weather` accepts `null`.

Precedence is: explicit server CLI options, then YAML, then built-in defaults.
The server exposes `--serial-port` and `--http-port` overrides:

```powershell
cargo run --manifest-path host/Cargo.toml --locked -- serve --config host/info-tv.example.yaml --serial-port COM9 --http-port 9876
```

This keeps the file's weather and USB settings but uses COM9 and HTTP port 9876.
USB filters have no effect while COM9 is selected explicitly. HTTP client
commands do not read this YAML; use `--url http://127.0.0.1:9876` before the
client command to select that service. See the [CLI guide](host-cli.md).
