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

This example enables automatic serial discovery and Shanghai weather. Shanghai
is an example location, not a built-in default.

```yaml
serial_port: auto
usb_vid: 0x303A
usb_pid: 0x1001
http_port: 8765
completed_retention_seconds: 300

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
