# Host-to-ESP32 Device Protocol

Status: Version 1 with eight-card overview extensions tested on desktop, firmware-built, and flashed on 2026-11-05. Five cards and two notifications returned actual device Presented feedback. The user confirmed physical text, layout, and page rotation; earlier detailed recovery evidence applies to the original demo.

Updated: 2026-11-06

The latest three-row companion/weather firmware was
[flashed on 2026-11-06](hardware-validation.md#7-companion-weather-and-alert-firmware-deployment).
Five simulated cards and a TEST weather notification returned actual device
Presented feedback; brightness 100% returned Applied feedback. The earlier visual
confirmation applies to the original overview. See
[Companion UI validation](companion-ui-validation.md),
[Brightness control](brightness-control.md), and
[Weather UI validation](weather-ui-validation.md) for scope and remaining checks.

## 1. Contract and Generation

The authoritative binary Protobuf contract is [device.proto](../protocol/device.proto).
Embedded capacities are in [device.options](../protocol/device.options). Producer
HTTP JSON is a separate contract, without device connection or layout fields.

Run `scripts/generate_protocol.py` to generate both bindings; `--check` verifies
the checked-in files. Python uses the official Protobuf runtime. Firmware uses
Nanopb 0.4.9.1, with bounded static strings/arrays and unmodified vendored runtime
sources plus license. Host dependencies and firmware components are locked.

## 2. Envelope and Operations

`Envelope` contains protocol version (currently 1), service-session identity,
message identity, and a typed operation `oneof`. Ordinary commands require
nonempty identities of at most 36 bytes. Pre-session Hello uses an empty session.
Host identities are UUID hex strings; device feedback IDs combine boot identity
and a boot-local sequence. Feedback explicitly refers to the original command.

| Operation | Direction | Meaning |
| --- | --- | --- |
| Hello | Both | Host requests discovery; device returns nonzero boot identity |
| Snapshot | Host to device | Validate and atomically replace the overview |
| CardUpsert | Host to device | Create or replace a card by identity/revision |
| Notification | Host to device | Independently admit a temporary presentation |
| DeviceSettings | Host to device | Apply an absolute device brightness setting |
| Weather | Host to device | Replace or clear independently retained weather |
| WeatherAlert | Host to device | Replace or clear one independent hazard alert, optionally notifying |
| Acknowledgment | Device to host | UI Accepted, first-refresh Presented, or settings Applied |
| Error | Device to host | Correlated rejection and diagnostic reason |
| Ping / Pong | Host / device | Current-session liveness |

Version 1 implements only `StatusView`: title, source/context labels, task-purpose icon, status text,
semantic tone, detail, and optional integer progress 0..100. Missing progress differs from zero. The
device chooses fonts, colors, and coordinates without recognizing producer names.

`View.icon` is a `TaskIcon` enum: generic task (0, also the default when omitted),
code (1), test (2), build (3), review (4), or deploy (5). Unknown values are rejected.
The producer API accepts the corresponding lowercase strings. Icon selection is
independent of execution state and participates in same-revision content equality.

Text/list/metric/media views, card removal, assets, Wi-Fi, and BLE remain future
extensions. Existing field numbers must remain stable; removed fields must be
reserved. Unknown operations, unsupported versions, invalid enums, and out-of-range
values are not admitted as valid display content.

## 3. USB Framing and Bounds

```text
0x00 | COBS(Protobuf payload || CRC32-IEEE little-endian) | 0x00
```

- Protobuf payload limit: 4096 bytes; delimiter-free encoded body limit: 4120 bytes.
- CRC matches Python zlib.crc32; the vector `123456789` yields `0xcbf43926`.
- Empty delimiter intervals are ignored. Invalid or excessive bodies are discarded.
- A zero delimiter restores collection after corruption, truncation, or boot noise.
- Reads may contain partial or multiple frames.
- Application logs use UART0; native USB is reserved for the protocol.
- COBS/CRC provides boundaries and corruption detection, not authentication.

Up to eight cards are retained. UTF-8 capacities excluding C terminators are:
title/source/context/status text 64 bytes, detail 160 bytes, identities 36 bytes, error detail
96 bytes. Strings containing NUL are rejected by the host API.
Shared compatibility input is under `protocol/test_vectors/`.
The generated worst-case envelope size is 4093 bytes, within the existing
4096-byte frame payload limit; the maximum eight-card snapshot is round-trip tested.

## 4. Sessions, Revisions, and Recovery

Host startup creates a new service-session identity; reconnect retains it.
Exchange Hello, send the current overview snapshot, and wait for UI Accepted.
Then send the current target brightness and wait for Applied before declaring
the connection online. Snapshots never contain notification history.
Device Hello now includes `max_cards: 8`; zero identifies older firmware without
the multi-conversation overview. The host refuses synchronization if capacity is
less than eight and reports that firmware must be updated. This makes the required
paired update explicit while keeping field numbers and protocol version stable.
The icon revision also requires `Hello.task_icons = true`; a missing/false value
identifies firmware that needs updating before this host synchronizes content.
Brightness control additionally requires `Hello.brightness_control = true`.
Persistent weather additionally requires `Hello.weather = true`. A snapshot can
include bounded weather values with remaining freshness, separate from cards.
Weather updates require a location, presence-aware integer temperature -100..100,
known condition enum, and remaining validity 1..3600000 ms. A fully empty Weather
clears the persistent area. Location capacity is 24 UTF-8 bytes. Retries retain
the original deadline; accepted duplicates never renew it. See the
[weather API and wire behavior](companion-ui-validation.md#weather-api).

Weather icons/ranges and hazard alerts additionally require
`Hello.weather_details = true` (6). Weather fields 5/6 are optional paired
`daily_low_c` / `daily_high_c`, each -100..100 with low <= high. Nanopb stores
these as signed 8-bit integers to keep the maximum snapshot within one frame.
`Envelope.weather_alert` (20) separately synchronizes one current alert after
the snapshot/brightness handshake, with its own validity in 1..86400000 ms.
An entirely empty alert clears it. Reconnect restores still-valid markers
without replaying notifications. See [weather and alert validation](weather-ui-validation.md)
for the full schema, HTTP contract, expiry, and notification rules.

Each card has an independent identity and increasing nonzero revision. Older
revisions cannot overwrite current state; equal revisions with conflicting content
are rejected. Retries retain operation identity. Firmware remembers 64 recently
accepted identities within the current service session, so retries do not reapply
snapshots or reset presentation. The host permits one command awaiting Accepted
or, for device settings, Applied.
Identity and semantic content, rather than byte-equal Protobuf, govern deduplication.

Snapshots validate all cards and unique identities before mutation. New sessions
clear old-session ordering and pending-event identities. Same-session snapshots
replace only the overview; already-admitted notices keep their local lifetime.
Card removal/tombstone semantics will be designed when removal is implemented.

## 5. Notifications and Timing

Notices carry an event identity separate from message identity, ordinary/important
priority, optional positive display duration, remaining start validity, and a view.
Defaults are 5/10 seconds; explicit durations must be 1..60000 ms. Capacity is eight.
Notifications can include a related `card_id`; after they finish, the overview
opens the page containing that card and grants it a full six-second interval.
Important notices interrupt ordinary notices, ending the interrupted notice.
Equal-priority task notices preserve admission order. A separately reserved
weather notification precedes queued tasks at equal priority, without
interrupting an already visible important notice. Weather notification expiry
or dismissal does not clear its still-valid persistent marker; explicit
withdrawal or alert expiry also cancels its queued/active notification.

The host starts a 30-second validity deadline when queuing a notice, drops expired
unsent notices, and shortens remaining validity on retries. Firmware establishes
a local monotonic deadline on first admission, including UI command-queue delay.
Duplicates do not renew it. Expiry prevents a pending notice from starting;
once visible, its display duration starts at first-refresh completion.

This is a bounded local USB policy, not synchronized wall-clock expiry. Precise
calendar deadlines and buffered network transports need an explicit clock/expiry
extension. Offline host submissions update task state without accumulating popup
history. Reconnect does not replay host notification backlogs.

Notice timeout does not resolve waiting/failed task state. Firmware remembers
64 recent event identities. There is no durable exactly-once guarantee.

## 6. Feedback and Failure

**Accepted** means the UI owner applied a state operation or admitted a notice.
Decode success and unchecked task handoff are insufficient.

**Presented** means the content became visible and all DMA transfers for its
first refresh completed. Card feedback includes card identity/revision, including
individual cards within a snapshot. Hidden or superseded revisions are not falsely
reported visible. Feedback does not establish that the user read the content.
The three-row overview emits a separate Presented acknowledgment for every visible
card after the shared refresh completes. Later pages stay unpresented until shown.
Feedback has its own identity and is not recursively acknowledged.

When brightness is zero, the device still processes commands and renders cached
content, but withholds Presented until the backlight is enabled. Hidden or
superseded content does not acquire retrospective presentation feedback.

**Applied** means the backlight driver successfully accepted the requested PWM
setting. Settings acknowledgments echo the present `brightness_percent` field,
including zero, and refer to the original command. This does not measure optical
brightness or imply that any message was Presented. Hardware failures return
`ERROR_CODE_HARDWARE` instead.

The host waits one second for Accepted or settings Applied, sends at most three times within the
connection, and does not wait for Presented before continuing. Rejections include
diagnostic details; queue saturation is not claimed as successful admission.
Feedback congestion forces resynchronization rather than blocking local UI timing.

Heartbeats run every second, with a three-second liveness timeout and one-second
reconnect attempts. Recovery rebuilds current state, without replaying intermediate
progress. Link failure before acknowledgment leaves delivery potentially uncertain.

State and deduplication are in memory. Restart, power loss, and cache eviction do
not provide durable delivery. Powered offline caching requires continued device power.

## 7. Device Brightness Settings

`DeviceSettings` uses envelope body tag 18. It requires the optional
`brightness_percent` field to be present with an integer 0..100. Missing input is
invalid; zero turns the backlight off. Settings require the current snapshot
session, do not occupy card/notification capacity, and do not reset page timers.
Firmware reapplies this absolute setting on retries and replies only after the
PWM driver succeeds. The host ignores admission-only, unrelated, missing-value,
or mismatched-value feedback as proof of application.

The host coalesces unsent settings to the latest target, keeps the target across
reconnections, and resynchronizes it after each snapshot. The default target is
100. Targets and feedback are retained only for the current service process;
there is no disk/NVS persistence. Applied brightness is unknown while disconnected.
