#pragma once

#include <cstddef>
#include <cstdint>
#include <type_traits>

#include "protocol/generated/device.pb.h"

namespace info_tv {

using Envelope = info_tv_v1_Envelope;
using Card = info_tv_v1_Card;
using View = info_tv_v1_View;
using Notification = info_tv_v1_Notification;

/** Own a complete decoded command across the communication/UI boundary. */
struct DisplayCommand {
  Envelope envelope{};
  uint64_t receivedAtMs = 0;
  bool linkLost = false;
};

/** Carry bounded UI feedback without copying a full snapshot. */
struct Feedback {
  char sessionId[37]{};
  char messageId[37]{};
  char cardId[37]{};
  uint64_t revision = 0;
  info_tv_v1_AckStage stage = info_tv_v1_AckStage_ACK_STAGE_UNSPECIFIED;
  info_tv_v1_ErrorCode error = info_tv_v1_ErrorCode_ERROR_CODE_UNSPECIFIED;
  char detail[97]{};
};

/** Describe a complete render request without LVGL or hardware pointers. */
struct RenderModel {
  enum class Kind { kEmpty, kOverview, kNotification };
  Kind kind = Kind::kEmpty;
  View view{};
  char sessionId[37]{};
  char messageId[37]{};
  char cardId[37]{};
  uint64_t revision = 0;
  uint32_t generation = 0;
  size_t cardIndex = 0;
  size_t cardCount = 0;
  bool connected = false;
};

static_assert(std::is_trivially_copyable_v<DisplayCommand>);
static_assert(std::is_trivially_copyable_v<Feedback>);

}  // namespace info_tv
