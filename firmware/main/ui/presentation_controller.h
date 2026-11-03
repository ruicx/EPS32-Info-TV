#pragma once

#include <cstdint>

#include "protocol/model.h"
#include "ui/display_state.h"

namespace info_tv {
/** Apply commands and arbitrate presentation without LVGL or RTOS dependencies. */
class PresentationController {
 public:
  /** Create an empty UI-owned presentation controller. */
  explicit PresentationController(DisplayState& state) : state_(state) {}
  /** Apply one command and produce its UI acceptance or rejection. */
  bool handleCommand(const DisplayCommand& command, uint64_t nowMs, Feedback& feedback);
  /** Advance local timers and return the current render request. */
  const RenderModel& tick(uint64_t nowMs);
  /** Report actual first-frame completion for a still-current render generation. */
  bool onFramePresented(uint32_t generation, uint64_t nowMs, Feedback& feedback);

 private:
  /** Populate a feedback identity from the command without serializing it. */
  void identify(const Envelope& envelope, Feedback& feedback) const;
  DisplayState& state_;
  RenderModel render_{};
  NotificationSlot active_{};
  bool hasActive_ = false;
  bool connected_ = false;
  uint64_t activeUntilMs_ = 0;
  uint64_t nextRotationMs_ = 0;
  size_t cardIndex_ = 0;
};
}  // namespace info_tv
