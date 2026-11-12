# info-tv Rust host

Run the local display service without installing Python. Windows archives include
`info-tv.exe` for the CLI/service and `info-tv-startup.exe` for windowless login
startup. Keep both executables together and update them from the same release.
Firmware must already
be installed on the supported ESP32-S3 board. This archive does not include a
firmware flashing tool. Full project and hardware instructions:
[ESP32-Info-TV](https://github.com/ruicx/EPS32-Info-TV).

## Quick start on Windows

Extract the archive to a stable location such as `C:\info-tv`. In PowerShell:

```powershell
Set-Location C:\info-tv
.\info-tv.exe ports
.\info-tv.exe serve
```

The service selects a single matching USB device and retries while disconnected.
For several matching devices, set `serial_port` in `info-tv.yaml` or pass
`serve --serial-port COM6`. Run one host instance per HTTP port and display.

From a second PowerShell window:

```powershell
C:\info-tv\info-tv.exe status
C:\info-tv\info-tv.exe task submit --task-id hello-1 --sequence 1 --state running --title "Hello info_tv"
C:\info-tv\info-tv.exe task list
```

API: `http://127.0.0.1:8765`; interactive reference: `/docs`. The reference UI
loads Swagger assets from a CDN. API operations work without those assets.
HTTP acceptance does not mean the display has presented the content.

## Configuration and state

Use `serve --config C:\info-tv\info-tv.yaml` to select a file explicitly. Without
`--config`, `serve` and `ports` look for `info-tv.yaml` beside the executable,
independent of the current working directory. If that default file is absent,
built-in defaults apply. An explicit
missing file or an invalid selected file is an error. CLI settings override YAML.
The included YAML leaves automatic weather disabled; uncomment its example to
enable it. Restart after changing configuration.

On Windows, set `lock_action: deep_sleep` in YAML to sleep the ESP32 when the
current session locks. Touch the top pad to wake; while Windows stays locked,
the visible preview lasts 15 seconds, then the device sleeps again. Unlocking
during the preview keeps it awake. Set `unlock_poll_seconds: 5` to check unlock
automatically after each five-second sleep. Timer wakes stay dark until the host
confirms unlock; locked probes sleep again. Startup and USB reconnection add to
the recovery delay. The default interval is zero, disabling automatic checks.
Update host and firmware together. The default `none` disables lock following;
`screen_off` only turns off the backlight and restores brightness on unlock.
The host samples session state once per second through a hidden Windows
PowerShell helper, requiring `Add-Type`. Keep the host running to confirm unlock.

The service saves accepted tasks, recent replay/closure protection, target
brightness, and weather/alert expiry in `data/host.sqlite3` beside the executable.
Hook ledgers use `data/codex-hooks.sqlite3`, `data/agy-hooks.sqlite3`, and
`data/zcode-hooks.sqlite3`. Logs rotate daily in the sibling `logs` directory,
retaining seven files. Symbolic links resolve to the actual executable directory.
The installation directory must be writable by the current user.

`serve --state-dir <path>` selects a custom host state directory, with logs under
`<path>/logs`. It does not change hook ledger paths; hooks accept an explicit
`--state-file`. Explicit relative paths are resolved against the working directory.

When upgrading from the per-user layout, stop the host and hook producers, back
up `%LOCALAPPDATA%\info_tv` (or `~/.local/state/info_tv` on other platforms), and
copy all SQLite databases and any `-wal`/`-shm` companions into the new `data`
directory. Copy old logs into the sibling `logs` directory. Preserve the YAML
configuration. Do not copy live SQLite files; use SQLite's backup API for an
online snapshot. There is no automatic import from the old location. See the
repository's `docs/host-cli.md` for migration and path override details.

Restart restores task state and target brightness. Connection and display
feedback are obtained again; old pop-up notifications are not replayed. Downtime
counts toward completed-task retention and weather expiry. Replacing the binary
preserves user data. Do not run older software against a newer database schema.

## Login startup

Register explicitly under the current Windows user:

```powershell
C:\info-tv\info-tv.exe autostart install --config C:\info-tv\info-tv.yaml
C:\info-tv\info-tv.exe autostart status
C:\info-tv\info-tv.exe autostart remove
```

Registration takes effect at the next login; start `serve` manually for the
current session. The logon task runs with limited user privileges, fixed paths,
and directly launches `info-tv-startup.exe`. This native Windows GUI-subsystem
launcher starts the adjacent `info-tv.exe serve` with `CREATE_NO_WINDOW`, waits
for it, and returns its exit code. The CLI remains a console application.
The launcher owns a kill-on-close Windows job, so terminating the task also
terminates the host and its helper processes. Committed SQLite state survives.
PowerShell is used to register the task, not as its startup action; Windows lock
monitoring still uses its separate hidden helper. No Windows 11-only console
allocation policy is required. Removal unregisters startup; it does not stop
an already-running service or delete its data. This is not a system service.
To stop a hidden instance before an update, end `info-tv.exe` in Task Manager.
Committed state survives this forced stop.
The task's working directory uses the actual executable directory, regardless
of where `autostart install` is invoked.
Short Windows drive paths are saved without the `\\?\` prefix when the ordinary
path resolves to the same location. Long or special paths retain their prefix.
Explicit relative config/state options are resolved before registration against
the directory from which the install command was invoked.
Startup errors and the host's console output are appended to `logs/startup.log`
beside the executables. The host's separate daily `host.*` logs retain their
seven-file rotation. `startup.log` is append-only. The launcher forwards server
options; explicit relative paths use its invocation directory.

After upgrading from the PowerShell startup task, run `autostart install` again
to replace its action. An old `data/autostart.ps1` is no longer used and can be
removed after verification. Re-register startup and update external hook commands
after moving the installation directory. Stop the task before replacing either
executable.

## Agent hooks

Use `C:\info-tv\info-tv.exe hook <source>` in agent hook configurations:

```text
info-tv.exe hook codex
info-tv.exe hook agy PreInvocation
info-tv.exe hook agy PreToolUse
info-tv.exe hook agy PostToolUse
info-tv.exe hook agy Stop
info-tv.exe hook zcode
```

The agent supplies its native callback JSON on stdin. Hook commands preserve
execution ordering and save events before attempting HTTP delivery. With the
service unavailable they retain events locally and emit neutral JSON. Retry on
the next callback or explicitly flush with `info-tv.exe hook codex --flush`.
Source-specific instructions are in the repository's `docs` directory.

## Build and verify from source

Requires Rust 1.89 or newer and the platform C/C++ build tools for bundled SQLite.
For Windows, use the MSVC toolchain with Visual Studio C++ Build Tools. Protobuf
compiler binaries are fetched as build dependencies; release users need neither
Rust, protoc, SQLite, nor Python installed.

From the repository root:

```powershell
cargo test --manifest-path host/Cargo.toml --features windows-startup --locked
cargo clippy --manifest-path host/Cargo.toml --all-targets --features windows-startup --locked -- -D warnings
cargo fmt --manifest-path host/Cargo.toml -- --check
powershell -NoProfile -File scripts/host/build_host_release.ps1
```

The archive is written under `build/host-dist`. The packaging script builds
both Windows executables with the static MSVC runtime and enables the
`windows-startup` feature automatically. Direct Cargo builds omit the startup
target unless this feature is enabled. Omit it for non-Windows checks.
Build scripts resolve `--target` / `-Target`, then `CARGO_BUILD_TARGET`, then the
Rust host triple; their output is under `host/target/<triple>/<profile>`.
They do not publish the archive.
Build `firmware/tests` first to run the Rust-to-C++ bridge integration. Set
`INFO_TV_PROTOCOL_BRIDGE` if the executable uses a nondefault path. Other Rust
tests do not need the device, ESP-IDF, or Python. Hardware and login startup
validation must be recorded separately from desktop tests.
