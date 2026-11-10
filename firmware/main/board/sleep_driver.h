#pragma once

#include <cstdint>

namespace info_tv {
/** Own ULP loading and the small RTC context retained across touch wakes. */
class SleepDriver {
 public:
  /** Stop the previous ULP run and recognize a validated touch-wake context. */
  void initialize();
  /** Load the embedded ULP program and check that touch sampling is available. */
  bool prepare(uint32_t baseline);
  /** Save context, arm release-before-touch detection, and enter deep sleep. */
  bool enter(uint32_t baseline, uint32_t brightness);
  /** Return whether this boot was requested by the ULP touch detector. */
  bool touchWake() const { return touchWake_; }
  /** Return the saved user brightness, with a cold-boot default of 100. */
  uint32_t brightness() const { return brightness_; }
  /** Return the pre-sleep baseline for recognizing and consuming the wake touch. */
  uint32_t baseline() const { return baseline_; }

 private:
  bool touchWake_ = false;
  bool ready_ = false;
  uint32_t brightness_ = 100;
  uint32_t baseline_ = 0;
};
}  // namespace info_tv
