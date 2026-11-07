# Antigravity CLI hook validation

On 2026-11-07, the installed Windows `agy 1.5.2` was exercised through print
mode, CLI conversation resume, and its documented ACP stdio interface. A
temporary workspace registered synchronous recording commands; the user's
global hook configuration was not changed. ACP used a disposable Gemini data
directory and the existing OS sign-in, without copying credentials.

The [official hooks reference](https://antigravity.google/docs/hooks?tab=cli)
and the installed `agy-customizations/docs/hooks.md` describe six events:
`SessionStart`, `PreInvocation`, `PostInvocation`, `PreToolUse`, `PostToolUse`,
and `Stop`. Named entries in `.agents/hooks.json` contain event handlers.
Invocation and stop handlers are flat lists; tool handlers use matcher groups.
Callbacks contain camelCase fields and no event-name field, so recording
commands received the configured event name as an argument.

## Identity and execution boundaries

- `conversationId` remained stable across CLI resume and ACP user turns.
- `invocationNum` began at zero for each user turn. Further model/tool cycles
  incremented it. `initialNumSteps` changed during those cycles, so every
  `PreInvocation` must not be treated as a new user turn.
- The first `PreInvocation` of each observed turn had a new trajectory position
  in `initialNumSteps`. This provides a local start key when combined with
  `conversationId`, for sequential conversations without trajectory rewrites.
- `executionNum` on `Stop` was zero for multiple different user turns. It is
  not a durable turn ID. `Stop` carries no matching start position or native
  user-message ID. Correlation therefore requires local per-conversation state
  and sequential callbacks; arbitrary delayed/reordered terminal callbacks
  cannot be reconstructed from this surface alone.
- `lastUserInput` is available for labels. It is text, not a unique identity;
  users can submit the same prompt more than once.

## Permission behavior

A recorder returning `{}` from `PreToolUse` caused both a file-read probe and
shell-command probes to fail without running. No permission request or
`PostToolUse` followed those calls. This differs materially from Codex's neutral
hook contract. Removing the pre-tool handler restored normal ACP permission
requests and execution for the same safe shell commands.

The documented pre-tool response is a policy decision (`allow`, `deny`, `ask`,
or `force_ask`). A display observer must not silently approve a tool, force a
new approval, or assume that empty JSON is neutral. A hooks-only integration
should avoid registering a pre-tool handler.

There is no native approval-request callback among the six documented events.
`PreToolUse` also fires for tools that need no approval, so it cannot faithfully
represent `waiting_input`. Native ACP permission requests are a separate
surface and would require a process wrapper/client to observe in production.

## Completion, cancellation, and tool errors

Ordinary text turns and tool turns ended with `Stop` containing
`terminationReason: NO_TOOL_CALL`, `fullyIdle: true`, and an empty `error`.
This means the turn ended, not that the user's task passed acceptance criteria.

Two real ACP `session/cancel` operations returned `stopReason: cancelled`
without a `Stop` callback. The second probe kept the agent alive for three
seconds after the cancellation response. A hooks-only adapter cannot promise
an interrupted update for such cancellations; the last running card can remain
until a later turn replaces it. Process termination must not be inferred from
silence or an elapsed-time threshold.

With the pre-tool recorder removed, native approvals allowed `cmd /c exit 0`
and `cmd /c exit 7`. ACP reported actual shell exit codes **0** and **1**
respectively under the installed PowerShell environment. Both corresponding
`PostToolUse` callbacks had `error: ""`; neither made the final turn fail.
Do not infer task failure from a tool result, an empty hook error, or shell
output text.

The documented `Stop` reasons also include `ERROR`, `USER_CANCELED`, execution
limits, and hook-induced termination. These were not observed as live callbacks
in this round. Any mapping for them must distinguish contract coverage from
real-agent verification. Background/non-idle stops and continuation policies
also require separate validation.

## Evidence and scope

The [sanitized capture bundle](evidence/agy-hooks-2026-11-07.json) contains
representative native payloads, the full event-name/identity timeline, native
shell outcomes, and cancellation observations. It excludes credentials,
transcript contents, and model reasoning. Paths have been normalized for
publication. These probes do not establish IDE/app behavior or physical device
delivery.

The [native hook adapter](agy-hooks.md) implements the supported sequential
invocation/stop mapping and documents these source limitations.
