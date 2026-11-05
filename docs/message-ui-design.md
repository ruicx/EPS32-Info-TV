# Message Interface and Screen UI Design Draft

Status: The multi-conversation overview direction has been accepted. Phase one is implemented and has passed desktop checks and a firmware build; calendar, weather, and general notifications remain design proposals. The firmware was flashed on 2026-11-05. Five cards and two notifications received actual device Presented feedback, and the user confirmed that physical text, layout, and page rotation were normal.

Date: 2026-11-05

## 1. Design Goals

The device is a 1.54-inch, 240 × 240 desktop information display. At a glance, the user should be able to tell what is happening, whether anything needs their attention, and when the next event will occur.

Assumptions: The Windows service remains the main source of content. This draft defines message semantics and screen layouts without implementing new producers. The screen is intended for short summaries; long-form reading, logs, and approval of agent actions remain on the computer. Source names are display labels, and firmware behavior does not branch on names such as Codex or zcode.

Keep the accepted behaviors: separate persistent state from notifications, update the same object in place, prioritize important notifications, restore the overview afterward, and synchronize current valid state after reconnection. Retention periods, rotation timing, and idle animation timing remain subject to trial tuning.

## 2. Messages to Display

| Scenario | Question the screen should answer | Persistent content | One-time notification |
| --- | --- | --- | --- |
| Agent running | Which project, what work, and which stage? | Source, task title, current stage; percentage only when real progress is available | Ordinary progress changes do not notify |
| Agent waiting for input | What needs me to return to the computer? | Task title, reason for waiting, clear next step | Important notification on entering the waiting state |
| Agent failed | What failed, and where should I handle it? | Task title, short reason, next step | Important notification on entering the failed state |
| Agent completed | What finished, and what was the result? | Short result, removed according to a retention policy to be decided | Notify once per completed task |
| Calendar | What is the next important event, and how soon? | Title, start/end time, optional location; at most three overview entries | Notify at the agreed reminder lead time |
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

### Three-Row Overview

Show at most three short entries at once, each with a title and one status line. Rotate groups when there are more than three entries. This makes several tasks visible together but requires shorter titles and descriptions, with lower readability from a distance.

Both layouts use the same content model. Choosing a layout must not require callers to change their submissions, and both layouts do not have to be implemented together.

### Multiple Agent Conversations Updating Continuously

Additional scenario: The user has several Codex and agy conversations open simultaneously. The default page for this case is the conversation overview; single cards present important content and state-transition notifications. Phase one supports at most eight persistent entries, three per page, with six-second rotation.

**Each conversation has one persistent display entry.** Task updates within that conversation replace its entry, while other conversations remain independent. Do not collapse all conversations from one application into one entry or create a new card for every chat response.

Distinguish three identity levels:

| Identity | Purpose | Lifetime |
| --- | --- | --- |
| `source` | Producer namespace, such as `codex` or `agy` | Unchanged when a window title changes |
| `conversation_id` (added) | Stable conversation identity; together with `source`, identifies its display entry | Retained across interactions; adapters must prevent collisions between instances of the same source |
| `task_id` (existing) | One execution within a conversation | New ID for each execution, preserving existing ordering and completion deduplication |

Events are still processed by `(source, task_id)`. With conversation association, the host projects task state onto a `(source, conversation_id)` entry. Do not simply reuse a long-lived conversation ID as `task_id`: completion deduplication applies to one execution, so reuse would suppress completion notifications for later executions. HTTP `conversation_id` is also distinct from the device protocol's service `session_id`.

A readable `conversation_title` has been added, and `context` identifies the project or workspace. The primary row text is "source #short-card-ID | short conversation title"; the secondary text is "project | current state and optional progress". The short ID is the first four characters of the service-assigned card UUID. It is only a visual aid and does not replace the full identity. Titles and paths are not identity keys either.

```text
+--------------------------------+
| 5 sessions | 2 need attention   |
|                                |
| Codex | Message API            |
| info_tv | Waiting for input    |
|                                |
| agy | Login flow               |
| webapp | Failed                |
|                                |
| Codex | Unit tests             |
| info_tv | Running              |
| USB online          Page 1 / 2 |
+--------------------------------+
```

Display behavior:

- Show at most three conversations per page. Keep the page stable when everything fits; otherwise rotate groups, initially every six seconds. Page numbers indicate additional content, and the header always shows the global attention count.
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

Use the full screen to emphasize the source, state, task or event title, and a two-line summary. The footer can indicate "Return to your computer" or "Returns to overview". Do not add confirmation, approval, or retry buttons.

Keep the initial defaults of five seconds for ordinary notifications and ten seconds for important notifications. Equal-priority notifications retain arrival order; important notifications can interrupt ordinary ones. Whether an interrupted ordinary notification resumes remains an open product rule; the current demo ends it.

### Daily Information and Idle Pages

Use a short list for calendar content and one main value with limited supporting text for weather. Time and animation belong on the idle page rather than occupying the center of every task card. The idle threshold and automatic rotation of weather/calendar pages remain to be decided.

### Text, Color, and Expiry

- Initial proposed sizes are 16 px for Chinese body text and 20 px for main titles, checked at the native 240 px screen size. Actual fonts and character coverage require firmware validation.
- Limit main titles and summaries to two lines each. Truncate at complete character boundaries, with no scrolling text by default. Callers should provide short summaries.
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

Define calendar and weather business data before freezing their URLs or introducing a universal endpoint:

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

The device currently supports eight cards and eight notifications, and service records remain until restart. These implementation limits require an explicit capacity policy before combining tasks, calendar, and weather. At capacity, reject new independent entries while allowing updates to existing ones. Agree on capacity and selection rules before adding more content.

Suggested validation sequence:

1. Compare the same real Chinese content in both layouts → Check native-size readability, long titles, unknown progress, and identification of multiple sources.
2. Freeze task and general-notification JSON contracts → Check duplicates, ordering, expiry, full capacity, and offline admission feedback.
3. Complete necessary display fields and Chinese fonts, then implement the chosen layout → Use desktop tests and physical screen photographs; a browser prototype does not establish hardware behavior.
4. Add update time, cancellation, deletion, and local expiry before calendar/weather integration → Verify that rescheduling or disconnection cannot produce stale reminders.

Design topics include the roles of single-card and three-row layouts, daily home-page content, separate project/next-action fields, and whether the top touch input only changes pages or skips notifications. The multi-conversation default and project label are implemented as described above; the remaining choices are still open. Touch is a GPIO5 top electrode and remains untested, so do not design it as a touchscreen. Skipping a notification does not change business state.
