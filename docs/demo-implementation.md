# Minimal Demo Implementation

Status: Implemented, build-tested, flashed, and validated on the physical board.

Updated: 2026-11-03

For the later task-retirement, manual-closure, YAML configuration, and automatic
weather implementation, see [Host lifecycle and weather](host-lifecycle-weather.md).
The original demo defaults and physical validation below describe the historical
Python baseline, whose sources now live in Git history. The production host is
Rust under `host/`; see the [current design](rust-host-design.md) and
[host guide](../host/README.md) for current source layout and commands.

## 1. Scope and Ownership

The production host framework accepts task events and maintains business state.
The firmware renders source-independent status cards and temporary notifications.
Only `demos/demo_task.py` supplies artificial events. There is no demo-specific
server endpoint or firmware mode.

Manual physical-display scenarios live in `demos/`, with their setup and expected
screen behavior documented there. `scripts/` retains development operations such
as protocol generation. Demos are not collected as automated pytest/CTest cases.

The host is named by its role rather than `windows/`. Its Python core and
pySerial transport accept platform-specific port paths. Only Windows has been
exercised; Linux and macOS support is not yet verified.

```text
POST /v1/task-events
  -> TaskService -> TaskStore
  -> generic card / notification
  -> DeviceSession -> Protobuf -> framing -> ByteTransport
  -> USB Serial/JTAG -> framing -> Nanopb -> command queue
  -> PresentationController -> DisplayState -> ScreenView -> DisplayDriver
  <- correlated Accepted / Presented feedback
```

## 2. Host Structure and Classes

```text
host/src/info_tv_service/
  app.py, __main__.py, config.py, runtime.py
  api/       models.py, routes.py
  tasks/     models.py, store.py, service.py
  device/    session.py, views.py, codec.py, framing.py
             transport.py, serial_transport.py, generated/
```

| Type | State and responsibility | Main interface |
| --- | --- | --- |
| `Settings` | Immutable startup parameters | Construct from CLI |
| `TaskEventRequest` | JSON and UTF-8 bounds validation | `to_event()` |
| `TaskEvent`, `TaskRecord`, `TaskUpdate` | Immutable domain values | Dataclasses |
| `TaskStore` | Runs, revisions, completion marker, dedup cache | `prepare()`, `commit()`, `list_tasks()` |
| `TaskService` | Atomic admission and display publication | `submit_event()` |
| `DeviceSession` | Connection, coalesced cards, notices, feedback | `run()`, `publish_card()`, `enqueue_notification()` |
| `ByteTransport` | Ordered async byte-stream structural interface | `open()`, `read()`, `write()`, `close()` |
| `SerialTransport` | One serial-owning I/O thread, bounded handoffs | Implements `ByteTransport` |
| `FrameDecoder` | Partial stream state and recovery | `feed()`, `reset()` |
| `ServiceRuntime` | Composition and supervised lifecycle | `start()`, `stop()` |

Views, envelope encoding, and frame encoding are functions. No module owns
global mutable state. FastAPI lifespan creates the runtime; one Uvicorn worker
owns task state and delivery. Blocking serial work stays in an owned thread,
joined on shutdown. Unexpected coordinator failure is logged and reported as
HTTP 503 instead of silently continuing admission.

`POST /v1/task-events` returns 202 with `accepted`, `duplicate`, or `stale` outcome,
card revision, and notification disposition. Conflicting identities/sequences
return 409; invalid input returns 422; exhausted capacity returns 503 before
committing task state. GET `/v1/tasks` and `/v1/device` expose content and actual
feedback. Recent delivery history is bounded.

## 3. Firmware Structure and Classes

```text
firmware/main/
  app_main.cpp, application.h/.cpp, config.h
  board/          board_config.h, display_driver.h/.cpp
  communication/  usb_transport.h/.cpp, device_session.h/.cpp
  protocol/       model.h, codec.h/.cpp, framing.h/.cpp, generated/
  ui/             display_state.h/.cpp, presentation_controller.h/.cpp
                  screen_view.h/.cpp
```

