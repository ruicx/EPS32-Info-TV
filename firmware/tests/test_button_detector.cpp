#include "input/button_detector.h"

#include <iostream>

#include "test_support.h"

namespace {

void testDebounceFilter() {
  info_tv::ButtonDetector detector(25, 350, 300);

  // Glitch: pressed for only 15ms (less than 25ms debounce)
  CHECK(detector.update(true, 100) == info_tv::ButtonEvent::kNone);
  CHECK(detector.update(true, 110) == info_tv::ButtonEvent::kNone);
  CHECK(detector.update(false, 115) == info_tv::ButtonEvent::kNone);

  // Even after interval timeout, no single click should be emitted
  CHECK(detector.update(false, 500) == info_tv::ButtonEvent::kNone);
}

void testSingleClick() {
  info_tv::ButtonDetector detector(25, 350, 300);

  // Press for 80ms (valid tap)
  CHECK(detector.update(true, 100) == info_tv::ButtonEvent::kNone);
  CHECK(detector.update(true, 150) == info_tv::ButtonEvent::kNone);
  CHECK(detector.update(false, 180) == info_tv::ButtonEvent::kNone);

  // Wait until double click interval (300ms) expires at 180 + 301 = 481ms
  CHECK(detector.update(false, 300) == info_tv::ButtonEvent::kNone);
  CHECK(detector.update(false, 480) == info_tv::ButtonEvent::kNone);
  CHECK(detector.update(false, 481) == info_tv::ButtonEvent::kSingleClick);

  // Subsequent idle ticks return kNone
  CHECK(detector.update(false, 500) == info_tv::ButtonEvent::kNone);
}

void testDoubleClick() {
  info_tv::ButtonDetector detector(25, 350, 300);

  // First tap: press at 100ms, release at 160ms (duration 60ms)
  CHECK(detector.update(true, 100) == info_tv::ButtonEvent::kNone);
  CHECK(detector.update(false, 160) == info_tv::ButtonEvent::kNone);

  // Gap of 80ms: second press starts at 240ms
  CHECK(detector.update(false, 200) == info_tv::ButtonEvent::kNone);
  CHECK(detector.update(true, 240) == info_tv::ButtonEvent::kNone);

  // Second press debounced at 240 + 25 = 265ms: fires double-click immediately!
  CHECK(detector.update(true, 255) == info_tv::ButtonEvent::kNone);
  CHECK(detector.update(true, 265) == info_tv::ButtonEvent::kDoubleClick);

  // Still holding: no repeated event
  CHECK(detector.update(true, 280) == info_tv::ButtonEvent::kNone);
  CHECK(detector.update(true, 300) == info_tv::ButtonEvent::kNone);

  // Release: resets to idle
  CHECK(detector.update(false, 320) == info_tv::ButtonEvent::kNone);
  CHECK(detector.update(false, 700) == info_tv::ButtonEvent::kNone);
}

void testLongPressIgnored() {
  info_tv::ButtonDetector detector(25, 350, 300);

  // Held longer than maxClickMs (350ms)
  CHECK(detector.update(true, 100) == info_tv::ButtonEvent::kNone);
  CHECK(detector.update(true, 400) == info_tv::ButtonEvent::kNone);
  CHECK(detector.update(true, 500) == info_tv::ButtonEvent::kNone);

  // Release after long hold: no click emitted
  CHECK(detector.update(false, 600) == info_tv::ButtonEvent::kNone);
  CHECK(detector.update(false, 1000) == info_tv::ButtonEvent::kNone);
}

void testReset() {
  info_tv::ButtonDetector detector(25, 350, 300);

  // Start pressing
  CHECK(detector.update(true, 100) == info_tv::ButtonEvent::kNone);
  detector.reset();

  // Releasing after reset doesn't emit anything
  CHECK(detector.update(false, 160) == info_tv::ButtonEvent::kNone);
  CHECK(detector.update(false, 600) == info_tv::ButtonEvent::kNone);
}

}  // namespace

int main() {
  testDebounceFilter();
  testSingleClick();
  testDoubleClick();
  testLongPressIgnored();
  testReset();
  std::cout << "All button detector tests passed.\n";
  return 0;
}
