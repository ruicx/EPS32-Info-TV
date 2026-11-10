# Antigravity CLI hook adapter

`info-tv hook agy` translates native Antigravity CLI callbacks into the common
`POST /v1/task-events` contract. It is a short-lived hook command; the normal
`info-tv` service owns USB and device delivery. No ACP wrapper is required to
use this adapter.

## Configure

Extract the Rust host archive to a stable path such as `C:\info-tv` and start it:

```powershell
C:\info-tv\info-tv.exe serve
```

For source builds, see the [host guide](../host/README.md).

Merge this named entry into the trusted workspace's `.agents/hooks.json`:

```json
{
  "info-tv": {
    "PreInvocation": [
      {
        "type": "command",
        "command": "C:/info-tv/info-tv.exe hook agy PreInvocation",
        "timeout": 3
      }
    ],
    "Stop": [
      {
        "type": "command",
        "command": "C:/info-tv/info-tv.exe hook agy Stop",
        "timeout": 3
      }
    ]
  }
}
```

Adjust the executable path if the checkout moves, and quote paths containing
spaces. Hook commands receive UTF-8 JSON on stdin. The native payload has no
event-name field, so the event argument is required. The consolidated commands
are `info-tv hook agy PreInvocation` and `info-tv hook agy Stop`.

