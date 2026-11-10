#pragma once

#include <cstdint>

#include "power/wake_reason.h"

namespace info_tv {
/** Own ULP loading, optional timer wake, and the retained RTC context. */
class SleepDriver {
 public:
  /** Stop the previous ULP run and recognize a validated sleep-wake context. */
  void initialize();
  /** Prepare touch sampling and save the interval; zero disables timer wake. */
  bool prepare(uint32_t baseline, uint32_t unlockPollSeconds);
  /** Save context, arm touch and optional timer wake, and enter deep sleep. */
  bool enter(uint32_t baseline, uint32_t brightness);
  /** Return whether this boot was requested by the ULP touch detector. */
  bool touchWake() const { return reason_ == WakeReason::kTouch; }
  /** Return whether this boot resumed a valid touch or timer sleep context. */
  bool sleepWake() const { return reason_ != WakeReason::kCold; }
  /** Return the recognized reason so firmware can enforce silent timer probes. */
  WakeReason wakeReason() const { return reason_; }
  /** Return the saved user brightness, with a cold-boot default of 100. */
  uint32_t brightness() const { return brightness_; }
  /** Return the pre-sleep baseline for recognizing and consuming the wake touch. */
  uint32_t baseline() const { return baseline_; }

 private:
  WakeReason reason_ = WakeReason::kCold;
  bool ready_ = false;
  uint32_t brightness_ = 100;
  uint32_t baseline_ = 0;
  uint32_t unlockPollSeconds_ = 0;
};
}  // namespace info_tv
