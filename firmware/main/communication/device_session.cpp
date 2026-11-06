#include "communication/device_session.h"

#include <cstdio>
#include <cstring>

#include "esp_random.h"

#include "protocol/codec.h"
#include "config.h"

namespace info_tv {
DeviceSession::DeviceSession(UsbTransport& transport, QueueHandle_t commands, QueueHandle_t feedback)
    : transport_(transport), commands_(commands), feedback_(feedback) {
  offlineCommand_.linkLost = true;
  bootId_ = (static_cast<uint64_t>(esp_random()) << 32) | esp_random();
  if (!bootId_) bootId_ = 1;
}

void DeviceSession::prepareReply(const char* sessionId) {
  reply_ = Envelope{};
  reply_.protocol_version = 1;
  std::strcpy(reply_.session_id, sessionId);
  std::snprintf(reply_.message_id, sizeof(reply_.message_id), "%016llx%016llx",
                static_cast<unsigned long long>(bootId_), static_cast<unsigned long long>(++sequence_));
}

void DeviceSession::send() {
  const size_t size = encodeEnvelope(reply_, payload_.data(), payload_.size());
  if (!size) return;
  const size_t encoded = encodeFrame(payload_.data(), size, wire_.data(), wire_.size());
  if (encoded && !transport_.write(wire_.data(), encoded)) needsOffline_ = true;
}

void DeviceSession::reject(const Envelope& command, info_tv_v1_ErrorCode code, const char* detail) {
  prepareReply(command.session_id);
  reply_.which_body = info_tv_v1_Envelope_error_tag;
  std::strcpy(reply_.body.error.in_reply_to, command.message_id);
  reply_.body.error.code = code;
  std::strcpy(reply_.body.error.detail, detail);
  send();
}

void DeviceSession::sendFeedback(const Feedback& feedback) {
  prepareReply(feedback.sessionId);
  if (feedback.error != info_tv_v1_ErrorCode_ERROR_CODE_UNSPECIFIED) {
    reply_.which_body = info_tv_v1_Envelope_error_tag;
    std::strcpy(reply_.body.error.in_reply_to, feedback.messageId);
    reply_.body.error.code = feedback.error;
    std::strcpy(reply_.body.error.detail, feedback.detail);
  } else {
    reply_.which_body = info_tv_v1_Envelope_acknowledgment_tag;
    auto& ack = reply_.body.acknowledgment;
    std::strcpy(ack.in_reply_to, feedback.messageId);
    std::strcpy(ack.card_id, feedback.cardId);
    ack.revision = feedback.revision;
    ack.stage = feedback.stage;
    if (feedback.stage == info_tv_v1_AckStage_ACK_STAGE_APPLIED) {
      ack.has_brightness_percent = true;
      ack.brightness_percent = feedback.brightnessPercent;
    }
  }
  send();
}

void DeviceSession::dispatch(uint64_t nowMs) {
  // decodeEnvelope resets its payload; avoid a full-size command temporary here.
  command_.linkLost = false;
  if (!decodeEnvelope(decoder_.data(), decoder_.size(), command_.envelope)) return;
  const auto& envelope = command_.envelope;
  if (!envelope.message_id[0]) return;
  if (envelope.protocol_version != 1) {
    reject(envelope, info_tv_v1_ErrorCode_ERROR_CODE_UNSUPPORTED, "Unsupported protocol version");
    return;
  }
  if (envelope.which_body == info_tv_v1_Envelope_hello_tag) {
    active_ = false;
    needsOffline_ = true;
    sessionId_[0] = 0;
    prepareReply("");
    reply_.which_body = info_tv_v1_Envelope_hello_tag;
    reply_.body.hello.boot_id = bootId_;
    reply_.body.hello.max_cards = policy::kMaxCards;
    reply_.body.hello.task_icons = true;
    reply_.body.hello.brightness_control = true;
    reply_.body.hello.weather = true;
    reply_.body.hello.weather_details = true;
    send();
    return;
  }
  if (envelope.which_body == info_tv_v1_Envelope_ping_tag) {
    if (!sessionId_[0] || std::strcmp(envelope.session_id, sessionId_)) return;
    lastReceivedMs_ = nowMs;
    prepareReply(sessionId_);
    reply_.which_body = info_tv_v1_Envelope_pong_tag;
    send();
    return;
  }
  const char* reason = validateCommand(envelope);
  if (reason) {
    reject(envelope, info_tv_v1_ErrorCode_ERROR_CODE_INVALID, reason);
    return;
  }
  if (envelope.which_body != info_tv_v1_Envelope_snapshot_tag &&
      (!active_ || std::strcmp(envelope.session_id, sessionId_))) {
    reject(envelope, info_tv_v1_ErrorCode_ERROR_CODE_INVALID, "Snapshot required before updates");
    return;
  }
  if (needsOffline_) {
    if (xQueueSend(commands_, &offlineCommand_, 0) != pdTRUE) {
      reject(envelope, info_tv_v1_ErrorCode_ERROR_CODE_BUSY, "UI command queue full");
      return;
    }
    needsOffline_ = false;
  }
  command_.receivedAtMs = nowMs;
  if (xQueueSend(commands_, &command_, 0) != pdTRUE) {
    reject(envelope, info_tv_v1_ErrorCode_ERROR_CODE_BUSY, "UI command queue full");
    return;
  }
  std::strcpy(sessionId_, envelope.session_id);
  active_ = true;
  lastReceivedMs_ = nowMs;
}

void DeviceSession::poll(uint64_t nowMs) {
  Feedback feedback{};
  while (xQueueReceive(feedback_, &feedback, 0) == pdTRUE) sendFeedback(feedback);
  const size_t count = transport_.read(input_.data(), input_.size());
  for (size_t index = 0; index < count; ++index)
    if (decoder_.feed(input_[index])) dispatch(nowMs);
  if (active_ && nowMs - lastReceivedMs_ >= policy::kHeartbeatTimeoutMs) {
    active_ = false;
    needsOffline_ = true;
  }
  if (needsOffline_) {
    if (xQueueSend(commands_, &offlineCommand_, 0) == pdTRUE) needsOffline_ = false;
  }
}

void DeviceSession::invalidate() {
  active_ = false;
  sessionId_[0] = 0;
  needsOffline_ = true;
  decoder_.reset();
  xQueueReset(commands_);
  xQueueReset(feedback_);
}
}  // namespace info_tv
