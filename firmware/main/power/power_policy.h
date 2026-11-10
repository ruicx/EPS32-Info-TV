#pragma once

#include <cstdint>

#include "protocol/generated/device.pb.h"
#include "power/wake_reason.h"

namespace info_tv {
/** Device-owned lock policy, silent timer probes, and one touch-wake preview. */
class PowerPolicy {
 public:
  /** Start locked after sleep, with a touch preview or a five-second silent probe. */
  explicit PowerPolicy(WakeReason reason = WakeReason::kCold, uint64_t nowMs = 0);
  /** Apply an absolute policy; repeated locked samples do not extend the preview. */
  void configure(info_tv_v1_LockAction action, bool locked);
  /** Start the fifteen-second window when content becomes visible on the panel. */
  void framePresented(uint64_t nowMs);
  /** Return whether the current lock state or expired preview requires deep sleep. */
  bool shouldSleep(uint64_t nowMs) const;
  /** Return whether this boot is still displaying a temporary touch-wake preview. */
  bool preview() const { return preview_; }
  /** Allow a positive PWM only after unlock confirmation or an explicit touch. */
  bool backlightAllowed() const { return !silent_; }
  /** Let a new touch take over a silent probe without renewing an existing preview. */
  bool touchPressed();
  /** End a preview that cannot become visible because the user selected brightness zero. */
  void skipDarkPreview() { preview_ = false; }

 private:
  info_tv_v1_LockAction action_ = info_tv_v1_LockAction_LOCK_ACTION_NONE;
  bool locked_ = false;
  bool preview_ = false;
  bool probing_ = false;
  bool silent_ = false;
  uint64_t probeDeadlineMs_ = 0;
  uint64_t previewDeadlineMs_ = 0;
};
}  // namespace info_tv
