# Repository Guidelines

## Project Structure & Module Organization

- `host/src/info_tv_service/`: Python 3.12 FastAPI service, task state, and USB device communication; tests live in `host/tests/`.
- `firmware/main/`: ESP32-S3 application, board drivers, communication, protocol, and LVGL UI; desktop C++ tests live in `firmware/tests/`.
- `protocol/`: shared Protobuf schema, Nanopb bounds, and compatibility vectors. Generated bindings are checked into both implementations.
- `scripts/`: protocol generation; `demos/`: physical-display demonstrations; `docs/`: architecture, hardware references, and validation evidence.

## Build, Test, and Development Commands

Run from the repository root unless stated otherwise:

```powershell
uv sync --project host --locked
uv run --project host info-tv --serial-port COM6
uv run --project host python demos/demo_task.py
idf.py -C firmware build
cmake -S firmware/tests -B build/native-tests
cmake --build build/native-tests --config Debug
ctest --test-dir build/native-tests -C Debug -LE hardware --output-on-failure
```

These install locked dependencies, launch the host, demonstrate task progress, build firmware, and build/run desktop tests. Replace `COM6` with the enumerated device port. Firmware builds require an activated ESP-IDF v6.1 environment.

From `host/`:

```powershell
uv run pytest
uv run ty check . ../scripts ../demos
uv run python ../scripts/generate_protocol.py --check
```

After schema changes, regenerate bindings from the root with `uv run --project host python scripts/generate_protocol.py`.

## Coding Style & Naming Conventions

Use four-space Python indentation, `snake_case` functions, `PascalCase` classes, complete type annotations, and NumPy-style docstrings. Prefer small, pure helpers and explicit dataclasses; avoid global mutable state. Static checking uses `ty`; no formatter is configured.

For C++, use two-space indentation, Google-style conventions, `camelCase` functions/variables, `PascalCase` classes, and Doxygen comments. Prefer `nullptr`, `override`, and short functions with early returns. Keep changes focused and match surrounding code.

## Testing Guidelines

Use pytest files named `test_*.py` and native C++ files named `test_*.cpp`, registered through CMake/CTest. Default pytest runs exclude `hardware`; mark physical-device cases explicitly. Use `integration` for cross-component Python tests. Build `protocol_bridge` before bridge integration tests. No coverage threshold is configured; add regression coverage for changed behavior.

## Commit & Pull Request Guidelines

Use `<Type>: <summary>` with `Feat`, `BugFix`, `Refactor`, or `Doc`, followed by a blank line and numbered change details, matching recent history.

Pull requests should explain the problem, resulting behavior, related issues, and verification performed. Include display screenshots or hardware evidence for UI/device changes, distinguishing desktop checks from physical validation.
