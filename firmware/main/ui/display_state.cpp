#include "ui/display_state.h"

#include <algorithm>
#include <cstring>

#include "protocol/codec.h"

namespace info_tv {
void DisplayState::applySnapshot(const Envelope& envelope) {
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
    std::strcpy(cards_[index].messageId, envelope.message_id);
  }
}

bool DisplayState::upsertCard(const Card& card, const char* messageId) {
  for (size_t index = 0; index < cardCount_; ++index) {
    auto& existing = cards_[index];
    if (std::strcmp(existing.card.card_id, card.card_id)) continue;
    if (card.revision < existing.card.revision) return false;
    if (card.revision == existing.card.revision) return sameCard(existing.card, card);
    existing = CardSlot{};
    existing.card = card;
    std::strcpy(existing.messageId, messageId);
    return true;
  }
  if (cardCount_ == cards_.size()) return false;
  auto& created = cards_[cardCount_++];
  created.card = card;
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
  if (notificationCount_ == notifications_.size() || receivedAtMs + note.valid_for_ms <= nowMs) return false;
  auto& slot = notifications_[notificationCount_++];
  slot = NotificationSlot{};
  slot.notification = note;
  std::strcpy(slot.messageId, envelope.message_id);
  std::strcpy(slot.sessionId, envelope.session_id);
  slot.expiresAtMs = receivedAtMs + note.valid_for_ms;
  std::strcpy(events_[eventIndex_++ % events_.size()].data(), note.notification_id);
  return true;
}

bool DisplayState::popNotification(uint64_t nowMs, NotificationSlot& output, bool importantOnly) {
  expire(nowMs);
  if (!notificationCount_) return false;
  size_t selected = 0;
  for (size_t index = 1; index < notificationCount_; ++index) {
    if (notifications_[index].notification.priority > notifications_[selected].notification.priority)
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
