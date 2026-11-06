# info_tv Requirements Analysis

Document status: Requirements baseline with deferred product tuning; the minimal USB demo is implemented and build-tested.

Created: 2026-11-02

Updated: 2026-11-03

## 1. Project Goals

Build a desktop companion display using an ESP32-S3 with a screen to present important calendar events, agent task status, weather, animated illustrations, and externally pushed messages.

Collect messages submitted by Codex CLI, Antigravity CLI, zcode, and other local producers, then present their useful information on a source-independent display. The confirmed solution direction and responsibility boundaries are recorded separately in [Software Architecture](architecture.md).

This document records product requirements rather than claiming that every capability is implemented. See [Minimal Demo Implementation](demo-implementation.md) for the implemented task/notification/USB subset and its temporary defaults, and [Hardware Validation](hardware-validation.md) for successful USB/display/recovery checks and user visual confirmation. The service directory is `host/`, with a portable Python core initially tested on Windows. In this document, **Confirmed** means explicitly stated by the user, supported by supplied source material, or observed in diagnostics, **Proposed** means a suggestion for discussion, and **To be confirmed** means more information or a decision is needed. Touch and PSRAM runtime operation remain untested.

## 2. Confirmed Information

### 2.1 Hardware and Physical Design

| Item | Current information | Evidence and limitations |
| --- | --- | --- |
| MCU | ESP32-S3 (QFN56), revision v0.2 | Identified by two matching esptool probes on 2026-11-03 |
| Connectivity hardware | Wi-Fi, Bluetooth LE, and native USB | Chip features reported by esptool; USB-Serial/JTAG identified on COM6; application-level messaging remains untested |
| Screen size | 1.54 inches | Provided by the user |
| Screen resolution | 240 × 240 | Provided by the user |
| Product form | An enclosed desktop device with a square display | Product image provided by the user |
| Display controller and interface | ST7789 over hardware SPI | Active vendor configuration uses `ST7789_2_DRIVER`; screen signals agree with the schematic |
| Display GPIO assignments | MOSI 1, clock 18, DC 17, reset 6, backlight 2 | Vendor display configuration and schematic |
| Top touch input | Touch electrode connected to GPIO5 | Documented in the schematic; touch detection and touch-driven page switching were not found in the reviewed application |
| Flash and PSRAM | Detected 16 MB Quad SPI Flash at 3.3 V; chip information reports 8 MB embedded PSRAM | Two matching esptool probes; differs from the user-reported `8M+8M` advertisement; PSRAM runtime operation remains untested |

The weather, clock, stock, and photo album screens shown in the product image are advertised product features. They do not establish requirements to reproduce those screens or prove that the original firmware exposes integration interfaces.

Firmware flashing follows the standard Espressif workflow using official tools such as `idf.py flash` or `esptool`. The actual connection and download-mode entry can be checked on the device. A vendor-specific flashing tool or the original firmware source code is not a prerequisite for developing replacement firmware. See the [official ESP32-S3 connection and flashing guide](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/get-started/establish-serial-connection.html).

Board-specific information is needed to configure peripherals in the new firmware: the screen controller and interface, GPIO assignments, backlight control, button wiring, and memory configuration. Successful flashing alone does not establish these details. A complete schematic is useful but not mandatory if the necessary information is available from a pin table, example project, or other reliable source. These details do not block requirements analysis or independent Windows-side work.

The user has supplied Arduino source code, bundled libraries, and a schematic. Display wiring, backlight control, touch electrode wiring, and native USB wiring have been reviewed. USB diagnostics subsequently identified the chip and memory specification. See [Hardware Reference](hardware-reference.md) for evidence, probe results, the advertisement discrepancy, existing application capabilities, and remaining on-device checks. ESP-IDF with its integrated FreeRTOS was subsequently selected for the new firmware; the supplied Arduino code remains a board reference. Implementation choices are tracked in the architecture documents.

### 2.2 Software Architecture Requirements

1. Run a Windows service process that receives messages submitted by local software, hooks, or sender adapters through a common interface.
2. Provide an ESP32 display service that presents content pushed by Windows.
3. Support Bluetooth, Wi-Fi networking, and USB communication between Windows and the ESP32.
4. Use a generic structured display model on the ESP32, supporting multiple message types independently of their sources.

