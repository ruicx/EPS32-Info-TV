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
  if (self) self->setTouched(true);
  return false;
}

bool onTouchInactive(touch_sensor_handle_t /*sensHandle*/,
                     const touch_inactive_event_data_t* /*event*/,
                     void* userCtx) {
  auto* self = static_cast<info_tv::TouchKey*>(userCtx);
  if (self) self->setTouched(false);
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

  touch_channel_config_t chanCfg = {
      .active_thresh = { 1500 },
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

  if (touch_sensor_enable(sensHandle) == ESP_OK) {
    for (int i = 0; i < 3; ++i) {
      touch_sensor_trigger_oneshot_scanning(sensHandle, 2000);
    }
    touch_sensor_disable(sensHandle);

    uint32_t benchmark[SOC_TOUCH_SAMPLE_CFG_NUM] = {};
    if (touch_channel_read_data(chanHandle, TOUCH_CHAN_DATA_TYPE_BENCHMARK, benchmark) == ESP_OK) {
      uint32_t thresh = static_cast<uint32_t>(benchmark[0] * 0.03f);
      if (thresh < 800) thresh = 800;
      chanCfg.active_thresh[0] = thresh;
      touch_sensor_reconfig_channel(chanHandle, &chanCfg);
      ESP_LOGI(kTag, "Touch key benchmark %lu, threshold %lu",
               static_cast<unsigned long>(benchmark[0]), static_cast<unsigned long>(thresh));
    }
  }

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
  return detector_.update(touched_.load(std::memory_order_relaxed), nowMs);
}

}  // namespace info_tv
