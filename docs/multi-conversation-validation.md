# Multi-conversation overview validation

Date: 2026-11-05

Scope: Desktop verification, an ESP32-S3 firmware build, and USB device feedback
after flashing on 2026-11-05. These images are CPU-rendered LVGL output rather than
photographs of the physical display. On the same date, the user confirmed that
physical text, layout, and page rotation were normal.
Earlier hardware evidence is retained in
[Hardware Validation](hardware-validation.md).

## Behavior

- Eight independent persistent conversation/task cards, three rows per page.
- Six-second page rotation; attention first, with all pages still visited.
- Source, conversation title, project, state, and optional reported progress.
- Stable conversation cards across executions, with increasing `run_sequence`;
  each execution keeps its own `task_id`, update sequence, and completion notice.
- Late execution updates cannot overwrite newer execution state; duplicate and
  conflicting event IDs retain the existing admission rules.
- Related notifications restore the page containing their card for a full interval.
- Per-row Presented feedback after the shared refresh, without claiming that
  hidden pages or superseded revisions were displayed.
- Cached offline state is labeled `last:` and does not show a live percentage.

## Checks

```powershell
cmake -S firmware/tests -B build/native-tests -DINFO_TV_BUILD_UI_TESTS=ON
cmake --build build/native-tests --config Debug
ctest --test-dir build/native-tests -C Debug -LE hardware --output-on-failure

cd host
uv run pytest
uv run ty check . ../scripts ../demos
uv run python ../scripts/generate_protocol.py --check
```

The optional screen test uses the LVGL dependency downloaded by the firmware
build; the default native core tests remain independent of LVGL. It checks widget
bounds, source/header content, long-to-short text replacement, row hiding,
and offline/empty/notification layout states. Portable pixel images
are written as `build/native-tests/screen-*.ppm`.

Results: 30 Python tests passed, including two real Python-to-C++ bridge tests;
four CTest cases passed with screen verification enabled; static analysis and
generated binding checks passed. The eight-conversation integration test waits
for later pages to receive their individual visibility acknowledgments.

The generated maximum envelope is 4029 bytes, within the unchanged 4096-byte
payload limit. Native codec tests round-trip an eight-card maximum-field snapshot.
The ESP-IDF v6.1 firmware build passed within the existing 1 MiB app partition.
The final binary is 682,768 bytes (35% partition space remains), SHA-256
`e11016545ae2c5c1076e7bfd2fbc8568bc842afb60309d9c02bc29624cacd7b4`.
Compiled Xtensa entry frames are 32 bytes for communication `dispatch` and
272 bytes for `poll` after moving/resetting large messages outside local stack
temporaries. These are static frame observations, not measured hardware stack
high-water marks.

## Actual LVGL output

Overview, at its native 240 × 240 resolution:

![Desktop-rendered multi-conversation overview](images/multi-conversation-overview.png)

Powered but disconnected cached content:

![Desktop-rendered offline state](images/multi-conversation-offline.png)

Temporary related notification:

![Desktop-rendered notification](images/multi-conversation-notification.png)

## Remaining limits

System labels remain English. The enabled LVGL Source Han Sans SC 16 px font is
a limited CJK subset; these screenshots establish the displayed example only,
not arbitrary Chinese coverage. A complete simplified-Chinese font remains work
for a separate asset pass.

Card deletion, automatic retention expiry, actual Codex/agy adapters, and the
general notification API are not implemented in this stage. Eight current cards
are retained until host restart; existing conversations can keep receiving new
executions at capacity. `demos/demo_conversations.py` submits simulated clients
through the real API for manual display checks.

The host and firmware were deployed together on 2026-11-05. Device Hello
advertises the required `max_cards >= 8`; the host reports older firmware
as incompatible instead of sending an oversized snapshot. Five simulated
conversations across two overview pages and both important notifications returned
actual device Presented feedback, establishing LCD refresh/DMA completion.
Separately, the user confirmed physical text, layout, and page rotation as normal.
This does not establish precise timing measurements or acknowledgment of each
individual notification. The eight-card maximum remains
covered by desktop tests; this device run submitted five cards.

See the [deployment and backup record](hardware-validation.md#6-multi-conversation-firmware-deployment).
