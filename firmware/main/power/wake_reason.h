#pragma once

namespace info_tv {
/** Distinguish a visible touch preview from a silent timer probe. */
enum class WakeReason { kCold, kTouch, kTimer };
}  // namespace info_tv
