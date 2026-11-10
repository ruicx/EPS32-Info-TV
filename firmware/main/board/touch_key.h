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
  /** Restore the pre-sleep baseline and consume the waking press until release. */
  void restoreAfterWake(uint32_t baseline) { baseline_ = baseline; consumeWakeTouch_ = true; }

  /**
   * @brief Process current touch state and return detected button events.
   * @param nowMs Current monotonic millisecond timestamp.
   * @return Detected ButtonEvent (kNone, kSingleClick, or kDoubleClick).
   */
  ButtonEvent tick(uint64_t nowMs);

  /**
   * @brief Update touched state from ISR callback.
   * @param active True when pad is active/touched.
   */
  void setIsrTouched(bool active) {
    isrTouched_.store(active, std::memory_order_relaxed);
  }

  /**
   * @brief Update touched state from unit test or manual source.
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

  /** @brief Return last read smooth data count. */
  uint32_t lastSmooth() const { return lastSmooth_; }
  /** @brief Return last read baseline benchmark count. */
  uint32_t lastBenchmark() const { return lastBenchmark_; }
  /** @brief Return current software tracked baseline count. */
  uint32_t baseline() const { return baseline_; }
  /** @brief Return current configured active threshold. */
  uint32_t threshold() const { return thresh_; }

 private:
  /** Consume the waking contact until a stable 100 ms release has been observed. */
  bool filterWakeTouch(bool released, uint64_t nowMs);
  std::atomic<bool> isrTouched_{false};
  std::atomic<bool> touched_{false};
  bool swTouched_ = false;
  uint64_t touchStartMs_ = 0;
  uint64_t lastAdaptMs_ = 0;
  ButtonDetector detector_{};
  uint32_t lastSmooth_ = 0;
  uint32_t lastBenchmark_ = 0;
  uint32_t baseline_ = 0;
  uint32_t thresh_ = 35;
  bool consumeWakeTouch_ = false;
  uint64_t wakeReleaseSinceMs_ = 0;
#if defined(ESP_PLATFORM)
  void* sensHandle_ = nullptr;
  void* chanHandle_ = nullptr;
#endif
};

}  // namespace info_tv
