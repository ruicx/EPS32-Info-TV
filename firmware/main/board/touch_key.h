#pragma once

#include <atomic>
#include <cstdint>

#include "input/button_detector.h"

namespace info_tv {

/**
 * @brief Capacitive touch pad key driver for ESP32-S3 TP_KEY (IO5 / TOUCH5).
 */
class TouchKey {
 public:
  TouchKey() = default;

  /**
   * @brief Initialize ESP32-S3 touch sensor hardware.
   * @return True if initialized successfully or in mock mode; false on hardware error.
   */
  bool initialize();

  /**
   * @brief Process current touch state and return detected button events.
   * @param nowMs Current monotonic millisecond timestamp.
   * @return Detected ButtonEvent (kNone, kSingleClick, or kDoubleClick).
   */
  ButtonEvent tick(uint64_t nowMs);

  /**
   * @brief Update touched state from ISR callback or unit test.
   * @param touched True when pad is active/touched.
   */
  void setTouched(bool touched) {
    touched_.store(touched, std::memory_order_relaxed);
  }

  /**
   * @brief Return whether touch pad is currently touched.
   */
  bool isTouched() const {
    return touched_.load(std::memory_order_relaxed);
  }

 private:
  std::atomic<bool> touched_{false};
  ButtonDetector detector_{};
#if defined(ESP_PLATFORM)
  void* sensHandle_ = nullptr;
  void* chanHandle_ = nullptr;
#endif
};

}  // namespace info_tv
