# Compatibility fixtures

`hook-transitions.json` records outputs generated from the Python host on
2026-11-07. Each scenario is applied in file order to a separate ledger per
source. Only random `event_id` values are omitted from the expected submissions.

The 39 transitions cover unknown-terminal tombstones, late starts, duplicate
callbacks, approval/resume, completion, interruption, tool-failure handling,
conversation ordinals, and agy invocation/stop correlation. Synthetic labels
and identities contain no captured private conversation data.

The Rust tests read these fixtures directly and do not need Python installed.

`startup-probe.cs` is a console application compiled by Windows PowerShell's
`Add-Type` during native-launcher tests. It records its console handle, working
directory, and arguments before exiting with code 37. It does not register tasks,
open the device, or require a separately installed C# toolchain.
Its bounded wait mode also reports its PID for task-termination regression checks.
