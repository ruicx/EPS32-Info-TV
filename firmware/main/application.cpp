#include "application.h"

#include <cassert>
#include <cstring>

#include "esp_check.h"
#include "esp_timer.h"

namespace info_tv {
void Application::start() {
  sleep_.initialize();
  power_ = PowerPolicy(sleep_.touchWake());
  if (sleep_.touchWake()) touchKey_.restoreAfterWake(sleep_.baseline());
  commands_ = xQueueCreate(4, sizeof(DisplayCommand));
  feedback_ = xQueueCreate(16, sizeof(Feedback));
  assert(commands_ && feedback_);
  const auto ui = xTaskCreate(uiTask, "info-tv-ui", 8192, this, 5, nullptr);
  const auto communication = xTaskCreate(communicationTask, "info-tv-comm", 8192, this, 4, nullptr);
  assert(ui == pdPASS && communication == pdPASS);
}

void Application::communicationTask(void* context) {
  auto& app = *static_cast<Application*>(context);
  app.usb_.initialize();
  // The session has large static buffers; allocate it once outside the task stack.
  auto* session = new DeviceSession(app.usb_, app.commands_, app.feedback_);
  assert(session);
  for (;;) {
    if (app.feedbackOverflow_.exchange(false)) session->invalidate();
    session->poll(esp_timer_get_time() / 1000);
    if (app.sleepRequested_.load()) {
      session->poll(esp_timer_get_time() / 1000);
      app.usb_.flush();
      app.sleepReady_.store(true);
      // The UI drains any final commands before committing to sleep or resuming I/O.
      while (app.sleepRequested_.load()) vTaskDelay(pdMS_TO_TICKS(5));
      app.sleepReady_.store(false);
    }
  }
}

void Application::queueFeedback(const Feedback& feedback) {
  if (xQueueSend(feedback_, &feedback, 0) != pdTRUE) feedbackOverflow_.store(true);
}

void Application::uiTask(void* context) {
  auto& app = *static_cast<Application*>(context);
  app.display_.initialize(app.sleep_.touchWake() ? 0 : 100);
  app.view_.initialize();
  app.touchKey_.initialize();
  uint32_t rendered = 0;
  uint32_t frameId = 0;
  uint32_t acknowledged = 0;
  const uint64_t bootMs = esp_timer_get_time() / 1000;
  bool brightnessReceived = false;
  bool previewVisible = false;
  for (;;) {
    const uint64_t nowMs = esp_timer_get_time() / 1000;
    Feedback feedback{};
    const auto buttonEvent = app.touchKey_.tick(nowMs);
    if (buttonEvent == ButtonEvent::kDoubleClick) {
      app.presentation_.dismissActiveNotification(nowMs);
    }
    static uint64_t clickShowUntilMs = 0;
    static uint32_t activeClick = 0;
    if (buttonEvent == ButtonEvent::kDoubleClick) {
      activeClick = 2;
      clickShowUntilMs = nowMs + 600;
    } else if (buttonEvent == ButtonEvent::kSingleClick) {
      activeClick = 1;
      clickShowUntilMs = nowMs + 400;
    } else if (nowMs >= clickShowUntilMs) {
      activeClick = 0;
    }
    const bool touchIndicatorChanged = app.view_.setTouchIndicator(
        app.touchKey_.isTouched(), activeClick);
    if (!app.display_.hasPendingFrame()) {
      const auto completed = app.display_.completedGeneration();
      if (completed && app.display_.backlightEnabled()) app.power_.framePresented(nowMs);
      if (completed && completed != acknowledged && app.display_.backlightEnabled()) {
        while (app.presentation_.onFramePresented(rendered, nowMs, feedback))
          app.queueFeedback(feedback);
        acknowledged = completed;
      }
      if (uxQueueSpacesAvailable(app.feedback_) >= policy::kRowsPerPage + 1 &&
          xQueueReceive(app.commands_, &app.uiCommand_, 0) == pdTRUE &&
          app.presentation_.handleCommand(app.uiCommand_, nowMs, feedback)) {
        if (app.uiCommand_.envelope.which_body == info_tv_v1_Envelope_device_settings_tag &&
            feedback.error == info_tv_v1_ErrorCode_ERROR_CODE_UNSPECIFIED) {
          if (app.display_.setBrightness(feedback.brightnessPercent)) {
            brightnessReceived = true;
            feedback.stage = info_tv_v1_AckStage_ACK_STAGE_APPLIED;
          } else {
            feedback.stage = info_tv_v1_AckStage_ACK_STAGE_UNSPECIFIED;
            feedback.error = info_tv_v1_ErrorCode_ERROR_CODE_HARDWARE;
            std::strcpy(feedback.detail, "Backlight PWM update failed");
          }
        }
        if (feedback.powerSettings && feedback.error == info_tv_v1_ErrorCode_ERROR_CODE_UNSPECIFIED) {
          if (feedback.lockAction != info_tv_v1_LockAction_LOCK_ACTION_DEEP_SLEEP ||
              app.sleep_.prepare(app.touchKey_.baseline())) {
            app.power_.configure(feedback.lockAction, feedback.sessionLocked);
            if (brightnessReceived && !app.display_.backlightEnabled()) app.power_.skipDarkPreview();
            feedback.stage = info_tv_v1_AckStage_ACK_STAGE_APPLIED;
          } else {
            feedback.stage = info_tv_v1_AckStage_ACK_STAGE_UNSPECIFIED;
            feedback.error = info_tv_v1_ErrorCode_ERROR_CODE_HARDWARE;
            std::strcpy(feedback.detail, "ULP touch wake preparation failed");
          }
        }
        app.queueFeedback(feedback);
      }
      // If the host is absent, reveal the normal offline screen after a bounded reconnect wait.
      if (app.sleep_.touchWake() && !brightnessReceived && !previewVisible && nowMs - bootMs >= 5000) {
        ESP_ERROR_CHECK(app.display_.setBrightness(app.sleep_.brightness()) ? ESP_OK : ESP_FAIL);
        previewVisible = true;
        if (!app.display_.backlightEnabled()) app.power_.skipDarkPreview();
      }
      if (app.power_.shouldSleep(nowMs) && uxQueueMessagesWaiting(app.commands_) == 0) {
        if (app.sleepReady_.load() && app.sleepRequested_.load()) {
          const uint32_t brightness = app.display_.brightness();
          ESP_ERROR_CHECK(app.display_.prepareSleep() ? ESP_OK : ESP_FAIL);
          ESP_ERROR_CHECK(app.sleep_.enter(app.touchKey_.baseline(), brightness) ? ESP_OK : ESP_FAIL);
        }
        if (!app.sleepReady_.load()) app.sleepRequested_.store(true);
      } else if (app.sleepRequested_.load()) {
        app.sleepRequested_.store(false);
      }
      const auto& model = app.presentation_.tick(nowMs);
      const bool contentChanged = model.generation != rendered;
      if (contentChanged) app.view_.render(model);
      const bool animated = app.display_.backlightEnabled() && app.view_.animate(nowMs);
      if (!app.sleepRequested_.load() && (contentChanged || animated || touchIndicatorChanged)) {
        // DMA identities advance for animation, while Presented tracks content.
        app.display_.present(++frameId, contentChanged);
        rendered = model.generation;
      }
    }
    lv_timer_handler();
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}
}  // namespace info_tv
