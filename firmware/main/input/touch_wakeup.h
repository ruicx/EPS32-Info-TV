#pragma once

#include <stdbool.h>
#include <stdint.h>

/** Shared main/ULP touch detection state; the threshold matches TouchKey. */
typedef struct {
  uint32_t baseline;
  uint32_t activeSamples;
  uint32_t releaseSamples;
  uint32_t idleSamples;
  bool armed;
} TouchWakeState;

/** Calibrate three stable sleep samples, then require three below-baseline samples to wake. */
static inline bool updateTouchWake(TouchWakeState* state, uint32_t sample) {
  if (!sample || !state->baseline) return false;
  if (!state->armed) {
    const uint32_t change = sample > state->baseline ? sample - state->baseline : state->baseline - sample;
    // Panel/CPU power changes can shift the idle reading across the old release threshold.
    if (change >= 18) {
      state->baseline = sample;
      state->releaseSamples = 1;
    } else {
      if (sample > state->baseline) state->baseline = sample;
      ++state->releaseSamples;
    }
    if (state->releaseSamples >= 3) state->armed = true;
    return false;
  }
  if (sample > state->baseline) state->baseline = sample;
  const uint32_t drop = state->baseline - sample;
  state->activeSamples = drop >= 35 ? state->activeSamples + 1 : 0;
  if (state->activeSamples >= 3) return true;
  if (drop < 18 && ++state->idleSamples >= 5) {
    state->idleSamples = 0;
    if (state->baseline > sample) --state->baseline;
  }
  return false;
}
