#include "power/power_policy.h"

namespace info_tv {
PowerPolicy::PowerPolicy(bool touchWake) : preview_(touchWake) {
  if (touchWake) {
    action_ = info_tv_v1_LockAction_LOCK_ACTION_DEEP_SLEEP;
    locked_ = true;
  }
}

void PowerPolicy::configure(info_tv_v1_LockAction action, bool locked) {
  action_ = action;
  locked_ = locked;
  if (action != info_tv_v1_LockAction_LOCK_ACTION_DEEP_SLEEP || !locked) preview_ = false;
}

void PowerPolicy::framePresented(uint64_t nowMs) {
  if (preview_ && !previewDeadlineMs_) previewDeadlineMs_ = nowMs + 15000;
}

bool PowerPolicy::shouldSleep(uint64_t nowMs) const {
  if (action_ != info_tv_v1_LockAction_LOCK_ACTION_DEEP_SLEEP || !locked_) return false;
  return !preview_ || (previewDeadlineMs_ && nowMs >= previewDeadlineMs_);
}
}  // namespace info_tv
