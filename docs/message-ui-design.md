# Message Interface and Screen UI Design Draft

Status: The multi-conversation overview direction has been accepted. Tasks and producer-supplied weather are implemented and desktop-tested; calendar, external weather retrieval, and general notifications remain proposals. The original firmware was flashed on 2026-11-05. Five cards and two notifications received actual device Presented feedback, and the user confirmed that physical text, layout, and page rotation were normal.

Visual update: The compact bubble layout and task-purpose icons below are a subsequent firmware UI
revision. Its desktop previews and verification are recorded in
[Bubble UI validation](bubble-ui-validation.md); the earlier physical confirmation
applies to the original layout.

Current layout (2026-11-06): Three compact rows share the screen with a full-body
whale companion and persistent weather. Counts and page position are in the
header. Sparse pages leave black space, and zero tasks show a short idle label.
This supersedes the five-row layout. See
[Companion UI validation](companion-ui-validation.md) for current previews, the
weather API, asset attribution, and desktop verification. It has not been flashed.

Date: 2026-11-05

## 1. Design Goals

The device is a 1.54-inch, 240 × 240 desktop information display. At a glance, the user should be able to tell what is happening, whether anything needs their attention, and when the next event will occur.

Assumptions: The Windows service remains the main source of content. This draft defines message semantics and screen layouts without implementing new producers. The screen is intended for short summaries; long-form reading, logs, and approval of agent actions remain on the computer. Source names are display labels, and firmware behavior does not branch on names such as Codex or zcode.

Keep the accepted behaviors: separate persistent state from notifications, update the same object in place, prioritize important notifications, restore the overview afterward, and synchronize current valid state after reconnection. Retention periods, rotation timing, and idle animation timing remain subject to trial tuning.

## 2. Messages to Display

### Accepted Content Classification

The user accepted these four categories on 2026-11-05. Classification does not
require every category to use the same bubble height or number of text lines.

| Category | Examples | Lifecycle | Implementation status |
| --- | --- | --- | --- |
| Task status | Codex or agy execution state | Update one persistent entry per conversation/task; state transitions can also notify | Compact rows, preset icons, and progress bars implemented; not flashed |
| Schedule reminder | Upcoming meeting or deadline | Keep the next eligible item in the overview and temporarily expand it at reminder time | Not implemented |
| Information card | Weather or a device metric | Replace current values and show freshness/validity | Producer-supplied weather occupies the persistent area; generic metrics and weather retrieval are not implemented |
| Instant notification | External message, task completion, or failure alert | Temporarily display, then restore the overview | Task transition notifications implemented; generic external notification API not implemented |

Task status and its transition notification describe the same underlying task.
Showing or dismissing the temporary notification does not create, remove, or
resolve its persistent entry. Connection, offline, and empty states are interface
states; clock/animation playback belongs to the idle presentation.

### Content Examples

| Scenario | Question the screen should answer | Persistent content | One-time notification |
| --- | --- | --- | --- |
| Agent running | Which project, what work, and which stage? | Source, task title, current stage; percentage only when real progress is available | Ordinary progress changes do not notify |
| Agent waiting for input | What needs me to return to the computer? | Task title, reason for waiting, clear next step | Important notification on entering the waiting state |
| Agent failed | What failed, and where should I handle it? | Task title, short reason, next step | Important notification on entering the failed state |
| Agent completed | What finished, and what was the result? | Short result, removed according to a retention policy to be decided | Notify once per completed task |
| Calendar | What is the next important event, and how soon? | One next eligible event, with title and time; retain it as ongoing until it ends | Expand at the agreed reminder lead time, then restore the overview |
| Weather | Which location, what conditions, and how fresh is the data? | Location, conditions, temperature, update time; optionally one additional measure | Ordinary refreshes do not notify; weather alert integration is a separate decision |
| External notification | What just happened, and does it need attention? | Does not enter persistent content by default | Title, two-line summary, source, ordinary or important priority |
| Idle companion | Is there anything that needs attention? | Local time and optional cached animation | Important notifications can interrupt |

Group waiting-for-input and failed tasks in an attention area while retaining their distinct status text. Not every error requires user action; the producer must provide an accurate next step. A notification disappearing does not mean the task has been resolved.

Keep full chat responses, reasoning traces, terminal logs, stack traces, and patches on the computer. The display can show their short results, waiting reasons, or failure summaries.

## 3. Pages and Information Hierarchy

