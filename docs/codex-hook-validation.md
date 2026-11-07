# Codex hook event validation

Date: 2026-11-07, Asia/Shanghai.

Result: real Codex events provide usable conversation and turn identities and
signals for starting work, requesting approval, and stopping. They do not yet
justify a complete mapping to all four host task states. In particular, a
command failure is not a turn failure, an interruption needs its own policy,
and a connection failure can end a session without a `Stop` callback.

This record covers event discovery before adapter implementation. No events
were submitted to `POST /v1/task-events`, and no ESP32/display behavior was
tested. The existing host API, firmware, and normal Codex configuration were
unchanged.

## Environment and method

- Windows; installed Codex CLI **0.166.0**, model `gpt-6.1-sol`.
- Python **3.12.13** recorder, launched once per callback as a command hook.
- Separate disposable `CODEX_HOME` and workspace under the Git-ignored
  `.local/codex-hook-validation/` directory. A temporary copy of the existing
  ChatGPT login enabled real requests; that copy was removed after testing.
- Eight registered events: `SessionStart`, `SessionEnd`, `UserPromptSubmit`,
  `PreToolUse`, `PermissionRequest`, `PostToolUse`, `Stop`, and `Interrupt`.
- Each recorder read one JSON object from stdin, wrote it to a separate file
  with a local capture timestamp, printed `{}`, and exited successfully.
  Hooks were synchronous with three-second timeouts and no event matchers.
- CLI probes used `codex --no-daemon exec --json`, an explicit read-only
  sandbox request, and `--dangerously-bypass-hook-trust` for the reviewed
  recorder definitions. This was a test-only invocation flag, not an approval
  or sandbox bypass.
- Additional probes used a separate `codex app-server --stdio` process from
  the same executable to drive actual turns, approval decisions, interruption,
  and archive operations. Only the recorder definitions' reviewed hashes were
  trusted in the disposable home; `hooks/list` confirmed all eight as trusted.
  App Server was a test driver, not a selected production adapter architecture.

