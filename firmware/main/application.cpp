#include "application.h"

#include <cassert>
#include <cstring>

#include "esp_check.h"
#include "esp_timer.h"

namespace info_tv {
void Application::start() {
  sleep_.initialize();
  power_ = PowerPolicy(sleep_.wakeReason(), esp_timer_get_time() / 1000);
  if (sleep_.sleepWake()) touchKey_.restoreAfterWake(sleep_.baseline(), sleep_.touchWake());
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
  app.display_.initialize(app.sleep_.sleepWake() ? 0 : 100);
  app.view_.initialize();
  app.touchKey_.initialize();
  uint32_t rendered = 0;
  uint32_t frameId = 0;
  uint32_t acknowledged = 0;
  const uint64_t bootMs = esp_timer_get_time() / 1000;
  bool brightnessReceived = false;
  bool previewVisible = false;
  uint32_t desiredBrightness = app.sleep_.brightness();
  for (;;) {
    const uint64_t nowMs = esp_timer_get_time() / 1000;
    Feedback feedback{};
    auto buttonEvent = app.touchKey_.tick(nowMs);
    if (app.touchKey_.isTouched() && app.power_.touchPressed()) {
      app.touchKey_.restoreAfterWake(app.touchKey_.baseline());
      buttonEvent = ButtonEvent::kNone;
    }
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
          desiredBrightness = feedback.brightnessPercent;
          // Acknowledge admission only while the timer probe is still silent.
          if (!app.power_.backlightAllowed() && desiredBrightness > 0) {
            feedback.stage = info_tv_v1_AckStage_ACK_STAGE_ACCEPTED;
          } else if (app.display_.setBrightness(desiredBrightness)) {
            brightnessReceived = true;
            if (!app.display_.backlightEnabled()) app.power_.skipDarkPreview();
            feedback.stage = info_tv_v1_AckStage_ACK_STAGE_APPLIED;
          } else {
            feedback.stage = info_tv_v1_AckStage_ACK_STAGE_UNSPECIFIED;
            feedback.error = info_tv_v1_ErrorCode_ERROR_CODE_HARDWARE;
            std::strcpy(feedback.detail, "Backlight PWM update failed");
          }
        }
        if (feedback.powerSettings && feedback.error == info_tv_v1_ErrorCode_ERROR_CODE_UNSPECIFIED) {
          if (feedback.lockAction != info_tv_v1_LockAction_LOCK_ACTION_DEEP_SLEEP ||
              app.sleep_.prepare(app.touchKey_.baseline(), feedback.unlockPollSeconds)) {
            app.power_.configure(feedback.lockAction, feedback.sessionLocked);
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
      if (app.power_.preview() && !brightnessReceived && !previewVisible && nowMs - bootMs >= 5000) {
        ESP_ERROR_CHECK(app.display_.setBrightness(desiredBrightness) ? ESP_OK : ESP_FAIL);
        previewVisible = true;
        if (!app.display_.backlightEnabled()) app.power_.skipDarkPreview();
      }
      if (app.power_.shouldSleep(nowMs) && uxQueueMessagesWaiting(app.commands_) == 0) {
        if (app.sleepReady_.load() && app.sleepRequested_.load()) {
          ESP_ERROR_CHECK(app.display_.prepareSleep() ? ESP_OK : ESP_FAIL);
          ESP_ERROR_CHECK(app.sleep_.enter(app.touchKey_.baseline(), desiredBrightness) ? ESP_OK : ESP_FAIL);
        }
        if (!app.sleepReady_.load()) app.sleepRequested_.store(true);
      } else if (app.sleepRequested_.load()) {
        app.sleepRequested_.store(false);
      }
      const auto& model = app.presentation_.tick(nowMs);
      const bool contentChanged = model.generation != rendered;
      if (contentChanged) app.view_.render(model);
      // Apply badge changes only when this iteration can submit their refresh.
      const bool touchIndicatorChanged = app.view_.setTouchIndicator(
          app.touchKey_.isTouched(), activeClick);
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
