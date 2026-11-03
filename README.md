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
| `scripts/` | Protocol generation and example producer |
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
uv run --project host python scripts/demo_task.py
```

The script calls the real `POST /v1/task-events` endpoint. It submits one unique
run, advances from 0% to 100%, and generates a completion notice. Service
acceptance does not mean the screen has shown the content. Inspect
`GET /v1/tasks` and `GET /v1/device` for Accepted/Presented feedback.

The API supports `running`, `waiting_input`, `completed`, and `failed`. Retries
retain their UUID `event_id` and content. Updates for one `(source, task_id)`
use increasing positive `sequence` values. A new execution uses a new task ID.

## Build the firmware

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
uv run ty check . ../scripts
uv run python ../scripts/generate_protocol.py --check
```

Native firmware-core tests require CMake and a desktop C/C++ compiler, not an ESP32.
Run these commands from the repository root:

```powershell
cmake -S firmware/tests -B build/native-tests
cmake --build build/native-tests --config Debug
ctest --test-dir build/native-tests -C Debug --output-on-failure
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

- One device, USB only; four task records, retained until host restart.
- Eight queued notices, 30-second start validity, ordinary/important display
  defaults of 5/10 seconds. Important notices interrupt ordinary notices; an
  interrupted ordinary notice ends. Cards rotate every four seconds.
- Offline submissions retain task state without accumulating popup history.
- State is in memory. A USB power loss is a cold boot, not powered offline caching.
- English demo inputs; Chinese fonts, calendar/weather producers, animation,
  touch, Wi-Fi, BLE, and OS service registration remain future work.
