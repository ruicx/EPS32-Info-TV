#include "board/sleep_driver.h"

#include <cstddef>

#include "esp_attr.h"
#include "esp_sleep.h"
#include "ulp_riscv.h"
#include "ulp_touch_wake.h"

extern const uint8_t touchWakeBinaryStart[] asm("_binary_ulp_touch_wake_bin_start");
extern const uint8_t touchWakeBinaryEnd[] asm("_binary_ulp_touch_wake_bin_end");

namespace {
constexpr uint32_t kSleepMagic = 0x54564c50;

/** Retain only recovery settings; task content is resynchronized from the host. */
struct SleepContext {
  uint32_t magic;
  uint32_t brightness;
  uint32_t baseline;
};
RTC_DATA_ATTR SleepContext sleepContext{};
}  // namespace

namespace info_tv {
void SleepDriver::initialize() {
  ulp_riscv_timer_stop();
  ulp_riscv_halt();
  touchWake_ = (esp_sleep_get_wakeup_causes() & (1ULL << ESP_SLEEP_WAKEUP_ULP)) &&
      sleepContext.magic == kSleepMagic && ulp_wakeTriggered == 1 &&
      sleepContext.brightness <= 100 && sleepContext.baseline > 0;
  if (touchWake_) {
    brightness_ = sleepContext.brightness;
    baseline_ = ulp_baseline ? ulp_baseline : sleepContext.baseline;
  }
  sleepContext.magic = 0;
}

bool SleepDriver::prepare(uint32_t baseline) {
  if (!baseline) return false;
  if (ready_) return true;
  if (ulp_riscv_load_binary(touchWakeBinaryStart, touchWakeBinaryEnd - touchWakeBinaryStart) != ESP_OK ||
      ulp_set_wakeup_period(0, 20000) != ESP_OK ||
      esp_sleep_pd_config(ESP_PD_DOMAIN_RTC_PERIPH, ESP_PD_OPTION_ON) != ESP_OK ||
      esp_sleep_enable_ulp_wakeup() != ESP_OK) return false;
  ready_ = true;
  return true;
}

bool SleepDriver::enter(uint32_t baseline, uint32_t brightness) {
  if (!prepare(baseline)) return false;
  sleepContext = {kSleepMagic, brightness, baseline};
  ulp_baseline = baseline;
  ulp_activeSamples = ulp_releaseSamples = ulp_idleSamples = ulp_armed = ulp_wakeTriggered = 0;
  if (ulp_riscv_run() != ESP_OK) return false;
  esp_deep_sleep_start();
  return true;
}
}  // namespace info_tv