| Type | Owner and responsibility | Main interface |
| --- | --- | --- |
| `Application` | Components, queues, task entrypoints | `start()` |
| `UsbTransport` | Communication task; native USB I/O | `initialize()`, `read()`, `write()` |
| `DeviceSession` | Communication task; handshake, validation, heartbeat, feedback | `poll()`, `invalidate()` |
| `FrameDecoder` | Communication task; stream decoding | `feed()`, `reset()` |
| `DisplayCommand`, `Feedback`, `RenderModel` | Fixed-capacity owned values | No receive-buffer/widget pointers |
| `DisplayState` | UI task; cards, revisions, notices, identities | `applySnapshot()`, `upsertCard()`, `enqueueNotification()` |
| `PresentationController` | UI task; admission, priority, timers, feedback | `handleCommand()`, `tick()`, `onFramePresented()` |
| `ScreenView` | UI task; persistent LVGL widgets | `initialize()`, `render()` |
| `DisplayDriver` | UI task; panel, DMA storage, LVGL display bridge | `initialize()`, `present()`, `completedGeneration()` |

The communication task never touches LVGL objects. The UI task alone applies
commands and calls the LVGL timer handler. Driver completion only performs
flush-ready notification and atomic completion publication. Feedback congestion
requests session resynchronization rather than blocking local timers.

The overview shows up to three conversation/task rows per page, rotating pages
every six seconds. Waiting/failed cards sort before running and completed cards;
all pages rotate without starvation, and progress updates do not reset the timer.
Notifications
temporarily replace it without deleting cards. New service sessions discard
old-session ordering and queued events; same-session snapshots do not replay
notification history. Waiting/failed state survives its temporary notice.
The eight-card extension and LVGL screen have desktop verification and a firmware
build. The new revision was flashed on 2026-11-05; five cards and two notifications
returned device Presented feedback. The user confirmed physical text, layout,
and page rotation on the same date; earlier
detailed recovery evidence covers the single-card demo.

## 4. Resource and Runtime Baseline

| Concern | Baseline |
| --- | --- |
| Host | Python 3.12; exact packages in `uv.lock` |
| Firmware | ESP-IDF 6.1, LVGL 9.3.0, Nanopb 0.4.9.1 |
| UI integration | Direct loop; no second LVGL task or `esp_lvgl_port` |
| Tasks | UI priority 5 / 8 KiB; communication priority 4 / 8 KiB; no core binding |
| Handoffs | Four owned commands, sixteen feedback records |
| Display | RGB565, one internal 240 x 24 DMA buffer; 27 MHz SPI mode 3, matching vendor defaults |
| Memory | 16 MB Flash configuration; no PSRAM dependency |
| Logging | UART0; USB reserved for binary protocol |
| Persistence | In-memory on both sides |

Tunable times are centralized in host `config.py` and firmware `config.h`.
Wire capacities live in `device.options` and must change with both implementations.
There are no touch, media, Wi-Fi, BLE, or OS-service placeholders. Future
transports reuse the protocol boundary; future view types extend the schema
and rendering without adding device transport knowledge to producers.

## 5. Verification and Hardware Follow-up

Host tests cover ordering, duplicate/conflicting events, capacity, validation,
coalescing, retry identity, reconnect snapshots, and acceptance versus visibility.
Native tests cover stream recovery, Python-generated compatibility input, atomic
snapshot rejection, notifications, expiry, revisions, and presentation. The bridge
runs actual host HTTP and firmware codec/presentation code together with simulated
first-refresh completion.

C++ cases are registered with CTest and currently labeled `unit`. The Python
native bridge case is marked `integration`; it does not require a physical
device. Python declares a strict `hardware` marker and excludes it by default.
Future physical-device C++ cases must carry the `hardware` CTest label. Neither
suite currently contains a registered hardware case; the physical validation
record refers to a separate local manual harness.

Basic orientation, text, backlight, USB traffic, presentation feedback, notification
restoration, and powered serial recovery have passed. The user confirmed the
visual notification-to-overview transition. See [Hardware Validation](hardware-validation.md).
Detailed color/brightness calibration, numerical DMA latency, stack/heap headroom,
and performance remain unmeasured.