The official [Hooks documentation](https://learn.chatgpt.com/docs/hooks)
describes hook input, discovery, trust, and continuation behavior. The
[configuration schema](https://learn.chatgpt.com/docs/config-schema.json)
includes hook trust state. Normal installation should use Codex's hook review
interface rather than copying the test-only trust bypass.

The initial restricted-network run failed with
`workspace routing discovery failed`. Repeating the same probe with permitted
network access completed normally. Results below distinguish these runs.

## Captured results

The [sanitized evidence](evidence/codex-hooks-2026-11-07.json) contains nine
scenario summaries, session lifecycle captures, ten representative payloads,
and selected App Server observations. There were **37 callbacks** across four
sessions: five `SessionStart`, five `SessionEnd`, eight `UserPromptSubmit`,
five `PreToolUse`, four `PermissionRequest`, two `PostToolUse`, six `Stop`, and
two `Interrupt` events. One CLI session was resumed, accounting for its second
start/end pair.

Paths were replaced by placeholders. Test session/turn/tool IDs and payload
field types were preserved. Capture timestamps were added by the recorder;
they are not Codex event timestamps or ordering guarantees. Raw captures and
the disposable probe scripts remain local and are not committed.

The following sequences list turn-scoped callbacks. Session start/end callbacks
are recorded separately in the evidence file.

| Scenario | Observed turn callbacks, in capture order | Independent outcome |
| --- | --- | --- |
| CLI connection failure | `UserPromptSubmit` | CLI emitted `turn.failed`; session ended without `Stop` |
| CLI ordinary reply | `UserPromptSubmit → Stop` | Reply `HOOK_PROBE_OK`; CLI emitted `turn.completed` |
| CLI resume and policy rejection | `UserPromptSubmit → PreToolUse → Stop` | Same session, new turn; command rejected before execution; CLI turn completed |
| Approval denial, initial and final probes | `UserPromptSubmit → PreToolUse → PermissionRequest → Stop` | Client declined command; agent replied and turn completed; no `PostToolUse` |
| Approved command with deliberate failure | `UserPromptSubmit → PreToolUse → PermissionRequest → PostToolUse → Stop` | Command printed `HOOK_EXIT_SEVEN`, exited **7**; turn completed |
| Approved successful command | `UserPromptSubmit → PreToolUse → PermissionRequest → PostToolUse → Stop` | Command printed `HOOK_SUCCESS`, exited **0**; turn completed |
| Interruption immediately after turn start | `Interrupt` | Turn interrupted before a `UserPromptSubmit` callback was captured |
| Interruption after submit callback | `UserPromptSubmit → Interrupt` | Turn interrupted; no `Stop` |

App Server's `item/completed` command records independently confirmed exit
codes 7 and 0. Its terminal turn notifications confirmed completed/interrupted
outcomes. These were observations from the
[App Server protocol](https://learn.chatgpt.com/docs/app-server), not fields
available to the command-hook recorder.

## Observed payload contract

| Callback | Fields relevant to an adapter |
| --- | --- |
| Common | `session_id`, `cwd`, `transcript_path`, `hook_event_name` |
| `SessionStart` | `source` was `startup` or `resume`; `model`, `permission_mode`; no `turn_id` |
| `SessionEnd` | `reason: "other"`; no `turn_id`, `model`, or `permission_mode` in captured payloads |
| `UserPromptSubmit` | `turn_id`, `prompt`, `model`, `permission_mode` |
| `PreToolUse` | `turn_id`, `tool_name: "Bash"`, `tool_input.command`, `tool_use_id`, `model`, `permission_mode` |
| `PermissionRequest` | `turn_id`, `tool_name`, `tool_input.command`, `tool_input.description`, `model`, `permission_mode`; no `tool_use_id` or approval result |
| `PostToolUse` | `turn_id`, `tool_name`, `tool_input`, `tool_use_id`, `tool_response`, `model`, `permission_mode` |
| `Stop` | `turn_id`, `stop_hook_active: false`, `last_assistant_message`, `model`, `permission_mode` |
| `Interrupt` | `turn_id`, `model`, `permission_mode` |

In these shell probes, `tool_response` was a **string containing command
output**, without a separate exit code or success field. Both the successful
and failed commands also printed a shell-profile diagnostic containing
`[ERROR]`. Matching that word would incorrectly classify the successful command.

For example, the deliberate exit-7 command produced the following subset;
the evidence file contains the complete sanitized capture:

```json
{
  "hook_event_name": "PostToolUse",
  "tool_name": "Bash",
  "tool_input": {
    "command": "Write-Output HOOK_EXIT_SEVEN; exit 7"
  },
  "tool_response": "[ERROR] - (starship::print): Under a 'dumb' terminal (TERM=dumb).\n\r\nHOOK_EXIT_SEVEN\r\n",
  "tool_use_id": "exec-833f004d-adfc-425e-aa1f-b0a1624a1e1f"
}
```

`session_id` stayed constant when the CLI session resumed; `turn_id` changed.
The transcript path gained a Windows extended-path prefix on resume, so its
spelling is unsuitable as a conversation identity. All four captured sessions
used the same workspace, confirming that the workspace path alone is also
insufficient to identify a conversation.

CLI payloads reported `permission_mode: "bypassPermissions"` even though the
probe requested read-only execution and a command was blocked by policy.
App Server's on-request probes reported `default`. An adapter should not infer
effective sandbox access from this label.

## Implications for the first adapter

These are implementation proposals based on the captures, not implemented
behavior:

| Host field or state | Proposed treatment | Remaining constraint |
| --- | --- | --- |
| `source` | Constant `codex` | Keep the existing common HTTP endpoint |
| `conversation_id` | Codex `session_id` | Resume must retain the same display entry |
| `task_id` | Codex `turn_id` | A new turn gets a new execution; do not reuse the session ID |
| `run_sequence` | Assign an increasing ordinal per conversation | Hooks provide no numeric ordinal; allocation must survive separate processes and retries |
| `event_id`, `sequence` | Assign and retain them when capturing an update | Hooks provide neither a submission UUID nor an update sequence; retries must reuse the same payload |
| `running` | `UserPromptSubmit`; tool activity can update detail | A missing start callback is possible during an early interruption |
| `waiting_input` | `PermissionRequest` can indicate pending approval | No approval-resolution callback was captured; arbitrary user questions were not tested |
| Resume from waiting | Successful execution reaches `PostToolUse`; denial reached `Stop` | The preceding `PreToolUse` occurs before approval and cannot clear that same pending request |
| `completed` | Treat `Stop` as a candidate end-of-turn signal | It does not establish task success; continuation hooks require additional handling |
| `failed` | Do not infer it from command output, denial, or `SessionEnd` | The network-failed turn had no `Stop` and no failure-specific callback among the eight configured events |
| Interruption | Retain it as a distinct source event pending a product decision | The current host `TaskState` has no interrupted/cancelled value |
| Progress | Leave `progress_percent` unset | None of the tested payloads supplied meaningful task progress |

`SessionStart` is session lifecycle information rather than evidence that a
task is running. `SessionEnd` must not complete a task: it occurred after both
successful and failed turns, and the same session could subsequently resume.

The official Hooks documentation also allows another `Stop` handler to request
continuation. This probe used only a neutral recorder, so it does not establish
that every `Stop` is the final end of work in a user's hook configuration.
Do not infer failure or success from the wording of `last_assistant_message`.

The intended production boundary remains a short-lived Windows hook command
that translates events and submits them to `POST /v1/task-events`. The captures
do not require `/v1/task-events/codex` or a change to the service/device boundary.

## Decisions and additional validation before implementation

1. Decide how the display represents an interrupted turn. It must not silently
   become a successful completion or a failed task.
2. Define the initial failure-detection scope. The eight tested hooks alone do
   not cover the observed connection failure with a distinct terminal signal.
   Further event investigation or an additional supported signal would be a
   separate design decision; this record does not select transcript parsing
   or a production App Server wrapper.
3. Define approval-resolution and `Stop` continuation behavior before claiming
   reliable waiting/completed states across arbitrary Codex configurations.
4. Test actual interactive CLI/desktop sessions, concurrent conversations and
   tools, steering, continuation hooks, repeated/delayed events, process crashes,
   and non-ASCII prompts. This round used serial controlled probes and did not
   establish ordering or delivery guarantees under those conditions.
5. Once mapping is agreed, verify the adapter's HTTP retries, conversation
   isolation, restart behavior, bounded UTF-8 text, and device presentation.
   Neither forwarding nor completion-notification deduplication was exercised
   by these event-capture probes.

The local recorder and drivers passed Ruff and ty checks. Documentation and
evidence consistency were checked separately; host/firmware test suites were
not rerun because production code was unchanged.