All three communication methods are in scope. Their implementation order, primary transport, and switching policy have not been decided.

The confirmed direction is `producer -> Windows service -> ESP32`. Initial producer targets are Codex CLI, Antigravity CLI, and zcode. Producers submit messages to Windows rather than managing a direct ESP32 connection. This identifies intended integrations; it does not assume that each product already exposes a compatible native hook or message API. See D-05 for the service boundary.

### 2.3 Hardware Readiness for Requirements Analysis

The documented display configuration, detected ESP32-S3 revision, 16 MB Flash, reported 8 MB embedded PSRAM, and working USB diagnostic connection provide a sufficient hardware baseline for continued requirements analysis.

Remaining display, backlight, touch, PSRAM runtime, and application USB checks belong to implementation validation. They are tracked in [Hardware Reference](hardware-reference.md) and do not need to be completed before deciding product behavior. The exact commercial module ordering code is not a requirements prerequisite.

## 3. Use Cases and Functional Requirements

### FR-01 Important Calendar Events

- Display calendar events relevant to the user, with enough information to identify each event and its time.
- Keep the next eligible event in a compact overview entry. Expand it temporarily
  at reminder time, then return to the overview with the entry retained. Mark it
  ongoing at its start; remove it after ending or cancellation and select the next
  eligible event. With no eligible event, calendar content occupies no space.
- Deliver calendar content through the Windows service. The calendar producer or retrieval mechanism remains to be specified separately from the common message service.
- The criteria for identifying important events, calendar sources, display time range, and refresh frequency are to be confirmed.
- Update existing event information when new content arrives and remind the user when an important event is approaching. Reminder lead time, repetition, and cancellation delivery mechanisms are to be confirmed.

Acceptance direction: After selecting a calendar source, designated important events appear on the device. Changes and cancellations produce the agreed display behavior.

### FR-02 Agent Task Status and Notifications

- Display task execution status and related notifications submitted by Codex CLI, Antigravity CLI, zcode, and other agent software.
- Agent software, its hooks, or sender adapters submit messages to the common local Windows service; the service prepares the unified device display representation and handles downstream delivery.
- The service core does not need to launch agents, monitor their consoles, or parse their private transcript formats to receive a submitted message. Available submission mechanisms for each target remain to be verified during integration design.
- Supported task states include running, waiting for input, completed, and failed when reported by the source.
- Allow a task to select a built-in purpose icon independently of its state.
  The initial catalog is task, code, test, build, review, and deploy. Show a
  progress bar only when the producer reports a completion percentage.
- New status for the same task should update existing content rather than create a duplicate card for every change.
- Do not invent a progress percentage when actual progress is unavailable. Whether to show the current stage, elapsed time, or other information is to be confirmed.
- Keep concurrent tasks independent. Give waiting-for-input and failed tasks greater attention in the overview.
- Announce task completion once, then restore the overview. Retain completed task state for a limited period; its duration remains to be decided.
- Important waiting-for-input and failure notifications may end while the task remains prominent in the overview until a subsequent source update resolves or changes its state.

Acceptance direction: Run tasks in an integrated agent client and verify that its submitted key states and notifications reach the ESP32 through the Windows service without overwriting unrelated tasks. The sender does not need to know the ESP32 address, port, or active transport.

### FR-03 Weather

- Display weather content delivered through the Windows service. The weather producer or retrieval mechanism remains to be specified separately from the common message service.
- The city, data provider, fields, and refresh frequency are to be confirmed.
- Replace old weather content with new content, record its update time, and distinguish valid data, stale data, and retrieval failures.
- Whether to include current conditions, forecasts, and weather alerts is to be confirmed.

Acceptance direction: Display the agreed weather fields for the selected city. After a retrieval failure or expiry, the device does not present old data as current.

### FR-04 Animated Illustration Playback

- Support animated illustrations and coordinate their playback with information pages.
- Play animations during idle periods and let important notifications interrupt them. Return to normal information display when playback ends. Detailed idle timing, duration, and looping rules remain open.
- Asset formats, dimensions, storage location, quantity, and target frame rate require hardware information and testing on the device.
- Proposed approach: preprocess assets on Windows, then cache and play them locally on the ESP32. This approach has not been finalized.

Acceptance direction: Play designated assets on the device. Entering and leaving playback restores information pages according to the agreed behavior.

