#include "ui/display_state.h"

#include <algorithm>
#include <cstdio>
#include <cstring>

#include "protocol/codec.h"

namespace info_tv {
void DisplayState::applySnapshot(const Envelope& envelope, uint64_t receivedAtMs) {
  if (std::strcmp(sessionId_, envelope.session_id)) {
    accepted_ = {};
    events_ = {};
    acceptedIndex_ = eventIndex_ = notificationCount_ = 0;
    std::strcpy(sessionId_, envelope.session_id);
  }
  cards_ = {};
  cardCount_ = envelope.body.snapshot.cards_count;
  for (size_t index = 0; index < cardCount_; ++index) {
    cards_[index].card = envelope.body.snapshot.cards[index];
    cards_[index].questionUntilMs = receivedAtMs + 1000 * cards_[index].card.view.content.status.recent_question_seconds;
    std::strcpy(cards_[index].messageId, envelope.message_id);
  }
  size_t retained = 0;
  for (size_t index = 0; index < notificationCount_; ++index) {
    const auto& note = notifications_[index];
    if (note.weatherAlert || !note.notification.card_id[0] || hasCard(note.notification.card_id))
      notifications_[retained++] = note;
  }
  notificationCount_ = retained;
}

bool DisplayState::hasCard(const char* cardId) const {
  for (size_t index = 0; index < cardCount_; ++index) {
    if (!std::strcmp(cards_[index].card.card_id, cardId)) return true;
  }
  return false;
}

bool DisplayState::upsertCard(const Card& card, const char* messageId, uint64_t receivedAtMs) {
  for (size_t index = 0; index < cardCount_; ++index) {
    auto& existing = cards_[index];
    if (std::strcmp(existing.card.card_id, card.card_id)) continue;
    if (card.revision < existing.card.revision) return false;
    if (card.revision == existing.card.revision) return sameCard(existing.card, card);
    existing = CardSlot{};
    existing.card = card;
    existing.questionUntilMs = receivedAtMs + 1000 * card.view.content.status.recent_question_seconds;
    std::strcpy(existing.messageId, messageId);
    return true;
  }
  if (cardCount_ == cards_.size()) return false;
  auto& created = cards_[cardCount_++];
  created.card = card;
  created.questionUntilMs = receivedAtMs + 1000 * card.view.content.status.recent_question_seconds;
  std::strcpy(created.messageId, messageId);
  return true;
}

void DisplayState::expire(uint64_t nowMs) {
  size_t retained = 0;
  for (size_t index = 0; index < notificationCount_; ++index) {
    if (notifications_[index].expiresAtMs > nowMs)
      notifications_[retained++] = notifications_[index];
  }
  notificationCount_ = retained;
}

bool DisplayState::enqueueNotification(const Envelope& envelope, uint64_t receivedAtMs, uint64_t nowMs) {
  expire(nowMs);
  const auto& note = envelope.body.notification;
  for (const auto& event : events_) {
    if (!std::strcmp(event.data(), note.notification_id)) return true;
  }
  size_t regularCount = 0;
  for (size_t index = 0; index < notificationCount_; ++index)
    if (!notifications_[index].weatherAlert) ++regularCount;
  if (regularCount == 8 || receivedAtMs + note.valid_for_ms <= nowMs) return false;
  auto& slot = notifications_[notificationCount_++];
  slot = NotificationSlot{};
  slot.notification = note;
  std::strcpy(slot.messageId, envelope.message_id);
  std::strcpy(slot.sessionId, envelope.session_id);
  slot.expiresAtMs = receivedAtMs + note.valid_for_ms;
  std::strcpy(events_[eventIndex_++ % events_.size()].data(), note.notification_id);
  return true;
}

void DisplayState::clearWeatherNotification() {
  size_t retained = 0;
  for (size_t index = 0; index < notificationCount_; ++index)
    if (!notifications_[index].weatherAlert) notifications_[retained++] = notifications_[index];
  notificationCount_ = retained;
}

void DisplayState::clearCardAttentionNotifications(const char* cardId) {
  size_t retained = 0;
  for (size_t index = 0; index < notificationCount_; ++index) {
    const auto& note = notifications_[index];
    if (note.weatherAlert || std::strcmp(note.notification.card_id, cardId) ||
        note.notification.view.content.status.tone != info_tv_v1_Tone_TONE_ATTENTION) {
      notifications_[retained++] = note;
    }
  }
  notificationCount_ = retained;
}

void DisplayState::notifyWeatherAlert(const Envelope& envelope, uint64_t receivedAtMs) {
  clearWeatherNotification();
  const auto& alert = envelope.body.weather_alert;
  auto& slot = notifications_[notificationCount_++];
  slot = NotificationSlot{};
  slot.weatherAlert = true;
  std::strcpy(slot.messageId, envelope.message_id);
  std::strcpy(slot.sessionId, envelope.session_id);
  slot.expiresAtMs = receivedAtMs + std::min(alert.valid_for_ms, policy::kNotificationValidityMs);
  auto& note = slot.notification;
  std::strcpy(note.notification_id, envelope.message_id);
  note.priority = info_tv_v1_Priority_PRIORITY_IMPORTANT;
  note.valid_for_ms = std::min(alert.valid_for_ms, policy::kNotificationValidityMs);
  note.has_view = true;
  std::strcpy(note.view.title, alert.title);
  std::strcpy(note.view.source, alert.source);
  std::strcpy(note.view.context, alert.location);
  note.view.which_content = info_tv_v1_View_status_tag;
  const char* levels[] = {"", "Blue", "Yellow", "Orange", "Red"};
  auto& status = note.view.content.status;
  std::snprintf(status.text, sizeof(status.text), "%s warning", levels[alert.severity]);
  status.tone = alert.severity == info_tv_v1_WeatherAlertSeverity_WEATHER_ALERT_SEVERITY_RED ?
      info_tv_v1_Tone_TONE_NEGATIVE : alert.severity == info_tv_v1_WeatherAlertSeverity_WEATHER_ALERT_SEVERITY_BLUE ?
      info_tv_v1_Tone_TONE_NEUTRAL : info_tv_v1_Tone_TONE_ATTENTION;
  std::strcpy(status.detail, alert.detail);
}

bool DisplayState::popNotification(uint64_t nowMs, NotificationSlot& output, bool importantOnly) {
  expire(nowMs);
  if (!notificationCount_) return false;
  size_t selected = 0;
  for (size_t index = 1; index < notificationCount_; ++index) {
    if (notifications_[index].notification.priority > notifications_[selected].notification.priority ||
        (notifications_[index].notification.priority == notifications_[selected].notification.priority &&
         notifications_[index].weatherAlert && !notifications_[selected].weatherAlert))
      selected = index;
  }
  if (importantOnly && notifications_[selected].notification.priority != info_tv_v1_Priority_PRIORITY_IMPORTANT)
    return false;
  output = notifications_[selected];
  for (size_t index = selected + 1; index < notificationCount_; ++index)
    notifications_[index - 1] = notifications_[index];
  --notificationCount_;
  return true;
}

bool DisplayState::accepted(const char* messageId) const {
  for (const auto& identity : accepted_)
    if (!std::strcmp(identity.data(), messageId)) return true;
  return false;
}

void DisplayState::remember(const char* messageId) {
  std::strcpy(accepted_[acceptedIndex_++ % accepted_.size()].data(), messageId);
}
}  // namespace info_tv
