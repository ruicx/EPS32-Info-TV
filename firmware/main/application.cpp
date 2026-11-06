#include "application.h"

#include <cassert>
#include <cstring>

#include "esp_timer.h"

namespace info_tv {
void Application::start() {
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
  }
}

void Application::queueFeedback(const Feedback& feedback) {
  if (xQueueSend(feedback_, &feedback, 0) != pdTRUE) feedbackOverflow_.store(true);
}

void Application::uiTask(void* context) {
  auto& app = *static_cast<Application*>(context);
  app.display_.initialize();
  app.view_.initialize();
  uint32_t rendered = 0;
  uint32_t acknowledged = 0;
  for (;;) {
    const uint64_t nowMs = esp_timer_get_time() / 1000;
    Feedback feedback{};
    if (!app.display_.hasPendingFrame()) {
      const auto completed = app.display_.completedGeneration();
      if (completed && completed != acknowledged && app.display_.backlightEnabled()) {
        while (app.presentation_.onFramePresented(completed, nowMs, feedback))
          app.queueFeedback(feedback);
        acknowledged = completed;
      }
      if (uxQueueSpacesAvailable(app.feedback_) >= policy::kRowsPerPage + 1 &&
          xQueueReceive(app.commands_, &app.uiCommand_, 0) == pdTRUE &&
          app.presentation_.handleCommand(app.uiCommand_, nowMs, feedback)) {
        if (app.uiCommand_.envelope.which_body == info_tv_v1_Envelope_device_settings_tag &&
            feedback.error == info_tv_v1_ErrorCode_ERROR_CODE_UNSPECIFIED) {
          if (app.display_.setBrightness(feedback.brightnessPercent)) {
            feedback.stage = info_tv_v1_AckStage_ACK_STAGE_APPLIED;
          } else {
            feedback.stage = info_tv_v1_AckStage_ACK_STAGE_UNSPECIFIED;
            feedback.error = info_tv_v1_ErrorCode_ERROR_CODE_HARDWARE;
            std::strcpy(feedback.detail, "Backlight PWM update failed");
          }
        }
        app.queueFeedback(feedback);
      }
      const auto& model = app.presentation_.tick(nowMs);
      if (model.generation != rendered) {
        app.view_.render(model);
        app.display_.present(model.generation);
        rendered = model.generation;
      }
    }
    lv_timer_handler();
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}
}  // namespace info_tv
