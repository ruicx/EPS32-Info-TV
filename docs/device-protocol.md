# Windows-to-ESP32 Message Format

Status: Binary Protobuf, the envelope/operation/view structure, card/notification separation, overview-only snapshots, service-session rule, and Accepted/Presented milestones confirmed on 2026-11-03. Detailed schemas, runtime integrations, and transport framing remain open.

Updated: 2026-11-03

## 1. Confirmed Encoding and Scope

Use **binary Protobuf** for Windows-to-ESP32 display messages and device feedback. Describe the shared contract in `.proto` definitions and generate compatible code for both implementations. Reuse the application message semantics over USB, Wi-Fi, and BLE.

This decision replaces the earlier device-side JSON proposal. Producer-to-FastAPI submission is a separate boundary; its proposed JSON HTTP interface is unaffected.

Messages carry supported display content rather than producer-specific events, screen coordinates, executable code, or full-screen pixel streams. Protobuf does not select an RPC framework or require gRPC. Transport, sessions, delivery feedback, presentation timing, and asset policy remain separate design concerns.

The [official language guide](https://protobuf.dev/programming-guides/proto3/) describes scalar types, enums, nested messages, lists, presence, and `oneof`. The schema syntax/edition and compiler/runtime versions will be chosen during implementation setup.

## 2. Confirmed Message Structure

Use three confirmed logical levels:

1. **Envelope:** protocol version, service-session identity, and message identity.
2. **Operation:** a typed `oneof` containing a snapshot, card update/removal, notification, or feedback message.
3. **Display content:** a supported typed view such as text, list, status, metric, or media content. Template-specific properties belong to that view rather than a generic string-to-value dictionary.

| Envelope concept | Confirmed purpose |
| --- | --- |
| Protocol version | Identify the device contract the sender expects |
| Service session | Scope state and ordering across Windows service restarts |
| Message identity | Correlate an operation with its feedback and identify a retransmission |

A card update contains card identity, content revision, and typed view content. A notification contains event identity, priority, presentation duration, and typed view content. Producer names are text content; neither operation selects behavior by recognizing Codex, Antigravity, or zcode.

This describes concepts, not finalized field names, numbers, or scalar types. Missing-versus-zero behavior requires deliberate field-presence design. Unknown operations, unsupported versions, and invalid enum values require explicit application handling.

## 3. Operation Families and Snapshot Scope

| Operation | Direction | Meaning | Status |
| --- | --- | --- | --- |
| Hello | Device to Windows | Report protocol support and connection information | Proposed handshake mechanism |
| Snapshot | Windows to device | Synchronize current valid display state | Confirmed operation family |
| Card upsert | Windows to device | Create or replace an overview card | Confirmed operation family |
| Card removal | Windows to device | Remove an overview card | Confirmed operation family |
| Notification | Windows to device | Queue a one-time notification independently of overview state | Confirmed operation family |
| Acknowledgment | Device to Windows | Report the accepted or presented stage | Confirmed operation family |
| Error | Either direction | Report an unsupported or invalid operation with correlation information where available | Confirmed operation family |

These are operation families rather than final Protobuf message names. Exact handshake fields, session establishment, snapshot application mechanics, error codes, and any heartbeat messages remain open.

Confirmed: a snapshot replaces the current overview state only. It does not include notification history or implicitly replay one-time events. Validate the snapshot before committing it so rejected content does not leave a partially replaced overview. Snapshot size and whether later chunking is needed will follow the agreed content limits.

## 4. Identity, State, and Ordering

Keep transport-message identity separate from overview-card identity and notification-event identity:

- A new card revision replaces existing content for that card; it does not create another progress notification.
- An intentional card update is a new message concerning the existing card.
- A retry retains the original message identity and equivalent application content. Do not rely on byte-for-byte serialization equality for duplicate detection; Protobuf serialization is not canonical.
- Notification identity represents the original event and suppresses repeated interruption even if transport delivery is retried.

The service-session rule scopes revision comparison across service restarts, so a previous session's higher revision does not block current content indefinitely. The concrete representations and comparison rules remain to be designed. See the official [serialization guidance](https://protobuf.dev/programming-guides/serialization-not-canonical/) for the separate issue of serialized-message equality.

Confirmed: Windows creates a new service-session identity when its service process starts. Transport reconnects within that process retain the session and request a current overview snapshot. Precise handshake and notification handling across this boundary still need design. The proposed transition keeps old-session content visibly marked as cached until a valid replacement snapshot is committed; after commitment, old-session revisions and messages cannot modify the synchronized state.

Card identity identifies an object, message identity identifies a delivery operation, and notification identity identifies a one-time event. Their scopes must be explicit even if their concrete representations are decided later. Do not use source name alone as task identity, since one source may submit multiple concurrent tasks.

View content remains source-independent. Text, list, status, metric, and media are the agreed display-content categories; their concrete schemas, supported fields, and bounds require subsequent design. A producer name is display content and does not select source-specific firmware behavior.

## 5. Notifications and Validity

Notifications need event identity, priority, content, and on-screen duration. Preserve the provisional ordinary/important duration defaults and interruption behavior already accepted in the requirements.

A notification timeout restores the overview without resolving waiting-for-input or failed state within it. Display duration is distinct from message validity. Define expiration representation and clock/synchronization assumptions before implementation; a retry must not extend an event's original validity, and expired reminders must not replay after reconnection.

Deduplication retention and restart behavior remain deferred for prototype evaluation. This protocol choice does not imply durable exactly-once delivery.

## 6. Reception and Display Feedback

Feedback references the corresponding transport message or presentation identity as defined by the final schema. Distinguish admission into the device's bounded processing path from actual presentation. Decode success alone does not establish that the content was retained or shown.

Define a presentation milestone for each applicable message category. A queued notification is not displayed; an updated overview card can remain hidden by a notification. A display acknowledgment does not prove the user read the content. Payload fields, retry behavior, and feedback retention remain open.

Use two confirmed success milestones:

- **Accepted:** the UI-side owner has validated and applied a state operation, or admitted a notification into the bounded pending-notification state. Merely receiving bytes, decoding, or handing off an unchecked command does not reach this milestone.
- **Presented:** applicable content has actually entered visible presentation and the defined first-refresh milestone has completed. An overview update hidden by a notification is accepted but not yet presented.

A rejected command reports failure instead of an accepted milestone. The confirmed distinction does not promise presentation for every progress update: a newer revision may replace it before it becomes visible. Which operations request presentation feedback, the exact refresh-completion event, and how expiry, replacement, or interruption ends tracking remain to be specified.

## 7. Proposed Binary Transport Framing

Protobuf serialization does not define stream message boundaries; see the [official techniques guide](https://protobuf.dev/programming-guides/techniques/).

| Transport | Proposed framing |
| --- | --- |
| USB serial | A bounded length-delimited binary frame; header, startup/log separation, and resynchronization remain to be designed |
| Wi-Fi WebSocket | One serialized device message per complete binary WebSocket message; reassemble WebSocket fragmentation before decoding |
| BLE GATT | Fragment and reassemble serialized bytes using explicit limits and fragment/session identification |

The selected Protobuf encoding does not finalize these transport bindings. A serial read, BLE fragment, or network callback is not necessarily a complete application message. JSON line or RFC 7464 record-separator framing is no longer a device protocol candidate and must not be reused unchanged for arbitrary binary payloads.

## 8. Proposed Runtime Integration

| Boundary or implementation | Current status |
| --- | --- |
| Windows-to-ESP32 serialization | Binary Protobuf, confirmed |
| Local producers to FastAPI | JSON HTTP with Pydantic validation, proposed separately |
| Windows codec | Official Python Protobuf runtime and generated messages, recommended |
| ESP32 codec | Nanopb-generated C structures/codecs called from C++, recommended for evaluation |

The [official Python generated-code guide](https://protobuf.dev/reference/python/python-generated/) describes Python generation. [Nanopb](https://jpa.kapsi.fi/nanopb/docs/concepts.html) generates `.pb.c` and `.pb.h` files and can bound strings, bytes, and lists with generator options. Nanopb has not been selected or integrated. Keep embedded generator settings in a separate `.options` file where practical to preserve a shared schema independent of that runtime.

## 9. Bounds, Evolution, Assets, and Diagnostics

- Set compatible limits for text bytes, list counts, decoded memory, and complete frame size. Generated types do not replace application or resource validation.
- Generate both implementations from the same schema revision through a reproducible build step, with compatible pinned compiler, generator, and runtime versions.
- Keep field numbers stable, reserve removed fields, and review schema changes for wire compatibility. Follow the official evolution rules rather than assuming every edit is compatible.
- Decode captured Protobuf messages into a readable debugging representation. This does not introduce another device wire encoding.
- Measure encoded sizes and runtime memory on representative messages. Text and image content are not automatically compressed by Protobuf.
- Reference cached assets in ordinary display updates. Transfer media separately in bounded units; formats and the asset-transfer protocol remain open.

## 10. Remaining Design Work

The envelope/operation/view split, overview-only snapshots, service-session rule, and Accepted/Presented distinction are confirmed. Next finalize concrete schema fields, numbers and limits, session/revision representations, handshake and snapshot application mechanics, validity representation, feedback correlation, backpressure/error behavior, codec integration, and binary framing. Timing and long-term retention values deferred for prototype evaluation remain adjustable. Items explicitly marked Proposed remain unselected.

No `.proto` schema, generated code, codec dependency, or transport implementation has been added by this decision record. The selected module boundaries and technologies remain as recorded in [Software Architecture](architecture.md) and [ESP32 Firmware Architecture](firmware-architecture.md).

## 11. Proposed Field-Level Draft

Status: Field names, scalar representations, and content details in this section are proposals for review. They do not assign Protobuf field numbers or finalize capacity limits. No schema source or generated implementation is created by this draft.

### 11.1 Envelope

| Field | Proposed type | Meaning |
| --- | --- | --- |
| `protocol_version` | `uint32` | Device contract version; zero is not a valid negotiated version |
| `session_id` | `string` | Opaque identity created for the Windows service process lifetime |
| `message_id` | `string` | Unique identity for an operation; retries retain it |
| `body` | `oneof` of operation messages | Exactly one supported operation in an admitted application message |

Use opaque string identifiers initially for inspectable diagnostics. Keep identifiers distinct across independent senders and sessions; do not derive uniqueness from a producer label alone. Feedback has its own message identity and explicitly references the original command identity. The pre-session hello is a handshake exception whose session-establishment rules remain open, not a reason to accept empty session identities on normal commands.

Generated Protobuf parsing alone does not enforce all application rules. Reject normal messages with missing required identities, an unsupported version, or no recognized operation body. [Protobuf field presence](https://protobuf.dev/programming-guides/field_presence/) and application validation must be considered together.

### 11.2 Overview State Operations

| Message | Proposed fields |
| --- | --- |
| `Snapshot` | `repeated Card cards` |
| `Card` | `string card_id`, `uint64 revision`, `View view` |
| `CardUpsert` | `Card card` |
| `CardRemove` | `string card_id`, `uint64 revision` |

The card identity is stable for the logical overview object, and its revision increases when that object's content changes within a service session. Retried messages do not increment the revision. Different concurrent tasks receive different card identities even when submitted by the same agent.

Removal includes a revision so a delayed earlier update cannot recreate a deleted card. The device needs a deletion-ordering rule and an explicit snapshot/session boundary for clearing that ordering state. Tombstone retention and snapshot barriers require final design; this draft does not silently assume that deleting all revision metadata is safe.

Snapshots contain only current overview cards. Their commit is all-or-nothing after validation; notification history remains outside the snapshot.

### 11.3 Typed View Content

Propose a reusable `View` with a `string title` and a `oneof content`:

| Content message | Proposed fields | Intended use |
| --- | --- | --- |
| `TextView` | `string text` | General messages and explanatory text |
| `ListView` | `repeated ListItem items` | Calendar entries, multiple task summaries, or other lists |
| `StatusView` | `string text`, `Tone tone`, `optional string detail` | A status label with an optional explanation |
| `MetricView` | `optional double value`, `string unit` | A numeric metric; absent value is distinguishable from zero |
| `MediaView` | `string asset_id` | A reference to a cached image or animation |

Proposed `ListItem` fields are `string text` and `optional string detail`. Proposed tone meanings are neutral, attention, positive, and negative; exact enum declarations remain open and do not fix colors or icons. Numeric values require application validation before display.

The wire content does not select fonts, pixel positions, or arbitrary LVGL widget trees. Templates own those details and remain subject to the confirmed rendered-preview iteration process. Media format and playback controls remain separate design items.

### 11.4 Notifications

| Field | Proposed type | Meaning |
| --- | --- | --- |
| `notification_id` | `string` | Identity of the original event for duplicate suppression |
| `priority` | `Priority` enum | Ordinary or important under the accepted scheduling behavior |
| `display_duration_ms` | `optional uint32` | On-screen duration; absence requests the current device policy default |
| `view` | `View` | Reuse the same typed display content as overview cards |

An explicitly supplied zero duration is invalid in this initial proposal; indefinite on-screen notifications have not been requested. Omitting duration permits the provisional 5-second/10-second defaults to be tuned without changing producer content.

Validity is intentionally not folded into display duration. Its concrete representation still needs a clock/expiry design before the contract can be implemented fully; the existing requirement to suppress expired reminders remains in force.

### 11.5 Feedback

| Message | Proposed fields |
| --- | --- |
| `Acknowledgment` | `string in_reply_to`, `AckStage stage` |
| `Error` | `optional string in_reply_to`, `ErrorCode code`, `string detail` |

`in_reply_to` references the original command's message identity within its service session. `AckStage` contains the confirmed Accepted and Presented milestones, plus the required schema default value. A command can receive both milestones with the same reference. Feedback messages are not themselves recursively acknowledged.

The error code set, handling of superseded or expired content, presentation tracking scope, exact first-refresh milestone, and retry limits remain open. The draft does not add an assurance that every accepted overview revision will eventually become visible.
