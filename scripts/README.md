# Development tools

The host is built and tested with Cargo under `host-rust/`. The Python project
here only supplies firmware protocol generation and Ruff/ty checks. It does not
install a host service, CLI, or hooks. Python 3.12+ and uv are needed for these
development operations; released host executables need neither.

Run from the repository root:

```powershell
uv sync --project scripts --locked
uv run --project scripts --locked python scripts/generate_protocol.py --check
uv run --project scripts --locked ruff check --config scripts/pyproject.toml scripts demos
uv run --project scripts --locked ty check --project scripts scripts demos
```

Omit `--check` to update the committed `firmware/main/protocol/generated/device.pb.c`
and `device.pb.h` after editing `protocol/device.proto` or `device.options`.
Nanopb is pinned to the vendored firmware runtime version. `grpcio-tools`
provides the schema compiler used by Nanopb; no standalone protoc is needed.
Rust bindings are generated independently by `host-rust/build.rs` using its
Cargo-locked, build-only protoc. No Python bindings are maintained.

The HTTP demos use only Python's standard library and can run directly:

```powershell
python demos/demo_task.py --help
python demos/demo_conversations.py --help
```

See [display demos](../demos/README.md) before running them against a device.
They submit real events to the running service.

Build the Windows release archive with `scripts/build_rust_release.ps1`; Python
is not used by that script. ESP-IDF retains its own independent tool environment.
