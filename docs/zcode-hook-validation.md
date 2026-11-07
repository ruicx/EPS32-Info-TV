# ZCode native hook validation

On 2026-11-07, the installed Windows ZCode **3.14.3.7762** desktop package's
bundled **0.16.9** CLI runtime was exercised through its `app-server --stdio`
interface. The production integration uses native command hooks; app-server
only drives the disposable validation sessions.

The [official hook reference](https://zcode.z.ai/en/docs/hooks) describes seven
events: `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PermissionRequest`,
`PostToolUse`, `PostToolUseFailure`, and `Stop`. The runtime writes one JSON
object to the hook's stdin, including native camelCase fields and compatibility
snake_case aliases. All recorder callbacks returned `{}` with exit code zero.

## Isolation and evidence

The test used a disposable home, workspace, session database, and user-level
`.zcode/cli/config.json` under the ignored `.local/zcode-hook-validation/`
directory. A temporary provider file selected the already configured model;
its credential copy was removed after each run. Normal user/project hook
configuration was not changed. The recorder did not open temporary transcripts.

The [sanitized capture bundle](evidence/zcode-hooks-2026-11-07.json) publishes
**20 callbacks from six turns in one session**:

| Event | Count |
| --- | ---: |
| `SessionStart` | 1 |
| `UserPromptSubmit` | 6 |
| `PreToolUse` | 3 |
| `PermissionRequest` | 2 |
| `PostToolUse` | 2 |
| `PostToolUseFailure` | 1 |
| `Stop` | 5 |

Workspace paths are replaced with `D:/validation/zcode/workspace`. Transcript
paths, model reasoning, raw tool stdout/stderr, and authentication fields are
excluded. Tool response samples retain only status/exit/cancellation fields.
Prompts and assistant replies come from the controlled probes.

## Identity and ordinary completion

A plain reply produced `SessionStart → UserPromptSubmit → Stop`. Subsequent
turns reused `sessionId` and received a new `turnId`. All supported callbacks
within a turn carried the same native `turnId`, including approval and tool
callbacks. The compatibility aliases include `session_id` and
`hook_event_name`; execution identity is supplied by native `turnId`.

Two consecutive identical prompts received different turn IDs. After an
interrupted turn, the recovery turn also received a new turn ID. Prompt text,
workspace name, and tool call IDs must not identify an execution.

`Stop` means the model reached its stopping phase. It does not establish that
the user's task passed acceptance criteria. Other stop hooks may request
continuation, which this adapter does not attempt to arbitrate.

## Approval and its timing race

The safe tool probe ran `exit 0` and `exit 7` through Bash in `build` mode. Each
tool required a native permission request. With a 750 ms delay before the test
client approved the exact command, both `PermissionRequest` recorder callbacks
completed, and both tools executed. Neutral `{}` output did not approve, deny,
or replace tool arguments.

Earlier test clients approved immediately. Their permission hook lifecycle
reported `TOOL_CANCELLED` / `Hook execution cancelled` before the recorder
launched, while the real permission request still reached the client. Immediate
permission resolution can therefore skip the native command hook. A fast
approval is not guaranteed to appear as `waiting_input` on the display.

There is no separate approval-resolved hook. For a tool that proceeds after
approval, `PostToolUse` or `PostToolUseFailure` is the next observed callback
that restores `running`. The card can remain waiting during tool execution.

## Tool failure is not task failure

The command `exit 7` returned `PostToolUse` with `status: failed` and
`exitCode: 7`, followed by the model's final `Stop`. A nonzero shell exit does
not necessarily produce `PostToolUseFailure`.

Reading a deliberately nonexistent file produced
`UserPromptSubmit → PreToolUse → PostToolUseFailure → Stop`. Its
`is_interrupt` field was false. The agent reported the missing file and ended
normally. Neither a tool error nor its raw error text is evidence that the
whole task failed. The adapter treats either post-tool callback as activity.

## Cancellation and model errors

Stopping model generation through `session/stop` returned the session to idle
without `Stop` or another terminal hook. The process remained alive for a
further three seconds. This was reproduced in three capture sessions. The
published six-turn timeline includes the final repetition and next-turn
recovery.

Initial model-selection errors also occurred while setting up the isolated
driver, before any command hook ran. No failure callback was emitted. The
native hook event set has no independent whole-turn `Error` or `Interrupt`
event. This validation does not claim coverage of every model/transport error
or cancellation during an executing tool.

The hooks-only adapter cannot promise `failed` or `interrupted` for these
cases. A canceled card can remain `running`, or `waiting_input` if cancellation
occurred while waiting. A new prompt updates the same conversation card.

## Adapter validation

The [adapter guide](zcode-hooks.md) records configuration, supported mappings,
and delivery behavior. Seventeen new regression cases replay these captures
and cover duplicate callbacks, repeated prompts, terminal tombstones,
concurrent starts, UTF-8 bounds, invalid input, offline retries, and independent
Codex/agy/ZCode cards sharing one database. **All 212 host tests passed**;
Ruff and ty passed.

A host wheel was also built and installed into the disposable Release-guide
environment. Isolated imports resolved to its `site-packages`, the installed
`info-tv-hook.exe` listed `zcode`, and a native JSON input created a queued
ZCode event while the test endpoint was offline. `pip check` passed.

The [adapter smoke evidence](evidence/zcode-adapter-smoke-2026-11-07.json)
records a real runtime invoking the installed sender through native hooks,
submitting to a real loopback host, and receiving desktop C++ firmware bridge
delivery feedback. This is desktop protocol/presentation-core validation;
no physical ESP32 was flashed or checked in this round.
