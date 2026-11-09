#pragma once

#include <cstdint>

namespace info_tv {

/**
 * @brief Events emitted by button or touch interactions.
 */
enum class ButtonEvent {
  kNone,
  kSingleClick,
  kDoubleClick,
};

/**
 * @brief Debounced click and double-click state machine.
 *
 * Implements noise debouncing, single-click detection, and double-click detection.
 * Designed to be completely decoupled from hardware drivers and FreeRTOS for testability.
 */
class ButtonDetector {
 public:
  /**
   * @brief Construct a button detector with standard timing parameters.
   *
   * @param debounceMs Minimum continuous press duration to qualify as a valid press.
   * @param maxClickMs Maximum press duration to qualify as a tap (not a long hold).
   * @param doubleClickIntervalMs Maximum gap between taps to qualify as a double-click.
   */
  explicit ButtonDetector(uint32_t debounceMs = 25,
                          uint32_t maxClickMs = 350,
                          uint32_t doubleClickIntervalMs = 300)
      : debounceMs_(debounceMs),
        maxClickMs_(maxClickMs),
        doubleClickIntervalMs_(doubleClickIntervalMs) {}

  /**
   * @brief Update button state and evaluate click events.
   *
   * @param isPressed Current hardware press/touch level.
   * @param nowMs Current monotonic timestamp in milliseconds.
   * @return Detected button event (kNone, kSingleClick, or kDoubleClick).
   */
  ButtonEvent update(bool isPressed, uint64_t nowMs);

  /**
   * @brief Reset detector state machine back to idle.
   */
  void reset();

 private:
  enum class State {
    kIdle,
    kPressing1,
    kReleased1,
    kPressing2,
    kWaitRelease2,
    kHeld,
  };

  State state_ = State::kIdle;
  uint32_t debounceMs_;
  uint32_t maxClickMs_;
  uint32_t doubleClickIntervalMs_;
  uint64_t pressStartMs_ = 0;
  uint64_t releaseStartMs_ = 0;
};

}  // namespace info_tv
