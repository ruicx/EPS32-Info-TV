#include "power/power_policy.h"

namespace info_tv {
PowerPolicy::PowerPolicy(WakeReason reason, uint64_t nowMs)
    : preview_(reason == WakeReason::kTouch), probing_(reason == WakeReason::kTimer),
      silent_(reason == WakeReason::kTimer), probeDeadlineMs_(nowMs + 5000) {
  if (reason != WakeReason::kCold) {
    action_ = info_tv_v1_LockAction_LOCK_ACTION_DEEP_SLEEP;
    locked_ = true;
  }
}

void PowerPolicy::configure(info_tv_v1_LockAction action, bool locked) {
  action_ = action;
  locked_ = locked;
  probing_ = false;
  if (action != info_tv_v1_LockAction_LOCK_ACTION_DEEP_SLEEP || !locked) preview_ = false;
  if (action != info_tv_v1_LockAction_LOCK_ACTION_DEEP_SLEEP || !locked) silent_ = false;
}

bool PowerPolicy::touchPressed() {
  if (!silent_) return false;
  silent_ = probing_ = false;
  preview_ = true;
  return true;
}

void PowerPolicy::framePresented(uint64_t nowMs) {
  if (preview_ && !previewDeadlineMs_) previewDeadlineMs_ = nowMs + 15000;
}

bool PowerPolicy::shouldSleep(uint64_t nowMs) const {
  if (action_ != info_tv_v1_LockAction_LOCK_ACTION_DEEP_SLEEP || !locked_) return false;
  if (probing_) return nowMs >= probeDeadlineMs_;
  return !preview_ || (previewDeadlineMs_ && nowMs >= previewDeadlineMs_);
}
}  // namespace info_tv
