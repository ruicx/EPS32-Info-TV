# Repository Guidelines

## Project Structure & Module Organization

- `host-rust/`: Rust service, durable task state, USB device communication, CLI, and hooks; integration tests live in `host-rust/tests/`.
- `firmware/main/`: ESP32-S3 application, board drivers, communication, protocol, and LVGL UI; desktop C++ tests live in `firmware/tests/`.
- `protocol/`: shared Protobuf schema, Nanopb bounds, and compatibility vectors. Firmware bindings are checked in; Cargo generates Rust bindings during builds.
- `scripts/`: protocol generation, locked Python development tools, and release packaging; `demos/`: standard-library Python HTTP demonstrations; `docs/`: architecture, hardware references, and validation evidence.

## Build, Test, and Development Commands

Run from the repository root unless stated otherwise:

```powershell
cargo run --manifest-path host-rust/Cargo.toml --locked -- serve --serial-port COM6
python demos/demo_task.py
idf.py -C firmware build
cmake -S firmware/tests -B build/native-tests
cmake --build build/native-tests --config Debug
ctest --test-dir build/native-tests -C Debug -LE hardware --output-on-failure
```

These launch the host, demonstrate task progress, build firmware, and build/run desktop tests. Replace `COM6` with the enumerated device port. Firmware builds require an activated ESP-IDF v6.1 environment.

Additional checks from the repository root:

```powershell
cargo fmt --manifest-path host-rust/Cargo.toml -- --check
cargo clippy --manifest-path host-rust/Cargo.toml --all-targets --locked -- -D warnings
cargo test --manifest-path host-rust/Cargo.toml --locked
uv sync --project scripts --locked
uv run --project scripts --locked ruff check --config scripts/pyproject.toml scripts demos
uv run --project scripts --locked ty check --project scripts scripts demos
uv run --project scripts --locked python scripts/generate_protocol.py --check
```

After schema changes, regenerate firmware bindings with `uv run --project scripts --locked python scripts/generate_protocol.py`. Cargo independently generates Rust bindings from the same schema.

## Coding Style & Naming Conventions

Use four-space Python indentation, `snake_case` functions, `PascalCase` classes, complete type annotations, and NumPy-style docstrings. Prefer small, pure helpers and explicit dataclasses; avoid global mutable state. Use Ruff for linting and ty for type checking; their settings live in `scripts/pyproject.toml`. Keep formatting changes scoped.

Use rustfmt and Clippy for Rust, keeping changes consistent with surrounding code. Build Windows host archives with `scripts/build_rust_release.ps1`; the package version comes from `host-rust/Cargo.toml`. No Python host package is built.

For C++, use two-space indentation, Google-style conventions, `camelCase` functions/variables, `PascalCase` classes, and Doxygen comments. Prefer `nullptr`, `override`, and short functions with early returns. Keep changes focused and match surrounding code.

## Documentation Language

Write all documentation in English. Bilingual README files are the only exception.

## Testing Guidelines

Use Rust integration tests under `host-rust/tests/` and native C++ files named `test_*.cpp`, registered through CMake/CTest. Mark physical-device checks explicitly; native C++ hardware cases use the `hardware` label. Build `protocol_bridge` before Rust bridge integration tests. Retain language-independent compatibility fixtures when removing legacy implementations. No coverage threshold is configured; add regression coverage for changed behavior.

## Commit & Pull Request Guidelines

Use `<Type>: <summary>` with `Feat`, `BugFix`, `Refactor`, or `Doc`, followed by a blank line and numbered change details, matching recent history.

Pull requests should explain the problem, resulting behavior, related issues, and verification performed. Include display screenshots or hardware evidence for UI/device changes, distinguishing desktop checks from physical validation.
