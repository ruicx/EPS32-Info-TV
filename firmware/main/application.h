#pragma once

#include <atomic>

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include "board/display_driver.h"
#include "communication/device_session.h"
#include "communication/usb_transport.h"
#include "ui/display_state.h"
#include "ui/presentation_controller.h"
#include "ui/screen_view.h"

namespace info_tv {
/** Own all application components and exactly two application task entrypoints. */
class Application {
 public:
  /** Allocate bounded queues and start the communication and UI tasks. */
  void start();

 private:
  /** Run the communication owner; framework tasks are separate. */
  static void communicationTask(void* context);
  /** Run the sole UI/LVGL owner and translate actual flush completion to feedback. */
  static void uiTask(void* context);
  /** Keep UI timing independent of feedback congestion and request recovery. */
  void queueFeedback(const Feedback& feedback);
  UsbTransport usb_;
  DisplayDriver display_;
  DisplayState state_;
  PresentationController presentation_{state_};
  ScreenView view_;
  QueueHandle_t commands_ = nullptr;
  QueueHandle_t feedback_ = nullptr;
  std::atomic<bool> feedbackOverflow_{false};
};
}  // namespace info_tv
