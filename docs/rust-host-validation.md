# Rust Host Validation

Updated: 2026-11-07

This record covers the first Rust host implementation in the working tree. The
[architecture](rust-host-design.md) and [user/build guide](../host/README.md)
describe behavior and commands. Desktop checks below do not establish physical
display behavior or successful login startup.

## Automated Checks

Validated on Windows x86-64 with Rust/Cargo 1.97.1:

```powershell
cargo test --manifest-path host/Cargo.toml --locked
cargo clippy --manifest-path host/Cargo.toml --all-targets --locked -- -D warnings
cargo fmt --manifest-path host/Cargo.toml -- --check
ctest --test-dir build/native-tests -C Debug -LE hardware --output-on-failure
```

All 24 Rust integration/regression tests passed, with no ignored tests. Clippy
and formatting passed. The existing native firmware suite passed all four cases:
framing, codec, presentation, and screen. CTest was invoked through the installed
ESP-IDF CMake tools because it was not on the shell PATH.

| Area | Evidence |
| --- | --- |
| Persistence | Task/card identity, revisions, replay protection, closure, and brightness zero survive coordinator restart. |
| Process failure | The real executable is forcibly terminated after HTTP acknowledgment, then restarted against the same database; state returns and event retry is duplicate. |
| Storage failure | A SQLite trigger rejects writes; failed operations return 503 without changing accepted task/brightness state. Removing the fault permits the same event to be admitted. |
| Concurrency | A held SQLite write lock and 100 concurrent submissions yield eight admitted tasks and explicit 503 rejections without exceeding capacity. Concurrent hook callbacks enqueue one transition. |
| Recovery/expiry | Downtime does not renew completed-task retention, weather, or alerts. Retired runs stay closed and old notification intent is suppressed. |
| Device protocol | The checked-in frame vector round-trips; corruption and oversized frames recover at delimiters; maximum-size payloads pass. |
| Firmware integration | Rust HTTP requests reach the actual native C++ codec/presentation bridge. Snapshot handshake, brightness Applied, card Accepted/Presented, and completion-notification feedback pass. |
| Device state machine | Wrong command IDs, wrong brightness, early Presented, stale revisions, missing capabilities, dead connections, shortened retry validity, queue bounds, and delivery-history eviction are covered. |
| Hooks | 39 language-independent transition fixtures generated from Python match Rust for Codex, agy, and ZCode. Alias handling, neutral offline capture, SQLite outbox, and compatibility-binary flush pass. |
| Configuration/CLI | Working-directory YAML discovery, explicit/relative paths, missing-file behavior, strict types, hexadecimal USB IDs, client isolation, and exit-code distinctions pass. Real process tests use paths containing spaces. |
| Weather | Source age, daily extrema, rounding, WMO mapping, malformed input, and Unicode label validation pass. |
| Startup launcher | Generated PowerShell parses with paths containing spaces/apostrophes. `autostart status` runs against the real user task registry without installing anything. |

## Python Host Removal

With user approval, the `host/` service, Python tests/bindings, wheel packaging,
and its dependency project were removed. The `host/` directory now contains the
Rust crate. Historical implementations remain in Git history; the 39 hook
transition fixtures and embedded API contract remain in the Rust crate. This
does not imply completion of the release checks below.

Python development dependencies now live in `scripts/pyproject.toml` and
`scripts/uv.lock`. A fresh `uv sync --project scripts --locked` installed the
Nanopb/compiler and Ruff/ty tools without the removed host or its HTTP/serial
dependencies. From the repository root, these commands passed:

```powershell
uv run --project scripts --locked python scripts/protocol/generate_protocol.py --check
uv run --project scripts --locked python scripts/protocol/generate_protocol.py
uv run --project scripts --locked ruff check --config scripts/pyproject.toml scripts demos
uv run --project scripts --locked ty check --project scripts scripts demos
```

Regeneration left the committed firmware bindings unchanged. Nanopb needed a
run outside the coding sandbox because its subprocess could not access Python's
temporary directories inside that sandbox. No generator workaround was added.
Both standard-library HTTP demos passed their `--help` checks without the Python
host. All 24 Rust tests (including the C++ bridge), Clippy, rustfmt, and four
native CTests passed again after removal. The running Rust host remained online
with fresh weather accepted by the physical device.

## Windows Distribution

`scripts/host/build_rust_release.ps1` successfully built both optimized executables
with `-C target-feature=+crt-static` for `x86_64-pc-windows-msvc` and produced:

```text
build/rust-host-dist/info-tv-0.1.0-x86_64-pc-windows-msvc.zip
```

The archive contains `info-tv.exe`, `info-tv-hook.exe`, `info-tv.yaml`, and a
standalone README. The current archive is approximately 7.1 MiB; the executables
are approximately 9.5 MiB and 6.1 MiB. Rebuilding can change archive bytes and size.

