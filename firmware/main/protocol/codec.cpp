#include "protocol/codec.h"

#include <cstring>

#include "pb_decode.h"
#include "pb_encode.h"

#include "config.h"

namespace info_tv {
namespace {
/** Check the supported view template and scalar bounds. */
bool validView(const View& view) {
  if (!view.title[0] || view.which_content != info_tv_v1_View_status_tag ||
      view.icon < info_tv_v1_TaskIcon_TASK_ICON_TASK ||
      view.icon > info_tv_v1_TaskIcon_TASK_ICON_DEPLOY) return false;
  const auto& status = view.content.status;
  return status.text[0] && status.tone >= info_tv_v1_Tone_TONE_NEUTRAL &&
         status.tone <= info_tv_v1_Tone_TONE_NEGATIVE &&
         (!status.has_progress_percent || status.progress_percent <= 100);
}

/** Check card identity, revision, and supported view content. */
bool validCard(const Card& card) {
  return card.card_id[0] && card.revision && card.has_view && validView(card.view);
}
}  // namespace

bool decodeEnvelope(const uint8_t* data, size_t size, Envelope& output) {
  output = Envelope{};
  if (!size || size > 4096) return false;
  auto stream = pb_istream_from_buffer(data, size);
  return pb_decode(&stream, info_tv_v1_Envelope_fields, &output);
}

size_t encodeEnvelope(const Envelope& envelope, uint8_t* data, size_t capacity) {
  auto stream = pb_ostream_from_buffer(data, capacity);
  return pb_encode(&stream, info_tv_v1_Envelope_fields, &envelope) ? stream.bytes_written : 0;
}

const char* validateCommand(const Envelope& envelope) {
  if (envelope.protocol_version != 1) return "Unsupported protocol version";
  if (!envelope.session_id[0] || !envelope.message_id[0]) return "Missing operation identity";
  switch (envelope.which_body) {
    case info_tv_v1_Envelope_device_settings_tag:
      return envelope.body.device_settings.has_brightness_percent &&
          envelope.body.device_settings.brightness_percent <= 100 ? nullptr : "Invalid brightness";
    case info_tv_v1_Envelope_snapshot_tag: {
      const auto& snapshot = envelope.body.snapshot;
      for (size_t index = 0; index < snapshot.cards_count; ++index) {
        if (!validCard(snapshot.cards[index])) return "Invalid snapshot card";
        for (size_t other = 0; other < index; ++other) {
          if (!std::strcmp(snapshot.cards[index].card_id, snapshot.cards[other].card_id))
            return "Duplicate snapshot card";
        }
      }
      return nullptr;
    }
    case info_tv_v1_Envelope_card_upsert_tag:
      return envelope.body.card_upsert.has_card && validCard(envelope.body.card_upsert.card)
                 ? nullptr : "Invalid card";
    case info_tv_v1_Envelope_notification_tag: {
      const auto& note = envelope.body.notification;
      if (!note.notification_id[0] || !note.valid_for_ms || note.valid_for_ms > policy::kNotificationValidityMs ||
          !note.has_view || !validView(note.view)) return "Invalid notification";
      if (note.priority != info_tv_v1_Priority_PRIORITY_ORDINARY &&
          note.priority != info_tv_v1_Priority_PRIORITY_IMPORTANT) return "Invalid priority";
      if (note.has_display_duration_ms && (!note.display_duration_ms || note.display_duration_ms > policy::kMaximumDurationMs))
        return "Invalid notification duration";
      return nullptr;
    }
    default:
      return "Unsupported display operation";
  }
}

bool sameCard(const Card& left, const Card& right) {
  const auto& a = left.view.content.status;
  const auto& b = right.view.content.status;
  return left.revision == right.revision && !std::strcmp(left.card_id, right.card_id) &&
         left.view.icon == right.view.icon &&
         !std::strcmp(left.view.source, right.view.source) &&
         !std::strcmp(left.view.context, right.view.context) &&
         !std::strcmp(left.view.title, right.view.title) && !std::strcmp(a.text, b.text) &&
         !std::strcmp(a.detail, b.detail) && a.tone == b.tone &&
         a.has_progress_percent == b.has_progress_percent &&
         (!a.has_progress_percent || a.progress_percent == b.progress_percent);
}
}  // namespace info_tv