### FR-05 Generic Message Push

- Provide a common local message ingestion interface in the Windows service for applications, scripts, hooks, and sender adapters.
- Validate accepted message content, prepare a unified device display structure, and manage downstream ESP32 delivery in the service process.
- Producers only submit messages to the service; device connection management and the active USB, Wi-Fi, or BLE transport are service responsibilities.
- Define required fields, supported content types, size limits, and feedback for invalid input.
- The initial interface accepts messages only from scripts, hooks, and applications on the same Windows computer. LAN and internet callers are outside the initial scope.
- Support same-object updates and suppress duplicate event notifications. Define validity so expired reminders are not replayed after reconnection.
- Distinguish service acceptance, pending device delivery, and actual display. Report submission failure clearly when the service is unavailable. Accepting a message while the device is offline does not mean it has been displayed.
- Message withdrawal and history queries remain undecided.

Acceptance direction: Valid messages from at least two local producer identities reach the device through the same service interface. Invalid messages receive clear feedback without disrupting subsequent valid messages. Changing the active device transport does not require changing producer submissions.

### FR-06 Multiple Communication Transports

- Support display message delivery over USB, Wi-Fi, and Bluetooth.
- Reuse display message semantics across transports so that the same content has the same meaning on each transport.
- Base Bluetooth communication on ESP32-S3 BLE capabilities rather than Bluetooth Classic SPP.
- Requirements for discovery, automatic reconnection, automatic switching, and simultaneous transport connections are to be confirmed.
- Discuss device acknowledgments, connection status, and error reporting in addition to downstream delivery.

Acceptance direction: Each of the three transports delivers and displays agreed messages. Disconnection and recovery behavior follows the finalized rules.

### FR-07 Generic Structured Display

- Render structured content on the device without parsing the original business protocols of calendar services, weather services, or agents.
- Allow multiple sources to reuse the same display type.
- Define the scope of a display type without assuming arbitrary HTML, unrestricted layouts, or script execution.
- Proposed initial types are text cards, list cards, status cards, metric cards, and media cards. Final types and fields are to be confirmed.
- Behavior for unsupported display types, oversized content, and unavailable assets is to be confirmed.

Acceptance direction: Two different sources display content using the same structured display type. Adding a source does not require source-specific recognition logic on the device.

Detailed presentation will be refined through rendered previews. Layout, typography, colors, spacing, information density, and text overflow presentation are not frozen during requirements analysis. See D-04 in Section 12.

## 4. Architecture Reference

The confirmed message flow, producer/service/device responsibilities, and open implementation choices are maintained in [Software Architecture](architecture.md). Requirements below specify observable behavior without selecting a message schema, protocol, or technology stack.

## 5. Display and Message Lifecycle

Status: The initial behaviors in this section were accepted by the user on
2026-11-03. The four content categories and next-event calendar presentation were
accepted on 2026-11-05. Explicitly open details remain undecided.

### 5.1 Content Categories

The accepted product categories are task status, schedule reminders, information
cards, and instant notifications. Task status includes agent executions;
information cards include weather and potential device metrics. Their layouts
can differ. Compact agent rows with preset icons, title, state, and optional
progress bars are implemented in the desktop-verified revision. Execution-time
semantics and fields remain undecided; time is not yet displayed.

