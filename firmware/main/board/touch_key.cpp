#include "board/touch_key.h"

#include "board/board_config.h"

#if defined(ESP_PLATFORM)
#include "driver/touch_sens.h"
#include "esp_log.h"

namespace {
constexpr const char* kTag = "touch_key";

bool onTouchActive(touch_sensor_handle_t /*sensHandle*/,
                   const touch_active_event_data_t* /*event*/,
                   void* userCtx) {
  auto* self = static_cast<info_tv::TouchKey*>(userCtx);
  if (self) self->setIsrTouched(true);
  ESP_EARLY_LOGI("touch_key", "Pad ACTIVE (pressed)");
  return false;
}

bool onTouchInactive(touch_sensor_handle_t /*sensHandle*/,
                     const touch_inactive_event_data_t* /*event*/,
                     void* userCtx) {
  auto* self = static_cast<info_tv::TouchKey*>(userCtx);
  if (self) self->setIsrTouched(false);
  ESP_EARLY_LOGI("touch_key", "Pad INACTIVE (released)");
  return false;
}
}  // namespace
#endif

namespace info_tv {

bool TouchKey::initialize() {
#if defined(ESP_PLATFORM)
  touch_sensor_sample_config_t sampleCfg[SOC_TOUCH_SAMPLE_CFG_NUM] = {
      TOUCH_SENSOR_V2_DEFAULT_SAMPLE_CONFIG(500, TOUCH_VOLT_LIM_L_0V5, TOUCH_VOLT_LIM_H_2V2)
  };
  touch_sensor_config_t sensCfg = TOUCH_SENSOR_DEFAULT_BASIC_CONFIG(SOC_TOUCH_SAMPLE_CFG_NUM, sampleCfg);
  touch_sensor_handle_t sensHandle = nullptr;
  if (touch_sensor_new_controller(&sensCfg, &sensHandle) != ESP_OK) {
    ESP_LOGE(kTag, "Failed to create touch sensor controller");
    return false;
  }
  sensHandle_ = sensHandle;

  thresh_ = 35;
  touch_channel_config_t chanCfg = {
      .active_thresh = { 100 },
      .charge_speed = TOUCH_CHARGE_SPEED_7,
      .init_charge_volt = TOUCH_INIT_CHARGE_VOLT_DEFAULT,
  };
  touch_channel_handle_t chanHandle = nullptr;
  if (touch_sensor_new_channel(sensHandle, board::kTouchChannel, &chanCfg, &chanHandle) != ESP_OK) {
    ESP_LOGE(kTag, "Failed to create touch channel %d", board::kTouchChannel);
    return false;
  }
  chanHandle_ = chanHandle;

  touch_sensor_filter_config_t filterCfg = TOUCH_SENSOR_DEFAULT_FILTER_CONFIG();
  touch_sensor_config_filter(sensHandle, &filterCfg);

  touch_event_callbacks_t callbacks = {
      .on_active = onTouchActive,
      .on_inactive = onTouchInactive,
      .on_measure_done = nullptr,
      .on_scan_done = nullptr,
      .on_timeout = nullptr,
      .on_proximity_meas_done = nullptr,
  };
  touch_sensor_register_callbacks(sensHandle, &callbacks, this);

  if (touch_sensor_enable(sensHandle) != ESP_OK) {
    ESP_LOGE(kTag, "Failed to enable touch sensor");
    return false;
  }
  if (touch_sensor_start_continuous_scanning(sensHandle) != ESP_OK) {
    ESP_LOGE(kTag, "Failed to start touch continuous scanning");
    return false;
  }
  ESP_LOGI(kTag, "Touch key initialized on GPIO%d (CH%d)", board::kTouchKey, board::kTouchChannel);
  return true;
#else
  return true;
#endif
}

ButtonEvent TouchKey::tick(uint64_t nowMs) {
#if defined(ESP_PLATFORM)
  if (chanHandle_) {
    uint32_t smooth = 0;
    auto* ch = static_cast<touch_channel_handle_t>(chanHandle_);
    if (touch_channel_read_data(ch, TOUCH_CHAN_DATA_TYPE_SMOOTH, &smooth) == ESP_OK && smooth > 0) {
      lastSmooth_ = smooth;
      if (baseline_ == 0) {
        baseline_ = smooth;
      }

      // Fast-track baseline upwards if reading jumps up (e.g. after finger release)
      if (lastSmooth_ > baseline_ + 25) {
        baseline_ = lastSmooth_;
      }

      // Touching TP_KEY drops count by ~100 (e.g. from ~16500 down to ~16400)
      const int32_t drop = static_cast<int32_t>(baseline_) - static_cast<int32_t>(lastSmooth_);
      if (filterWakeTouch(drop < 18, nowMs)) return ButtonEvent::kNone;
      if (drop >= static_cast<int32_t>(thresh_)) {
        if (!swTouched_) {
          swTouched_ = true;
          touchStartMs_ = nowMs;
        }
      } else if (drop < 18) {
        swTouched_ = false;
      }

      // Safety timeout: if held for > 5s, force release and re-baseline
      if (swTouched_) {
        if (nowMs - touchStartMs_ > 5000) {
          swTouched_ = false;
          baseline_ = lastSmooth_;
        }
      } else {
        // Slow baseline adaptation when untouched to track thermal drift
        if (nowMs - lastAdaptMs_ >= 100) {
          lastAdaptMs_ = nowMs;
          if (baseline_ < lastSmooth_) {
            ++baseline_;
          } else if (baseline_ > lastSmooth_) {
            --baseline_;
          }
        }
      }
    }

    touched_.store(swTouched_, std::memory_order_relaxed);
  }
#endif
  if (filterWakeTouch(!touched_.load(std::memory_order_relaxed), nowMs)) return ButtonEvent::kNone;
  return detector_.update(touched_.load(std::memory_order_relaxed), nowMs);
}

bool TouchKey::filterWakeTouch(bool released, uint64_t nowMs) {
  if (!consumeWakeTouch_) return false;
  if (!released) {
    wakeReleaseSinceMs_ = 0;
  } else if (!wakeReleaseSinceMs_) {
    wakeReleaseSinceMs_ = nowMs;
  } else if (nowMs - wakeReleaseSinceMs_ >= 100) {
    consumeWakeTouch_ = false;
    detector_.reset();
  }
  touched_.store(false, std::memory_order_relaxed);
  return true;
}

}  // namespace info_tv
