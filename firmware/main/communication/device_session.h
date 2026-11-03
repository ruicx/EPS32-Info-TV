#pragma once

#include <array>
#include <cstdint>

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

#include "communication/usb_transport.h"
#include "protocol/framing.h"
#include "protocol/model.h"

namespace info_tv {
/** Own framing, heartbeat, command handoff, and outbound feedback on one task. */
class DeviceSession {
 public:
  /** Bind the byte driver and bounded application queues. */
  DeviceSession(UsbTransport& transport, QueueHandle_t commands, QueueHandle_t feedback);
  /** Process bounded stream input, feedback, and connectivity events. */
  void poll(uint64_t nowMs);
  /** Force resynchronization after a saturated feedback handoff. */
  void invalidate();

 private:
  /** Decode and dispatch one verified payload. */
  void dispatch(uint64_t nowMs);
  /** Send the reusable outgoing envelope as a bounded binary frame. */
  void send();
  /** Assign a unique boot-local feedback identity. */
  void prepareReply(const char* sessionId);
  /** Encode UI feedback without synthesizing an acceptance milestone. */
  void sendFeedback(const Feedback& feedback);
  /** Report a transport-side rejection for a fully decoded command. */
  void reject(const Envelope& command, info_tv_v1_ErrorCode code, const char* detail);
  UsbTransport& transport_;
  QueueHandle_t commands_;
  QueueHandle_t feedback_;
  FrameDecoder decoder_;
  DisplayCommand command_{};
  Envelope reply_{};
  std::array<uint8_t, 4096> payload_{};
  std::array<uint8_t, 4128> wire_{};
  std::array<uint8_t, 1024> input_{};
  char sessionId_[37]{};
  uint64_t bootId_ = 0;
  uint64_t sequence_ = 0;
  uint64_t lastReceivedMs_ = 0;
  bool active_ = false;
  bool needsOffline_ = false;
};
}  // namespace info_tv
