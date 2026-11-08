# info_tv

A local host service and ESP32-S3 display terminal. Producers submit task events
to a loopback HTTP API; the service sends structured Protobuf views over USB.

The first implementation supports task progress, completion/attention notices,
overview restoration, delivery feedback, and reconnect synchronization. The demo
has been flashed and tested on the physical board: USB, progress, notifications,
overview restoration, and powered serial reconnection passed. See the
[hardware validation record](docs/hardware-validation.md) for evidence and limits.

## Rust host

The host is implemented in Rust under `host/`, with durable
task/brightness recovery and optional per-user login startup. See the
[Rust host guide](host/README.md) and
[architecture and migration design](docs/rust-host-design.md).
[Validation results](docs/rust-host-validation.md) distinguish completed desktop
checks from pending physical-device and login qualification.

Build and run from the repository root:

```powershell
cargo run --manifest-path host/Cargo.toml --locked -- serve
```

Use `--config <path>` to select YAML. Without it, `serve` and `ports` read
`info-tv.yaml` from the current working directory if present, otherwise defaults.
Copy `host/info-tv.example.yaml` for a starting configuration.

Build the Windows binary archive with `scripts/host/build_rust_release.ps1`; output is
under `build/rust-host-dist`. The extracted executable needs no Python installation.
The script does not publish a GitHub release. The Python host has been removed;
its implementation remains in Git history. Python is only needed for development
tools, optional demos, or the separate firmware flashing tool.

## User guide: install from a Release on Windows

Source changes do not automatically publish release assets. Use a release that
contains the Rust host archive and matching firmware described below.

Follow this section if you want to use the display without building the project.
You need the supported **ESP32-S3 board with 16 MB Flash and a 240 × 240 ST7789
display**, a USB cable that carries data, and a Windows computer. Firmware is
specific to the [documented board and wiring](docs/hardware-reference.md).
Install and sign in to Codex, Antigravity CLI, or ZCode separately if you want
agent updates. The adapters were validated with Codex 0.166.0, agy 1.5.2, and
ZCode desktop 3.14.3 (bundled runtime 0.16.9).

You do not need Git, uv, a source checkout, or ESP-IDF for these steps. Run the
commands below in **PowerShell**. This guide uses `C:\info-tv` as a fixed install
location so hooks can find their executable even when started from another
project.

### 1. Download the host and complete firmware

