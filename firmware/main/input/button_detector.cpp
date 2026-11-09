#include "input/button_detector.h"

namespace info_tv {

ButtonEvent ButtonDetector::update(bool isPressed, uint64_t nowMs) {
  switch (state_) {
    case State::kIdle:
      if (isPressed) {
        pressStartMs_ = nowMs;
        state_ = State::kPressing1;
      }
      return ButtonEvent::kNone;

    case State::kPressing1:
      if (!isPressed) {
        const uint64_t duration = nowMs - pressStartMs_;
        if (duration >= debounceMs_ && duration <= maxClickMs_) {
          releaseStartMs_ = nowMs;
          state_ = State::kReleased1;
        } else {
          state_ = State::kIdle;
        }
      } else if (nowMs - pressStartMs_ > maxClickMs_) {
        state_ = State::kHeld;
      }
      return ButtonEvent::kNone;

    case State::kReleased1:
      if (isPressed) {
        pressStartMs_ = nowMs;
        state_ = State::kPressing2;
        return ButtonEvent::kNone;
      }
      if (nowMs - releaseStartMs_ > doubleClickIntervalMs_) {
        state_ = State::kIdle;
        return ButtonEvent::kSingleClick;
      }
      return ButtonEvent::kNone;

    case State::kPressing2:
      if (!isPressed) {
        const uint64_t duration = nowMs - pressStartMs_;
        state_ = State::kIdle;
        if (duration >= debounceMs_ && duration <= maxClickMs_) {
          return ButtonEvent::kDoubleClick;
        }
        return ButtonEvent::kNone;
      }
      if (nowMs - pressStartMs_ >= debounceMs_) {
        state_ = State::kWaitRelease2;
        return ButtonEvent::kDoubleClick;
      }
      return ButtonEvent::kNone;

    case State::kWaitRelease2:
      if (!isPressed) {
        state_ = State::kIdle;
      }
      return ButtonEvent::kNone;

    case State::kHeld:
      if (!isPressed) {
        state_ = State::kIdle;
      }
      return ButtonEvent::kNone;
  }
  return ButtonEvent::kNone;
}

void ButtonDetector::reset() {
  state_ = State::kIdle;
  pressStartMs_ = 0;
  releaseStartMs_ = 0;
}

}  // namespace info_tv
