# info-tv Rust host

Run the local display service without installing Python. Firmware must already
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
`--config`, `serve` and `ports` look for `info-tv.yaml` in the current working
directory. If that default file is absent, built-in defaults apply. An explicit
missing file or an invalid selected file is an error. CLI settings override YAML.
The included YAML leaves automatic weather disabled; uncomment its example to
enable it. Restart after changing configuration.

The service saves accepted tasks, recent replay/closure protection, target
brightness, and weather/alert expiry in `%LOCALAPPDATA%\info_tv\host.sqlite3`.
Logs rotate daily under `logs`, retaining seven files. `serve --state-dir <path>`
selects an isolated state directory. Hook ledgers keep their existing independent
per-user paths, or use an explicit `--state-file`.

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
and a hidden PowerShell launcher. Removal unregisters startup; it does not stop
an already-running service or delete its data. This is not a system service.
To stop a hidden instance before an update, end `info-tv.exe` in Task Manager.
Committed state survives this forced stop.

## Agent hooks

Replace the Python executable path in existing hook configurations with
`C:\info-tv\info-tv-hook.exe`; source names and callback arguments stay the same.
The equivalent consolidated entry point is `info-tv.exe hook <source>`:

```text
info-tv.exe hook codex
info-tv.exe hook agy PreInvocation
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
cargo test --manifest-path host-rust/Cargo.toml --locked
cargo clippy --manifest-path host-rust/Cargo.toml --all-targets --locked -- -D warnings
cargo fmt --manifest-path host-rust/Cargo.toml -- --check
powershell -NoProfile -File scripts/build_rust_release.ps1
```

The archive is written under `build/rust-host-dist`. The packaging script builds
both executables with the static MSVC runtime. It does not publish them.
Build `firmware/tests` first to run the Rust-to-C++ bridge integration. Set
`INFO_TV_PROTOCOL_BRIDGE` if the executable uses a nondefault path. Other Rust
tests do not need the device, ESP-IDF, or Python. Hardware and login startup
validation must be recorded separately from desktop tests.