Open [Releases](https://github.com/ruicx/ESP32-Info-TV/releases) and expand the
chosen release's **Assets**. Download both assets from the **same release**:

- The Rust host archive, such as `info-tv-<version>-x86_64-pc-windows-msvc.zip`.
  Extract its executables, `info-tv.yaml`, and README directly into `C:\info-tv`.
- The complete firmware image, such as
  `info_tv-firmware-<version>-esp32s3.bin`. Save it as `C:\info-tv\firmware.bin`.

```text
C:\info-tv\
  info-tv.exe
  info-tv.yaml
  firmware.bin
```

The GitHub **Source code** archives are for developers. The firmware image is a
single merged file covering the whole application flash layout, so no separate
bootloader or partition-table files are needed for first-time flashing. If these
assets are absent, that release is not ready for this installation path.
Building the host from source does not require installing the removed Python
host.

### 2. Check the host and install the optional flashing tool

The host executable runs directly without Python:

```powershell
C:\info-tv\info-tv.exe --help
C:\info-tv\info-tv.exe hook --help
```

If compatible firmware is already installed, continue to step 4. To flash it
yourself, install [Python for Windows](https://www.python.org/downloads/windows/)
with pip and the `py` launcher, then create a separate flashing environment:

```powershell
py -3 -m venv C:\info-tv\flash-tools
C:\info-tv\flash-tools\Scripts\python.exe -m pip install "esptool>=5,<6"
```

See the [esptool installation guide](https://docs.espressif.com/projects/esptool/en/latest/esp32s3/installation.html).
The flashing environment is independent of the running host.

### 3. Flash the display

Flashing replaces the board's existing firmware. Keep its original recovery
image if you want to restore the vendor software later. Close any running
info_tv host and serial monitor before flashing; only one program can own the
serial port.

Connect the board by USB, then list ports:

```powershell
C:\info-tv\info-tv.exe ports
```

Find the board's `COM` port in the output or Windows **Device Manager > Ports
(COM & LPT)**. Unplugging and reconnecting the board helps identify which entry
belongs to it. The verified board uses USB VID/PID `303A:1001`. **Replace `COM6`
below with your board's actual port.** First check its chip/Flash identity:

```powershell
C:\info-tv\flash-tools\Scripts\python.exe -m esptool --chip esp32s3 --port COM6 flash-id
```

Check that it is the intended ESP32-S3 with 16 MB Flash. Then write the merged
firmware image downloaded from the Release, starting at offset `0x0`:

```powershell
C:\info-tv\flash-tools\Scripts\python.exe -m esptool --chip esp32s3 --port COM6 --baud 460800 write-flash 0x0 C:\info-tv\firmware.bin
```

The merged image contains the bootloader at `0x0`, the partition table at
`0x8000`, and the application at `0x10000`, with DIO/80 MHz/16 MB settings, so a
single `write-flash` covers first-time flashing. Always use the image from the
same release as the host archive; follow a release's own instructions if its
layout changes. This is the standard
[ESP-IDF binary flashing procedure](https://docs.espressif.com/projects/esptool/en/latest/esp32s3/esptool/flashing-firmware.html).

Wait for esptool to finish writing, verifying, and resetting the board. If it
stays in download mode, reset or reconnect it, then list ports again: the COM
number can change. If automatic connection fails and your board exposes
**BOOT** and **RESET**, hold BOOT, press and release RESET, then release BOOT
and retry. Otherwise use the board vendor's download-mode instructions. See
[Espressif's boot-mode guide](https://docs.espressif.com/projects/esptool/en/latest/esp32s3/advanced-topics/boot-mode-selection.html).

### 4. Start the host and check the screen

Start the service in a PowerShell window:

```powershell
Set-Location C:\info-tv
.\info-tv.exe serve
```

Leave this window open. The host automatically selects a single matching USB
device and reconnects after disconnects. If several devices match, stop it with
**Ctrl+C** and start it with an explicit port instead:

```powershell
C:\info-tv\info-tv.exe serve --serial-port COM6
```

Open a **second PowerShell window** to check the running service:

```powershell
C:\info-tv\info-tv.exe status
```

Look for `"state": "online"`. The local API is available at
`http://127.0.0.1:8765`, with an interactive reference at
`http://127.0.0.1:8765/docs`. An HTTP server starting successfully does not by
itself mean the display is connected.

Before configuring an agent, send a test card from this second window:

```powershell
$testRun = [guid]::NewGuid().ToString()
C:\info-tv\info-tv.exe task submit --task-id $testRun --sequence 1 --state running --title "Hello info_tv"
C:\info-tv\info-tv.exe task submit --task-id $testRun --sequence 2 --state completed --title "Hello info_tv"
C:\info-tv\info-tv.exe task list
```

The screen should show the card and a completion notice. In `task list`,
`delivery.accepted: true` means the firmware accepted the card;
`delivery.presented: true` confirms presentation feedback. For optional startup
after login, run the following command; see the [host guide](host/README.md#login-startup).

```powershell
C:\info-tv\info-tv.exe autostart install --config C:\info-tv\info-tv.yaml
```

Stop the host before replacing its executable or flashing firmware.

### 5. Connect agent hooks

A hook is a command the agent runs when an event occurs. It forwards an update
to the already running host; extracting the host archive alone does not configure
hooks. Configure whichever agents you use. Keep the host running while
using the agents.

**Codex:** create or edit `%USERPROFILE%\.codex\hooks.json` (for example,
`C:\Users\YourName\.codex\hooks.json`). If you set `CODEX_HOME`, use that
directory instead. Save it as UTF-8 JSON, with the filename `hooks.json`, not
`hooks.json.txt`.

For a new file, paste:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {"hooks": [{"type": "command", "command": "C:/info-tv/info-tv.exe hook codex", "timeout": 3}]}
    ],
    "PreToolUse": [
      {"hooks": [{"type": "command", "command": "C:/info-tv/info-tv.exe hook codex", "timeout": 3}]}
    ],
    "PermissionRequest": [
      {"hooks": [{"type": "command", "command": "C:/info-tv/info-tv.exe hook codex", "timeout": 3}]}
    ],
    "PostToolUse": [
      {"hooks": [{"type": "command", "command": "C:/info-tv/info-tv.exe hook codex", "timeout": 3}]}
    ],
    "Stop": [
      {"hooks": [{"type": "command", "command": "C:/info-tv/info-tv.exe hook codex", "timeout": 3}]}
    ],
    "Interrupt": [
      {"hooks": [{"type": "command", "command": "C:/info-tv/info-tv.exe hook codex", "timeout": 3}]}
    ]
  }
}
```

If the file already exists, back it up and append these handlers to the matching
event arrays inside its existing `hooks` object. Preserve other handlers and
avoid duplicate JSON keys. Restart Codex, open **`/hooks`**, then review and
trust the info_tv handlers; configured hooks are skipped until trusted.
Changing their command later requires review again. In desktop Codex, use
**Settings > Hooks** to review and trust them. See the
[official Codex hooks guide](https://learn.chatgpt.com/docs/hooks) and
[adapter details](docs/codex-hooks.md).

**Antigravity CLI (`agy`):** in the project where you run agy, create or edit
`.agents/hooks.json`. Create the `.agents` directory if needed. Add this named
entry, preserving any existing entries:

```json
{
  "info-tv": {
    "PreInvocation": [
      {"type": "command", "command": "C:/info-tv/info-tv.exe hook agy PreInvocation", "timeout": 3}
    ],
    "Stop": [
      {"type": "command", "command": "C:/info-tv/info-tv.exe hook agy Stop", "timeout": 3}
    ]
  }
}
```

Restart agy in that trusted project and use **`/hooks`** to check that both
handlers are loaded. For all projects, the same entry can instead go in
`%USERPROFILE%\.gemini\config\hooks.json`; use one scope to avoid duplicates.
That global file is also shared with other Antigravity products; this guide
targets the CLI. Do not put hooks in agy's `settings.json`, and do not copy
Codex's `PreToolUse` handler into agy: its policy-response contract differs.
See the [official agy hooks guide](https://antigravity.google/docs/hooks?tab=cli)
and [adapter details](docs/agy-hooks.md).

**ZCode (built-in ZCode Agent):** create or edit
`%USERPROFILE%\.zcode\cli\config.json`. Save it as UTF-8 JSON. Merge the following
`hooks` object into the existing configuration, preserving other settings and
handlers. ZCode requires `hooks.enabled: true`; its configuration structure
differs from Codex and agy.

```json
{
  "hooks": {
    "enabled": true,
    "events": {
      "UserPromptSubmit": [
        {"hooks": [{"type": "process", "command": "C:/info-tv/info-tv.exe", "args": ["hook", "zcode"], "timeoutMs": 3000}]}
      ],
      "PreToolUse": [
        {"hooks": [{"type": "process", "command": "C:/info-tv/info-tv.exe", "args": ["hook", "zcode"], "timeoutMs": 3000}]}
      ],
      "PermissionRequest": [
        {"hooks": [{"type": "process", "command": "C:/info-tv/info-tv.exe", "args": ["hook", "zcode"], "timeoutMs": 3000}]}
      ],
      "PostToolUse": [
        {"hooks": [{"type": "process", "command": "C:/info-tv/info-tv.exe", "args": ["hook", "zcode"], "timeoutMs": 3000}]}
      ],
      "PostToolUseFailure": [
        {"hooks": [{"type": "process", "command": "C:/info-tv/info-tv.exe", "args": ["hook", "zcode"], "timeoutMs": 3000}]}
      ],
      "Stop": [
        {"hooks": [{"type": "process", "command": "C:/info-tv/info-tv.exe", "args": ["hook", "zcode"], "timeoutMs": 3000}]}
      ]
    }
  }
}
```

Open **Settings > Hooks** to check the entries, then start a **new session**;
existing sessions retain their earlier hook configuration. Use the user-level
file above: the [official ZCode guide](https://zcode.z.ai/en/docs/hooks) currently
says project-level hooks do not execute. See the
[adapter details and native limitations](docs/zcode-hooks.md).

Send a new prompt such as `Reply exactly HOOKS_OK; do not use tools.` in your
configured agent, then run `C:\info-tv\info-tv.exe task list`.
Expect a card with source `codex`, `agy`, or `zcode`; a quick response may already
show `completed`. Each conversation keeps one card across turns, and independent
conversations get separate cards. Completed means the turn ended, not that a
task passed acceptance criteria. agy 1.5.2 has no approval hook and can omit the
stop callback on cancellation. ZCode also omitted a terminal callback when
canceled during generation; fast approvals can skip its approval hook, and
waiting clears on the next post-tool callback. These native limits prevent
reliable waiting/interrupted display in the affected cases.

### 6. Everyday use and troubleshooting

Start the host, connect the display, then use your configured agent normally.
Completed/interrupted cards expire after five minutes by default. For optional
weather or a fixed serial port, create your own `C:\info-tv\config.yaml` using
the [configuration reference](docs/host-configuration.md), then start with
`C:\info-tv\info-tv.exe serve --config C:\info-tv\config.yaml`.
Weather is disabled until configured.

| Symptom | What to check |
| --- | --- |
| `py` is not recognized when flashing | Install Python with the launcher and pip, then open a new PowerShell window. The host itself needs no Python. |
| Flashing cannot connect | Check the USB data cable and COM number, close the host/serial monitor, and try download mode. Retry at `--baud 115200` if writes are unreliable. |
| Host stays `offline` | Repeat the port-list command in step 3; use the current COM port if selection is ambiguous, and install matching host/firmware versions. |
| Host port 8765 is already in use | Close the previous host instance before starting another one. |
| The screen is dark | Check USB power, then run `C:\info-tv\info-tv.exe brightness 50` with the host online. |
| Manual test works but agent cards do not appear | Check the absolute hook executable path, JSON filename/syntax, and `/hooks`; trust Codex handlers and restart the agent after editing. |
| An agy card stays running after cancellation | This is the documented missing native callback; the next turn replaces the run. |
| ZCode hooks do not fire | Use the user-level config, enable `hooks.enabled`, select the built-in ZCode Agent, and start a new session. |
| A ZCode card stays running/waiting after cancellation | Native hooks can omit a terminal callback; the next prompt updates the card. |

If an event was captured while the host was unavailable, the next callback
retries it. You can also retry explicitly after starting the host:

```powershell
C:\info-tv\info-tv.exe hook codex --flush
C:\info-tv\info-tv.exe hook agy --flush
C:\info-tv\info-tv.exe hook zcode --flush
```

Hook ledgers and the default host database live under `%LOCALAPPDATA%\info_tv`;
keep them when upgrading or resuming conversations. The host restores accepted
tasks, target brightness, and weather expiry across restarts. Device delivery
feedback is obtained again, and old pop-up notifications are not replayed.
To upgrade, stop the host, replace the executable at the same stable path,
and follow the matching firmware instructions. Keep your YAML and state files.

## Repository

| Directory | Responsibility |
| --- | --- |
| `host/` | Rust host, SQLite recovery, CLI/hooks, and login startup |
| `firmware/` | ESP-IDF 6.1, FreeRTOS, C++, LVGL 9.3, ST7789 |
| `protocol/` | Shared schema, Nanopb bounds, and compatibility vector |
| `scripts/` | Firmware protocol generation, locked Python development tools, and release packaging |
| `demos/` | Manual physical-display demonstrations using the production HTTP API |
| `docs/` | Requirements, hardware evidence, and implementation design |

See [current host architecture](docs/rust-host-design.md),
[device protocol](docs/device-protocol.md), and
[hardware reference](docs/hardware-reference.md).

## Run the host from source

Requires Rust 1.89+ and platform C/C++ build tools for bundled SQLite. From the
repository root:

```powershell
cargo run --manifest-path host/Cargo.toml --locked -- serve
```

Copy the example and uncomment its `weather` mapping to enable Shanghai weather
(or edit the coordinates for your location), then start with that file:

```powershell
Copy-Item host/info-tv.example.yaml info-tv.yaml
# Edit info-tv.yaml to enable and configure weather.
cargo run --manifest-path host/Cargo.toml --locked -- serve --config info-tv.yaml
```

See the [YAML field reference](docs/host-configuration.md) for field meanings,
types, defaults, limits, and configuration precedence.

Serial discovery defaults to `auto`: the host selects a single USB `303A:1001`
candidate and rescans after disconnects. YAML keys `usb_vid` and `usb_pid` can
override that USB filter. Use `info-tv ports --config host/info-tv.example.yaml`
to list candidates using the same configuration;
with multiple matching devices, select one explicitly with `--serial-port COM6`.
Other ESP32 devices share this USB ID; the protocol handshake checks compatibility.
See [task lifecycle, YAML, and automatic weather](docs/host-lifecycle-weather.md)
for configuration, removal APIs, and verification scope.

For manual selection, use the currently enumerated port, not necessarily COM6. Linux/macOS serial
paths use the same option; these platforms remain untested. The API binds only
to `127.0.0.1:8765`, with documentation at `http://127.0.0.1:8765/docs`. Startup
retries an unavailable device while continuing to accept task state.

The CLI also calls the running host directly:

```powershell
cargo run --manifest-path host/Cargo.toml --locked -- status
cargo run --manifest-path host/Cargo.toml --locked -- task submit --task-id build-1 --sequence 1 --state running --title "Build firmware" --progress-percent 20
cargo run --manifest-path host/Cargo.toml --locked -- task list
cargo run --manifest-path host/Cargo.toml --locked -- weather updater
cargo run --manifest-path host/Cargo.toml --locked -- brightness 30
```

Use `info-tv serve --config ...` for explicit startup; existing startup commands
remain supported. Client results are JSON. See the [CLI guide](docs/host-cli.md)
for task closure, retries, weather/alerts, connection options, and exit codes.

Check `GET /v1/device` for `state: online`. In another terminal:

```powershell
python demos/demo_task.py
```

The script calls the real `POST /v1/task-events` endpoint. It submits one unique
run, advances from 0% to 100%, and generates a completion notice. Service
acceptance does not mean the screen has shown the content. Inspect
`GET /v1/tasks` and `GET /v1/device` for Accepted/Presented feedback.

See [physical display demos](demos/README.md) for setup, expected behavior, and
the current task-retention limit.

Real Codex hook events have been [captured and validated](docs/codex-hook-validation.md).
The [Codex hook adapter](docs/codex-hooks.md) now forwards running, approval,
end-of-turn, and interrupted states through this same API.
The [Antigravity CLI hook adapter](docs/agy-hooks.md) forwards native invocation
starts and explicit stop outcomes. Its [event validation](docs/agy-hook-validation.md)
records the missing approval and cancellation callbacks in agy 1.5.2.
The [ZCode adapter](docs/zcode-hooks.md) forwards native turn, approval, and
post-tool events. Its [validation](docs/zcode-hook-validation.md) records stable
turn IDs, tool-failure behavior, approval races, and missing cancellation hooks.

The API supports `running`, `waiting_input`, `completed`, `failed`, and
`interrupted`. Retries
retain their UUID `event_id` and content. Updates for one `(source, task_id)`
use increasing positive `sequence` values. A new execution uses a new task ID.

For multiple conversations, also submit `conversation_id`, `run_sequence`, and
optionally `conversation_title` and `context`. Each conversation keeps one card
across executions; `run_sequence` increases for each new execution, while
`sequence` orders updates within it. Existing submissions without conversation
fields continue to create independent task cards. See the
[message/UI design and request example](docs/message-ui-design.md).

The compact overview shows three rows per page, rotating pages every six seconds.
Each row shows an icon, title, and state, with a thin progress bar when known.
Use optional `icon` values `task` (default), `code`, `test`, `build`, `review`, or
`deploy`; `progress_percent` accepts an integer 0..100 or null.
Waiting/failed rows sort first; all pages remain reachable. The compact icon
revision passed desktop checks and a firmware build. The latest companion/weather
firmware was [flashed on 2026-11-06](docs/hardware-validation.md#7-companion-weather-and-alert-firmware-deployment);
five cards and a TEST weather alert returned actual device Presented feedback.
The original three-row overview was flashed on 2026-11-05; five cards and two notifications
reported actual device Presented feedback. The user confirmed physical text,
layout, and page rotation on the same date. Update the firmware together with the host: older firmware
does not advertise the required eight-card overview and task-icon capabilities.
See [current UI previews and weather API](docs/companion-ui-validation.md).
The header holds counts and page position; a full-body whale companion and weather
remain below the message area. One or two rows leave unused space black.
The companion now blinks and occasionally shifts its weight; see the
[actual LVGL animation preview](docs/companion-animation.md).
Weather comes from `PUT /v1/weather` or the optional YAML-configured Open-Meteo
updater, independently of task cards, and expires locally. Automatic retrieval
is disabled without a `weather` configuration. The example selects Shanghai.
Weather now supports local condition icons and optional `daily_low_c` /
`daily_high_c`. `PUT /v1/weather/alert` controls one independent hazard marker
with first/upgrade notifications. See [weather previews and API](docs/weather-ui-validation.md).
Connection status is a small USB/offline icon in the header, leaving separate
weather range/freshness and warning lines; see [current layout](docs/header-connection-ui.md).

Character artwork: [YunYueSama / codex-deepseek-pet](https://github.com/YunYueSama/codex-deepseek-pet),
modified by selecting a frame, trimming transparency, and resizing. See the
[asset attribution and license](firmware/main/ui/assets/README.md).

## Build the firmware

Device backlight settings are available through `PUT /v1/device/settings` with
`{"brightness_percent":30}` (integer 0..100; zero turns the backlight off).
`GET /v1/device/settings` distinguishes the target from device Applied feedback.
The host persists the target and restores it on restart and reconnect.
The brightness revision is built and desktop-tested; the latest flashed firmware
returned Applied feedback at 100%. Update host
and firmware together; see [brightness control](docs/brightness-control.md).

Use an activated **ESP-IDF v6.1** environment, separate from the protocol-generation environment:

```powershell
idf.py -C firmware build
```

The component manager downloads the locked LVGL version. Nanopb runtime sources
and generated bindings are checked in. The firmware uses the verified 16 MB
Flash configuration and does not require PSRAM for this demo.

The output is `firmware/build/info_tv.bin`, together with bootloader and partition
images. Building does not write the device. When hardware flashing is arranged,
stop the host first so it releases the serial port, then use:

```powershell
idf.py -C firmware -p COM6 flash
```

Re-enumerate the port afterward and restart the host. Application logs use
UART0; do not run an IDF USB serial monitor concurrently with the host protocol.
Basic screen orientation, text, backlight, and application USB operation have
passed bring-up. Detailed color/brightness calibration and performance remain
to be evaluated. A full pre-demo Flash backup is retained locally as recorded
in the hardware validation document.

## Verification

Run host checks from the repository root:

```powershell
cargo fmt --manifest-path host/Cargo.toml -- --check
cargo clippy --manifest-path host/Cargo.toml --all-targets --locked -- -D warnings
cargo test --manifest-path host/Cargo.toml --locked
```

Native firmware-core tests require CMake and a desktop C/C++ compiler:

```powershell
cmake -S firmware/tests -B build/native-tests
cmake --build build/native-tests --config Debug
ctest --test-dir build/native-tests -C Debug -LE hardware --output-on-failure
```

Build native tests before running Rust tests to include the HTTP-to-C++ bridge
integration. `protocol_bridge` is a helper executable, not a CTest case; set
`INFO_TV_PROTOCOL_BRIDGE` if it is built in a nondefault location. It simulates
refresh completion and does not test LCD hardware. After an ESP-IDF build has
downloaded LVGL, configure with `-DINFO_TV_BUILD_UI_TESTS=ON` to include the
fourth desktop screen test. Physical checks remain separate from desktop tests.

Python development dependencies are isolated under `scripts/` and are not
installed with the host. To generate/check the committed Nanopb firmware bindings:

```powershell
uv sync --project scripts --locked
uv run --project scripts --locked python scripts/protocol/generate_protocol.py --check
uv run --project scripts --locked ruff check --config scripts/pyproject.toml scripts demos
uv run --project scripts --locked ty check --project scripts scripts demos
```

Omit `--check` to regenerate after schema changes. Cargo generates Rust bindings
from the same schema during builds. See [development tools](scripts/README.md).
The language-independent compatibility fixtures in `host/tests/fixtures`
remain usable without the removed Python service.

## Package the host

```powershell
powershell -NoProfile -File scripts/host/build_rust_release.ps1
```

The Windows archive is written under `build/rust-host-dist`; its version comes
from `host/Cargo.toml`. See the [host guide](host/README.md). The script
builds the executable with the static MSVC runtime and does not publish it.

For a user-facing Release, use the automated release workflow instead of
assembling assets by hand.

## Releases

Pushing a tag `v<version>` that matches the `host/Cargo.toml` version triggers
the [Release workflow](.github/workflows/release.yml). It packages the host for
Windows x64/ARM64 and Linux x64 (musl)/ARM64, builds the firmware in the pinned
ESP-IDF v6.1 container, merges the flash layout into
`info_tv-firmware-<version>-esp32s3.bin`, and publishes a GitHub Release with a
`SHA256SUMS.txt` covering every asset. A manual `workflow_dispatch` run performs
the same builds and keeps them as workflow artifacts without publishing, which
verifies the pipeline ahead of tagging.

## Demo limits

The host persists task/replay state, brightness, and weather validity. Windows
login startup is available through its `autostart` commands.

- One device, USB only; eight current conversation/task cards. Completed and
  interrupted cards retire after five minutes by default; other states remain until manually closed.
  A later execution replaces its conversation's current run or reopens a retired one.
- Eight queued notices, 30-second start validity, ordinary/important display
  defaults of 5/10 seconds. Important notices interrupt ordinary notices; an
  interrupted ordinary notice ends. Three-row pages rotate every six seconds.
- Offline submissions retain task state without accumulating popup history.
- The host restores persisted state after restart. A USB power loss cold-boots
  the device; it receives a fresh snapshot when the host reconnects.
- English system labels; the bundled LVGL CJK font supports a limited character
  subset, not arbitrary Chinese. Full Chinese font coverage, automatic calendar
  producers, additional character actions, touch, Wi-Fi, BLE, and operation before login remain
  future work. Closed-task protection retains 256 persisted retired identities.