MSVC `dumpbin /dependents` inspection of both executables found only Windows
system DLL dependencies, with no Python, SQLite, or separately installed MSVC
runtime DLL requirement. Release `--version` and compatibility-hook `--help`
smoke checks passed. This is dependency inspection on the development machine,
not a clean-VM qualification. No GitHub release was published.

## Preliminary Resource Comparison

Both hosts were started with private configuration, an explicitly absent serial
port, weather disabled, and no submitted tasks. Measurements include the full
launched process tree, including console helpers and the Python venv launcher.
Each host warmed up for two seconds, then ran idle for an eight-second sample.
Rust used the optimized, static-runtime Windows build; Python used the existing
Python 3.12 virtual environment.

| Metric | Rust | Python |
| --- | --- | --- |
| Sum of working sets | 20.60 MiB | 66.46 MiB |
| Sum of private bytes | 8.77 MiB | 47.71 MiB |
| Processes | 2: host and console helper | 3: venv launcher, interpreter, console helper |
| CPU time increase in sample | 0 ms at reported resolution | 0 ms at reported resolution |

The observed memory difference supports the background-memory goal. Summed
working sets can count shared pages more than once; private bytes are reported
separately. These short idle samples do not establish a CPU improvement, peak
memory, throughput, hook startup latency, or behavior with a connected device.
An earlier four-second process-tree sample also showed approximately 20.6/66.5
MiB working sets and 8.8/47.7 MiB private bytes; small CPU-time changes were within
the coarse sampling resolution.

## Physical Device and Project Hook Follow-up

Later on 2026-11-07, the user attached the ESP32. Windows enumerated it on
`COM6` with VID/PID `303A:1001`. The old Python service was replaced by a hidden
Rust service for this test. Its five existing task records were saved locally
before switching; firmware and user-level Codex configuration were not changed.

The first real connection reproduced Windows error 995 immediately after opening
the async serial stream. The host was purging input after Tokio had already
started an asynchronous read; the Windows purge aborted that read. Removing the
purge allowed handshake and brightness application to complete. Existing frame
and session validation handle stale input. A driver stop-bit-query warning still
appears on open, but it did not prevent synchronization or display feedback.

The updated optimized binary reported `online`, target/applied brightness 100,
and no device error. Synthetic `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, and
`Stop` callbacks were sent through the same adapter command and SQLite ledger
used by the project hooks. Observed results:

- The running card received real device `Accepted` and `Presented` feedback.
- Unchanged running callbacks did not create new revisions.
- Completion updated the same card to revision 2, with `Accepted` and `Presented`.
- The independent completion notification also received `Presented` feedback.

The test card is titled `Rust Codex hook test`. Local records are under
`.local/run/rust-codex-hook-smoke.json`. These are device acknowledgments, not a
photograph or user visual confirmation. All 24 Rust tests were rerun after the
serial fix; the Windows archive was rebuilt.

A read-only Codex 0.166.0 App Server `hooks/list` query discovered all six entries
in `.codex/hooks.json` as enabled project hooks, initially `untrusted`. No trust
hashes were changed and no agent/model task was started for this query. Native
automatic callbacks were initially pending user review. Synthetic adapter calls
alone do not establish native hook execution.

After the user trusted the project hooks, the next real message in this
conversation automatically produced a Codex `running` task through
`UserPromptSubmit`. The host reported revision 1, device `Accepted` and
`Presented`, no delivery error, and an empty hook outbox. This verifies the native
Codex-to-Rust-to-ESP32 path. On the following turn, the previous execution's
ledger state was `completed` at sequence 2, the outbox was still empty, and the
device had reported a second completion notification as `Presented`. This also
confirms the native `Stop` path after the initial synthetic smoke notification.

## Remaining Qualification

- Actual unplug/replug, port changes, powered host restart, and user visual
  confirmation remain unverified for Rust. Opening, handshake, brightness
  application, and actual device display feedback passed in the follow-up above.
  Firmware was not flashed.
- Startup installation/removal and actual logout/login were not exercised; only
  read-only status and generated launcher syntax were checked. Startup was not
  registered on the user's computer.
- A clean Windows machine without developer tools still needs a full install/run
  check. Linux/macOS and Windows ARM64 are not qualified by this record.
- Live Open-Meteo retrieval passed on 2026-11-07 after restarting Rust with the
  existing Shanghai configuration: the updater reported success, weather was
  fresh, and the physical device accepted it. Proxy variants, long-running
  connected workloads, suspend/resume, and wall-clock corrections remain pending.
- Existing Python in-memory cards are not automatically imported at cutover;
  existing hook ledger compatibility is covered by schema and transition tests.

The Python service was subsequently removed with user approval. Its source
remains in Git history, and the compatibility fixtures, embedded API contract,
and historical hardware evidence are retained. Removal does not qualify the
remaining release checks above. Python is now limited to development tooling
and optional HTTP demos under `scripts/` and `demos/`.
