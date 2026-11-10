#include "power/power_policy.h"

#include "input/touch_wakeup.h"
#include "board/touch_key.h"
#include "test_support.h"

/** Verify visible-time timing, stale lock samples, unlock, and later relocking. */
int main() {
  using info_tv::PowerPolicy;
  constexpr auto kDeep = info_tv_v1_LockAction_LOCK_ACTION_DEEP_SLEEP;
  constexpr auto kNone = info_tv_v1_LockAction_LOCK_ACTION_NONE;
  PowerPolicy cold;
  CHECK(!cold.shouldSleep(0));
  cold.configure(kDeep, true);
  CHECK(cold.shouldSleep(0));
  PowerPolicy wake(true);
  CHECK(!wake.shouldSleep(100000));  // Boot and USB reconnection do not consume preview time.
  wake.framePresented(100000);
  wake.configure(kDeep, true);
  wake.framePresented(110000);  // Refreshes and repeated settings never extend the window.
  CHECK(!wake.shouldSleep(114999));
  CHECK(wake.shouldSleep(115000));
  PowerPolicy unlocked(true);
  unlocked.framePresented(1000);
  unlocked.configure(kDeep, false);
  CHECK(!unlocked.shouldSleep(50000));
  unlocked.configure(kDeep, true);
  CHECK(unlocked.shouldSleep(50000));
  PowerPolicy disabled(true);
  disabled.configure(kNone, true);
  CHECK(!disabled.shouldSleep(50000));
  PowerPolicy dark(true);
  dark.skipDarkPreview();
  CHECK(dark.shouldSleep(0));
  dark.configure(kDeep, false);
  CHECK(!dark.shouldSleep(50000));

  TouchWakeState touch{16500, 0, 0, 0, false};
  for (int i = 0; i < 10; ++i) CHECK(!updateTouchWake(&touch, 16400)); // Held at entry.
  for (int i = 0; i < 3; ++i) CHECK(!updateTouchWake(&touch, 16500));
  CHECK(touch.armed);
  CHECK(!updateTouchWake(&touch, 16400));
  CHECK(!updateTouchWake(&touch, 16500)); // A noise spike is not a touch.
  CHECK(!updateTouchWake(&touch, 16400));
  CHECK(!updateTouchWake(&touch, 16400));
  CHECK(updateTouchWake(&touch, 16400));
  CHECK(!updateTouchWake(&touch, 0));
  // Recorded on hardware after 30 seconds: the sleep baseline shifts by 35 counts.
  TouchWakeState shifted{16611, 0, 0, 0, false};
  for (int i = 0; i < 3; ++i) CHECK(!updateTouchWake(&shifted, 16576));
  CHECK(shifted.armed);
  CHECK(shifted.baseline == 16576);
  for (int i = 0; i < 1000; ++i) CHECK(!updateTouchWake(&shifted, 16576));
  CHECK(!updateTouchWake(&shifted, 16476));
  CHECK(!updateTouchWake(&shifted, 16476));
  CHECK(updateTouchWake(&shifted, 16476));
  // A settling ADC must not arm until three readings fit the release-noise band.
  TouchWakeState settling{16611, 0, 0, 0, false};
  for (uint32_t sample : {16611U, 16580U, 16540U, 16500U})
    CHECK(!updateTouchWake(&settling, sample));
  CHECK(!settling.armed);
  CHECK(!updateTouchWake(&settling, 16500));
  CHECK(!updateTouchWake(&settling, 16500));
  CHECK(settling.armed);
  info_tv::TouchKey key;
  key.restoreAfterWake(16500);
  key.setTouched(true);
  CHECK(key.tick(100) == info_tv::ButtonEvent::kNone);
  key.setTouched(true);
  CHECK(key.tick(180) == info_tv::ButtonEvent::kNone);
  key.setTouched(false);
  CHECK(key.tick(200) == info_tv::ButtonEvent::kNone);
  CHECK(key.tick(300) == info_tv::ButtonEvent::kNone);
  CHECK(key.tick(700) == info_tv::ButtonEvent::kNone); // The waking press produced no click.
  key.setTouched(true);
  CHECK(key.tick(800) == info_tv::ButtonEvent::kNone);
  key.setTouched(false);
  CHECK(key.tick(880) == info_tv::ButtonEvent::kNone);
  CHECK(key.tick(1181) == info_tv::ButtonEvent::kSingleClick);
  return 0;
}
