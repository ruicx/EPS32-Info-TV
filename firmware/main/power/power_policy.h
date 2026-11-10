#pragma once

#include <cstdint>

#include "protocol/generated/device.pb.h"

namespace info_tv {
/** Device-owned lock policy and one nonrenewable touch-wake preview. */
class PowerPolicy {
 public:
  /** Start conservatively locked after a touch wake until the host confirms otherwise. */
  explicit PowerPolicy(bool touchWake = false);
  /** Apply an absolute policy; repeated locked samples do not extend the preview. */
  void configure(info_tv_v1_LockAction action, bool locked);
  /** Start the fifteen-second window when content becomes visible on the panel. */
  void framePresented(uint64_t nowMs);
  /** Return whether the current lock state or expired preview requires deep sleep. */
  bool shouldSleep(uint64_t nowMs) const;
  /** Return whether this boot is still displaying a temporary touch-wake preview. */
  bool preview() const { return preview_; }
  /** End a preview that cannot become visible because the user selected brightness zero. */
  void skipDarkPreview() { preview_ = false; }

 private:
  info_tv_v1_LockAction action_ = info_tv_v1_LockAction_LOCK_ACTION_NONE;
  bool locked_ = false;
  bool preview_ = false;
  uint64_t previewDeadlineMs_ = 0;
};
}  // namespace info_tv