### Single-Card Focus

One item per screen supports viewing from farther away and is a candidate when there are few persistent items:

```text
+--------------------------------+
| Codex | info_tv        Running  | Source and state
|                                |
| Improve message API            | Main title, at most two lines
| Checking protocol compatibility| Stage or summary, at most two lines
|                                |
| ==================       65%   | Only when real progress is available
| 2 other items | 1 needs input  | Global context
| USB online               1 / 3 | Connection and position
+--------------------------------+
```

When tasks are waiting or have failed, prioritize their content while preserving display opportunities for other tasks. Progress updates must not restart rotation or let a high-frequency producer occupy the screen indefinitely. Detailed weights and timing remain trial settings.

### Compact Task Overview

Show at most three rounded message bubbles at once. Each has a task-purpose icon,
conversation title, and compact state on one text line. A thin progress bar uses
reserved space below the text when a percentage is known. Rotate groups when
there are more than three entries. Source, project, and detail appear in the
expanded notification; producers should use distinguishable short titles.

All bubbles are rounded rectangles with smooth edges and no tails.
Task purpose is independent of source identity.
Use a dark background, muted metadata, and softly tinted surfaces. Amber, red,
green, and blue accents accompany the state text for attention, failure,
completion, and ordinary progress. Offline bubbles use a neutral surface and
an `Offline` indicator without a live percentage. Keep the connection indicator
in the persistent area and the page count in the header, outside the bubbles.

The bottom 88 px are reserved for a full-body character on the left and weather
plus connection state on the right. One or two rows stay aligned to the top;
unused slots remain black. Zero tasks show `No tasks yet`. The bottom area does
not move when cards arrive, leave a partial page, or are replaced by a notification.

Both layouts use the same content model. Choosing a layout must not require callers to change their submissions, and both layouts do not have to be implemented together.

### Compact Agent Layout and Pending Execution Timing

A single-line rounded rectangle shows `icon | title | state` for agent tasks.
Known states use `RUN`, `WAIT`, `DONE`, and `FAIL`. Reserve a fixed width for state,
truncate the title to the remaining width, and keep source/project/detail in the expanded notification.
Short titles should distinguish conversations when their names would otherwise
be identical. Three entries fit per page in the desktop-verified implementation.
Elapsed time is omitted until its meaning and reporting are confirmed.

Execution timing is not available in the current task API or device view.
The proposed meaning is elapsed time for the current execution, including input
waiting, frozen on completion/failure and reset for a new execution. This timing
definition is not yet confirmed. Start/end reporting, unknown timing, and offline
behavior must be specified before implementing the timer.

### Task Icons and Progress Bars

Allow producers to select a built-in task-purpose icon with an optional `icon`
identifier. The initial catalog is `task` (default), `code`, `test`,
`build`, `review`, and `deploy`. These describe task purpose; state text and its
color continue to express running, waiting, completed, or failed status.
Source names do not select icons implicitly. The device stores the icon artwork;
messages carry only a catalog identifier.

The compact layout is `icon | title | state`. A thin progress
bar sits inside the bottom of the same rounded rectangle when a percentage is
available. Reserve its space so progress appearing or disappearing does not move
neighboring entries. Body text remains on one line; title width must be checked
at the native 240 x 240 resolution. The notification layout can use the same icon
with its larger progress bar.

Reuse the existing optional integer `progress_percent` field in the range 0..100.
An omitted or null percentage hides the bar; zero is valid known progress. The
producer reports completion percentage; the display does not estimate it from
elapsed time. A value of 100 does not independently change task state, and a
completed state does not invent an unreported percentage. Waiting and failure
can retain their last reported percentage while state text/color remain explicit.
Offline cached content continues to hide percentages and progress bars.

Task-event fields (a fragment, not a complete request):

```json
{
  "icon": "test",
  "title": "Unit tests",
  "state": "running",
  "progress_percent": 42
}
```

Implementation status: The API accepts the six `icon` strings and rejects unknown
values with 422; omitting the field selects `task`. Each event is complete state,
so later updates must repeat an icon that should remain selected. Cards and
notifications share the same preset. The firmware uses bundled LVGL symbols,
not arbitrary images or emoji. The host requires `Hello.task_icons = true`
before synchronization, so this revision needs a paired host/firmware update.
All six presets and progress presence are covered by desktop tests; the new
firmware has not been flashed.

