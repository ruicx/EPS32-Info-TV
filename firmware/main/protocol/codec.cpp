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
         (!status.has_progress_percent || status.progress_percent <= 100) &&
         status.recent_question_seconds <= 30;
}

/** Check card identity, revision, and supported view content. */
bool validCard(const Card& card) {
  return card.card_id[0] && card.revision && card.has_view && validView(card.view);
}

/** Validate a complete weather observation or a fully empty clear. */
bool validWeather(const info_tv_v1_Weather& weather) {
  if (!weather.has_temperature_c)
    return !weather.location[0] && !weather.valid_for_ms &&
        !weather.has_daily_low_c && !weather.has_daily_high_c &&
        weather.condition == info_tv_v1_WeatherCondition_WEATHER_CONDITION_UNKNOWN;
  if (weather.has_daily_low_c != weather.has_daily_high_c) return false;
  if (weather.has_daily_low_c && (weather.daily_low_c < -100 || weather.daily_high_c > 100 ||
      weather.daily_low_c > weather.daily_high_c)) return false;
  return weather.location[0] && weather.temperature_c >= -100 && weather.temperature_c <= 100 &&
      weather.valid_for_ms && weather.valid_for_ms <= 3600000 &&
      weather.condition >= info_tv_v1_WeatherCondition_WEATHER_CONDITION_UNKNOWN &&
      weather.condition <= info_tv_v1_WeatherCondition_WEATHER_CONDITION_FOG;
}

/** Validate one bounded alert independently of current weather availability. */
bool validWeatherAlert(const info_tv_v1_WeatherAlert& alert) {
  if (!alert.alert_id[0])
    return !alert.title[0] && !alert.source[0] && !alert.location[0] && !alert.detail[0] &&
        !alert.valid_for_ms && !alert.notify &&
        alert.severity == info_tv_v1_WeatherAlertSeverity_WEATHER_ALERT_SEVERITY_UNSPECIFIED;
  return alert.title[0] && alert.source[0] && alert.location[0] &&
      alert.valid_for_ms && alert.valid_for_ms <= 86400000 &&
      alert.severity >= info_tv_v1_WeatherAlertSeverity_WEATHER_ALERT_SEVERITY_BLUE &&
      alert.severity <= info_tv_v1_WeatherAlertSeverity_WEATHER_ALERT_SEVERITY_RED;
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
    case info_tv_v1_Envelope_weather_alert_tag:
      return validWeatherAlert(envelope.body.weather_alert) ? nullptr : "Invalid weather alert";
    case info_tv_v1_Envelope_weather_tag:
      return validWeather(envelope.body.weather) ? nullptr : "Invalid weather";
    case info_tv_v1_Envelope_device_settings_tag:
      return envelope.body.device_settings.has_brightness_percent &&
          envelope.body.device_settings.brightness_percent <= 100 ? nullptr : "Invalid brightness";
    case info_tv_v1_Envelope_snapshot_tag: {
      const auto& snapshot = envelope.body.snapshot;
      if (snapshot.has_weather && !validWeather(snapshot.weather)) return "Invalid snapshot weather";
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
         (!a.has_progress_percent || a.progress_percent == b.progress_percent) &&
         a.recent_question_seconds == b.recent_question_seconds;
}
}  // namespace info_tv
