#pragma once

#include <cstdint>

// Provisional, immutable demo timing defaults.
namespace info_tv::policy {
constexpr uint32_t kOrdinaryDurationMs = 5000;
constexpr uint32_t kImportantDurationMs = 10000;
constexpr uint32_t kRotationMs = 4000;
constexpr uint32_t kNotificationValidityMs = 30000;
constexpr uint32_t kMaximumDurationMs = 60000;
constexpr uint32_t kHeartbeatTimeoutMs = 3000;
}  // namespace info_tv::policy