### Multiple Agent Conversations Updating Continuously

Additional scenario: The user has several Codex and agy conversations open simultaneously. The default page for this case is the conversation overview; single cards present important content and state-transition notifications. The current UI supports at most eight persistent task entries, three per compact page, with six-second rotation. Weather has a separate slot.

**Each conversation has one persistent display entry.** Task updates within that conversation replace its entry, while other conversations remain independent. Do not collapse all conversations from one application into one entry or create a new card for every chat response.

Distinguish three identity levels:

| Identity | Purpose | Lifetime |
| --- | --- | --- |
| `source` | Producer namespace, such as `codex` or `agy` | Unchanged when a window title changes |
| `conversation_id` (added) | Stable conversation identity; together with `source`, identifies its display entry | Retained across interactions; adapters must prevent collisions between instances of the same source |
| `task_id` (existing) | One execution within a conversation | New ID for each execution, preserving existing ordering and completion deduplication |

Events are still processed by `(source, task_id)`. With conversation association, the host projects task state onto a `(source, conversation_id)` entry. Do not simply reuse a long-lived conversation ID as `task_id`: completion deduplication applies to one execution, so reuse would suppress completion notifications for later executions. HTTP `conversation_id` is also distinct from the device protocol's service `session_id`.

A readable `conversation_title` has been added, and `context` identifies the project or workspace. The compact overview shows the icon, title, and state, with optional progress below. Notifications show "source #short-card-ID | project" as metadata. The short ID is the first four characters of the service-assigned card UUID. It is only a visual aid and does not replace the full identity. Titles and paths are not identity keys either.

```text
+--------------------------------+
| 8 tasks       2 need you   1/3  |
| ( [code] Message API    WAIT )  |
|                                |
| ( [build] Login flow    FAIL )  |
|                                |
| ( [test] Unit tests      RUN )  |
|   ========-----------------    |
|                                |
| Full-body companion  Shanghai  |
|                       23 C     |
|                       Clear    |
|                       USB online|
+--------------------------------+
```

Display behavior:

- Show at most three conversations per compact page. Keep the page stable when everything fits; otherwise rotate groups every six seconds. The header holds page position when there is more than one page, and a nonzero global attention count.
- Sort waiting and failed conversations first, running conversations next, and recently completed conversations last. Preserve stable ordering within each group. Visit every page before repeating so unresolved attention items cannot permanently hide other conversations.
- Ordinary progress and summary updates change the existing entry without jumping pages or resetting the rotation timer. Entering waiting or failed state triggers one important notification. After it ends, restore the overview page containing that conversation, then continue rotation.
- Notify once when an execution completes. When the next execution begins in the same conversation, its existing entry returns to running state. The adapter explicitly associates the current execution; delayed results from an older execution cannot replace it.
- The first version assumes one current execution per conversation. If parallel executions within a conversation are needed later, define aggregation rules rather than treating the last received task as the state of the entire conversation.
- Closing a conversation needs explicit removal semantics. A lack of new events does not establish closure. Retirement timing for recently completed or idle entries remains subject to trial tuning. Execution completion, an actual input request, and a long period without updates are distinct conditions.

The host maintains each conversation's current display state. The device still receives source-independent status/list content and does not need to understand Codex or agy. Existing callers without conversation fields retain independent task-card behavior.

Phase one increases both host and device capacity to eight entries. The protocol bound for eight maximum-length cards still fits within 4096 bytes. At capacity, new entries are rejected, while updates and new executions for existing conversations remain admissible. Closing/deletion and automatic retirement are not implemented; records remain until service restart. A ninth conversation must not silently replace another one.

Conversation request example (implemented and accepted):

```json
{
  "event_id": "d48b883e-d76f-4b5c-a3e6-d4a44e155746",
  "source": "codex",
  "conversation_id": "thread-01",
  "conversation_title": "Message API",
  "context": "info_tv",
  "run_sequence": 2,
  "task_id": "run-02",
  "sequence": 1,
  "state": "running",
  "title": "Check protocol",
  "detail": "Checking protocol compatibility"
}
```

Supply `conversation_id` together with a positive integer `run_sequence`. Increment `run_sequence` for each new execution within that conversation; increment `sequence` only within its execution. Reports from older executions are stale. Different tasks claiming the same execution ordinal, or moving a task to another conversation, return 409. Omitting conversation fields preserves the original single-task semantics. `GET /v1/tasks` returns the current execution for each persistent entry, not execution history.