Use `/hooks` to inspect the loaded handlers. Workspace hooks must be discovered
from the actual trusted workspace, rather than agy's scratch directory. The
CLI also supports global `~/.gemini/config/hooks.json`, shared with other
Antigravity products. Hooks in `~/.gemini/antigravity-cli/settings.json` are not
loaded. See the [official hook reference](https://antigravity.google/docs/hooks?tab=cli).
This implementation does not install or modify normal user/project hook
configuration automatically.

Register only the two events above. A display sender must not be installed as
an agy `PreToolUse` handler: returning `{}` from that event prevented execution
in the [real-agent validation](agy-hook-validation.md). The supported invocation
and stop handlers return neutral `{}` and do not grant permissions, request
approval, inject instructions, or request continuation.

## Mapping and identity

| Native callback | Result |
| --- | --- |
| `PreInvocation`, `invocationNum == 0` | Start a new `running` execution at a newer `initialNumSteps` position |
| Later invocations in the same turn | No new task or progress estimate |
| Idle `Stop`, `NO_TOOL_CALL` | `completed`, meaning the turn ended |
| Idle `Stop`, `ERROR` | `failed`, with fixed detail `Execution error` |
| Idle `Stop`, `MAX_INVOCATIONS`, `MAX_FORCED_INVOCATIONS`, `MAX_TOKEN_BUDGET_EXCEEDED` | `failed`, identifying the execution limit |
| Idle `Stop`, `USER_CANCELED` | `interrupted`, if agy actually emits this callback |
| Non-idle stops or other reasons | No state change |

Only `NO_TOOL_CALL` was observed as a live stop reason in the initial probe.
The other explicit outcome mappings are covered by contract tests, not claimed
as live-agent validation. Tool exit codes and error text do not determine the
task state. Raw error text is not forwarded.

The source namespace is `agy`; native `conversationId` becomes
`conversation_id`. A deterministic UUIDv5 over the source, conversation ID,
and first invocation's trajectory position supplies `task_id`. This includes
the conversation because the same step position occurs in independent
conversations. A SQLite transaction assigns an increasing
`run_sequence` per conversation, and each submitted state change increments
`sequence`. The native `executionNum` is not a durable execution identity.

The first captured prompt supplies the stable conversation title; each new
turn supplies its task title. The first workspace's basename supplies `context`.
Labels collapse controls/whitespace and fit 64 UTF-8 bytes. The adapter uses
the built-in `code` wire icon. Updated firmware displays an `A` source badge
for AGY, alongside `C` for Codex and `Z` for ZCode, in rows and notifications.
It does not read transcripts/artifacts, forward tool
arguments or output, or invent a progress percentage.

The persistent cursor rejects duplicate/older starts. A new start supersedes
the previous execution, even when it had no terminal callback. Stops update
only the current running execution. A SHA-256 digest of the original prompt
rejects stops with a different prompt; full prompts are not retained in the
ledger. Once an execution is terminal, repeated stops cannot change it.

## Retry and state files

The default ledger is `%LOCALAPPDATA%/info_tv/agy-hooks.sqlite3` on Windows,
with `~/.local/state/info_tv/agy-hooks.sqlite3` as the portable fallback.
All callbacks for this installation must share the same file. Codex keeps its
existing separate default ledger. Explicitly sharing a custom file also keeps
the two producer cursors independent.

The adapter reuses the Codex sender's durable outbox and acknowledgment rules:
the UUID, sequence, and exact JSON body are committed before HTTP delivery;
only recognized `202` acknowledgments remove them. Concurrent duplicate sends
are safe because the host deduplicates UUIDs. HTTP uses a one-second flush
window, a default 0.5-second phase timeout, and no environment proxy. Runtime
storage/input/network failures print a diagnostic to stderr and return `{}`
with a successful exit status. Network failures retain pending events.

The default host URL is `http://127.0.0.1:8765`. To retry without a new callback:

```powershell
info-tv hook agy --flush
info-tv hook agy --url http://127.0.0.1:8766 --flush
info-tv hook agy --state-file D:/info_tv-state/agy.sqlite3 --flush
```

Use identical URL/state options in both configured handlers. A large backlog
may need more than one flush. There is no background sender. Keep the ledger
while conversations may resume: deleting it can reuse ordinals already known
by the host. The Rust host restores accepted task state from SQLite after
restart, obtains new device feedback, and does not replay old pop-up notices.

## Native limitations

- The native hooks do not include approval-request events, so this adapter
  does not report `waiting_input`. A tool call is not evidence of an approval.
- Two real ACP cancellations returned `cancelled` without a `Stop` hook.
  Antigravity CLI does not emit a native session-end hook on exit. To prevent
  abandoned cards, the service monitors Antigravity's active conversation
  presence lock (`.gemini/antigravity-cli/presence/<conversationId>.lock`),
  automatically retiring the card from the display when the Antigravity process
  exits.
- Stop lacks a native turn/message ID or matching trajectory position. The
  supported case is one sequential execution per conversation with synchronous
  callbacks. An arbitrarily delayed stop for an identical repeated prompt
  cannot be distinguished from the current run. Source-event replay, concurrent
  executions in one conversation, background continuations, and subagent cards
  are not supported.
- Trajectory positions must increase. Conversation rewrites/compaction that
  reuse or reduce positions need a stronger native identity; starts at an old
  position are ignored rather than assigned a conflicting task ID.
- This mapping assumes no other stop hook requests continuation. Unknown
  termination reasons, terminal step types, hook-induced stops, and non-idle
  stops remain unchanged until their semantics are separately validated.
- Completed means end of a turn, not successful fulfillment of the request.
  Failed cards follow the host's existing failure notification/retention rules;
  they do not use completed-card expiry. Interrupted display behavior is shared
  with the [Codex adapter](codex-hooks.md).

## Verification

On 2026-11-07, **195 host tests passed**, including eighteen new agy cases and
the existing Codex/native firmware bridge regression tests. Coverage includes
the real callback timeline, repeated prompts, UTF-8 bounds, duplicate starts
on concurrent SQLite connections, unsupported outcomes, explicit documented
failure reasons, retry after a lost acknowledgment, and producer separation.
Ruff and ty also passed. See the [native event evidence](agy-hook-validation.md)
for the distinction between captured callbacks and documented-only outcomes.

A real agy 1.5.2 process then invoked the installed `info-tv-hook.exe` through
only the two configured native handlers. A loopback FastAPI server and the
desktop C++ firmware bridge verified normal completion, four successive turns
on one card, independent conversations at the same initial step position,
unchanged native command approval, and recovery on the next turn after a
cancellation without `Stop`. Both final cards received `Accepted` and
`Presented`; the outbox was empty. ACP drove the test agent but did not submit
task events. See the [saved host records](evidence/agy-adapter-smoke-2026-11-07.json).

Protocol generation consistency also passed. No firmware or wire contract was
changed, and no physical ESP32 was flashed or tested in this round. All real
adapter probes used temporary workspace hook files; normal Codex and agy hook
configuration was not installed or changed.
