#include <stdint.h>

#include "ulp_riscv.h"
#include "ulp_riscv_touch_ulp_core.h"
#include "ulp_riscv_utils.h"

#include "../input/touch_wakeup.h"

// Exported RTC variables are initialized by the main CPU before each sleep.
uint32_t baseline;
uint32_t activeSamples;
uint32_t releaseSamples;
uint32_t idleSamples;
uint32_t armed;
uint32_t wakeTriggered;

/** Sample TOUCH5 every 20 ms while the main CPU sleeps; wake only on a new press. */
int main(void) {
  uint32_t sample = 0;
  if (wakeTriggered || ulp_riscv_touch_pad_filter_read_smooth(5, &sample) != ESP_OK) return 0;
  TouchWakeState state = {baseline, activeSamples, releaseSamples, idleSamples, armed != 0};
  const bool wake = updateTouchWake(&state, sample);
  baseline = state.baseline;
  activeSamples = state.activeSamples;
  releaseSamples = state.releaseSamples;
  idleSamples = state.idleSamples;
  armed = state.armed;
  if (wake) {
    wakeTriggered = 1;
    ulp_riscv_wakeup_main_processor();
  }
  return 0;
}
