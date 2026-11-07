# info_tv

A local host service and ESP32-S3 display terminal. Producers submit task events
to a loopback HTTP API; the service sends structured Protobuf views over USB.

The first implementation supports task progress, completion/attention notices,
overview restoration, delivery feedback, and reconnect synchronization. The demo
has been flashed and tested on the physical board: USB, progress, notifications,
overview restoration, and powered serial reconnection passed. See the
[hardware validation record](docs/hardware-validation.md) for evidence and limits.

## User guide: install from a Release on Windows

Follow this section if you want to use the display without building the project.
You need the supported **ESP32-S3 board with 16 MB Flash and a 240 × 240 ST7789
display**, a USB cable that carries data, and a Windows computer. Firmware is
specific to the [documented board and wiring](docs/hardware-reference.md).
Install and sign in to Codex or Antigravity CLI separately if you want agent
updates. The adapters were validated with Codex 0.166.0 and agy 1.5.2.

You do not need Git, uv, a source checkout, or ESP-IDF for these steps. Run the
commands below in **PowerShell**. This guide uses `C:\info-tv` as a fixed install
location so hooks can find their executable even when started from another
project.

### 1. Download the host and complete firmware

Install [Python for Windows](https://www.python.org/downloads/windows/), version
**3.12 or newer**, including pip and the `py` launcher. Open a new PowerShell
window and check the version, then create the download directory:

```powershell
py -3 --version
New-Item -ItemType Directory -Force C:\info-tv\downloads | Out-Null
```

Open [Releases](https://github.com/ruicx/EPS32-Info-TV/releases) and expand the
chosen release's **Assets**. Download both assets from the **same release**:

- The host wheel, named `info_tv_service-<version>-py3-none-any.whl`. Save it in
  `C:\info-tv\downloads`; keep only the chosen version's wheel in this directory.
- The complete firmware archive for the supported ESP32-S3 display. Extract it
  so the files have the layout below. The archive name can vary by release.

The GitHub **Source code** archives are for developers. A complete firmware
download must provide all four files below; `info_tv.bin` alone is insufficient
for first-time installation. If those assets are not attached to a release,
that release is not ready for this installation path.

```text
C:\info-tv\
  downloads\
    info_tv_service-<version>-py3-none-any.whl
  firmware\
    flash_args
    info_tv.bin
    bootloader\
      bootloader.bin
    partition_table\
      partition-table.bin
```

`<version>` represents the version in your downloaded filename; do not rename
the wheel. After extraction, `flash_args` must be directly inside
`C:\info-tv\firmware`, rather than inside another versioned subdirectory.

### 2. Install the host and flashing tool

Create a Python environment dedicated to info_tv, then install the downloaded
wheel and esptool. An internet connection is needed to install dependencies;
the first installation can take several minutes.

```powershell
py -3 -m venv C:\info-tv\venv
C:\info-tv\venv\Scripts\python.exe -m pip install --upgrade pip
$wheel = Get-ChildItem C:\info-tv\downloads -Filter 'info_tv_service-*.whl'
C:\info-tv\venv\Scripts\python.exe -m pip install $wheel.FullName
C:\info-tv\venv\Scripts\python.exe -m pip install "esptool>=5,<6"
C:\info-tv\venv\Scripts\info-tv.exe --help
C:\info-tv\venv\Scripts\info-tv-hook.exe --help
```

The last two commands should show help, including `serve` and the hook sources
`codex` and `agy`. These commands use full executable paths, so you do not need
to activate the environment or change PowerShell's execution policy. See the
[Python environment reference](https://docs.python.org/3/library/venv.html) and
[esptool installation guide](https://docs.espressif.com/projects/esptool/en/latest/esp32s3/installation.html)
for installation problems.

### 3. Flash the display

Flashing replaces the board's existing firmware. Keep its original recovery
image if you want to restore the vendor software later. Close any running
info_tv host and serial monitor before flashing; only one program can own the
serial port.

Connect the board by USB, then list ports:

```powershell
C:\info-tv\venv\Scripts\info-tv.exe ports
```

Find the board's `COM` port in the output or Windows **Device Manager > Ports
(COM & LPT)**. Unplugging and reconnecting the board helps identify which entry
belongs to it. The verified board uses USB VID/PID `303A:1001`. **Replace `COM6`
below with your board's actual port.** First check its chip/Flash identity:

```powershell
C:\info-tv\venv\Scripts\python.exe -m esptool --chip esp32s3 --port COM6 flash-id
```

Check that it is the intended ESP32-S3 with 16 MB Flash. Then change to the
extracted firmware directory and write the files using its supplied address
manifest:

```powershell
Set-Location C:\info-tv\firmware
C:\info-tv\venv\Scripts\python.exe -m esptool --chip esp32s3 --port COM6 --baud 460800 write-flash "@flash_args"
```

Keep the quotes around `"@flash_args"` in PowerShell. For the current board
layout, this manifest writes the bootloader at `0x0`, partition table at
`0x8000`, and application at `0x10000`, with DIO/80 MHz/16 MB settings. Keep
these files together from one build; follow a release's own instructions if
its layout changes. This is the standard
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
C:\info-tv\venv\Scripts\info-tv.exe serve
```

Leave this window open. The host automatically selects a single matching USB
device and reconnects after disconnects. If several devices match, stop it with
**Ctrl+C** and start it with an explicit port instead:

```powershell
C:\info-tv\venv\Scripts\info-tv.exe serve --serial-port COM6
```

Open a **second PowerShell window** to check the running service:

```powershell
C:\info-tv\venv\Scripts\info-tv.exe status
```

Look for `"state": "online"`. The local API is available at
`http://127.0.0.1:8765`, with an interactive reference at
`http://127.0.0.1:8765/docs`. An HTTP server starting successfully does not by
itself mean the display is connected.

Before configuring an agent, send a test card from this second window:

```powershell
$testRun = [guid]::NewGuid().ToString()
C:\info-tv\venv\Scripts\info-tv.exe task submit --task-id $testRun --sequence 1 --state running --title "Hello info_tv"
C:\info-tv\venv\Scripts\info-tv.exe task submit --task-id $testRun --sequence 2 --state completed --title "Hello info_tv"
C:\info-tv\venv\Scripts\info-tv.exe task list
```

The screen should show the card and a completion notice. In `task list`,
`delivery.accepted: true` means the firmware accepted the card;
`delivery.presented: true` confirms presentation feedback. There is no automatic
Windows service installation: start `serve` again after restarting your PC.
Stop it with Ctrl+C before updating the package or flashing firmware.

### 5. Connect Codex or agy hooks

A hook is a command the agent runs when an event occurs. It forwards an update
to the already running host; installing the wheel alone does not configure
hooks. Configure whichever agent you use, or both. Keep the host running while
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
      {"hooks": [{"type": "command", "command": "C:/info-tv/venv/Scripts/info-tv-hook.exe codex", "timeout": 3}]}
    ],
    "PreToolUse": [
      {"hooks": [{"type": "command", "command": "C:/info-tv/venv/Scripts/info-tv-hook.exe codex", "timeout": 3}]}
    ],
    "PermissionRequest": [
      {"hooks": [{"type": "command", "command": "C:/info-tv/venv/Scripts/info-tv-hook.exe codex", "timeout": 3}]}
    ],
    "PostToolUse": [
      {"hooks": [{"type": "command", "command": "C:/info-tv/venv/Scripts/info-tv-hook.exe codex", "timeout": 3}]}
    ],
    "Stop": [
      {"hooks": [{"type": "command", "command": "C:/info-tv/venv/Scripts/info-tv-hook.exe codex", "timeout": 3}]}
    ],
    "Interrupt": [
      {"hooks": [{"type": "command", "command": "C:/info-tv/venv/Scripts/info-tv-hook.exe codex", "timeout": 3}]}
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
      {"type": "command", "command": "C:/info-tv/venv/Scripts/info-tv-hook.exe agy PreInvocation", "timeout": 3}
    ],
    "Stop": [
      {"type": "command", "command": "C:/info-tv/venv/Scripts/info-tv-hook.exe agy Stop", "timeout": 3}
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

Send a new prompt such as `Reply exactly HOOKS_OK; do not use tools.` in your
configured agent, then run `C:\info-tv\venv\Scripts\info-tv.exe task list`.
Expect a card with source `codex` or `agy`; a quick response may already show
`completed`. Each conversation keeps one card across turns, and independent
conversations get separate cards. Completed means the turn ended, not that a
task passed acceptance criteria. agy 1.5.2 has no approval hook and can omit the
stop callback on cancellation, so those cases cannot reliably show waiting or
interrupted states.

### 6. Everyday use and troubleshooting

Start the host, connect the display, then use your configured agent normally.
Completed/interrupted cards expire after five minutes by default. For optional
weather or a fixed serial port, create your own `C:\info-tv\config.yaml` using
the [configuration reference](docs/host-configuration.md), then start with
`C:\info-tv\venv\Scripts\info-tv.exe serve --config C:\info-tv\config.yaml`.
Weather is disabled until configured.

| Symptom | What to check |
| --- | --- |
| `py` is not recognized, or Python is older than 3.12 | Install Python with the launcher and pip, then open a new PowerShell window. |
| Flashing cannot connect | Check the USB data cable and COM number, close the host/serial monitor, and try download mode. Retry at `--baud 115200` if writes are unreliable. |
| Host stays `offline` | Repeat the port-list command in step 3; use the current COM port if selection is ambiguous, and install matching host/firmware versions. |
| Host port 8765 is already in use | Close the previous host instance before starting another one. |
| The screen is dark | Check USB power, then run `C:\info-tv\venv\Scripts\info-tv.exe brightness 50` with the host online. |
| Manual test works but agent cards do not appear | Check the absolute hook executable path, JSON filename/syntax, and `/hooks`; trust Codex handlers and restart the agent after editing. |
| An agy card stays running after cancellation | This is the documented missing native callback; the next turn replaces the run. |

If an event was captured while the host was unavailable, the next callback
retries it. You can also retry explicitly after starting the host:

```powershell
C:\info-tv\venv\Scripts\info-tv-hook.exe codex --flush
C:\info-tv\venv\Scripts\info-tv-hook.exe agy --flush
```

Hook ledgers live under `%LOCALAPPDATA%\info_tv`; keep them when updating or
resuming conversations. The host keeps cards in memory, so previously
acknowledged cards do not automatically return after a host restart; send a new
prompt to update the display. For an upgrade, stop the host, download a matching
host/firmware pair, install the new wheel into the same environment, and repeat
the flash/start steps. Keeping `C:\info-tv\venv` preserves the hook executable
path.

## Repository

| Directory | Responsibility |
| --- | --- |
| `host/` | Python 3.12+, FastAPI, uv; portable core, initially tested on Windows |
| `firmware/` | ESP-IDF 6.1, FreeRTOS, C++, LVGL 9.3, ST7789 |
| `protocol/` | Shared schema, Nanopb bounds, and compatibility vector |
| `scripts/` | Protocol generation and development operations |
| `demos/` | Manual physical-display demonstrations using the production HTTP API |
| `docs/` | Requirements, hardware evidence, and implementation design |

See [implementation and class design](docs/demo-implementation.md),
[device protocol](docs/device-protocol.md), and
[hardware reference](docs/hardware-reference.md).

## Run the host from source

From the repository root:

```powershell
uv sync --project host --locked
uv run --project host info-tv serve
```

To use YAML configuration with automatic Shanghai weather:

```powershell
uv run --project host info-tv --config host/config.example.yaml
```

See the [YAML field reference](docs/host-configuration.md) for field meanings,
types, defaults, limits, and configuration precedence.

Serial discovery defaults to `auto`: the host selects a single USB `303A:1001`
candidate and rescans after disconnects. YAML keys `usb_vid` and `usb_pid` can
override that USB filter. Use `info-tv ports --config host/config.example.yaml`
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
uv run --project host info-tv status
uv run --project host info-tv task submit --task-id build-1 --sequence 1 --state running --title "Build firmware" --progress-percent 20
uv run --project host info-tv task list
uv run --project host info-tv weather updater
uv run --project host info-tv brightness 30
```

Use `info-tv serve --config ...` for explicit startup; existing startup commands
remain supported. Client results are JSON. See the [CLI guide](docs/host-cli.md)
for task closure, retries, weather/alerts, connection options, and exit codes.

Check `GET /v1/device` for `state: online`. In another terminal:

```powershell
uv run --project host python demos/demo_task.py
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
The host retains the target for its process lifetime and restores it on reconnect.
The brightness revision is built and desktop-tested; the latest flashed firmware
returned Applied feedback at 100%. Update host
and firmware together; see [brightness control](docs/brightness-control.md).

Use an activated **ESP-IDF v6.1** environment, separate from the host uv environment:

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

Run Python checks **from `host/`**, so pytest uses that project's configuration:

```powershell
cd host
uv run pytest
uv run ruff check --config pyproject.toml . ../scripts ../demos
uv run ty check . ../scripts ../demos
uv run python ../scripts/generate_protocol.py --check
```

Native firmware-core tests require CMake and a desktop C/C++ compiler, not an ESP32.
Run these commands from the repository root:

```powershell
cmake -S firmware/tests -B build/native-tests
cmake --build build/native-tests --config Debug
ctest --test-dir build/native-tests -C Debug --show-only
ctest --test-dir build/native-tests -C Debug -LE hardware --output-on-failure
```

CTest discovers the registered C++ tests; the current three tests have the
`unit` label and run entirely on the desktop. `protocol_bridge` is a helper
executable driven by the Python integration test, not a standalone CTest case.
After a firmware build has downloaded LVGL, configure native tests with
`-DINFO_TV_BUILD_UI_TESTS=ON` to add the fourth desktop screen test. It renders
the real widget layout into portable images. See
[multi-conversation validation and screenshots](docs/multi-conversation-validation.md).

Hardware-dependent C++ cases must use the `hardware` CTest label, and Python
cases must use `@pytest.mark.hardware`. There are currently no registered
hardware-dependent cases in either suite; the earlier physical checks used
the local manual harness described in the validation record.

Pytest registers strict `hardware` and `integration` markers. Its default
selection excludes `hardware`; the native bridge test is marked `integration`
and requires a compiled executable, without requiring an ESP32. Useful filters:

```powershell
# From the repository root: discover/run C++ cases without hardware.
ctest --test-dir build/native-tests -C Debug -N -LE hardware
ctest --test-dir build/native-tests -C Debug -LE hardware --output-on-failure

# From host/: run the desktop integration test.
uv run pytest -m "integration and not hardware"

# Explicit opt-in, when physical-device cases have been added.
uv run pytest -m hardware
# From the repository root:
ctest --test-dir build/native-tests -C Debug -L hardware --output-on-failure
```

On Windows with multiple Visual Studio installations, configure with
`-G "Visual Studio 17 2022" -A x64`. The resulting `protocol_bridge` executable
enables an additional Python test connecting the real HTTP service to the real
C++ codec and presentation core. The bridge simulates refresh completion;
it does not test LCD hardware. Set `INFO_TV_PROTOCOL_BRIDGE` if your generator
places the executable elsewhere.

Regenerate bindings after schema changes, from the repository root:

```powershell
uv run --project host python scripts/generate_protocol.py
```

## Package the host

For a user-facing Release, attach the host wheel and a complete firmware archive
from the same revision. The firmware archive must preserve the build directory's
`flash_args`, `bootloader/bootloader.bin`, `partition_table/partition-table.bin`,
and `info_tv.bin` layout used by the [Release user guide](#user-guide-install-from-a-release-on-windows).
Do not publish only the application image for first-time installs. Release
automation is not currently provided in this repository; these files must be
assembled and attached when publishing.

```powershell
uv build host --out-dir build/host-dist
```

The package version is generated by `hatch-vcs` from repository Git tags (for
example `v0.1.0`), with development versions between releases. The generated
`host/src/info_tv_service/_version.py` is included in distributions and ignored
by Git and code checks. Builds without Git metadata or retained package metadata
fall back to `0.0.0`. Source distributions retain their version when rebuilt into
wheels. Ruff and ty settings live in `host/pyproject.toml`; generated protocol
bindings are excluded from checks. Ruff formatting is available explicitly with
`uv run ruff format` from `host/`; keep formatting changes scoped.

Python 3.12 is the default development interpreter in `host/.python-version`,
while package metadata permits Python 3.12 and newer. Select another interpreter
explicitly with `uv run --project host --python 3.14 ...`. Ruff and ty target the
minimum supported Python version. Ordinary dependency declarations specify lower
bounds; `uv.lock` fixes the reproducible installation. Protocol compiler/runtime
constraints remain narrower to match the checked-in bindings and vendored Nanopb
runtime; update and verify those together when upgrading protocol tooling.

## Demo limits

- One device, USB only; eight current conversation/task cards. Completed cards
  retire after five minutes by default; other states remain until manually closed.
  A later execution replaces its conversation's current run or reopens a retired one.
- Eight queued notices, 30-second start validity, ordinary/important display
  defaults of 5/10 seconds. Important notices interrupt ordinary notices; an
  interrupted ordinary notice ends. Three-row pages rotate every six seconds.
- Offline submissions retain task state without accumulating popup history.
- State is in memory. A USB power loss is a cold boot, not powered offline caching.
- English system labels; the bundled LVGL CJK font supports a limited character
  subset, not arbitrary Chinese. Full Chinese font coverage, automatic calendar
  producers, additional character actions, touch, Wi-Fi, BLE, and OS service registration remain
  future work. Closed-task protection retains 256 retired identities in memory.