Connection, offline, and empty states belong to the interface. Clock and
animation playback belong to idle presentation rather than an additional message
category. See [Message Interface and Screen UI Design](message-ui-design.md#accepted-content-classification)
for category definitions and implementation status.

Content uses two lifecycle behaviors:

| Category | Examples | Required behavior |
| --- | --- | --- |
| Persistent state | Current weather, next eligible calendar event, current task status | Replace existing content when the same object is updated |
| One-time notifications | Task completion, meeting reminders, external messages | Enter a notification queue, display according to policy, then leave |

These lifecycle behaviors do not require two separate message formats in the final
protocol. A task can have both a persistent status entry and a temporary
transition notification; the notification does not resolve the underlying task.

### 5.2 Task Updates and Attention

- Repeated progress updates replace the existing task state. Rapid intermediate updates are combined so that the latest state takes precedence.
- Concurrent tasks retain independent state. A failure or request for input in one task does not overwrite another task.
- Waiting-for-input and failed tasks receive greater attention in the overview. Dismissing or timing out their notification does not resolve the task state.
- Task completion generates one completion notification. Completed state remains visible for a limited period before removal; that period is still open.
- Duplicate submissions of the same event do not repeatedly interrupt the user. Multiple simultaneous completions may be summarized while preserving the individual task states.

### 5.3 Notification Scheduling and Restoration

- Important notifications can interrupt ordinary notifications and idle animations.
- Notifications of equal priority are shown in arrival order.
- Initial display durations are 5 seconds for an ordinary notification and 10 seconds for an important notification. These are provisional defaults accepted for initial use and may be tuned after experience with rendered or device previews.
- After notification display ends, restore the overview. A waiting-for-input or failed task remains prominent there until a subsequent update changes its state.
- How an interrupted ordinary notification resumes or is requeued remains to be decided.

### 5.4 Current Content, Animation, and Reconnection

- Calendar and weather updates replace their older content. Stale information is distinguishable from current information.
- Approaching important events produce reminders; their lead time remains open.
- Idle animations yield to important notifications. Normal information display resumes when playback ends.
- After reconnection, synchronize current valid state rather than replay every intermediate progress update.
- Do not replay expired reminders. The replay policy for other unexpired one-time notifications remains open.

### 5.5 Submission and Delivery Feedback

- Make service acceptance distinguishable from actual display on the device.
- A message accepted while the device is offline is pending delivery, not already displayed.
- Report submission failure clearly if the service is unavailable. Report invalid input without disrupting subsequent valid messages.
- Feedback representation, acknowledgment mechanisms, queue limits, and persistence across process or device restarts belong to later design or unresolved reliability requirements.

## 6. Screen and Interaction Constraints

- Limit information per page on the 240 × 240 screen, prioritizing readability of important content.
- Define font coverage for Chinese, English, numbers, and common symbols. Arbitrary pushed content may contain characters outside a fixed font subset.
- Define truncation, pagination, or scrolling behavior for long text.
- Whether to display the source, time, connection status, and data update time is to be confirmed.
- The schematic documents a top touch electrode on GPIO5. Define its intended actions during requirements analysis, then validate sensing and interaction behavior during implementation. Do not assume the device has a touchscreen.
- An RGB565 full-screen pixel buffer requires 115,200 bytes, approximately 112.5 KiB; two buffers require approximately 225 KiB. This excludes fonts, decoding, networking, and other runtime memory.
- Do not commit to animation frame rates, asset capacity, or refresh performance before confirming the screen interface and available memory.

## 7. Operation and Reliability Requirements

The following topics need concrete behavior and measurable criteria once the approach is agreed:

| Topic | Behavior to define |
| --- | --- |
| Windows service operation | A background service process is required; startup, shutdown, configuration, Windows Service Control Manager registration, and any optional tray UI remain design decisions |
| Windows sleep or application exit | Keep cached information, mark disconnected or stale content as appropriate, and continue the local clock and cached animation playback; expiry and reconnection details remain open |
| Device restart | Default page, reconnection, and state restoration |
| Stale data | Validity periods and expiry indicators for each content category |
| Message bursts | Combine rapid progress updates, suppress duplicate event notifications, and optionally summarize simultaneous completions; queue capacity, rate limits, and drop policies remain open |
| Communication failures | Retry scope, retry limits, and failure reporting |
| Interface access | Restrict initial ingestion to callers on the Windows host; define the local interface and any caller checks during design |
| Diagnostics | Minimum logs, connection information, and failure details |
| Performance | Acceptance targets for notification latency, page responsiveness, animation frame rate, and continuous runtime |

Keep logs clearly separated from display protocol data so that debug output cannot be interpreted as display messages.

## 8. Capabilities Not Included by Default

The user has not requested the following capabilities, so they are not mandatory requirements for this phase:

- Approving agent actions or sending agent control commands from the device.
- Running agents on the ESP32 or executing code embedded in pushed content.
- Independently integrating all information sources without Windows.
- Arbitrary web rendering, live desktop mirroring, or continuous video streaming.
- Multiple-device management, a cloud platform, historical message search, or remote firmware updates.
- Reproducing every original product page, including stocks and photo albums.

If any of these capabilities are needed later, add explicit requirements and acceptance criteria.

## 9. Behavioral Acceptance Scenarios

| ID | Scenario | Expected behavior |
| --- | --- | --- |
| AC-01 | One task reports several progress updates rapidly | One task remains represented, with the newest accepted state; intermediate progress does not create repeated notification cards |
| AC-02 | Task A is running while task B requests input | Both states remain available, and B receives greater attention |
| AC-03 | A task completes and the same completion event is submitted again | Announce the completion once, restore the overview, and retain completed state for the eventual agreed retention period |
| AC-04 | A waiting-for-input or failure notification times out | Restore the overview while keeping that task prominent until a subsequent source update changes it |
| AC-05 | An important notification arrives during ordinary notification display or idle animation | The important notification takes priority; equal-priority notifications retain arrival order; initial notification durations are 5 seconds ordinary and 10 seconds important |
| AC-06 | Updated calendar or weather content arrives and later becomes stale | Replace previous content, preserve the update time, and distinguish stale information according to the eventual expiry policy |
| AC-07 | The device disconnects, progress changes, a reminder expires, and the device reconnects | Synchronize current valid state without replaying intermediate progress or the expired reminder |
| AC-08 | A message is accepted while the device is offline | Report acceptance and pending delivery without claiming actual display |
| AC-09 | The service is unavailable, or a caller submits invalid content | Give clear failure feedback; invalid content does not disrupt subsequent valid submissions |

These scenarios define behavior, not test implementation. Values and policies explicitly left open elsewhere must be settled before their corresponding acceptance check is finalized. The proposed implementation validation sequence is in [Software Architecture](architecture.md).

## 10. Open Questions

### 10.1 First Priority: Product Behavior and Source Integration

1. Deferred trial tuning: completed-task retention, stale-data thresholds, and restart retention will be decided after observing prototype behavior, as agreed by the user. Calendar reminder lead time, handling of interrupted ordinary notifications, and replay of unexpired one-time notifications also remain open. These are tracked decisions, not blockers to architecture discussion.
2. Existing firmware reuse: whether original firmware features must be retained. Arduino source code and supporting libraries are available as references; their availability does not require retaining the original application or choosing Arduino for the new firmware.
3. Agent integration: Codex CLI, Antigravity CLI, and zcode are identified as producer targets. Their versions, available submission mechanisms, required events, and sender setup remain to be determined.
4. Deferred restart behavior: which cached or pending state survives service or device restarts will be evaluated with the prototype. Cached offline operation while powered and current-state synchronization are confirmed; independent device-side calendar and weather retrieval is outside the initial scope. Persistent storage is not implicitly required by the current decisions.

### 10.2 Second Priority: Initial User Experience

1. What produces calendar messages? Are important events marked manually or selected by rules, and are advance reminders needed?
2. What produces weather messages, and which city and fields should be displayed? Are forecasts or alerts needed?
3. How should multiple tasks and events fit within the overview while keeping waiting-for-input and failed tasks prominent? Detailed layout will be refined through rendered previews.
4. What additional events qualify as important notifications beyond waiting-for-input and failure, and are repeated reminders needed?
5. How is idle time determined, where do animation assets come from, and should users be able to upload them? Idle playback and important-notification interruption are confirmed.
6. What is the preferred order of the three transports, and is automatic switching required?
7. Should message withdrawal, history queries, or pending-message persistence be included in the initial scope? Interface fields and protocol formats are design topics tracked in the architecture document.
8. What actions should the top touch button support, including notification acknowledgment or dismissal?

## 11. Requirements Completion Criteria

Use the following criteria to finalize the initial requirements. The hardware baseline is sufficient for this discussion; remaining hardware tests are implementation validation tasks rather than requirements completion gates.

- The common message interface's required behavior, display content, and initial producer setup are defined. Product-specific event capture is specified per integration rather than embedded in the service core.
- Normal display behavior, offline behavior, and the calling scope of the push interface are defined.
- Rules for updates, interruption, disconnection recovery, and page restoration are defined; deferred tuning and retention policies are explicitly tracked.
- The initial transport and the goals and implementation order for the remaining transports are defined.
- Initial use cases have concrete input examples, expected display behavior, and acceptance targets.

Detailed visual design does not need to be finalized to complete requirements analysis. It will be iterated through rendered previews under D-04.

The user agreed to defer completed-state retention, stale-data timing, and restart-retention choices until prototype evaluation. Architecture discussion can proceed without final values or a finalized persistence policy. An initial prototype must state its temporary retention behavior before evaluation; temporary choices do not imply confirmed product requirements.

Update this document throughout the requirements discussion. Move resolved items from Proposed or To be confirmed into Confirmed while retaining unresolved questions.

## 12. Initial Behavior Decisions

Status: D-01 through D-06 were confirmed by the user on 2026-11-03. These decisions define product behavior, solution constraints, and the visual review process; they do not select a technology stack or protocol format.

### D-01 Normal Display Mode

Confirmed: Normally display an overview of weather, important calendar events, and agent status. Important notifications temporarily interrupt the normal display.

Acceptance direction: Normal operation provides the agreed overview, and an important notification can temporarily take display priority. Use the scheduling, provisional durations, and overview restoration rules in Section 5. The detailed arrangement and amount of visible information will be refined through rendered previews.

### D-02 Behavior When Windows Is Unavailable

Confirmed: When Windows shuts down, sleeps, or disconnects, retain cached information, mark disconnected or stale content as appropriate, and continue the local clock and cached animation playback. Independent device-side source integrations are outside the initial scope.

Acceptance direction: Disconnect Windows after content has been delivered. Cached information remains available, its offline or stale status is distinguishable, and local clock and cached animation operation can continue while the device remains powered. The form of the status indication will be refined through rendered previews.

Continuing a local clock while powered does not imply retaining accurate time through a power loss. Time synchronization, restart behavior, data expiry, and reconnection synchronization remain separate decisions.

### D-03 Generic Push Interface Calling Scope

Confirmed: The initial push interface serves scripts, hooks, and applications running on the same Windows computer. Direct LAN and internet callers are outside the initial scope.

Acceptance direction: A program on the Windows host can submit a valid message and receive the agreed feedback. The ingestion interface is not exposed to LAN or internet callers.

This decision concerns who can submit messages to Windows. It is independent of whether Windows communicates with the ESP32 over USB, Wi-Fi, or BLE. Local-only ingestion can still retrieve weather or calendar data through outgoing network requests.

### D-04 Visual Refinement Through Rendered Previews

Confirmed: Render the display before finalizing detailed presentation, then adjust it based on the visible result. Requirements establish the content categories and product behavior while layout, typography, colors, spacing, information density, and text overflow presentation remain open for visual iteration.

Acceptance direction: Review rendered previews at the target 240 × 240 resolution using representative calendar, agent, weather, notification, and offline content. Refine presentation from that review without treating every visual adjustment as a change to the accepted product behavior. Exact visual settings are not prerequisites for continuing requirements analysis.

### D-05 Common Windows Message Service

Confirmed: Codex CLI, Antigravity CLI, zcode, and other local producers submit messages to a Windows service. The service process owns content handling and downstream delivery to the ESP32. Producers do not communicate with the ESP32 directly.

The message flow and detailed responsibility boundaries are recorded in [Software Architecture](architecture.md). Application names identify producer targets, not guaranteed built-in hook support.

The user also confirmed the overall process and module framework: one Windows service process with internal modules, separate producer/device message contracts, Windows-managed business state, and ESP32-controlled presentation. Technical protocols, languages, and deployment details remain design decisions in the architecture document.

Acceptance direction: Two different producers can submit messages through the same local interface and have them displayed through the service. Producers do not require ESP32 connection details. Switching the service's active device transport leaves the producer-facing interface unchanged.

### D-06 Task, Notification, and Recovery Behavior

Confirmed: Adopt the task update, concurrent-task attention, completion, important-notification persistence, calendar/weather refresh, idle animation, reconnection, duplicate suppression, and delivery feedback behaviors in Section 5. Use provisional 5-second ordinary and 10-second important notification durations. The acceptance scenarios in Section 9 express the initial observable outcomes.

Notification expiry ends the temporary interruption; it does not resolve the underlying waiting-for-input or failed task state. Remaining retention, expiry, interruption-resumption, and restart-persistence details stay open rather than being assigned implicit defaults.

### Next Discussion Topics

Proceed with the architecture discussion in [Software Architecture](architecture.md). Revisit deferred timing and retention choices during prototype evaluation. Continue defining calendar/weather content and producers and touch input actions as needed, while keeping visual refinement in rendered previews.