Each submission is complete state. Later updates should include any conversation title and project label that must remain visible; this API does not apply partial field patches.

System labels remain English. The enabled LVGL Source Han Sans SC 16 px CJK font is a subset and cannot cover arbitrary Chinese input. Complete simplified-Chinese coverage still needs a separate font asset pass. The desktop screenshots show supported Chinese examples, not a guarantee that every Chinese character can be displayed.

### Notification Page

Use one 110 px message bubble in the upper area, retaining the companion/weather
area. Source/project, title, state, and summary each occupy one bounded line,
with an optional progress bar. Longer text truncates; full details remain on the
computer. Retain the overview's typography and state colors. Do not add
confirmation, approval, or retry buttons.

Keep the initial defaults of five seconds for ordinary notifications and ten seconds for important notifications. Equal-priority notifications retain arrival order; important notifications can interrupt ordinary ones. Whether an interrupted ordinary notification resumes remains an open product rule; the current demo ends it.

### Daily Information and Idle Pages

Keep one next eligible calendar item in the overview as a compact title/time
entry. At the reminder lead time, temporarily expand it to show supporting
details such as location or joining instructions. Restore the overview afterward
while retaining the calendar entry. Mark it ongoing when it starts; when it ends
or is canceled, remove it and select the next eligible item. If no eligible item
exists, calendar content occupies no space. The source, eligibility rules, and
reminder lead time remain open; this behavior is not implemented yet.

Weather uses one main temperature with city and condition in the persistent
area. Missing data shows `Not set`; expired cached data shows `Stale` with a
dimmed temperature. This state is separate from USB connection status. A static
full-body character stays beside it, with local blinking and occasional weight
shifts documented in [Companion animation](companion-animation.md). Time and
additional animation must not obscure
message content. External weather retrieval and other information cards remain
future work.

### Text, Color, and Expiry

- Initial proposed sizes are 16 px for Chinese body text and 20 px for main titles, checked at the native 240 px screen size. Actual fonts and character coverage require firmware validation.
- Current compact and notification titles/summaries each occupy one line. Truncate at complete character boundaries, with no scrolling text by default. Callers should provide short summaries.
- Convey running, attention, completed, and failed states with both text and color. Color must not be the only indicator.
- Disconnection is a connection condition; expiry is a content condition. Express them separately. Weather can show "Updated at 14:20 / Data expired". Offline task content should say "Last reported: running" rather than imply live execution.
- Omit durations when there is no reliable basis. Last update time, execution elapsed time, and current-stage elapsed time are different measures.
- Ended, canceled, or expired calendar events must not remain labeled as upcoming. The device needs local validity checks while disconnected, rather than relying solely on the next host update.

## 4. Two Interface Boundaries

### Producer to Windows: Business Facts

Keep `POST /v1/task-events` and its four states and identity semantics. Phase one adds optional conversation fields and project labels, as shown above. A separate `next_action` field remains a proposal; use `detail` for the next step today.

The following request is accepted by the **existing interface**. Its `detail` carries both the reason and next action:

```json
{
  "event_id": "a48b883e-d76f-4b5c-a3e6-d4a44e155743",
  "source": "codex",
  "task_id": "info-tv-ui-run-01",
  "sequence": 3,
  "state": "waiting_input",
  "title": "Improve message API",
  "detail": "Confirm notification retention; return to your computer",
  "progress_percent": null
}
```

Task identity is `(source, task_id)`. Increment `sequence` within one execution and use a new `task_id` for a new execution. Retries retain the same `event_id` and all content. If the progress percentage is unknown, omit it or send `null`; zero must not stand in for unknown progress.

Propose a separate `POST /v1/notifications` endpoint for scripts, calendar reminders, and external messages that do not belong to a task. This is an **unimplemented draft**:

```json
{
  "event_id": "b58b883e-d76f-4b5c-a3e6-d4a44e155744",
  "source": "calendar",
  "title": "Project meeting starts soon",
  "detail": "Starts at 15:00; join from your computer",
  "priority": "important",
  "expires_at": "2026-11-05T15:05:00+08:00"
}
```

Require a timezone-aware `expires_at` in this proposal. Expired notifications must not begin display; the service's default policy determines display duration. The business deadline and the five-/ten-second display duration are separate concepts. Retrying the same `event_id` with identical content must not repeat the notification; reusing it with different content is a conflict.

