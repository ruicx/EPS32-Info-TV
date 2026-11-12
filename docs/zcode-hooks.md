# ZCode hook adapter

The short-lived Windows hook command translates native ZCode callbacks into
the common `POST /v1/task-events` contract. It runs on the computer alongside
ZCode and the host service. No ZCode-specific HTTP endpoint, wire message, or
firmware behavior is required.

Validated with desktop **3.14.3.7762**, bundled CLI runtime **0.16.9**. See the
[real callback validation](zcode-hook-validation.md) for evidence and limits.

## Configure native hooks

Extract the Rust host archive and keep the service running as described in the
[Release user guide](../README.md#user-guide-install-from-a-release-on-windows).
`info-tv hook zcode` reads one UTF-8 JSON callback from stdin.

Merge this `hooks` object into `%USERPROFILE%/.zcode/cli/config.json`, preserving
other configuration and existing handlers. Change the absolute executable path
if your installation differs. The `process` executor separates arguments
without invoking a shell; `timeoutMs` is measured in milliseconds.

```json
{
  "hooks": {
    "enabled": true,
    "events": {
      "UserPromptSubmit": [
        {"hooks": [{"type": "process", "command": "C:/info-tv/info-tv.exe", "args": ["hook", "zcode"], "timeoutMs": 3000}]}
      ],
      "PreToolUse": [
        {"hooks": [{"type": "process", "command": "C:/info-tv/info-tv.exe", "args": ["hook", "zcode"], "timeoutMs": 3000}]}
      ],
      "PermissionRequest": [
        {"hooks": [{"type": "process", "command": "C:/info-tv/info-tv.exe", "args": ["hook", "zcode"], "timeoutMs": 3000}]}
      ],
      "PostToolUse": [
        {"hooks": [{"type": "process", "command": "C:/info-tv/info-tv.exe", "args": ["hook", "zcode"], "timeoutMs": 3000}]}
      ],
      "PostToolUseFailure": [
        {"hooks": [{"type": "process", "command": "C:/info-tv/info-tv.exe", "args": ["hook", "zcode"], "timeoutMs": 3000}]}
      ],
      "Stop": [
        {"hooks": [{"type": "process", "command": "C:/info-tv/info-tv.exe", "args": ["hook", "zcode"], "timeoutMs": 3000}]}
      ]
    }
  }
}
```

Use the built-in **ZCode Agent** for this integration. Open **Settings → Hooks**
to check the entries and start a new session after editing configuration;
sessions capture their hook configuration at startup. Keep handlers synchronous.
The adapter does not install or edit normal configuration automatically.

The [official guide](https://zcode.z.ai/en/docs/hooks) currently says project
hooks are ignored; use the user-level file above. `.agents/settings.json` and
`.claude/settings.json` are migration sources, not active ZCode hook files.
Project hook loading and hook-based plugins were not tested in this round.

## State and identity

| Native event | Submitted state |
| --- | --- |
| `UserPromptSubmit` | `running`; begins a new native turn |
| `PreToolUse` | `running` for a known open turn |
| `PermissionRequest` | `waiting_input`, if the native command hook executes |
| `PostToolUse` | `running`, including nonzero shell exits |
| `PostToolUseFailure` | `running`; an individual tool may fail or be interrupted and recover |
| `Stop` | `completed`; the turn reached the stopping phase |
| `SessionStart` and unknown events | Ignored |

Source is `zcode`. Native `sessionId` becomes `conversation_id`. A deterministic
UUID derived from both `sessionId` and `turnId` identifies a task, including
when different conversations happen to reuse a turn ID. Native execution IDs
are required; prompt text is never an identity fallback.

The SQLite ledger assigns an increasing `run_sequence` per conversation, with
an increasing `sequence` per execution. Duplicate starts and unchanged states
are ignored. Completed executions cannot reopen. A stop without a known start
leaves a tombstone without allocating a conversation ordinal. Activity without
a known start is ignored. Callback processes serialize ledger updates through
SQLite transactions.

Each conversation keeps one display card across turns. The first prompt supplies
the stable conversation title; each prompt supplies the current task title.
The workspace basename supplies context, and the wire icon is `code`.
Updated firmware uses the `Z` source badge for ZCode, distinguishing it from
Codex (`C`) and AGY (`A`) in both overview rows and notifications. Titles/context
are limited to 64 UTF-8 bytes and details to 160, with controls and repeated
whitespace removed. Progress is unknown; the adapter does not fabricate it.
It never opens transcripts or forwards raw tool inputs, results, or errors.
The final assistant message may appear as a bounded stop detail.

## Delivery and retry

Default ledger: `data/zcode-hooks.sqlite3` beside the actual executable,
resolving symbolic links independently of the agent's working directory.
`--state-file` overrides this path. See [migration instructions](host-cli.md#portable-paths-and-migration)
when upgrading from the previous per-user directory. ZCode's
execution table is separate from the Codex and agy tables even if a custom
ledger file is intentionally shared. Preserve the ledger when resuming sessions
or upgrading; it retains run ordering and pending delivery payloads.

The event UUID and exact JSON payload are committed before HTTP delivery.
Delivery shares the existing outbox behavior: a one-second flush window,
default 0.5-second HTTP phase timeouts, and no environment proxies. Recognized
202 acknowledgments (`accepted`, `duplicate`, `stale`, `closed`) remove the
event; network errors and invalid acknowledgments retain it for retry. Another
callback or explicit flush retries pending events:

```powershell
info-tv hook zcode --flush
info-tv hook zcode --url http://127.0.0.1:8766 --flush
info-tv hook zcode --state-file D:/info-tv-state/zcode.sqlite3 --flush
```

Runtime validation, storage, and HTTP errors print diagnostics to stderr and
neutral `{}` to stdout with normal exit status. The hook sends no allow/deny,
input replacement, injected context, or continuation decision. There is no
background sender or automatic ledger history cleanup. The Rust host restores
accepted cards from SQLite on restart; delivery feedback is obtained again and
old pop-up notifications are not replayed.

## Native limits

- Cancellation during generation emitted no terminal hook, even after a further
  three seconds. Model-selection errors can occur before any callback. The
  adapter cannot reliably submit `interrupted` or whole-task `failed` states;
  a missing terminal callback leaves the last state until the next prompt.
- Immediate permission resolution canceled the native approval command hook in
  earlier probes. Fast approvals may never display `waiting_input`.
- Approval resolution has no separate callback. The next post-tool callback
  restores `running`, so a long tool can keep showing the previous waiting state.
- A failed or canceled tool is not a whole-turn outcome. The adapter does not
  infer task failure from `exitCode`, `is_interrupt`, or raw error text.
- Keep callbacks synchronous and ordered per conversation. Arbitrary historical
  replay of previously unseen starts, concurrent turns in one session,
  subagents/background work, and desktop-only workflows outside the bundled
  native runtime are not validated.
- This mapping assumes no other `Stop` hook requests continuation. Such a hook
  could cause a card to close before the native turn actually ends.

Seventeen new regression cases and all **212 host tests** passed, together with
Ruff and ty. The [smoke evidence](evidence/zcode-adapter-smoke-2026-11-07.json)
distinguishes native hook/HTTP/C++ delivery checks from physical display testing.
