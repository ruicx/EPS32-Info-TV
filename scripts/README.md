# Development tools

Scripts are grouped by responsibility:

```text
scripts/
  host/
    build_host.ps1          # Release or Debug host executables
    build_rust_release.ps1  # Windows release archive
    build_host.sh           # Bash host build
    build_rust_release.sh   # Linux tar.gz release archive
  firmware/
    build_firmware.ps1      # Build or build and flash
    build_firmware.sh       # Bash build or build and flash
    prepare_character.ps1   # Generate character image and C assets
  protocol/
    generate_protocol.py    # Generate or verify Nanopb bindings
  pyproject.toml            # Shared Python development environment
  uv.lock
```

See [character assets](../firmware/main/ui/assets/README.md) for the source
images and arguments required by `firmware/prepare_character.ps1`.

## Build and flash shortcuts

The build scripts resolve project paths relative to themselves, so they can
be invoked from any working directory. Examples below run from the repository root.

```powershell
./scripts/host/build_host.ps1
./scripts/host/build_host.ps1 -Debug
./scripts/firmware/build_firmware.ps1
./scripts/firmware/build_firmware.ps1 -Action Flash -Port COM6
```

Host builds require Rust and native build tools (on Windows, the Visual Studio
C++ build tools and Windows SDK). Cargo builds both host executables with the
locked dependencies; the default output is `host/target/release`, or
`host/target/debug` with `-Debug`, unless Cargo's target directory is overridden.
Use `host/build_rust_release.ps1` for a packaged Windows release archive:

```powershell
./scripts/host/build_rust_release.ps1
```

Firmware commands require an activated ESP-IDF v6.1 PowerShell environment.
`Build` is the default action. `Flash` builds first and requires an explicit port;
replace `COM6` with the device's serial port and stop any service or monitor using
that port before flashing. Build output goes to `firmware/build`.
The scripts stop with an error when the underlying command fails.

## Linux / Bash

Run with Bash; no executable permission changes are required:

```bash
bash scripts/host/build_host.sh
bash scripts/host/build_host.sh --debug
bash scripts/host/build_host.sh --target aarch64-unknown-linux-gnu
bash scripts/host/build_rust_release.sh
bash scripts/firmware/build_firmware.sh
bash scripts/firmware/build_firmware.sh --action flash --port /dev/ttyACM0
```

Install Rust and native C/C++ build tools for Host builds. Cross compilation with
`--target` also requires the appropriate Rust target and native linker/toolchain.
The Linux packaging script defaults to the Rust compiler's host triple, reuses
`build_host.sh`, and reads the version and output directory from Cargo metadata.
It requires Python 3, tar, and sha256sum, and writes the two executables,
configuration, and README to `build/rust-host-dist/info-tv-VERSION-TARGET.tar.gz`.
Linux archives use the target's normal runtime linkage; GNU builds require a
compatible system runtime on the destination machine.

Activate ESP-IDF v6.1 before firmware operations. Replace `/dev/ttyACM0` with the
device port, ensure your account has serial-port access, and stop any service or
monitor using that port before flashing.

The Python commands below also work in Bash. Character asset preparation via
`firmware/prepare_character.ps1` remains Windows-only because it uses
`System.Drawing`; the generated assets are already checked in and are sufficient
for normal Linux firmware builds.

## Python development tools

The host is built and tested with Cargo under `host/`. The Python project
here only supplies firmware protocol generation and Ruff/ty checks. It does not
install a host service, CLI, or hooks. Python 3.12+ and uv are needed for these
development operations; released host executables need neither.

Run from the repository root:

```powershell
uv sync --project scripts --locked
uv run --project scripts --locked python scripts/protocol/generate_protocol.py --check
uv run --project scripts --locked ruff check --config scripts/pyproject.toml scripts demos
uv run --project scripts --locked ty check --project scripts scripts demos
```

Omit `--check` to update the committed `firmware/main/protocol/generated/device.pb.c`
and `device.pb.h` after editing `protocol/device.proto` or `device.options`.
Nanopb is pinned to the vendored firmware runtime version. `grpcio-tools`
provides the schema compiler used by Nanopb; no standalone protoc is needed.
Rust bindings are generated independently by `host/build.rs` using its
Cargo-locked, build-only protoc. No Python bindings are maintained.

The HTTP demos use only Python's standard library and can run directly:

```powershell
python demos/demo_task.py --help
python demos/demo_conversations.py --help
```

See [display demos](../demos/README.md) before running them against a device.
They submit real events to the running service.

Build the Windows release archive with `scripts/host/build_rust_release.ps1`; Python
is not used by that script. ESP-IDF retains its own independent tool environment.
