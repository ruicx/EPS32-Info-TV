# Host Task Lifecycle and Automatic Weather

Updated: 2026-11-07

## Configuration

See the [YAML field reference](host-configuration.md) for a complete table of
settings, defaults, allowed values, and override rules.

The service accepts an explicit UTF-8 YAML path or discovers `info-tv.yaml` in
the working directory. Run from the root:

```powershell
cargo run --manifest-path host/Cargo.toml --locked -- serve --config info-tv.yaml
```

Copy and edit [the example](../host/info-tv.example.yaml) as `info-tv.yaml`
for local use; uncomment its weather mapping to enable retrieval. The
default `serial_port: auto` selects a single USB candidate using `usb_vid` and
`usb_pid` (defaults `303A:1001`); omitting these keys retains those defaults.
Use `info-tv ports --config host/info-tv.example.yaml` to inspect candidates or set
an explicit port such as COM6. See [serial discovery](host-cli.md#start-and-connect)
for ambiguity handling, shared USB IDs, and reconnect behavior.
`--serial-port` and `--http-port` override their YAML values. The original
`info-tv --serial-port COM6` command remains valid. Weather requests depend on
the selected configuration, including working-directory discovery.
Unknown keys, invalid ranges, and malformed YAML fail before resources open.
Configuration is read at startup; restart the process after editing it.

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

USB IDs must be unquoted hexadecimal or decimal integers from 0 to 65535.
Explicit serial paths bypass the USB filters. Restart after configuration edits.

Omit `weather`, or set it to `null`, to disable retrieval. Coordinates identify
the requested location; the label is only display text and is not geocoded.
Shanghai is explicit configuration, not inferred location. The English label
fits the currently bundled display font. Other labels must fit 24 UTF-8 bytes.
Refresh must be at least 60 seconds, retry at least one second, and validity
between one and 3600 seconds. The service still binds exclusively to loopback.

## Task Lifecycle

The accepted default policy is:

- `completed` and `interrupted`: remove after five minutes from the transition
  into either state. Updates that remain in these states and duplicate requests
  do not reset the timer.
- `running`, `waiting_input`, and `failed`: retain until explicitly closed or
  replaced by a source update. Silence does not establish failure or completion.
- All current cards can be closed manually with `DELETE /v1/tasks/{card_id}`.
  Obtain the service-assigned identity from `GET /v1/tasks`. A repeated close
  returns `removed: false`; successful admission returns `removed: true`.

Cleanup runs once per second and before admitting an event. Closing immediately
releases one of the eight host slots, including while the device is offline.
The host drops unsent related notifications and queues an authoritative snapshot.
An accepted HTTP response does not establish that the device applied removal.
The next reconnect snapshot also excludes removed cards.

The host remembers the latest 256 retired task/conversation identities. Within
that window, retries remain duplicates, older updates remain stale, and higher
sequence updates for a closed run return `outcome: closed` without reviving it.
A conversation can return with a new `task_id` and greater `run_sequence`; it
receives a new card identity after retirement. A standalone task needs a new
task ID. Current task state and bounded replay/closure protection are persisted in
SQLite and restored after a host restart. Protection ends after the relevant
retired identities are evicted; this is not an unbounded history.

The paired firmware change cancels active and queued notifications related to
cards missing from the replacement snapshot. Unrelated notices and weather alerts
remain. Update firmware for these cancellation semantics; older firmware can
replace the overview but may finish an already accepted task notification.

## Automatic Weather

The updater fetches at startup, then every 15 minutes by default. An HTTP or data
failure retries after one minute without stopping the service or replacing the
last valid data. Requests have a ten-second timeout. The HTTP client honors
environment proxy settings, including SOCKS, and closes on application shutdown.

[Open-Meteo](https://open-meteo.com/) supplies model-based current temperature,
WMO weather condition, and today's minimum/maximum. These are model values, not
station observations or official hazard alerts. Data attribution: Open-Meteo,
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The free endpoint is
for non-commercial use; see its [terms](https://open-meteo.com/en/terms).
Fields and WMO mappings follow the [official API documentation](https://open-meteo.com/en/docs).

The updater requests Celsius, UTC Unix timestamps, and the location's automatic
timezone for daily values. Temperatures round to integer degrees for the existing
device schema. Unknown weather codes use the existing unknown condition.
Missing values, invalid ranges, stale timestamps, and far-future timestamps are
rejected. Validity is computed from the source timestamp, so retrieving the same
old model output does not restart a full freshness period. Network failures leave
existing expiry intact; reconnect never restores expired weather as fresh.

`GET /v1/weather/updater` reports provider, location, last attempt, last success,
source timestamp, and latest retrieval error. `GET /v1/weather` continues to
report retained weather freshness and separate device delivery feedback.
Manual PUT/DELETE weather endpoints remain available; automatic retrieval may
replace their result at the next successful refresh. It does not change the
independent weather-alert API or synthesize warnings from a thunderstorm icon.

## Verification and Limits

The following results describe the historical Python implementation. Current
Rust checks and remaining qualification are in [Rust host validation](rust-host-validation.md).

Verification completed on 2026-11-07:

- Host: 128 pytest cases passed on both Python 3.12 and 3.14, including the native bridge integration.
- `uv run ruff check --config pyproject.toml . ../scripts ../demos`: passed.
- `uv run ty check . ../scripts ../demos`: passed.
- `scripts/generate_protocol.py --check`: passed; wire schema unchanged.
- Native firmware: four CTest cases passed, including presentation and screen.
- ESP-IDF 6.1 build: passed; `info_tv.bin` is 872576 bytes, with 17% app-partition headroom.
- `git diff --check`: passed.
- Wheel and source distribution builds passed, including version preservation when rebuilding outside Git.

Desktop regression checks cover automatic retention without subsequent events,
capacity reuse across more than eight runs, closed-run late events, conversation
reopening, snapshot removal/reconnect, notification cancellation, YAML validation,
CLI overrides, retrieval failure/recovery, source-age validity, polling startup,
retry, and HTTP-client shutdown. The native C++ presentation test checks both
active and pending orphaned notices while keeping an unrelated notification.
The HTTP-to-C++ bridge verifies removal-snapshot acceptance and continued online
state. Type checking and generated protocol consistency are checked separately.

A live Shanghai fetch through the production updater succeeded on 2026-11-07
local time, without opening a serial port. This does not establish physical
display behavior. Firmware build and desktop checks are separate from flashing;
this revision has not been flashed or visually validated on the physical board.