The service generates notifications for task state transitions. Producers must not also submit a general notification for the same transition, which would create duplicates across interfaces.

The minimal weather API is now `PUT /v1/weather`, `GET /v1/weather`, and
`DELETE /v1/weather`; its validated fields and freshness lifecycle are documented
in [Companion UI validation](companion-ui-validation.md#weather-api). It supports
one producer-supplied observation, with last-admitted replacement and a bounded
remaining lifetime, not multi-source observation ordering or provider retrieval.
The richer business models below remain proposals:

| Content | Proposed minimum business data | Updates and withdrawal |
| --- | --- | --- |
| Calendar | Source, event ID, increasing version, title, timezone-aware start/end times, optional location | Replace by ID; cancellation needs an explicit state; reminders reference the event version so rescheduling/cancellation invalidates old reminders |
| Weather | Source, location ID, observation time, validity deadline, conditions, temperature and unit | Replace by location; older observations cannot overwrite newer ones; retrieval failure and expiry of cached values are recorded separately |

This phase does not add generic CRUD, history queries, arbitrary styling, or media upload APIs. Task retention expiry and calendar cancellation require device-side card removal semantics; add those when implementing the corresponding behavior.

### Windows to ESP32: Generic Display Content

Keep the existing `Envelope → Snapshot / CardUpsert / Notification → View` structure. Persistent cards and notifications share `View` while retaining separate lifecycles.

Add display templates incrementally as real content requires them:

| Template | Minimum display fields | Purpose |
| --- | --- | --- |
| `status` (existing) | Title, state, detail, optional progress | Tasks and status notifications |
| `text` (proposed) | Title, short body | External notifications |
| `list` (proposed) | Title, up to three entries with primary/secondary text | Calendar or multi-item summaries |
| `metric` (proposed) | Title, main value, unit, supporting text | Weather or other measurements |

Source/context labels, content update time, and validity should be generic display metadata rather than fields confined to the business API. The device also needs enough information to advance time and evaluate expiry while offline. The current relative USB notification validity is insufficient to promise absolute calendar deadlines.

Future animation should reference cached assets instead of sending each frame through ordinary messages. This phase does not freeze an asset protocol. Firmware does not parse raw calendar, weather-service, or agent protocols, and does not accept HTML, scripts, or arbitrary coordinates.

Keep existing Protobuf field numbers stable. New templates or metadata require updated bindings on both sides, capability/version handling, and compatibility tests. Unsupported content on old firmware must be explicitly rejected or converted by the host into a supported summary; it must not be reported as successfully displayed.

## 5. Feedback, Limits, and Validation

Service admission, device acceptance, and first actual display are separate milestones. Preserve the distinction between HTTP 202 and device `Accepted` / `Presented`; appearing on screen does not establish that the user read it. The proposed general-notification API needs delivery queries correlated by `event_id`. Define its response structure when implementing that API; it does not exist yet.

Current input limits are 64 UTF-8 bytes for a title and 160 bytes for detail, roughly 21 and 53 common Chinese characters respectively. Mixed text must be checked by encoded byte length. These are transport bounds, not readability guarantees. Reject oversized input explicitly; the display layer only truncates otherwise valid content to fit its layout.

The device currently supports eight cards, eight notifications, and one separate
weather observation. Service records remain until restart. Weather does not use
task capacity. At capacity, reject new independent task entries while allowing
updates to existing ones. Calendar integration still requires a selection policy.

Suggested validation sequence:

1. Compare the same real Chinese content in both layouts → Check native-size readability, long titles, unknown progress, and identification of multiple sources.
2. Freeze task and general-notification JSON contracts → Check duplicates, ordering, expiry, full capacity, and offline admission feedback.
3. Complete necessary display fields and Chinese fonts, then implement the chosen layout → Use desktop tests and physical screen photographs; a browser prototype does not establish hardware behavior.
4. Add update time, cancellation, deletion, and local expiry before calendar/weather integration → Verify that rescheduling or disconnection cannot produce stale reminders.

Design topics include the roles of focus and compact overview layouts, daily home-page content, separate project/next-action fields, and whether the top touch input only changes pages or skips notifications. The compact multi-conversation default, task icons, progress bars, and project label are implemented as described above; the remaining choices are still open. Touch is a GPIO5 top electrode and remains untested, so do not design it as a touchscreen. Skipping a notification does not change business state.
