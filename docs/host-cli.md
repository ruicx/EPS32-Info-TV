# Host command-line interface

The `info-tv` command starts the service or calls the same HTTP API as producers.
Use the extracted Rust executable. From this repository, prefix each command
with `cargo run --manifest-path host/Cargo.toml --locked --` and omit the
`info-tv` command name. No Python environment is required.

## Start and connect

```powershell
info-tv serve
info-tv serve --config host/info-tv.example.yaml
info-tv serve --serial-port COM6 --http-port 8765
```

The original `info-tv --serial-port COM6` and `info-tv --config ...` forms remain
supported. Server CLI options override YAML settings. The service binds to IPv4
loopback and owns the serial port; client commands contact the running service
without opening the device themselves.

The default serial setting is `auto`, including when `serial_port` is omitted
from YAML. To inspect the available ports without starting the service or
opening any serial handle:

```powershell
info-tv ports
info-tv ports --config host/info-tv.example.yaml
info-tv serve --serial-port auto
```

`ports` outputs paths, descriptions, USB VID/PID, serial numbers, and a
`candidate` flag. Automatic selection requires exactly one port matching the
configured USB VID/PID. Defaults are `303A:1001`, as recorded for this board's
native USB Serial/JTAG interface. Configure a different identity in YAML:

```yaml
serial_port: auto
usb_vid: 0x303A
usb_pid: 0x1001
```

Both IDs are unsigned 16-bit integers (0..65535). YAML accepts hexadecimal
integers with a `0x` prefix or decimal integers; do not quote these values.
Omitted IDs retain the defaults. `ports --config ...` uses the same YAML filter
as `serve --config ...`; plain `ports` discovers `info-tv.yaml` in the current
working directory and otherwise uses built-in defaults. Explicit serial paths
bypass USB filtering.

This ID is shared by other ESP32 devices and does not prove that info_tv
firmware is installed; the existing protocol handshake checks compatibility.
With no match or multiple matches, the host stays offline, reports the reason,
and retries while continuing to serve its API. Use `--serial-port COM6` to
select a particular device or an adapter with a different USB ID.

Discovery runs again on every reconnect, so changing COM numbers after a
disconnect does not require restarting the service. Explicit paths remain
fixed. The actual selected path appears in service logs.

```powershell
info-tv status
info-tv --url http://127.0.0.1:9876 --timeout 10 status
info-tv --help
info-tv task submit --help
```

Client options `--url` and `--timeout` go **before** the command. Defaults are
`http://127.0.0.1:8765` and five seconds. HTTP client commands do not read server YAML
or use environment HTTP proxies. If the server uses a different HTTP port,
specify its URL explicitly.

## Tasks

```powershell
info-tv task submit --task-id build-1 --sequence 1 --state running --title "Build firmware" --progress-percent 20 --icon build
info-tv task submit --task-id build-1 --sequence 2 --state completed --title "Build firmware" --progress-percent 100
info-tv task list
info-tv task close <card_id>
```

Replace `<card_id>` with the identity returned by submission or listing. Closure
is idempotent and uses the card identity, rather than the producer's task ID.
Completed and interrupted cards also expire according to the configured retention policy.

`--source` defaults to `cli`. Use a unique `--task-id` for each execution and
increasing positive `--sequence` values for its updates. States are `running`,
`waiting_input`, `completed`, `failed`, `interrupted`, and `closed`. Submitting
`closed` retires the card immediately without a completion notification.
Optional display arguments include
`--detail`, `--progress-percent`, `--icon`, and `--context`.

For a conversation, supply `--conversation-id` and `--run-sequence` together,
plus optional `--conversation-title`. Increase the run sequence for each new
execution and give that execution a new task ID.

A new UUID event identity is generated for each submission unless `--event-id`
is supplied. To retry safely after a timeout, generate the UUID before the first
attempt and keep the UUID and **every submitted field** unchanged:

```powershell
$eventId = [guid]::NewGuid().ToString()
info-tv task submit --event-id $eventId --task-id build-2 --sequence 1 --state running --title "Build firmware"
```

The CLI never retries requests automatically. API acceptance does not imply
device presentation; inspect `task list` and `status` for delivery feedback.

## Weather, alerts, and brightness

```powershell
info-tv weather get
info-tv weather updater
info-tv weather set --location Shanghai --temperature-c 18 --condition cloudy --daily-low-c 12 --daily-high-c 20
info-tv weather clear
info-tv alert get
info-tv alert clear
info-tv brightness
info-tv brightness 30
```

Weather conditions are `unknown`, `clear`, `cloudy`, `rain`, `snow`, `storm`, and
`fog`. Daily low/high temperatures must be supplied together. Optional
`--valid-for-seconds` defaults to 1800, with the same bounds as the HTTP API.
Manual replacement or clearing does not disable the automatic updater; its next
successful retrieval can publish weather again. Weather and alerts are independent.
Brightness accepts an integer from 0 to 100; zero turns off the backlight.
To follow Windows lock/unlock automatically, set `lock_action: screen_off` in
the [host YAML](host-configuration.md#follow-windows-session-locking) and restart.
While locked, brightness commands update the saved target for unlock; the
effective target remains zero. Query output distinguishes the saved target,
effective target, lock override, and device-applied level.
Use `lock_action: deep_sleep` for ULP touch wake and a 15-second locked preview;
this requires updated firmware and disconnects USB while asleep. See the same
configuration guide for wake, offline, and unlock behavior.

To publish an alert, supply its source-selected identity, sequence, severity,
and remaining validity. This example is synthetic:

```powershell
$alertId = [guid]::NewGuid().ToString()
info-tv alert set --alert-id $alertId --sequence 1 --title "TEST rain" --source Demo --location Shanghai --severity yellow --valid-for-seconds 60 --detail "Synthetic preview only"
```

Retain `--alert-id` and increase `--sequence` for subsequent alert updates.
Severity choices are `blue`, `yellow`, `orange`, and `red`.

## Output and exit codes

Successful client commands write the API response as UTF-8-compatible JSON text
to standard output. Shell redirection and JSON consumers can read it directly:

```powershell
$tasks = info-tv task list | ConvertFrom-Json
```

Errors go to standard error. Exit code 0 means a successful HTTP response,
1 means a connection, HTTP, or response decoding error, and 2 means invalid CLI
usage or server configuration. HTTP error messages include the status and API
response, including validation details. Schema validation remains authoritative
in the service. Exit code 0 does not guarantee a task update was newly applied:
inspect `outcome` for duplicate, stale, or closed submissions.

Rust regression tests exercise the real CLI executable, Axum routes, durable
restart recovery, and offline hook retries. The native bridge covers the C++
protocol/presentation core separately; it does not validate physical display
behavior. See [Rust host validation](rust-host-validation.md).
