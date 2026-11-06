#include <array>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <iostream>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

#include "protocol/codec.h"
#include "protocol/framing.h"
#include "ui/presentation_controller.h"

namespace {
/** Emit firmware-core feedback as an actual Protobuf/COBS frame. */
void send(info_tv::Envelope& envelope, uint64_t& sequence) {
  envelope.protocol_version = 1;
  std::snprintf(envelope.message_id, sizeof(envelope.message_id), "bridge-%llu", static_cast<unsigned long long>(++sequence));
  std::array<uint8_t, 4096> payload{};
  std::array<uint8_t, 4128> wire{};
  const auto size = info_tv::encodeEnvelope(envelope, payload.data(), payload.size());
  const auto framed = info_tv::encodeFrame(payload.data(), size, wire.data(), wire.size());
  std::cout.write(reinterpret_cast<const char*>(wire.data()), framed);
  std::cout.flush();
}

/** Convert controller feedback into the shared wire representation. */
void reply(const info_tv::Feedback& feedback, uint64_t& sequence) {
  info_tv::Envelope envelope{};
  std::strcpy(envelope.session_id, feedback.sessionId);
  if (feedback.error != info_tv_v1_ErrorCode_ERROR_CODE_UNSPECIFIED) {
    envelope.which_body = info_tv_v1_Envelope_error_tag;
    envelope.body.error.code = feedback.error;
    std::strcpy(envelope.body.error.in_reply_to, feedback.messageId);
    std::strcpy(envelope.body.error.detail, feedback.detail);
  } else {
    envelope.which_body = info_tv_v1_Envelope_acknowledgment_tag;
    auto& ack = envelope.body.acknowledgment;
    std::strcpy(ack.in_reply_to, feedback.messageId);
    std::strcpy(ack.card_id, feedback.cardId);
    ack.revision = feedback.revision;
    ack.stage = feedback.stage;
    if (feedback.stage == info_tv_v1_AckStage_ACK_STAGE_APPLIED) {
      ack.has_brightness_percent = true;
      ack.brightness_percent = feedback.brightnessPercent;
    }
  }
  send(envelope, sequence);
}
}  // namespace

/** Run a native protocol peer using the real firmware codec and presentation core.
 * The bridge simulates refresh completion; it does not emulate ST7789 hardware.
 */
int main() {
#ifdef _WIN32
  _setmode(_fileno(stdin), _O_BINARY);
  _setmode(_fileno(stdout), _O_BINARY);
#endif
  info_tv::FrameDecoder decoder;
  info_tv::DisplayState state;
  info_tv::PresentationController controller(state);
  uint64_t sequence = 0;
  uint32_t brightnessPercent = 100;
  const auto started = std::chrono::steady_clock::now();
  char byte;
  while (std::cin.get(byte)) {
    if (!decoder.feed(static_cast<uint8_t>(byte))) continue;
    const uint64_t now = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - started).count();
    info_tv::DisplayCommand command{};
    command.receivedAtMs = now;
    if (!info_tv::decodeEnvelope(decoder.data(), decoder.size(), command.envelope)) continue;
    info_tv::Envelope response{};
    std::strcpy(response.session_id, command.envelope.session_id);
    if (command.envelope.which_body == info_tv_v1_Envelope_hello_tag) {
      response.which_body = info_tv_v1_Envelope_hello_tag;
      response.body.hello.boot_id = 123;
      response.body.hello.max_cards = info_tv::policy::kMaxCards;
      response.body.hello.task_icons = true;
      response.body.hello.brightness_control = true;
      response.body.hello.weather = true;
      response.body.hello.weather_details = true;
      send(response, sequence);
    } else if (command.envelope.which_body == info_tv_v1_Envelope_ping_tag) {
      response.which_body = info_tv_v1_Envelope_pong_tag;
      send(response, sequence);
    } else {
      info_tv::Feedback feedback{};
      if (controller.handleCommand(command, now, feedback)) {
        // Simulate successful hardware application; the bridge has no backlight.
        if (command.envelope.which_body == info_tv_v1_Envelope_device_settings_tag &&
            feedback.error == info_tv_v1_ErrorCode_ERROR_CODE_UNSPECIFIED) {
          feedback.stage = info_tv_v1_AckStage_ACK_STAGE_APPLIED;
          brightnessPercent = feedback.brightnessPercent;
        }
        reply(feedback, sequence);
      }
    }
    const auto& model = controller.tick(now);
    info_tv::Feedback feedback{};
    while (brightnessPercent > 0 && controller.onFramePresented(model.generation, now, feedback))
      reply(feedback, sequence);
  }
}
