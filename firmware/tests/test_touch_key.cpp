#include "board/touch_key.h"

#include "test_support.h"

namespace {
/** Replay regular five-millisecond samples and count externally visible edges/clicks. */
struct Replay {
  info_tv::TouchKey key;
  uint64_t nowMs = 0;
  unsigned presses = 0;
  unsigned releases = 0;
  unsigned singles = 0;
  unsigned doubles = 0;

  /** Feed one sample and record only changes of the confirmed touch state. */
  void sample(uint32_t value) {
    const bool previous = key.isTouched();
    const auto event = key.updateSample(value, nowMs);
    if (!previous && key.isTouched()) ++presses;
    if (previous && !key.isTouched()) ++releases;
    if (event == info_tv::ButtonEvent::kSingleClick) ++singles;
    if (event == info_tv::ButtonEvent::kDoubleClick) ++doubles;
    nowMs += 5;
  }

  /** Hold one input value for a duration aligned to the polling interval. */
  void hold(uint32_t value, uint64_t durationMs) {
    const uint64_t endMs = nowMs + durationMs;
    while (nowMs < endMs) sample(value);
  }
};

/** Reject isolated and short noise bursts on both press and release. */
void checkNoise() {
  Replay replay;
  replay.hold(16500, 100);
  replay.sample(16000);
  CHECK(!replay.key.isTouched());
  replay.hold(16500, 50);
  replay.hold(16400, 10);
  replay.hold(16500, 400);
  CHECK(replay.presses == 0 && replay.singles == 0 && replay.doubles == 0);
  replay.hold(16400, 60);
  CHECK(replay.key.isTouched());
  replay.sample(16500);
  CHECK(replay.key.isTouched());
  replay.hold(16400, 50);
  replay.hold(16500, 10);
  replay.hold(16400, 50);
  CHECK(replay.releases == 0);
  replay.hold(16500, 400);
  CHECK(replay.presses == 1 && replay.releases == 1 && replay.singles == 1);

  Replay upward;
  upward.hold(16500, 100);
  upward.hold(17000, 10);
  upward.hold(16500, 400);
  CHECK(upward.presses == 0 && upward.singles == 0);
  upward.hold(16400, 60);
  upward.hold(17000, 10);
  upward.hold(16400, 50);
  CHECK(upward.releases == 0);
  upward.hold(16500, 400);
  CHECK(upward.releases == 1 && upward.singles == 1);
}

/** Preserve one click per tap and one double-click for two distinct contacts. */
void checkClicks() {
  Replay replay;
  replay.hold(16500, 100);
  replay.hold(16400, 80);
  replay.hold(16500, 500);
  CHECK(replay.singles == 1 && replay.doubles == 0);
  replay.hold(16400, 80);
  replay.hold(16500, 80);
  replay.hold(16400, 80);
  replay.hold(16500, 500);
  CHECK(replay.presses == 3 && replay.releases == 3);
  CHECK(replay.singles == 1 && replay.doubles == 1);
}

/** Keep the documented press/release thresholds exact while freezing a pending contact. */
void checkThresholdBoundaries() {
  Replay replay;
  replay.hold(16500, 95);  // Cross the threshold on the 100 ms baseline-update tick.
  replay.hold(16465, 25);
  CHECK(replay.key.isTouched());  // Exactly 35 counts below baseline is a press.
  replay.hold(16482, 50);
  CHECK(replay.key.isTouched());  // Exactly 18 counts below baseline is not release.
  replay.hold(16483, 25);
  CHECK(!replay.key.isTouched());
  replay.hold(16500, 400);
  CHECK(replay.presses == 1 && replay.releases == 1 && replay.singles == 1);
}

/** Recognize slow contact, hold through the hysteresis band, and track idle drift. */
void checkSlowPressAndDrift() {
  Replay replay;
  replay.hold(16500, 100);
  for (uint32_t value = 16500; value >= 16400; --value) replay.sample(value);
  CHECK(replay.key.isTouched());
  replay.hold(16475, 100);
  CHECK(replay.key.isTouched() && replay.presses == 1);
  replay.hold(16500, 400);
  CHECK(replay.releases == 1 && replay.singles == 0);  // The slow press is a hold.
  for (uint32_t value = 16500; value >= 16450; --value) replay.hold(value, 200);
  CHECK(replay.presses == 1 && !replay.key.isTouched());
}

/** Recover a shifted wake baseline without turning the waking contact into a click. */
void checkWakeRecovery() {
  Replay shifted;
  shifted.key.restoreAfterWake(16611);
  shifted.hold(16576, 3000);
  shifted.hold(16476, 80);
  CHECK(shifted.key.isTouched());
  shifted.hold(16576, 500);
  CHECK(shifted.singles == 1 && shifted.doubles == 0);

  Replay held;
  held.key.restoreAfterWake(16500);
  held.hold(16400, 2000);
  CHECK(held.presses == 0 && held.singles == 0);
  held.hold(16500, 200);
  held.hold(16400, 80);
  held.hold(16500, 500);
  CHECK(held.presses == 1 && held.singles == 1);
}

/** Ignore failed reads, qualify short taps, and avoid clicks from a long hold. */
void checkReadGapsAndHold() {
  Replay replay;
  replay.sample(16000);  // Startup noise must not seed the baseline.
  replay.hold(16500, 100);
  CHECK(replay.key.baseline() == 16500);
  replay.hold(16400, 10);
  replay.sample(0);
  replay.hold(16500, 100);
  CHECK(replay.presses == 0);
  replay.hold(16400, 25);
  CHECK(replay.key.isTouched());
  replay.hold(16500, 400);
  CHECK(replay.singles == 1);
  replay.hold(16400, 6000);
  replay.hold(16500, 400);
  CHECK(!replay.key.isTouched() && replay.singles == 1 && replay.doubles == 0);
  replay.hold(16400, 80);
  replay.hold(16500, 400);
  CHECK(replay.singles == 2);

  Replay timer;
  timer.key.restoreAfterWake(16500, false);
  timer.hold(16500, 100);
  timer.hold(16400, 80);
  timer.hold(16500, 400);
  CHECK(timer.presses == 1 && timer.singles == 1);
}
}  // namespace

/** Exercise the same sampled detector used by firmware without ESP hardware. */
int main() {
  checkNoise();
  checkClicks();
  checkThresholdBoundaries();
  checkSlowPressAndDrift();
  checkWakeRecovery();
  checkReadGapsAndHold();
}
