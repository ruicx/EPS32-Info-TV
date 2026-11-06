# info_tv

A local host service and ESP32-S3 display terminal. Producers submit task events
to a loopback HTTP API; the service sends structured Protobuf views over USB.

The first implementation supports task progress, completion/attention notices,
overview restoration, delivery feedback, and reconnect synchronization. The demo
has been flashed and tested on the physical board: USB, progress, notifications,
overview restoration, and powered serial reconnection passed. See the
[hardware validation record](docs/hardware-validation.md) for evidence and limits.

## Repository

| Directory | Responsibility |
| --- | --- |
| `host/` | Python 3.12, FastAPI, uv; portable core, initially tested on Windows |
| `firmware/` | ESP-IDF 6.1, FreeRTOS, C++, LVGL 9.3, ST7789 |
| `protocol/` | Shared schema, Nanopb bounds, and compatibility vector |
| `scripts/` | Protocol generation and development operations |
| `demos/` | Manual physical-display demonstrations using the production HTTP API |
| `docs/` | Requirements, hardware evidence, and implementation design |

See [implementation and class design](docs/demo-implementation.md),
[device protocol](docs/device-protocol.md), and
[hardware reference](docs/hardware-reference.md).

## Run the host

From the repository root:

```powershell
uv sync --project host --locked
uv run --project host info-tv --serial-port COM6
```

Use the currently enumerated port, not necessarily COM6. Linux/macOS serial
paths use the same option; these platforms remain untested. The API binds only
to `127.0.0.1:8765`, with documentation at `http://127.0.0.1:8765/docs`. Startup
retries an unavailable device while continuing to accept task state.

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

The API supports `running`, `waiting_input`, `completed`, and `failed`. Retries
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
revision passed desktop checks and a firmware build; it has not been flashed.
The original three-row overview was flashed on 2026-11-05; five cards and two notifications
reported actual device Presented feedback. The user confirmed physical text,
layout, and page rotation on the same date. Update the firmware together with the host: older firmware
does not advertise the required eight-card overview and task-icon capabilities.
See [current UI previews and weather API](docs/companion-ui-validation.md).
The header holds counts and page position; a full-body whale companion and weather
remain below the message area. One or two rows leave unused space black.
The companion now blinks and occasionally shifts its weight; see the
[actual LVGL animation preview](docs/companion-animation.md).
Weather comes from `PUT /v1/weather`, independently of task cards, and expires
locally. No city or weather provider is configured automatically.

Character artwork: [YunYueSama / codex-deepseek-pet](https://github.com/YunYueSama/codex-deepseek-pet),
modified by selecting a frame, trimming transparency, and resizing. See the
[asset attribution and license](firmware/main/ui/assets/README.md).

## Build the firmware

Device backlight settings are available through `PUT /v1/device/settings` with
`{"brightness_percent":30}` (integer 0..100; zero turns the backlight off).
`GET /v1/device/settings` distinguishes the target from device Applied feedback.
The host retains the target for its process lifetime and restores it on reconnect.
The brightness revision is built and desktop-tested, but not flashed. Update host
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

## Demo limits

- One device, USB only; eight current conversation/task cards, retained until
  host restart. A later execution replaces its conversation's current run.
- Eight queued notices, 30-second start validity, ordinary/important display
  defaults of 5/10 seconds. Important notices interrupt ordinary notices; an
  interrupted ordinary notice ends. Three-row pages rotate every six seconds.
- Offline submissions retain task state without accumulating popup history.
- State is in memory. A USB power loss is a cold boot, not powered offline caching.
- English system labels; the bundled LVGL CJK font supports a limited character
  subset, not arbitrary Chinese. Full Chinese font coverage, automatic calendar/weather
  producers, additional character actions, touch, Wi-Fi, BLE, and OS service registration remain
  future work. Card removal and automatic retention expiry are not implemented.
